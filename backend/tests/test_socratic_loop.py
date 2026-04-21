"""
Tests for services/socratic_loop.py

Pure unit tests — no DB, no LLM, no network.
DB calls in update_mastery are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sympy import Integer, Rational, symbols

from services.socratic_loop import (
    MasteryUpdate,
    ProbeQuestion,
    SocraticLoop,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
    mr.steps = steps or ["Rearrange", "Divide"]
    sr.math_result = mr
    return sr


def _no_expression_result() -> MagicMock:
    sr = MagicMock()
    sr.request.operation = "solve"
    sr.request.expression = ""
    sr.request.variable = "x"
    sr.math_result = None
    return sr


# ── generate_probe ────────────────────────────────────────────────────────────

def test_generate_probe_returns_probe_question() -> None:
    loop = SocraticLoop()
    probe = loop.generate_probe("Solve 2x - 4 = 0", _mock_sympy_result())
    assert isinstance(probe, ProbeQuestion)
    assert isinstance(probe.question_text, str)
    assert len(probe.question_text) > 0
    assert probe.strategy_used in (
        "change_coefficients", "add_constraint", "reverse_operation", "ask_why"
    )
    assert isinstance(probe.tests_concept, str)


def test_generate_probe_no_expression_falls_back_to_ask_why() -> None:
    loop = SocraticLoop()
    probe = loop.generate_probe("What is calculus?", _no_expression_result())
    assert probe.strategy_used == "ask_why"
    assert probe.expected_answer is None


def test_generate_probe_ask_why_has_no_expected_answer() -> None:
    loop = SocraticLoop()
    probe = loop.generate_probe("Solve 2x = 4", _mock_sympy_result(), difficulty_delta=0)
    if probe.strategy_used == "ask_why":
        assert probe.expected_answer is None


def test_generate_probe_difficulty_delta_negative_favours_easy() -> None:
    loop = SocraticLoop()
    # difficulty_delta < 0 → reverse_operation strategy attempted first
    probe = loop.generate_probe("Solve 2x - 4 = 0", _mock_sympy_result(), difficulty_delta=-1)
    assert probe.strategy_used in ("reverse_operation", "ask_why")


def test_generate_probe_difficulty_delta_positive_favours_constraint() -> None:
    loop = SocraticLoop()
    probe = loop.generate_probe("Solve 2x - 4 = 0", _mock_sympy_result(), difficulty_delta=1)
    assert probe.strategy_used in ("add_constraint", "ask_why")


# ── evaluate_response ────────────────────────────────────────────────────────

def test_evaluate_correct_answer_gives_full_delta() -> None:
    loop = SocraticLoop()
    probe = ProbeQuestion(
        question_text="What is x?",
        expected_answer=Integer(2),
        tests_concept="linear_equations",
        strategy_used="change_coefficients",
    )
    update = loop.evaluate_response(probe, "2")
    assert update.is_correct is True
    assert update.delta == pytest.approx(SocraticLoop.DELTA_CORRECT)
    assert update.confusion_signal is None


def test_evaluate_incorrect_answer_gives_negative_delta() -> None:
    loop = SocraticLoop()
    probe = ProbeQuestion(
        question_text="What is x?",
        expected_answer=Integer(2),
        tests_concept="linear_equations",
        strategy_used="change_coefficients",
    )
    update = loop.evaluate_response(probe, "5")
    assert update.is_correct is False
    assert update.delta == pytest.approx(SocraticLoop.DELTA_INCORRECT)
    assert update.confusion_signal is not None


def test_evaluate_ask_why_non_empty_gives_hint_delta() -> None:
    loop = SocraticLoop()
    probe = ProbeQuestion(
        question_text="Why do we isolate the variable?",
        expected_answer=None,
        tests_concept="linear_equations",
        strategy_used="ask_why",
    )
    update = loop.evaluate_response(probe, "Because we want to find x by itself")
    assert update.is_correct is True
    assert update.delta == pytest.approx(SocraticLoop.DELTA_CORRECT_WITH_HINT)


def test_evaluate_ask_why_empty_gives_negative_delta() -> None:
    loop = SocraticLoop()
    probe = ProbeQuestion(
        question_text="Why?",
        expected_answer=None,
        tests_concept="linear_equations",
        strategy_used="ask_why",
    )
    update = loop.evaluate_response(probe, "   ")
    assert update.is_correct is False
    assert update.delta == pytest.approx(SocraticLoop.DELTA_INCORRECT)


def test_evaluate_unparseable_response_is_incorrect() -> None:
    loop = SocraticLoop()
    probe = ProbeQuestion(
        question_text="What is x?",
        expected_answer=Integer(3),
        tests_concept="algebra",
        strategy_used="change_coefficients",
    )
    update = loop.evaluate_response(probe, "I have no idea!!! ???")
    assert update.is_correct is False


def test_evaluate_sign_error_detected() -> None:
    loop = SocraticLoop()
    probe = ProbeQuestion(
        question_text="What is x?",
        expected_answer=Integer(3),
        tests_concept="algebra",
        strategy_used="change_coefficients",
    )
    # Student answered -3 (sign error)
    update = loop.evaluate_response(probe, "-3")
    assert update.is_correct is False
    assert update.confusion_signal is not None
    assert "sign" in update.confusion_signal.lower()


# ── Delta rule constants ──────────────────────────────────────────────────────

def test_delta_asymmetry() -> None:
    """Correct > hint credit > |incorrect| in absolute terms."""
    loop = SocraticLoop()
    assert loop.DELTA_CORRECT > loop.DELTA_CORRECT_WITH_HINT > 0
    assert loop.DELTA_INCORRECT < 0
    assert abs(loop.DELTA_CORRECT) > abs(loop.DELTA_INCORRECT)


# ── update_mastery ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_mastery_correct_increases_score() -> None:
    loop = SocraticLoop()
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=MagicMock(
        **{"__getitem__": lambda self, k: {"mastery_score": 0.5}[k]}
    ))
    db.execute = AsyncMock()

    update = MasteryUpdate(
        concept="linear_equations",
        delta=0.10,
        is_correct=True,
        confusion_signal=None,
    )
    await loop.update_mastery("user-1", update, db=db)

    # execute must have been called twice: mastery upsert + event insert
    assert db.execute.call_count == 2
    call_args = db.execute.call_args_list[0]
    # The mastery_after value passed should be 0.5 + 0.10 = 0.60
    args = call_args[0]
    assert any(abs(a - 0.60) < 1e-6 for a in args if isinstance(a, float)), \
        f"Expected mastery_after ≈ 0.60 in execute args: {args}"


@pytest.mark.asyncio
async def test_update_mastery_incorrect_decreases_score() -> None:
    loop = SocraticLoop()
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=MagicMock(
        **{"__getitem__": lambda self, k: {"mastery_score": 0.5}[k]}
    ))
    db.execute = AsyncMock()

    update = MasteryUpdate(
        concept="linear_equations",
        delta=-0.05,
        is_correct=False,
        confusion_signal="Arithmetic error",
    )
    await loop.update_mastery("user-1", update, db=db)

    args = db.execute.call_args_list[0][0]
    assert any(abs(a - 0.45) < 1e-6 for a in args if isinstance(a, float)), \
        f"Expected mastery_after ≈ 0.45 in execute args: {args}"


@pytest.mark.asyncio
async def test_update_mastery_clamps_to_zero() -> None:
    loop = SocraticLoop()
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=MagicMock(
        **{"__getitem__": lambda self, k: {"mastery_score": 0.02}[k]}
    ))
    db.execute = AsyncMock()

    update = MasteryUpdate(
        concept="algebra",
        delta=-0.10,
        is_correct=False,
        confusion_signal=None,
    )
    await loop.update_mastery("user-1", update, db=db)

    args = db.execute.call_args_list[0][0]
    floats = [a for a in args if isinstance(a, float)]
    assert min(floats) >= 0.0


@pytest.mark.asyncio
async def test_update_mastery_no_existing_row_uses_default() -> None:
    loop = SocraticLoop()
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=None)  # no existing row
    db.execute = AsyncMock()

    update = MasteryUpdate(
        concept="quadratics",
        delta=0.10,
        is_correct=True,
        confusion_signal=None,
    )
    await loop.update_mastery("user-1", update, db=db)
    db.execute.assert_called()


# ── _try_parse ────────────────────────────────────────────────────────────────

def test_try_parse_plain_number() -> None:
    loop = SocraticLoop()
    result = loop._try_parse("3")
    assert result == Integer(3)


def test_try_parse_equation_form() -> None:
    loop = SocraticLoop()
    result = loop._try_parse("x = 5")
    assert result == Integer(5)


def test_try_parse_expression() -> None:
    loop = SocraticLoop()
    result = loop._try_parse("2 + 3")
    assert result == Integer(5)


def test_try_parse_empty_returns_none() -> None:
    loop = SocraticLoop()
    assert loop._try_parse("") is None


def test_try_parse_garbage_returns_none() -> None:
    loop = SocraticLoop()
    result = loop._try_parse("I don't know what this is ???")
    assert result is None
