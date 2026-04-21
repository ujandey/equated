"""
Tests for services/concept_graph.py

Pure unit tests — reads from the real data/concept_graph.json.
No DB, no LLM, no network.
"""

from __future__ import annotations

import pytest

from services.concept_graph import ConceptGraph, get_concept_graph
from services.diagnosis_engine import StudentProfile


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cg() -> ConceptGraph:
    return ConceptGraph()


# ── Node count ────────────────────────────────────────────────────────────────

def test_graph_has_at_least_40_nodes(cg: ConceptGraph) -> None:
    assert len(cg.nodes) >= 40, f"Expected ≥40 nodes, got {len(cg.nodes)}"


def test_graph_covers_all_subjects(cg: ConceptGraph) -> None:
    subjects = {node.get("subject") for node in cg.nodes.values()}
    for expected in ("algebra", "trigonometry", "calculus", "physics", "chemistry"):
        assert expected in subjects, f"Subject '{expected}' missing from graph"


# ── get_prerequisites ────────────────────────────────────────────────────────

def test_derivatives_requires_limits(cg: ConceptGraph) -> None:
    prereqs = cg.get_prerequisites("derivatives")
    assert "limits" in prereqs, "derivatives should transitively require limits"


def test_chain_rule_requires_derivatives(cg: ConceptGraph) -> None:
    prereqs = cg.get_prerequisites("chain_rule")
    assert "derivatives" in prereqs


def test_stoichiometry_requires_mole_concept(cg: ConceptGraph) -> None:
    prereqs = cg.get_prerequisites("stoichiometry")
    assert "mole_concept" in prereqs


def test_prerequisites_exclude_topic_itself(cg: ConceptGraph) -> None:
    for topic in ("linear_equations", "integrals", "kinematics"):
        prereqs = cg.get_prerequisites(topic)
        assert topic not in prereqs, f"{topic} should not appear in its own prerequisites"


def test_prerequisites_of_root_node_is_empty(cg: ConceptGraph) -> None:
    # arithmetic has no requires[]
    prereqs = cg.get_prerequisites("arithmetic")
    assert prereqs == []


def test_unknown_topic_returns_empty_prerequisites(cg: ConceptGraph) -> None:
    assert cg.get_prerequisites("nonexistent_topic_xyz") == []


# ── topological_sort ─────────────────────────────────────────────────────────

def test_topological_sort_prereq_before_dependent(cg: ConceptGraph) -> None:
    concepts = ["derivatives", "limits", "functions"]
    ordered = cg.topological_sort(concepts)
    assert ordered.index("functions") < ordered.index("limits"), \
        "functions should come before limits"
    assert ordered.index("limits") < ordered.index("derivatives"), \
        "limits should come before derivatives"


def test_topological_sort_single_element(cg: ConceptGraph) -> None:
    assert cg.topological_sort(["arithmetic"]) == ["arithmetic"]


def test_topological_sort_empty(cg: ConceptGraph) -> None:
    assert cg.topological_sort([]) == []


def test_topological_sort_contains_all_inputs(cg: ConceptGraph) -> None:
    concepts = ["stoichiometry", "mole_concept", "chemical_equations", "arithmetic"]
    ordered = cg.topological_sort(concepts)
    assert set(ordered) == set(concepts)


def test_topological_sort_calculus_chain(cg: ConceptGraph) -> None:
    chain = ["integrals", "derivatives", "limits", "functions"]
    ordered = cg.topological_sort(chain)
    idx = {c: ordered.index(c) for c in chain}
    assert idx["functions"] < idx["limits"]
    assert idx["limits"] < idx["derivatives"]
    assert idx["derivatives"] < idx["integrals"]


# ── get_common_errors ─────────────────────────────────────────────────────────

def test_common_errors_nonempty_for_known_topics(cg: ConceptGraph) -> None:
    for topic in ("derivatives", "quadratics", "stoichiometry"):
        errors = cg.get_common_errors(topic)
        assert len(errors) > 0, f"Expected common_errors for {topic}"


def test_common_errors_unknown_topic_returns_empty(cg: ConceptGraph) -> None:
    assert cg.get_common_errors("does_not_exist") == []


def test_common_errors_are_strings(cg: ConceptGraph) -> None:
    for error in cg.get_common_errors("linear_equations"):
        assert isinstance(error, str)


# ── get_confusion_points ──────────────────────────────────────────────────────

def test_confusion_points_nonempty_for_known_topics(cg: ConceptGraph) -> None:
    for topic in ("limits", "integrals", "mole_concept"):
        points = cg.get_confusion_points(topic)
        assert len(points) > 0, f"Expected confusion_points for {topic}"


def test_confusion_points_unknown_topic_returns_empty(cg: ConceptGraph) -> None:
    assert cg.get_confusion_points("ghost_topic") == []


# ── find_analogous_concept ────────────────────────────────────────────────────

def test_analogous_returns_same_subject(cg: ConceptGraph) -> None:
    # "chain_rule" is calculus; known concepts include both calculus and chemistry
    result = cg.find_analogous_concept(
        "chain_rule",
        ["derivatives", "mole_concept", "quadratics"],
    )
    # derivatives is in the same subject AND is a direct prerequisite
    assert result == "derivatives"


def test_analogous_empty_known_returns_none(cg: ConceptGraph) -> None:
    assert cg.find_analogous_concept("integrals", []) is None


def test_analogous_unknown_topic_still_returns_something(cg: ConceptGraph) -> None:
    result = cg.find_analogous_concept("mystery_topic", ["arithmetic", "mole_concept"])
    # Should return one of the provided known concepts (no crash).
    assert result in ("arithmetic", "mole_concept")


# ── get_teaching_path ────────────────────────────────────────────────────────

def test_teaching_path_excludes_strong_topics(cg: ConceptGraph) -> None:
    profile = StudentProfile(
        strong=["arithmetic", "limits", "functions"],
        weak=[],
        unseen=[],
        confusion_type="unknown",
        confidence=0.8,
    )
    path = cg.get_teaching_path("derivatives", profile)
    assert "arithmetic" not in path
    assert "limits" not in path
    assert "functions" not in path


def test_teaching_path_includes_weak_and_unseen_prereqs(cg: ConceptGraph) -> None:
    profile = StudentProfile(
        strong=[],
        weak=["functions"],
        unseen=["limits"],
        confusion_type="procedural",
        confidence=0.3,
    )
    path = cg.get_teaching_path("derivatives", profile)
    assert "functions" in path
    assert "limits" in path


def test_teaching_path_is_topologically_ordered(cg: ConceptGraph) -> None:
    profile = StudentProfile(strong=[], weak=[], unseen=[], confidence=0.5)
    path = cg.get_teaching_path("chain_rule", profile)
    # derivatives must come before chain_rule
    if "derivatives" in path and "chain_rule" in path:
        assert path.index("derivatives") < path.index("chain_rule")


def test_teaching_path_unknown_topic_returns_empty(cg: ConceptGraph) -> None:
    profile = StudentProfile(strong=[], weak=[], unseen=[], confidence=0.5)
    path = cg.get_teaching_path("topic_that_does_not_exist", profile)
    assert path == []


# ── singleton ─────────────────────────────────────────────────────────────────

def test_get_concept_graph_singleton_returns_same_instance() -> None:
    a = get_concept_graph()
    b = get_concept_graph()
    assert a is b
