from services.student_model import StudentModelService


def test_detects_arithmetic_and_concept_patterns():
    service = StudentModelService()

    patterns = service.detect_mistake_patterns(
        "Solve 7 + 5 and write the answer in cm",
        "I think 7 + 5 = 11",
    )

    codes = {pattern["mistake_code"] for pattern in patterns}
    assert "arithmetic_error" in codes
    assert "unit_error" in codes


def test_success_streak_increases_mastery_faster():
    service = StudentModelService()

    normal_gain = service._compute_new_mastery(
        current_mastery=0.40,
        success=True,
        hints_used=0,
        retry_count=0,
        consecutive_successes=0,
        consecutive_failures=0,
        confidence=0.9,
    )
    streak_gain = service._compute_new_mastery(
        current_mastery=0.40,
        success=True,
        hints_used=0,
        retry_count=0,
        consecutive_successes=3,
        consecutive_failures=0,
        confidence=0.9,
    )

    assert streak_gain > normal_gain


def test_simple_explanation_request_reduces_assumed_level():
    service = StudentModelService()

    lowered = service._compute_assumed_level(
        current_assumed_level=0.60,
        success=False,
        asked_for_simple=True,
        hints_used=1,
    )

    assert lowered < 0.60


def test_chat_outcome_marks_simplify_request_as_struggle():
    service = StudentModelService()

    outcome = service.build_chat_interaction_outcome(
        user_message="explain simply please",
        assistant_response="Let's do it in easier steps.",
        subject="math",
        topic="math: quadratic equations",
        session_id="session-1",
        follow_up_anchor_kind="simplify_request",
        topic_decision_type="follow_up",
        topic_question_count=2,
        confidence=0.8,
        verified=True,
    )

    assert outcome["success"] is False
    assert outcome["hints_used"] == 1
    assert outcome["retry_count"] >= 1
