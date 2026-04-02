from datetime import datetime, timedelta, timezone

from knowledge.curriculum_graph import (
    find_knowledge_gaps,
    get_prerequisites,
    load_curriculum,
    suggest_next_topic,
)


def test_load_curriculum_contains_core_subjects():
    graph = load_curriculum()

    assert {"math", "physics", "chemistry", "coding", "biology"}.issubset(graph["subject_index"])


def test_get_prerequisites_returns_transitive_chain():
    prerequisites = get_prerequisites("applications_of_derivatives")

    assert prerequisites == ["Arithmetic", "Fractions", "Algebra basics", "Functions and graphs", "Limits", "Derivatives"]


def test_alias_resolution_prefers_intro_integration_for_basics_phrase():
    graph = load_curriculum()

    intro_alias_hits = graph["alias_index"].get("integration_basics")

    assert intro_alias_hits == ["introduction_to_integration"]
    assert get_prerequisites("integration basics") == [
        "Arithmetic",
        "Fractions",
        "Algebra basics",
        "Functions and graphs",
        "Limits",
        "Derivatives",
    ]


def test_find_knowledge_gaps_returns_weighted_severity():
    student_model = {
        "topics": [
            {"topic": "Arithmetic", "mastery": 0.9},
            {"topic": "Fractions", "mastery": 0.82},
            {"topic": "Algebra basics", "mastery": 0.76},
            {"topic": "Functions and graphs", "mastery": 0.58},
            {"topic": "Limits", "mastery": 0.2},
        ]
    }

    gaps = find_knowledge_gaps("derivatives", student_model)

    assert [gap["topic"] for gap in gaps] == ["Limits", "Functions and graphs"]
    assert gaps[0]["severity"] > gaps[1]["severity"]
    assert gaps[0]["severity_label"] in {"high", "critical"}
    assert gaps[1]["severity_label"] in {"low", "medium"}


def test_suggest_next_topic_prioritizes_weak_subject_globally():
    student_model = {
        "topics": [
            {"topic": "Arithmetic", "mastery": 0.95},
            {"topic": "Fractions", "mastery": 0.92},
            {"topic": "Algebra basics", "mastery": 0.9},
            {"topic": "Functions and graphs", "mastery": 0.82},
            {"topic": "Programming basics", "mastery": 0.96},
            {"topic": "Control flow", "mastery": 0.89},
            {"topic": "Functions", "mastery": 0.84},
            {"topic": "Data structures", "mastery": 0.79},
            {"topic": "Limits", "mastery": 0.39},
        ],
        "weak_areas": [
            {"topic": "Derivatives", "mastery": 0.39, "consecutive_failures": 3, "failures": 4}
        ],
    }

    recommendation = suggest_next_topic(student_model)

    assert recommendation is not None
    assert recommendation["topic"] == "Limits"
    assert "weakest active subject" in recommendation["reason"] or "prerequisite gap" in recommendation["reason"]


def test_suggest_next_topic_avoids_large_difficulty_jump_when_mastery_low():
    student_model = {
        "topics": [
            {"topic": "Arithmetic", "mastery": 0.94},
            {"topic": "Fractions", "mastery": 0.88},
            {"topic": "Algebra basics", "mastery": 0.83},
            {"topic": "Functions and graphs", "mastery": 0.8},
            {"topic": "Limits", "mastery": 0.74},
            {"topic": "Derivatives", "mastery": 0.44},
            {"topic": "Introduction to integration", "mastery": 0.18},
        ],
        "weak_areas": [],
    }

    recommendation = suggest_next_topic(student_model)

    assert recommendation is not None
    assert recommendation["topic"] != "Advanced integration techniques"
    assert recommendation["difficulty"] <= 4


def test_decay_reduces_effective_mastery_and_promotes_review():
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    student_model = {
        "topics": [
            {"topic": "Arithmetic", "mastery": 0.95},
            {"topic": "Fractions", "mastery": 0.9},
            {"topic": "Algebra basics", "mastery": 0.88},
            {"topic": "Functions and graphs", "mastery": 0.82},
            {"topic": "Limits", "mastery": 0.86, "last_interacted_at": stale_timestamp},
        ],
        "weak_areas": [],
    }

    recommendation = suggest_next_topic(student_model)
    gaps = find_knowledge_gaps("derivatives", student_model)

    assert recommendation is not None
    assert recommendation["topic"] == "Limits"
    assert "revised" in recommendation["reason"]
    assert any(gap["topic"] == "Limits" and gap["stale"] is True for gap in gaps)
