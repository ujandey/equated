"""
Tests — Confidence Scoring System

Tests the confidence module invariants:
  - overall = min(parse, verification)
  - verified=True impossible with overall=LOW
  - method="none" forces verification_confidence=LOW
  - String inputs auto-convert to ConfidenceLevel
"""

import pytest

from services.confidence import (
    ConfidenceLevel,
    ConfidenceReport,
    compute_confidence_report,
)


class TestConfidenceLevel:
    """Tests for the ConfidenceLevel enum ordering."""

    def test_ordering(self):
        assert ConfidenceLevel.LOW < ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.MEDIUM < ConfidenceLevel.HIGH
        assert not ConfidenceLevel.HIGH < ConfidenceLevel.LOW

    def test_minimum(self):
        assert ConfidenceLevel.minimum(ConfidenceLevel.HIGH, ConfidenceLevel.LOW) == ConfidenceLevel.LOW
        assert ConfidenceLevel.minimum(ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.minimum(ConfidenceLevel.HIGH, ConfidenceLevel.HIGH) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.minimum(ConfidenceLevel.LOW, ConfidenceLevel.LOW) == ConfidenceLevel.LOW

    def test_from_string(self):
        assert ConfidenceLevel.from_string("high") == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_string("HIGH") == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_string("medium") == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_string("low") == ConfidenceLevel.LOW

    def test_from_string_invalid_defaults_to_low(self):
        assert ConfidenceLevel.from_string("invalid") == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_string("") == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_string(None) == ConfidenceLevel.LOW


class TestComputeConfidenceReport:
    """Tests for the core confidence computation function."""

    def test_high_confidence_verified(self):
        """HIGH parse + HIGH verification + symbolic → verified=True."""
        report = compute_confidence_report(
            parse_confidence="high",
            verification_confidence="high",
            method="symbolic",
            parser_source="heuristic",
            math_check_passed=True,
        )
        assert report.verified is True
        assert report.overall_confidence == ConfidenceLevel.HIGH
        assert report.method == "symbolic"

    def test_medium_confidence_verified(self):
        """MEDIUM parse + MEDIUM verification + numeric → verified=True."""
        report = compute_confidence_report(
            parse_confidence="medium",
            verification_confidence="medium",
            method="numeric",
            parser_source="llm",
            math_check_passed=True,
        )
        assert report.verified is True
        assert report.overall_confidence == ConfidenceLevel.MEDIUM

    def test_low_confidence_never_verified(self):
        """LOW overall → verified MUST be False (hard invariant)."""
        report = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="high",
            method="symbolic",
            parser_source="heuristic",
            math_check_passed=True,
        )
        assert report.verified is False
        assert report.overall_confidence == ConfidenceLevel.LOW

    def test_low_parse_forces_low_overall(self):
        """Low parse confidence always drags overall down."""
        report = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="high",
            method="symbolic",
            parser_source="failed",
            math_check_passed=True,
        )
        assert report.overall_confidence == ConfidenceLevel.LOW
        assert report.verified is False

    def test_method_none_forces_low_verification(self):
        """method='none' → verification_confidence forced to LOW."""
        report = compute_confidence_report(
            parse_confidence="high",
            verification_confidence="high",  # will be overridden
            method="none",
            parser_source="skipped",
            math_check_passed=True,
        )
        assert report.verification_confidence == ConfidenceLevel.LOW
        assert report.overall_confidence == ConfidenceLevel.LOW
        assert report.verified is False

    def test_math_check_failed_not_verified(self):
        """Even with HIGH confidence, math_check_passed=False → not verified."""
        report = compute_confidence_report(
            parse_confidence="high",
            verification_confidence="high",
            method="symbolic",
            parser_source="heuristic",
            math_check_passed=False,
        )
        assert report.verified is False
        assert report.overall_confidence == ConfidenceLevel.HIGH  # overall is still high

    def test_minimum_rule(self):
        """overall = min(parse, verification)."""
        report = compute_confidence_report(
            parse_confidence="high",
            verification_confidence="medium",
            method="numeric",
            parser_source="heuristic",
            math_check_passed=True,
        )
        assert report.overall_confidence == ConfidenceLevel.MEDIUM
        assert report.verified is True

    def test_failure_reason_preserved(self):
        """failure_reason should be stored in the report."""
        report = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="low",
            method="none",
            parser_source="skipped",
            math_check_passed=False,
            failure_reason="no_math_intent",
        )
        assert report.failure_reason == "no_math_intent"

    def test_report_is_frozen(self):
        """ConfidenceReport should be immutable."""
        report = compute_confidence_report(
            parse_confidence="high",
            verification_confidence="high",
            method="symbolic",
            parser_source="heuristic",
            math_check_passed=True,
        )
        with pytest.raises(AttributeError):
            report.verified = False

    def test_string_inputs_auto_convert(self):
        """String confidence values should auto-convert to ConfidenceLevel."""
        report = compute_confidence_report(
            parse_confidence="medium",
            verification_confidence="high",
            method="symbolic",
            parser_source="heuristic",
            math_check_passed=True,
        )
        assert isinstance(report.parse_confidence, ConfidenceLevel)
        assert isinstance(report.verification_confidence, ConfidenceLevel)


class TestVerificationDowngrade:
    """Tests for verification downgrade scenarios."""

    def test_no_math_intent_produces_low_report(self):
        """Non-math queries should get method=none, overall=LOW."""
        report = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="low",
            method="none",
            parser_source="skipped",
            math_check_passed=False,
            failure_reason="no_math_intent",
        )
        assert report.verified is False
        assert report.overall_confidence == ConfidenceLevel.LOW
        assert report.method == "none"
        assert report.parser_source == "skipped"

    def test_parse_failure_downgrade(self):
        """Parser failure → overall can't be above LOW."""
        report = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="medium",
            method="numeric",
            parser_source="failed",
            math_check_passed=True,
        )
        assert report.overall_confidence == ConfidenceLevel.LOW
        assert report.verified is False
