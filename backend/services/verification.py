"""
Services — Solution Verification Engine

Verifies every solution before delivery to the student.
Uses math engine cross-checks and optional cross-model comparison.
"""

import structlog
from dataclasses import dataclass

from services.math_engine import math_engine, MathResult

logger = structlog.get_logger("equated.verification")


@dataclass
class VerificationResult:
    """Result of verifying a solution."""
    is_verified: bool
    confidence: float          # 0.0 - 1.0
    math_check_passed: bool
    discrepancies: list[str]
    suggestion: str | None = None


class VerificationEngine:
    """
    Verifies AI-generated solutions for correctness.

    Verification methods:
      1. Math engine re-computation (primary)
      2. Cross-model comparison (optional, for ambiguous problems)
      3. Format validation (structural checks)
    """

    CONFIDENCE_THRESHOLD = 0.85

    def verify(self, problem: str, ai_answer: str, math_result: MathResult | None = None) -> VerificationResult:
        """Run all verification checks on a solution."""
        discrepancies = []
        math_passed = True
        confidence = 0.9

        # Check 1: Math engine verification
        if math_result and math_result.success:
            if not self._answers_match(ai_answer, math_result.result):
                discrepancies.append(
                    f"AI answer '{ai_answer}' differs from math engine result '{math_result.result}'"
                )
                math_passed = False
                confidence -= 0.4

        # Check 2: Format validation
        if not self._has_valid_structure(ai_answer):
            discrepancies.append("Solution missing expected structural elements")
            confidence -= 0.1

        # Check 3: Sanity checks
        sanity_issues = self._sanity_check(ai_answer)
        discrepancies.extend(sanity_issues)
        confidence -= len(sanity_issues) * 0.05

        is_verified = confidence >= self.CONFIDENCE_THRESHOLD and math_passed
        suggestion = None
        if not is_verified:
            suggestion = "Regenerate solution with a stronger model"

        logger.info(
            "verification_complete",
            verified=is_verified,
            confidence=round(confidence, 2),
            discrepancies=len(discrepancies),
        )

        return VerificationResult(
            is_verified=is_verified,
            confidence=max(0.0, min(1.0, confidence)),
            math_check_passed=math_passed,
            discrepancies=discrepancies,
            suggestion=suggestion,
        )

    def _answers_match(self, ai_answer: str, engine_result: str) -> bool:
        """Compare AI answer with math engine result (fuzzy)."""
        # Normalize both for comparison
        ai_clean = ai_answer.strip().lower().replace(" ", "")
        engine_clean = engine_result.strip().lower().replace(" ", "")
        return ai_clean == engine_clean or engine_clean in ai_clean

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
