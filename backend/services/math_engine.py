"""
Services — Math Engine (SymPy)

Symbolic computation engine for guaranteed mathematical correctness.
LLMs should NEVER do arithmetic — this engine handles:
  - Symbolic algebra and simplification
  - Calculus (derivatives, integrals)
  - Equation solving
  - Matrix operations
"""

from dataclasses import dataclass
from sympy import (
    symbols, sympify, simplify, expand, factor,
    diff, integrate, limit, solve, Matrix,
    latex, oo, pi, E, I
)
from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations,
    implicit_multiplication_application,
)


@dataclass
class MathResult:
    """Result of a symbolic computation."""
    expression: str       # Input expression
    result: str          # Computed result (string)
    latex_result: str    # LaTeX-formatted result
    steps: list[str]     # Intermediate steps
    success: bool
    error: str | None = None


class MathEngine:
    """SymPy-powered symbolic math computation engine."""

    TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)

    def solve_expression(self, expr_str: str) -> MathResult:
        """Parse and simplify a mathematical expression."""
        try:
            expr = parse_expr(expr_str, transformations=self.TRANSFORMATIONS)
            result = simplify(expr)
            return MathResult(
                expression=expr_str,
                result=str(result),
                latex_result=latex(result),
                steps=[f"Input: {expr_str}", f"Simplified: {result}"],
                success=True,
            )
        except Exception as e:
            return MathResult(
                expression=expr_str, result="", latex_result="",
                steps=[], success=False, error=str(e),
            )

    def differentiate(self, expr_str: str, var: str = "x") -> MathResult:
        """Compute the derivative of an expression."""
        try:
            x = symbols(var)
            expr = parse_expr(expr_str, transformations=self.TRANSFORMATIONS)
            result = diff(expr, x)
            return MathResult(
                expression=f"d/d{var}({expr_str})",
                result=str(result),
                latex_result=latex(result),
                steps=[
                    f"Expression: {expr}",
                    f"Differentiate with respect to {var}",
                    f"Result: {result}",
                ],
                success=True,
            )
        except Exception as e:
            return MathResult(
                expression=expr_str, result="", latex_result="",
                steps=[], success=False, error=str(e),
            )

    def integrate_expr(self, expr_str: str, var: str = "x") -> MathResult:
        """Compute the indefinite integral of an expression."""
        try:
            x = symbols(var)
            expr = parse_expr(expr_str, transformations=self.TRANSFORMATIONS)
            result = integrate(expr, x)
            return MathResult(
                expression=f"∫({expr_str}) d{var}",
                result=str(result) + " + C",
                latex_result=latex(result) + " + C",
                steps=[
                    f"Expression: {expr}",
                    f"Integrate with respect to {var}",
                    f"Result: {result} + C",
                ],
                success=True,
            )
        except Exception as e:
            return MathResult(
                expression=expr_str, result="", latex_result="",
                steps=[], success=False, error=str(e),
            )

    def solve_equation(self, equation_str: str, var: str = "x") -> MathResult:
        """Solve an equation for a given variable."""
        try:
            x = symbols(var)
            # Handle "expr = value" format
            if "=" in equation_str:
                lhs, rhs = equation_str.split("=", 1)
                expr = parse_expr(lhs, transformations=self.TRANSFORMATIONS) - parse_expr(rhs, transformations=self.TRANSFORMATIONS)
            else:
                expr = parse_expr(equation_str, transformations=self.TRANSFORMATIONS)

            solutions = solve(expr, x)
            return MathResult(
                expression=equation_str,
                result=str(solutions),
                latex_result=", ".join(latex(s) for s in solutions),
                steps=[
                    f"Equation: {equation_str}",
                    f"Solving for {var}",
                    f"Solutions: {solutions}",
                ],
                success=True,
            )
        except Exception as e:
            return MathResult(
                expression=equation_str, result="", latex_result="",
                steps=[], success=False, error=str(e),
            )

    def matrix_operation(self, matrix_data: list[list], operation: str = "det") -> MathResult:
        """Perform matrix operations (det, inverse, eigenvalues, etc.)."""
        try:
            m = Matrix(matrix_data)
            if operation == "det":
                result = m.det()
            elif operation == "inverse":
                result = m.inv()
            elif operation == "eigenvalues":
                result = m.eigenvals()
            elif operation == "rref":
                result = m.rref()
            else:
                return MathResult(
                    expression=str(matrix_data), result="", latex_result="",
                    steps=[], success=False, error=f"Unknown operation: {operation}",
                )

            return MathResult(
                expression=f"{operation}({matrix_data})",
                result=str(result),
                latex_result=latex(result),
                steps=[f"Matrix: {m}", f"Operation: {operation}", f"Result: {result}"],
                success=True,
            )
        except Exception as e:
            return MathResult(
                expression=str(matrix_data), result="", latex_result="",
                steps=[], success=False, error=str(e),
            )


# Singleton
math_engine = MathEngine()
