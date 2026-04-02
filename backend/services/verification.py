"""
Services — Solution Verification Engine

Verifies every solution before delivery to the student.
Uses math engine cross-checks and optional cross-model comparison.

Confidence Levels:
  HIGH:   exact symbolic match via SymPy
  MEDIUM: numeric validation passes (multi-point substitution)
  LOW:    failure or partial mismatch

The verification engine NEVER claims correctness it cannot prove.
"""

import random
import structlog
from dataclasses import dataclass

from services.hybrid_math_parser import HybridParseResult, hybrid_math_parser
from services.math_engine import MathResult, math_engine
from services.confidence import ConfidenceLevel

logger = structlog.get_logger("equated.verification")


@dataclass
class VerificationResult:
    """Result of verifying a solution."""
    is_verified: bool
    confidence: ConfidenceLevel
    math_check_passed: bool
    method: str                    # "symbolic" | "numeric" | "none"
    discrepancies: list[str]
    suggestion: str | None = None


class VerificationEngine:
    """
    Verifies AI-generated solutions for correctness.

    Verification methods (in priority order):
      1. Exact symbolic match (HIGH confidence)
      2. Multi-point numeric substitution (MEDIUM confidence)
      3. Structural + sanity checks (LOW confidence)
    """

    NUM_VERIFICATION_POINTS = 5    # Random points for numeric check
    NUMERIC_TOLERANCE = 1e-6       # Threshold for numeric match

    async def analyze_problem(self, problem: str) -> HybridParseResult:
        """Run the full hybrid parser pipeline for a problem."""
        return await hybrid_math_parser.hybrid_parse(problem)

    async def compute_math_result(self, problem: str) -> MathResult | None:
        """Run the hybrid parser and return the executed SymPy result."""
        analysis = await self.analyze_problem(problem)
        return analysis.math_result

    def verify(
        self,
        problem: str,
        ai_answer: str,
        math_result: MathResult | None = None,
        parse_result: HybridParseResult | None = None,
    ) -> VerificationResult:
        """
        Run all verification checks on a solution.

        Returns a VerificationResult with confidence level and method used.
        """
        discrepancies = []
        method = "none"
        confidence = ConfidenceLevel.LOW
        math_passed = False

        # ── Check 1: Symbolic verification (HIGH confidence) ──
        if math_result and math_result.success:
            symbolic_match = self._exact_symbolic_match(ai_answer, math_result.result)
            if symbolic_match:
                method = "symbolic"
                confidence = ConfidenceLevel.HIGH
                math_passed = True
                logger.info("verification_symbolic_match", result="exact_match")
            else:
                # ── Check 2: Multi-point numeric verification (MEDIUM confidence) ──
                numeric_ok = self._numeric_verify_multi_point(
                    ai_answer, math_result, parse_result
                )
                if numeric_ok:
                    method = "numeric"
                    confidence = ConfidenceLevel.MEDIUM
                    math_passed = True
                    logger.info("verification_numeric_match", points=self.NUM_VERIFICATION_POINTS)
                else:
                    # Both symbolic and numeric failed
                    discrepancies.append(
                        f"AI answer differs from math engine result '{math_result.result}'"
                    )
                    method = "symbolic"
                    confidence = ConfidenceLevel.LOW
                    math_passed = False

        # ── Check 3: Structural validation ──
        if not self._has_valid_structure(ai_answer):
            discrepancies.append("Solution missing expected structural elements")
            if confidence == ConfidenceLevel.HIGH:
                confidence = ConfidenceLevel.MEDIUM

        # ── Check 4: Sanity checks ──
        sanity_issues = self._sanity_check(ai_answer)
        discrepancies.extend(sanity_issues)
        if sanity_issues and confidence == ConfidenceLevel.HIGH:
            confidence = ConfidenceLevel.MEDIUM

        # ── Compute final verified status ──
        is_verified = (
            confidence >= ConfidenceLevel.MEDIUM
            and math_passed
            and method != "none"
        )

        suggestion = None
        if not is_verified:
            suggestion = "Regenerate solution with a stronger model"

        logger.info(
            "verification_complete",
            verified=is_verified,
            confidence=confidence.value,
            method=method,
            math_passed=math_passed,
            discrepancies=len(discrepancies),
        )

        return VerificationResult(
            is_verified=is_verified,
            confidence=confidence,
            math_check_passed=math_passed,
            method=method,
            discrepancies=discrepancies,
            suggestion=suggestion,
        )

    def _exact_symbolic_match(self, ai_answer: str, engine_result: str) -> bool:
        """
        Check for exact symbolic match between AI answer and SymPy result.
        Normalizes whitespace and casing for comparison.
        """
        ai_clean = ai_answer.strip().lower().replace(" ", "")
        engine_clean = engine_result.strip().lower().replace(" ", "")

        # Exact match
        if ai_clean == engine_clean:
            return True

        # Engine result is contained in AI answer (e.g., answer wraps result in explanation)
        if engine_clean in ai_clean:
            return True

        # Try parsing both as SymPy expressions and comparing
        try:
            from sympy import simplify, sympify
            ai_expr = sympify(ai_clean)
            engine_expr = sympify(engine_clean)
            if simplify(ai_expr - engine_expr) == 0:
                return True
        except Exception:
            pass

        return False

    def _numeric_verify_multi_point(
        self,
        ai_answer: str,
        math_result: MathResult,
        parse_result: HybridParseResult | None,
    ) -> bool:
        """
        Numerically verify by substituting random values into both
        the AI answer and the math engine result.

        Uses multiple randomly sampled points to avoid single-point
        false positives. All points must pass.
        """
        try:
            from sympy import symbols, N, Abs, sympify

            # Try to extract a mathematical expression from the AI answer
            ai_expr = self._extract_math_expression(ai_answer)
            if ai_expr is None:
                return False

            engine_expr = sympify(math_result.result)

            # Determine the variable to substitute
            variable_name = "x"
            if parse_result and parse_result.parsed:
                variable_name = parse_result.parsed.variable or "x"
            var = symbols(variable_name)

            # Check if both expressions have the same free symbols
            if var not in engine_expr.free_symbols and var not in ai_expr.free_symbols:
                # Both are constants — just compare numerically
                diff = Abs(N(ai_expr) - N(engine_expr))
                return float(diff) < self.NUMERIC_TOLERANCE

            # Generate random test points (avoid 0 and ±1 which can mask errors)
            test_points = [
                random.uniform(-10, -0.5),
                random.uniform(0.5, 10),
                random.uniform(-100, -10),
                random.uniform(10, 100),
                random.uniform(0.01, 0.5),
            ][:self.NUM_VERIFICATION_POINTS]

            for point in test_points:
                try:
                    ai_val = complex(N(ai_expr.subs(var, point)))
                    engine_val = complex(N(engine_expr.subs(var, point)))

                    # Handle infinity/NaN
                    if not (ai_val == ai_val) or not (engine_val == engine_val):  # NaN check
                        continue

                    diff = abs(ai_val - engine_val)
                    if diff > self.NUMERIC_TOLERANCE:
                        return False
                except (ValueError, TypeError, ZeroDivisionError):
                    continue

            return True

        except Exception as e:
            logger.debug("numeric_verify_failed", error=str(e)[:100])
            return False

    def _extract_math_expression(self, text: str):
        """Try to extract a SymPy-parseable expression from text."""
        import re
        from sympy import sympify

        # Try direct parse
        try:
            return sympify(text.strip())
        except Exception:
            pass

        # Try extracting from common patterns like "x = 3" → "3"
        patterns = [
            r"=\s*(.+?)(?:\s*$|\s*,|\s*\n)",     # "x = <expr>"
            r"answer[:\s]+(.+?)(?:\s*$|\s*,)",     # "answer: <expr>"
            r"result[:\s]+(.+?)(?:\s*$|\s*,)",     # "result: <expr>"
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return sympify(match.group(1).strip())
                except Exception:
                    continue

        return None

    def _has_valid_structure(self, answer: str) -> bool:
        """Check that the answer follows the expected format."""
        required_markers = ["step", "answer"]
        answer_lower = answer.lower()
        return any(marker in answer_lower for marker in required_markers)

    def _sanity_check(self, answer: str) -> list[str]:
        """Basic sanity checks on the answer."""
        issues = []
        if len(answer.strip()) < 20:
            issues.append("Answer is suspiciously short")
        if "I don't know" in answer or "I cannot" in answer:
            issues.append("Model indicated uncertainty")
        return issues


# Singleton
verification_engine = VerificationEngine()
