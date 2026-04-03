from types import SimpleNamespace

import pytest

from services.master_controller import master_controller
from services.topic_blocks import AnchorMatch, TopicRoutingDecision


def _routing(block_id: str, decision_type: str = "new_topic", anchor_kind: str | None = None) -> TopicRoutingDecision:
    return TopicRoutingDecision(
        block_id=block_id,
        decision_type=decision_type,
        reason="test",
        is_new_block=decision_type == "new_topic",
        scores={},
        thresholds={},
        anchor=AnchorMatch(kind=anchor_kind, text=None, confidence=0.9 if anchor_kind else 0.0),
        subject="physics",
    )


@pytest.mark.asyncio
async def test_validation_gate_blocks_ambiguous_derivative(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)

    solve_calls = []
    monkeypatch.setattr("services.master_controller.symbolic_solver.solve_expression", lambda *_args, **_kwargs: solve_calls.append(True))

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve derivative",
    )

    assert result.trace.validation_passed is False
    assert result.response.clarification_request is not None
    assert "provide" in result.response.clarification_request.lower()
    assert solve_calls == []


@pytest.mark.asyncio
async def test_unicode_normalization_solves_quadratic(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="x = -2, 2",
                steps=[{"step": 1, "explanation": "Factor the equation."}],
                concept_used="Quadratic equation",
                quick_summary="Roots are -2 and 2.",
                problem_interpretation="Solve x^2 - 4 = 0",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "step_by_step"})
    monkeypatch.setattr("services.master_controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    captured = {}

    original_extract = master_controller._run_validation_gates

    def _capture_validation(intent, query):
        captured["normalized_query"] = query
        return original_extract(intent, query)

    monkeypatch.setattr(master_controller, "_run_validation_gates", _capture_validation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x² - 4 = 0",
    )

    assert captured["normalized_query"] == "Solve x^2 - 4 = 0"
    assert "-2" in result.response.final_answer and "2" in result.response.final_answer
    assert result.trace.tool_used == "sympy"


@pytest.mark.asyncio
async def test_follow_up_context_reuses_same_block(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="Gauss's law formula: ΦE = Qenc/ε0",
                steps=[],
                concept_used="Electrostatics",
                quick_summary="Flux equals enclosed charge over permittivity.",
                problem_interpretation="Explain Gauss law",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "conceptual"})
    monkeypatch.setattr("services.master_controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="physics")))
    monkeypatch.setattr("services.master_controller.model_router.route", lambda *_args, **_kwargs: SimpleNamespace())
    async def _fallback(*_args, **_kwargs):
        return SimpleNamespace(content="Gauss law formula is ΦE = Qenc/ε0", model="mock-model")

    monkeypatch.setattr("services.master_controller.fallback_handler.generate_with_fallback", _fallback)
    monkeypatch.setattr("services.master_controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    routing_calls = iter(
        [
            _routing("block-gauss", "new_topic"),
            _routing("block-gauss", "follow_up", anchor_kind="continuation"),
        ]
    )
    async def _route(**_kwargs):
        return next(routing_calls)

    monkeypatch.setattr(master_controller, "_select_context", _route)

    first = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Explain Gauss law",
    )
    second = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Now give formula",
    )

    assert first.block_id == "block-gauss"
    assert second.block_id == "block-gauss"
    assert "Qenc" in second.response.final_answer


@pytest.mark.asyncio
async def test_symbolic_first_enforcement_never_uses_llm_math(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="x = 2",
                steps=[{"step": 1, "explanation": "Subtract 3 then divide by 2."}],
                concept_used="Linear equations",
                quick_summary="x = 2",
                problem_interpretation="Solve 2*x + 3 = 7",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "step_by_step"})
    monkeypatch.setattr("services.master_controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    fallback_calls = []

    async def _fallback(*_args, **_kwargs):
        fallback_calls.append(True)
        return SimpleNamespace(content="hallucinated math", model="mock")

    monkeypatch.setattr("services.master_controller.fallback_handler.generate_with_fallback", _fallback)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve 2*x + 3 = 7",
    )

    assert result.trace.tool_used == "sympy"
    assert result.response.verified is True
    assert fallback_calls == []


@pytest.mark.asyncio
async def test_multi_intent_query_requires_clarification(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 and explain stokes theorem",
    )

    assert result.trace.validation_passed is False
    assert "one task at a time" in (result.response.clarification_request or "").lower()
