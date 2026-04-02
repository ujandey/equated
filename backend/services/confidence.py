"""
Services — Confidence Scoring System

Central module for computing multi-dimensional confidence reports.
Every solution must pass through this before being returned to the user.

Invariants:
  - overall_confidence = min(parse_confidence, verification_confidence)
  - verified=True is IMPOSSIBLE when overall_confidence=LOW
  - Every decision is fully traceable via structured fields
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass

import structlog

logger = structlog.get_logger("equated.services.confidence")


class ConfidenceLevel(str, Enum):
    """Three-tier confidence level."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def __lt__(self, other: "ConfidenceLevel") -> bool:
        order = {ConfidenceLevel.LOW: 0, ConfidenceLevel.MEDIUM: 1, ConfidenceLevel.HIGH: 2}
        return order[self] < order[other]

    def __le__(self, other: "ConfidenceLevel") -> bool:
        return self == other or self < other

    def __gt__(self, other: "ConfidenceLevel") -> bool:
        order = {ConfidenceLevel.LOW: 0, ConfidenceLevel.MEDIUM: 1, ConfidenceLevel.HIGH: 2}
        return order[self] > order[other]

    def __ge__(self, other: "ConfidenceLevel") -> bool:
        return self == other or self > other

    @classmethod
    def minimum(cls, a: "ConfidenceLevel", b: "ConfidenceLevel") -> "ConfidenceLevel":
        """Return the lower of two confidence levels."""
        if a < b:
            return a
        return b

    @classmethod
    def from_string(cls, s: str) -> "ConfidenceLevel":
        """Convert a string to ConfidenceLevel, defaulting to LOW."""
        try:
            return cls(s.lower())
        except (ValueError, AttributeError):
            return cls.LOW


@dataclass(frozen=True)
class ConfidenceReport:
    """
    Multi-dimensional confidence report for a solution.

    This is the single source of truth for whether a solution should be
    trusted. Every field is explicitly set — no implicit defaults.
    """
    verified: bool
    parse_confidence: ConfidenceLevel
    verification_confidence: ConfidenceLevel
    overall_confidence: ConfidenceLevel
    method: str          # "symbolic" | "numeric" | "none"
    parser_source: str   # "heuristic" | "llm" | "heuristic_fallback" | "failed" | "skipped"
    failure_reason: str | None = None


def compute_confidence_report(
    parse_confidence: ConfidenceLevel | str,
    verification_confidence: ConfidenceLevel | str,
    method: str,
    parser_source: str,
    math_check_passed: bool,
    failure_reason: str | None = None,
) -> ConfidenceReport:
    """
    Compute a full confidence report from parse + verification results.

    Rules:
      1. overall = min(parse, verification)
      2. verified = True requires: overall >= MEDIUM AND math_check_passed
      3. verified = False whenever overall == LOW (hard invariant)
      4. method="none" forces verification_confidence=LOW
    """
    # Normalize string inputs
    if isinstance(parse_confidence, str):
        parse_confidence = ConfidenceLevel.from_string(parse_confidence)
    if isinstance(verification_confidence, str):
        verification_confidence = ConfidenceLevel.from_string(verification_confidence)

    # Rule 4: no verification method → LOW
    if method == "none":
        verification_confidence = ConfidenceLevel.LOW

    # Rule 1: overall = min
    overall = ConfidenceLevel.minimum(parse_confidence, verification_confidence)

    # Rule 2 & 3: verification decision
    verified = (
        overall >= ConfidenceLevel.MEDIUM
        and math_check_passed
        and method != "none"
    )

    report = ConfidenceReport(
        verified=verified,
        parse_confidence=parse_confidence,
        verification_confidence=verification_confidence,
        overall_confidence=overall,
        method=method,
        parser_source=parser_source,
        failure_reason=failure_reason,
    )

    logger.info(
        "confidence_report",
        verified=report.verified,
        parse_confidence=report.parse_confidence.value,
        verification_confidence=report.verification_confidence.value,
        overall_confidence=report.overall_confidence.value,
        method=report.method,
        parser_source=report.parser_source,
        failure_reason=report.failure_reason,
    )

    return report
