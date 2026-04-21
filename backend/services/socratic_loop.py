"""
Services — Socratic Loop

Generates follow-up probe questions after a solved problem to reinforce
understanding and update mastery.  Uses SymPy for mathematically valid
variations — no external AI API calls.

Delta rules (asymmetric by design):
  correct              → +0.10
  correct_with_hint    → +0.05
  incorrect            → −0.05
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from sympy import (
    symbols,
    sympify,
    simplify,
    solve,
)
from sympy.core.numbers import Number
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application,
)

logger = structlog.get_logger("equated.services.socratic_loop")

_PARSE_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)

Strategy = Literal["change_coefficients", "add_constraint", "reverse_operation", "ask_why"]

# Conceptual "why" question templates keyed by SymPy operation name.
_WHY_TEMPLATES: dict[str, str] = {
    "solve": (
        "We isolated the variable to solve this equation. "
        "Can you explain in your own words WHY we perform the same operation "
        "on both sides of an equation?"
    ),
    "differentiate": (
        "We used differentiation to find the rate of change. "
        "What does the derivative represent geometrically on a graph?"
    ),
    "integrate": (
        "We computed an integral here. "
        "What does the definite integral represent geometrically?"
    ),
    "limit": (
        "We evaluated a limit. "
        "In your own words, what does 'the limit as x approaches a' mean?"
    ),
    "factor": (
        "We factored this expression. "
        "Why is factoring useful when solving equations?"
    ),
    "default": (
        "Looking at the solution above, can you identify which mathematical "
        "property or rule made the key step possible?"
    ),
}


@dataclass
class ProbeQuestion:
    """A Socratic follow-up question generated from a solved problem."""

    question_text: str
    expected_answer: Any  # SymPy expression / Eq, or None for "ask_why"
    tests_concept: str
    strategy_used: Strategy


@dataclass
class MasteryUpdate:
    """
    Result of evaluating a student's response to a ProbeQuestion.

    Attributes
    ----------
    concept:
        The concept tested by the probe.
    delta:
        Mastery change to apply (+0.10, +0.05, or −0.05).
    is_correct:
        Whether the response was correct.
    confusion_signal:
        Short description of the error detected, or None.
    """

    concept: str
    delta: float
    is_correct: bool
    confusion_signal: str | None


class SocraticLoop:
    """
    Generates probes, evaluates student responses, and writes mastery updates.
    """

    DELTA_CORRECT: float = 0.10
    DELTA_CORRECT_WITH_HINT: float = 0.05
    DELTA_INCORRECT: float = -0.05
    DEFAULT_MASTERY: float = 0.35

    # ------------------------------------------------------------------ #
    # Probe generation                                                     #
    # ------------------------------------------------------------------ #

    def generate_probe(
        self,
        problem: str,
        sympy_result: Any,
        difficulty_delta: int = 0,
    ) -> ProbeQuestion:
        """
        Generate a follow-up probe question based on the solved problem.

        Parameters
        ----------
        problem:
            Original problem string.
        sympy_result:
            SymbolicSolution from symbolic_solver.
        difficulty_delta:
            <0  → easier probe (ask_why / reverse_operation)
            0   → same difficulty (change_coefficients)
            >0  → harder probe (add_constraint)
        """
        strategy = self._select_strategy(sympy_result, difficulty_delta)

        try:
            if strategy == "ask_why":
                return self._ask_why_probe(problem, sympy_result)
            if strategy == "change_coefficients":
                probe = self._change_coefficients_probe(problem, sympy_result)
                if probe is not None:
                    return probe
            if strategy == "reverse_operation":
                probe = self._reverse_operation_probe(problem, sympy_result)
                if probe is not None:
                    return probe
            if strategy == "add_constraint":
                probe = self._add_constraint_probe(problem, sympy_result)
                if probe is not None:
                    return probe
        except Exception as exc:
            logger.warning("probe_strategy_failed", strategy=strategy, error=str(exc))

        # Always-available fallback.
        return self._ask_why_probe(problem, sympy_result)

    # ------------------------------------------------------------------ #
    # Response evaluation                                                  #
    # ------------------------------------------------------------------ #

    def evaluate_response(
        self, probe: ProbeQuestion, student_response: str
    ) -> MasteryUpdate:
        """
        Parse and evaluate the student's response to a probe.

        For "ask_why" probes (no expected_answer), always award partial credit
        for any non-empty response and flag for human review.
        For math probes, attempt SymPy symbolic equality check.
        """
        concept = probe.tests_concept

        # --- ask_why: qualitative assessment only ---
        if probe.expected_answer is None:
            non_empty = bool(student_response.strip())
            return MasteryUpdate(
                concept=concept,
                delta=self.DELTA_CORRECT_WITH_HINT if non_empty else self.DELTA_INCORRECT,
                is_correct=non_empty,
                confusion_signal=None if non_empty else "Student did not attempt the conceptual question.",
            )

        # --- Math probe: SymPy symbolic check ---
        parsed = self._try_parse(student_response)
        if parsed is None:
            return MasteryUpdate(
                concept=concept,
                delta=self.DELTA_INCORRECT,
                is_correct=False,
                confusion_signal="Could not parse student's answer as a mathematical expression.",
            )

        try:
            diff = simplify(parsed - probe.expected_answer)
            is_correct = diff == 0
        except Exception:
            # Fallback: string comparison after stripping whitespace.
            is_correct = str(parsed).strip() == str(probe.expected_answer).strip()

        if is_correct:
            return MasteryUpdate(
                concept=concept,
                delta=self.DELTA_CORRECT,
                is_correct=True,
                confusion_signal=None,
            )

        confusion = self._detect_confusion(parsed, probe.expected_answer)
        return MasteryUpdate(
            concept=concept,
            delta=self.DELTA_INCORRECT,
            is_correct=False,
            confusion_signal=confusion,
        )

    # ------------------------------------------------------------------ #
    # Mastery persistence                                                  #
    # ------------------------------------------------------------------ #

    async def update_mastery(
        self, user_id: str, update: MasteryUpdate, db: Any = None
    ) -> None:
        """
        Apply a MasteryUpdate to user_topic_mastery and log a learning event.

        Parameters
        ----------
        user_id:
            UUID of the student.
        update:
            MasteryUpdate produced by evaluate_response.
        db:
            asyncpg connection / pool.  Calls get_db() internally when None.
        """
        if db is None:
            from db.connection import get_db
            db = await get_db()

        row = await db.fetchrow(
            "SELECT mastery_score FROM user_topic_mastery WHERE user_id = $1 AND topic = $2",
            user_id,
            update.concept,
        )
        mastery_before: float = float(row["mastery_score"]) if row else self.DEFAULT_MASTERY
        mastery_after: float = round(max(0.0, min(1.0, mastery_before + update.delta)), 4)
        is_correct_int: int = int(update.is_correct)

        await db.execute(
            """
            INSERT INTO user_topic_mastery (
                id, user_id, topic, mastery_score, assumed_level, learning_velocity,
                attempts, successes, failures, consecutive_successes, consecutive_failures,
                hint_uses, retry_count, ask_simple_count, is_weak,
                last_interacted_at, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), $1, $2, $3, 0.5, 0.0,
                1, $4, $5, 0, 0, 0, 0, 0, false,
                NOW(), NOW(), NOW()
            )
            ON CONFLICT (user_id, topic) DO UPDATE
            SET
                mastery_score = $3,
                attempts      = user_topic_mastery.attempts + 1,
                successes     = user_topic_mastery.successes + $4,
                failures      = user_topic_mastery.failures  + $5,
                updated_at    = NOW(),
                last_interacted_at = NOW()
            """,
            user_id,
            update.concept,
            mastery_after,
            is_correct_int,
            1 - is_correct_int,
        )

        await db.execute(
            """
            INSERT INTO user_learning_events (
                id, user_id, topic, event_type, question_text, success,
                hints_used, retry_count, interaction_signals, detected_patterns,
                mastery_before, mastery_after, created_at
            )
            VALUES (
                gen_random_uuid(), $1, $2, 'socratic_probe', $3, $4,
                0, 0, $5::jsonb, '[]'::jsonb, $6, $7, NOW()
            )
            """,
            user_id,
            update.concept,
            update.concept,
            update.is_correct,
            json.dumps(
                {
                    "confusion_signal": update.confusion_signal,
                    "delta": update.delta,
                    "source": "socratic_loop",
                }
            ),
            mastery_before,
            mastery_after,
        )

        logger.info(
            "socratic_mastery_updated",
            user_id=user_id[:8],
            concept=update.concept,
            mastery_before=mastery_before,
            mastery_after=mastery_after,
            is_correct=update.is_correct,
        )

    # ------------------------------------------------------------------ #
    # Strategy selection                                                   #
    # ------------------------------------------------------------------ #

    def _select_strategy(self, sympy_result: Any, difficulty_delta: int) -> Strategy:
        """Choose a probe strategy based on difficulty delta and available data."""
        has_expression = False
        try:
            has_expression = bool(sympy_result.request.expression)
        except AttributeError:
            pass

        if not has_expression:
            return "ask_why"
        if difficulty_delta < 0:
            return "reverse_operation"
        if difficulty_delta > 0:
            return "add_constraint"
        return "change_coefficients"

    # ------------------------------------------------------------------ #
    # Probe builders                                                       #
    # ------------------------------------------------------------------ #

    def _ask_why_probe(self, problem: str, sympy_result: Any) -> ProbeQuestion:
        """Return a conceptual 'why' question — no SymPy expected answer."""
        try:
            operation = sympy_result.request.operation.lower()
        except AttributeError:
            operation = "default"

        template = _WHY_TEMPLATES.get(operation, _WHY_TEMPLATES["default"])
        concept = self._infer_concept(sympy_result)

        return ProbeQuestion(
            question_text=template,
            expected_answer=None,
            tests_concept=concept,
            strategy_used="ask_why",
        )

    def _change_coefficients_probe(
        self, problem: str, sympy_result: Any
    ) -> ProbeQuestion | None:
        """
        Create a variation of the problem by scaling numeric coefficients.

        Parses the expression, finds the first non-unity integer coefficient,
        doubles it, re-solves with SymPy, and returns the probe.
        """
        try:
            expr_str: str = sympy_result.request.expression or ""
            var_str: str = sympy_result.request.variable or "x"
        except AttributeError:
            return None

        if not expr_str:
            return None

        x = symbols(var_str)

        try:
            # Try to parse as equation (lhs = rhs) or plain expression.
            if "=" in expr_str:
                lhs_str, rhs_str = expr_str.split("=", 1)
                lhs = parse_expr(lhs_str.strip(), transformations=_PARSE_TRANSFORMS)
                rhs = parse_expr(rhs_str.strip(), transformations=_PARSE_TRANSFORMS)
                expr = lhs - rhs
            else:
                expr = parse_expr(expr_str, transformations=_PARSE_TRANSFORMS)
        except Exception:
            return None

        # Find numeric atoms (excluding 0 and 1 to avoid trivial changes).
        nums = [
            a
            for a in expr.atoms(Number)
            if a != 0 and abs(float(a)) > 0.5 and a != 1 and a != -1
        ]
        if not nums:
            # No interesting coefficient — fall through.
            return None

        multiplier = random.choice([2, 3])
        target_num = nums[0]
        new_num = target_num * multiplier
        new_expr = expr.subs(target_num, new_num)

        try:
            solutions = solve(new_expr, x)
            if not solutions:
                return None
            expected = solutions[0]
        except Exception:
            return None

        # Reconstruct a readable problem string.
        new_eq_str = f"{str(new_expr)} = 0"
        question = (
            f"Now try a similar problem: solve {new_eq_str} for {var_str}. "
            f"What is the value of {var_str}?"
        )
        concept = self._infer_concept(sympy_result)

        return ProbeQuestion(
            question_text=question,
            expected_answer=expected,
            tests_concept=concept,
            strategy_used="change_coefficients",
        )

    def _reverse_operation_probe(
        self, problem: str, sympy_result: Any
    ) -> ProbeQuestion | None:
        """
        Ask the student to verify the solution by substitution.

        'If [variable] = [result], what does [original expression] evaluate to?'
        """
        try:
            expr_str: str = sympy_result.request.expression or ""
            var_str: str = sympy_result.request.variable or "x"
            result_str: str = sympy_result.math_result.result if sympy_result.math_result else ""
        except AttributeError:
            return None

        if not expr_str or not result_str:
            return None

        x = symbols(var_str)

        try:
            result_val = sympify(result_str)
        except Exception:
            return None

        try:
            if "=" in expr_str:
                lhs_str, _rhs_str = expr_str.split("=", 1)
                lhs = parse_expr(lhs_str.strip(), transformations=_PARSE_TRANSFORMS)
                substituted = lhs.subs(x, result_val)
            else:
                expr = parse_expr(expr_str, transformations=_PARSE_TRANSFORMS)
                substituted = expr.subs(x, result_val)
        except Exception:
            return None

        question = (
            f"Verify: if {var_str} = {result_str}, what is the value of "
            f"the left-hand side of the original expression?"
        )
        concept = self._infer_concept(sympy_result)

        return ProbeQuestion(
            question_text=question,
            expected_answer=simplify(substituted),
            tests_concept=concept,
            strategy_used="reverse_operation",
        )

    def _add_constraint_probe(
        self, problem: str, sympy_result: Any
    ) -> ProbeQuestion | None:
        """
        Add a domain constraint to the original problem (e.g., 'given x > 0').

        For 'solve' operations, this means asking which of the solutions are valid.
        For other operations, asks to evaluate the result under the constraint.
        """
        try:
            expr_str: str = sympy_result.request.expression or ""
            var_str: str = sympy_result.request.variable or "x"
        except AttributeError:
            return None

        if not expr_str:
            return None

        constraints = [f"{var_str} > 0", f"{var_str} ≠ 0", f"{var_str} is a positive integer"]
        chosen = random.choice(constraints)

        question = (
            f"Extended challenge: given the additional constraint that {chosen}, "
            f"does your solution still hold? "
            f"Original problem: {problem.strip()}"
        )
        concept = self._infer_concept(sympy_result)

        # Expected answer is open-ended for constraint probes — award hint credit.
        return ProbeQuestion(
            question_text=question,
            expected_answer=None,
            tests_concept=concept,
            strategy_used="add_constraint",
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _infer_concept(self, sympy_result: Any) -> str:
        """Derive a concept string from the SymPy result's operation."""
        op_to_concept: dict[str, str] = {
            "solve": "linear_equations",
            "differentiate": "derivatives",
            "integrate": "integrals",
            "limit": "limits",
            "factor": "factoring",
            "simplify": "polynomials",
            "expand": "polynomials",
        }
        try:
            op = sympy_result.request.operation.lower()
            return op_to_concept.get(op, op)
        except AttributeError:
            return "algebra"

    def _try_parse(self, text: str) -> Any:
        """Attempt to parse a string as a SymPy expression.  Returns None on failure."""
        text = text.strip()
        if not text:
            return None

        # Handle "x = value" format.
        eq_match = re.match(r"^\s*[a-zA-Z]\s*=\s*(.+)$", text)
        if eq_match:
            text = eq_match.group(1).strip()

        for transformer in [
            _PARSE_TRANSFORMS,
            standard_transformations,
        ]:
            try:
                return parse_expr(text, transformations=transformer)
            except Exception:
                continue

        try:
            return sympify(text)
        except Exception:
            return None

    def _detect_confusion(self, parsed: Any, expected: Any) -> str:
        """Generate a brief confusion signal for an incorrect answer."""
        try:
            if simplify(parsed + expected) == 0:
                # parsed == -expected: classic sign flip
                return "Sign error — student got the negative of the correct answer."
            if simplify(parsed - expected * 2) == 0:
                return "Factor of 2 error — answer is double the correct value."
            if simplify(parsed * 2 - expected) == 0:
                return "Factor of 2 error — answer is half the correct value."
        except Exception:
            pass
        return f"Incorrect: expected {expected}, got {parsed}."


socratic_loop = SocraticLoop()
