import pytest

from services.master_controller import master_controller


def test_normalize_input_converts_unicode_math():
    normalized = master_controller.normalize_input("Solve x² − 4 = 0")

    assert normalized == "Solve x^2 - 4 = 0"


def test_validation_gate_requires_function_for_incomplete_second_derivative():
    clarification = master_controller._run_validation_gates("solve", "Solve d^2x/dt^2")

    assert clarification == "Please provide the function"


def test_intent_classification_for_simple_follow_up_phrase():
    intent = master_controller.classify_intent("Explain simply")

    assert intent == "explain"
