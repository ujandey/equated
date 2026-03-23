"""
Tests — Math Engine Unit Tests
"""

import pytest
from services.math_engine import MathEngine


class TestMathEngine:
    def setup_method(self):
        self.engine = MathEngine()

    def test_solve_expression(self):
        result = self.engine.solve_expression("x**2 + 2*x + 1")
        assert result.success
        assert result.result == "(x + 1)**2"

    def test_differentiate(self):
        result = self.engine.differentiate("x**3 + 2*x")
        assert result.success
        assert "3*x**2" in result.result

    def test_integrate(self):
        result = self.engine.integrate_expr("2*x")
        assert result.success
        assert "x**2" in result.result

    def test_solve_equation(self):
        result = self.engine.solve_equation("2*x + 3 = 7")
        assert result.success
        assert "2" in result.result

    def test_matrix_determinant(self):
        result = self.engine.matrix_operation([[1, 2], [3, 4]], "det")
        assert result.success
        assert result.result == "-2"

    def test_invalid_expression(self):
        result = self.engine.solve_expression("///invalid///")
        assert not result.success
        assert result.error is not None
