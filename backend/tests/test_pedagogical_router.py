from ai.pedagogical_router import (
    STRATEGY_ANALOGY,
    STRATEGY_REMEDIAL,
    STRATEGY_SCAFFOLDED,
    STRATEGY_WORKED_EXAMPLE,
    build_strategy_system_prompt,
    classify_question_type,
    detect_homework_dump,
    route,
)


def test_classify_question_type_conceptual():
    assert classify_question_type("Why does completing the square work?") == "conceptual"


def test_detect_homework_dump_for_multipart_assignment():
    query = "Homework:\n1. Solve x+2=5\n2. Solve x^2-4=0\n3. Find the derivative of x^3"
    assert detect_homework_dump(query) is True


def test_route_returns_remedial_for_low_mastery():
    decision = route(
        "Teach me limits",
        {
            "topics": [{"topic": "limits", "mastery": 0.22}],
            "weak_areas": [],
            "mistake_patterns": [],
            "interaction_signals": {},
        },
    )
    assert decision["strategy"] == STRATEGY_REMEDIAL


def test_route_returns_scaffolded_for_repeated_mistakes():
    decision = route(
        "Help me solve this integral step by step",
        {
            "topics": [{"topic": "integration", "mastery": 0.63}],
            "weak_areas": [{"topic": "integration", "mastery": 0.63, "consecutive_failures": 2, "failures": 3}],
            "mistake_patterns": [{"mistake_label": "Sign handling error", "frequency": 2}],
            "interaction_signals": {"retries": 4, "failures": 3},
        },
    )
    assert decision["strategy"] == STRATEGY_SCAFFOLDED


def test_route_returns_worked_example_for_just_solve():
    decision = route("Just solve this equation and give the final answer.", {"topics": []})
    assert decision["strategy"] == STRATEGY_WORKED_EXAMPLE


def test_route_returns_analogy_for_conceptual_query():
    decision = route(
        "What does electric potential actually mean intuitively?",
        {
            "topics": [{"topic": "electric potential", "mastery": 0.71}],
            "weak_areas": [],
            "mistake_patterns": [],
            "interaction_signals": {"successes": 4, "failures": 0, "total_events": 4},
        },
    )
    assert decision["strategy"] == STRATEGY_ANALOGY


def test_strategy_prompt_includes_reason_and_confidence():
    prompt = build_strategy_system_prompt(
        {
            "strategy": STRATEGY_WORKED_EXAMPLE,
            "reason": "Explicit solve request.",
            "confidence": 0.91,
        }
    )
    assert "worked_example" in prompt
    assert "Explicit solve request." in prompt
    assert "0.91" in prompt
