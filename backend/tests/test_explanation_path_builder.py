"""
Tests for services/explanation_path_builder.py

Pure unit tests — no DB, no LLM, no network.
ConceptGraph is loaded from the real data/concept_graph.json.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.concept_graph import ConceptGraph
from services.diagnosis_engine import StudentProfile
from services.explanation_path_builder import (
    ExplanationPathBuilder,
    ExplanationScript,
    Segment,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cg() -> ConceptGraph:
    return ConceptGraph()


@pytest.fixture(scope="module")
def builder() -> ExplanationPathBuilder:
    return ExplanationPathBuilder()


def _mock_sympy_result(
    operation: str = "solve",
    expression: str = "2*x - 4",
    variable: str = "x",
    result: str = "2",
    steps: list[str] | None = None,
) -> MagicMock:
    sr = MagicMock()
    sr.request.operation = operation
    sr.request.expression = expression
    sr.request.variable = variable
    mr = MagicMock()
    mr.result = result
    mr.steps = steps or ["Step 1: rearrange", "Step 2: divide"]
    sr.math_result = mr
    return sr


def _profile(
    strong: list[str] | None = None,
    weak: list[str] | None = None,
    unseen: list[str] | None = None,
    confusion_type: str = "unknown",
    confidence: float = 0.5,
) -> StudentProfile:
    return StudentProfile(
        strong=strong or [],
        weak=weak or [],
        unseen=unseen or [],
        confusion_type=confusion_type,
        confidence=confidence,
    )


# ── build: return type ────────────────────────────────────────────────────────

def test_build_returns_explanation_script(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=_profile(),
        concept_graph=cg,
    )
    assert isinstance(script, ExplanationScript)


def test_script_has_segments(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=_profile(),
        concept_graph=cg,
    )
    assert isinstance(script.segments, list)


def test_script_has_tone(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=_profile(),
        concept_graph=cg,
    )
    assert script.tone in ("encouraging", "efficient", "challenging")


def test_script_has_nonempty_llm_prompt(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    script = builder.build(
        problem="Differentiate x^2",
        sympy_result=_mock_sympy_result(operation="differentiate"),
        student_profile=_profile(),
        concept_graph=cg,
    )
    assert len(script.llm_prompt) > 100, "llm_prompt should be a substantial string"


# ── Tone selection ────────────────────────────────────────────────────────────

def test_encouraging_tone_for_low_confidence(
    builder: ExplanationPathBuilder,
) -> None:
    tone = builder._select_tone(_profile(confidence=0.2, weak=["a", "b", "c"]))
    assert tone == "encouraging"


def test_encouraging_tone_for_many_weak_topics(
    builder: ExplanationPathBuilder,
) -> None:
    tone = builder._select_tone(
        _profile(weak=["a", "b", "c", "d"], confidence=0.6)
    )
    assert tone == "encouraging"


def test_challenging_tone_for_high_mastery(
    builder: ExplanationPathBuilder,
) -> None:
    tone = builder._select_tone(
        _profile(strong=["a", "b", "c", "d", "e", "f"], weak=["x"], confidence=0.85)
    )
    assert tone == "challenging"


def test_efficient_tone_as_default(
    builder: ExplanationPathBuilder,
) -> None:
    tone = builder._select_tone(_profile(confidence=0.5))
    assert tone == "efficient"


# ── Segment rules ─────────────────────────────────────────────────────────────

def test_strong_concept_produces_skip_segment(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    profile = _profile(strong=["arithmetic", "variables_expressions"])
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=profile,
        concept_graph=cg,
    )
    skip_concepts = {s.concept for s in script.segments if s.type == "skip"}
    # arithmetic and variables_expressions are prereqs of linear_equations
    assert "arithmetic" in skip_concepts or "variables_expressions" in skip_concepts


def test_weak_concept_produces_remind_segment(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    profile = _profile(weak=["variables_expressions"])
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=profile,
        concept_graph=cg,
    )
    remind_concepts = {s.concept for s in script.segments if s.type == "remind"}
    assert "variables_expressions" in remind_concepts


def test_procedural_confusion_adds_flag_error_segments(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    profile = _profile(confusion_type="procedural")
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=profile,
        concept_graph=cg,
    )
    flag_types = [s.type for s in script.segments]
    assert "flag_error" in flag_types


def test_conceptual_confusion_adds_method_clarification(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    profile = _profile(confusion_type="conceptual")
    script = builder.build(
        problem="Differentiate x^2",
        sympy_result=_mock_sympy_result(operation="differentiate"),
        student_profile=profile,
        concept_graph=cg,
    )
    flag_segs = [s for s in script.segments if s.type == "flag_error"]
    assert any("method" in s.instruction.lower() or "approach" in s.instruction.lower()
               for s in flag_segs)


def test_remind_max_sentences_is_two_or_less(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    profile = _profile(weak=["limits", "functions"])
    script = builder.build(
        problem="Differentiate x^2",
        sympy_result=_mock_sympy_result(operation="differentiate"),
        student_profile=profile,
        concept_graph=cg,
    )
    for seg in script.segments:
        if seg.type == "remind":
            assert seg.max_sentences <= 2


# ── LLM prompt content ────────────────────────────────────────────────────────

def test_llm_prompt_contains_problem_statement(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    problem = "Solve 2x - 4 = 0 for x"
    script = builder.build(
        problem=problem,
        sympy_result=_mock_sympy_result(),
        student_profile=_profile(),
        concept_graph=cg,
    )
    assert problem in script.llm_prompt


def test_llm_prompt_contains_do_not_invent(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=_profile(),
        concept_graph=cg,
    )
    assert "invent" in script.llm_prompt.lower() or "alter" in script.llm_prompt.lower()


def test_llm_prompt_includes_verified_steps(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    steps = ["Rearrange to 2x = 4", "Divide both sides by 2", "x = 2"]
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(steps=steps),
        student_profile=_profile(),
        concept_graph=cg,
    )
    for step in steps:
        assert step in script.llm_prompt


def test_llm_prompt_includes_tone_directive(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=_profile(confidence=0.1, weak=["a", "b", "c"]),
        concept_graph=cg,
    )
    assert "TONE" in script.llm_prompt


def test_llm_prompt_includes_weak_areas_when_present(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    profile = _profile(weak=["limits", "functions"])
    script = builder.build(
        problem="Differentiate x^2",
        sympy_result=_mock_sympy_result(operation="differentiate"),
        student_profile=profile,
        concept_graph=cg,
    )
    assert "limits" in script.llm_prompt or "functions" in script.llm_prompt


def test_llm_prompt_includes_skip_instruction(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    profile = _profile(strong=["arithmetic"])
    script = builder.build(
        problem="Solve 2x - 4 = 0",
        sympy_result=_mock_sympy_result(),
        student_profile=profile,
        concept_graph=cg,
    )
    assert "[SKIP]" in script.llm_prompt


# ── Topic extraction ──────────────────────────────────────────────────────────

def test_extract_topic_maps_solve_to_linear_equations(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    topic = builder._extract_topic(
        "Solve 2x - 4 = 0",
        _mock_sympy_result(operation="solve"),
        cg,
    )
    assert topic == "linear_equations"


def test_extract_topic_maps_differentiate_to_derivatives(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    topic = builder._extract_topic(
        "Differentiate x^2",
        _mock_sympy_result(operation="differentiate"),
        cg,
    )
    assert topic == "derivatives"


def test_extract_topic_fallback_for_missing_operation(
    builder: ExplanationPathBuilder, cg: ConceptGraph
) -> None:
    sr = MagicMock()
    sr.request = MagicMock(side_effect=AttributeError)
    topic = builder._extract_topic("Some problem text", sr, cg)
    # Should not raise, returns a string
    assert isinstance(topic, str)
