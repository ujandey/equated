"""
Tests — Security: Environment Validation & Razorpay

Tests:
  - Environment validation catches missing AI keys
  - Environment validation warns on missing optional keys
  - Razorpay webhook disabled when secret not configured
  - Strict LLM JSON validation rejects bad inputs
"""

import pytest
from unittest.mock import patch, MagicMock

from config.settings import Settings


class TestEnvironmentValidation:
    """Tests for the startup environment validation."""

    def test_no_ai_keys_raises_system_exit(self):
        """If no AI provider keys are set, startup must abort."""
        settings = Settings(
            DEEPSEEK_API_KEY="",
            GROQ_API_KEY="",
            OPENAI_API_KEY="",
            MISTRAL_API_KEY="",
            GEMINI_API_KEY="",
        )
        with pytest.raises(SystemExit):
            settings.validate_critical_env()

    def test_placeholder_keys_raise_system_exit(self):
        """Placeholder values should be treated as missing."""
        settings = Settings(
            DEEPSEEK_API_KEY="your-deepseek-key",
            GROQ_API_KEY="your-groq-key",
            OPENAI_API_KEY="",
            MISTRAL_API_KEY="",
            GEMINI_API_KEY="",
        )
        with pytest.raises(SystemExit):
            settings.validate_critical_env()

    def test_single_valid_key_passes(self):
        """At least one valid key should pass validation."""
        settings = Settings(
            DEEPSEEK_API_KEY="sk-real-key-12345",
            GROQ_API_KEY="",
            OPENAI_API_KEY="",
            MISTRAL_API_KEY="",
            GEMINI_API_KEY="",
        )
        # Should NOT raise
        settings.validate_critical_env()

    def test_has_any_ai_provider_property(self):
        """Test the has_any_ai_provider computed property."""
        settings_empty = Settings(
            DEEPSEEK_API_KEY="",
            GROQ_API_KEY="",
            OPENAI_API_KEY="",
            MISTRAL_API_KEY="",
            GEMINI_API_KEY="",
        )
        assert settings_empty.has_any_ai_provider is False

        settings_one = Settings(
            DEEPSEEK_API_KEY="sk-valid",
            GROQ_API_KEY="",
            OPENAI_API_KEY="",
            MISTRAL_API_KEY="",
            GEMINI_API_KEY="",
        )
        assert settings_one.has_any_ai_provider is True

    def test_razorpay_configured_property(self):
        """Test the razorpay_configured computed property."""
        settings_no = Settings(
            RAZORPAY_KEY_ID="",
            RAZORPAY_KEY_SECRET="",
            RAZORPAY_WEBHOOK_SECRET="",
        )
        assert settings_no.razorpay_configured is False

        settings_partial = Settings(
            RAZORPAY_KEY_ID="rzp_live_xxx",
            RAZORPAY_KEY_SECRET="secret123",
            RAZORPAY_WEBHOOK_SECRET="",
        )
        assert settings_partial.razorpay_configured is False

        settings_full = Settings(
            RAZORPAY_KEY_ID="rzp_live_xxx",
            RAZORPAY_KEY_SECRET="secret123",
            RAZORPAY_WEBHOOK_SECRET="webhook_secret",
        )
        assert settings_full.razorpay_configured is True

    def test_placeholder_detection(self):
        """Test that common placeholder values are detected."""
        settings = Settings()
        assert settings._is_placeholder("your-deepseek-key") is True
        assert settings._is_placeholder("your-custom-thing") is True  # starts with "your-"
        assert settings._is_placeholder("sk-real-api-key-12345") is False
        assert settings._is_placeholder("") is False  # empty is not a placeholder


class TestLLMJsonValidation:
    """Tests for strict LLM JSON validation in the parser."""

    @pytest.fixture
    def parser(self):
        from services.hybrid_math_parser import HybridMathParser
        return HybridMathParser()

    def test_valid_json_passes(self, parser):
        """Well-formed math JSON should have no errors."""
        valid = {
            "operation": "solve",
            "expression": "x**2 - 4",
            "variable": "x",
        }
        errors = parser._validate_llm_json_strict(valid)
        assert errors == []

    def test_empty_expression_rejected(self, parser):
        errors = parser._validate_llm_json_strict({
            "operation": "solve",
            "expression": "",
        })
        assert len(errors) > 0
        assert any("Empty expression" in e for e in errors)

    def test_text_in_expression_rejected(self, parser):
        """Natural language words in expression should be flagged."""
        errors = parser._validate_llm_json_strict({
            "operation": "solve",
            "expression": "the value of x plus three",
        })
        assert len(errors) > 0
        assert any("Suspicious token" in e for e in errors)

    def test_valid_math_functions_allowed(self, parser):
        """sin, cos, log, etc. should NOT be rejected."""
        errors = parser._validate_llm_json_strict({
            "operation": "evaluate",
            "expression": "sin(pi/4) + cos(pi/3) + log(10)",
        })
        assert errors == []

    def test_multi_equals_in_solve_rejected(self, parser):
        """solve with multiple '=' signs should be rejected."""
        errors = parser._validate_llm_json_strict({
            "operation": "solve",
            "expression": "x = y = 5",
        })
        assert len(errors) > 0
        assert any("'='" in e for e in errors)

    def test_invalid_variable_rejected(self, parser):
        """Variables must be single letters."""
        errors = parser._validate_llm_json_strict({
            "operation": "solve",
            "expression": "x**2",
            "variable": "xyz",
        })
        assert len(errors) > 0
        assert any("Invalid variable" in e for e in errors)

    def test_invalid_bounds_rejected(self, parser):
        """Bounds must be a 2-element list."""
        errors = parser._validate_llm_json_strict({
            "operation": "integrate",
            "expression": "x**2",
            "bounds": [0, 1, 2],  # 3 elements
        })
        assert len(errors) > 0
        assert any("Invalid bounds" in e for e in errors)

    def test_sympy_names_allowed(self, parser):
        """SymPy-specific names like Abs, Rational should be allowed."""
        errors = parser._validate_llm_json_strict({
            "operation": "evaluate",
            "expression": "Abs(Rational(1, 3))",
        })
        assert errors == []
