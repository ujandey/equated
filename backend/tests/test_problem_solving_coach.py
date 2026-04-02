from services.problem_solving_coach import (
    STRATEGY_ALGEBRAIC,
    STRATEGY_GUESS_AND_CHECK,
    problem_solving_coach,
)


def test_detect_strategy_finds_guess_and_check():
    result = problem_solving_coach.detect_strategy("I guess x = 3, maybe that works.")

    assert result["strategy"] == STRATEGY_GUESS_AND_CHECK


def test_detect_strategy_finds_algebraic_manipulation():
    result = problem_solving_coach.detect_strategy("2x + 3 = 11, so 2x = 8 and x = 4")

    assert result["strategy"] == STRATEGY_ALGEBRAIC


def test_suggest_improvement_flags_units_and_knowns_unknowns():
    result = problem_solving_coach.suggest_improvement(
        "A car travels 60 km in 2 hours. Find its speed in km/h.",
        "I did 60/2 = 30",
    )

    joined = " ".join(result["suggestions"]).lower()
    assert "units" in joined
    assert "knowns and unknowns" in joined


def test_suggest_improvement_recommends_diagram_for_geometry():
    result = problem_solving_coach.suggest_improvement(
        "Find the area of a triangle with base 8 cm and height 5 cm.",
        "I used 8 x 5",
    )

    joined = " ".join(result["suggestions"]).lower()
    assert "diagram" in joined


def test_should_coach_detects_attempt_signal():
    assert problem_solving_coach.should_coach("I tried x = 4 and then 2x + 1 = 9")
