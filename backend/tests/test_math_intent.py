"""
Tests — Math Intent Detector

Tests the is_math_like() function for various input categories:
  - Greetings / pleasantries → False
  - Math equations → True
  - STEM keywords → True
  - Ambiguous inputs → conservative (True)
  - Code → True (should be routed to AI)
  - Empty / short → False
"""

from services.math_intent_detector import is_math_like


class TestMathIntentPositive:
    """Inputs that SHOULD be detected as math-like."""

    def test_simple_equation(self):
        assert is_math_like("solve 2x + 3 = 5")

    def test_quadratic(self):
        assert is_math_like("x^2 + 3x - 10 = 0")

    def test_integral(self):
        assert is_math_like("integrate sin(x) dx from 0 to pi")

    def test_derivative(self):
        assert is_math_like("differentiate e^x * sin(x)")

    def test_matrix(self):
        assert is_math_like("find the determinant of the matrix [[1,2],[3,4]]")

    def test_latex_expression(self):
        assert is_math_like("\\frac{d}{dx} x^2 + 3x")

    def test_math_symbols(self):
        assert is_math_like("∫ x² dx = x³/3 + C")

    def test_physics_problem(self):
        assert is_math_like("calculate the velocity if acceleration = 9.8 m/s²")

    def test_chemistry_stoichiometry(self):
        assert is_math_like("balance the equation for the oxidation of iron")

    def test_pure_numbers(self):
        assert is_math_like("123 + 456 * 789")

    def test_variable_expression(self):
        assert is_math_like("2x + 3y = 10")

    def test_trigonometric(self):
        assert is_math_like("find sin(45)")

    def test_logarithmic(self):
        assert is_math_like("log(100) + ln(e)")

    def test_limit(self):
        assert is_math_like("find the limit of 1/x as x approaches infinity")

    def test_probability(self):
        assert is_math_like("what is the probability of rolling a 6 twice?")

    def test_code_content(self):
        """Code should be sent to AI (math-like returns True for routing)."""
        assert is_math_like("def fibonacci(n): return n if n < 2 else fib(n-1) + fib(n-2)")

    def test_algebraic_term(self):
        assert is_math_like("simplify 3x^2 + 2x - 5")


class TestMathIntentNegative:
    """Inputs that should NOT be detected as math-like."""

    def test_greeting_hello(self):
        assert not is_math_like("hello")

    def test_greeting_hi(self):
        assert not is_math_like("hi")

    def test_greeting_hey(self):
        assert not is_math_like("hey")

    def test_thanks(self):
        assert not is_math_like("thanks")

    def test_thank_you(self):
        assert not is_math_like("thank you")

    def test_bye(self):
        assert not is_math_like("bye")

    def test_who_are_you(self):
        assert not is_math_like("who are you")

    def test_empty(self):
        assert not is_math_like("")

    def test_whitespace(self):
        assert not is_math_like("   ")

    def test_single_char(self):
        assert not is_math_like("a")

    def test_ok(self):
        assert not is_math_like("ok")


class TestMathIntentEdgeCases:
    """Edge cases and ambiguous inputs."""

    def test_mixed_greeting_with_math(self):
        """If greeting includes math, should return True due to length."""
        assert is_math_like("hello, can you solve x^2 + 3x = 10 for me?")

    def test_explain_concept(self):
        """STEM keyword should trigger positive."""
        assert is_math_like("explain the theorem of Pythagoras")

    def test_numeric_heavy_text(self):
        """High digit ratio should trigger positive."""
        assert is_math_like("12345678901234567890")

    def test_none_input(self):
        """None should not crash."""
        assert not is_math_like(None)

    def test_very_long_greeting(self):
        """Long greetings shouldn't match the short-greeting filter."""
        long_input = "hello how are you today I hope you are doing well"
        # This is long enough to skip the greeting filter, but has no math
        result = is_math_like(long_input)
        assert not result


class TestCacheKeyUniqueness:
    """Tests that cache keys differentiate operations correctly."""

    def test_different_ops_same_expr(self):
        from services.query_normalizer import query_normalizer

        key_solve = query_normalizer.generate_cache_key(
            "x^2", operation="solve", expression="x**2"
        )
        key_diff = query_normalizer.generate_cache_key(
            "x^2", operation="differentiate", expression="x**2"
        )
        assert key_solve != key_diff

    def test_same_op_same_expr(self):
        from services.query_normalizer import query_normalizer

        key1 = query_normalizer.generate_cache_key(
            "solve x^2=4", operation="solve", expression="x**2-4"
        )
        key2 = query_normalizer.generate_cache_key(
            "solve x^2=4", operation="solve", expression="x**2-4"
        )
        assert key1 == key2

    def test_backward_compat_no_operation(self):
        """Without operation/expression, key should still work."""
        from services.query_normalizer import query_normalizer

        key = query_normalizer.generate_cache_key("solve x^2")
        assert len(key) == 32
