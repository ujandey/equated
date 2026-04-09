"""
Services — Math Engine (SymPy)

Symbolic computation engine for guaranteed mathematical correctness.
LLMs should NEVER do arithmetic — this engine handles:
  - Symbolic algebra and simplification
  - Calculus (derivatives, integrals)
  - Equation solving
  - Matrix operations

All operations route through SympySandbox for resource isolation.
When sandbox is disabled (dev mode), falls back to direct SymPy calls.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass

from sympy import (
    symbols, sympify, simplify, expand, factor,
    diff, integrate, limit, solve, Matrix,
    latex, oo, pi, E, I
)
from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)

from config.settings import settings

logger = structlog.get_logger("equated.services.math_engine")


@dataclass
class MathResult:
    """Result of a symbolic computation."""
    expression: str       # Input expression
    result: str          # Computed result (string)
    latex_result: str    # LaTeX-formatted result
    steps: list[str]     # Intermediate steps
    success: bool
    error: str | None = None
    compute_seconds: float = 0.0    # Measured by sandbox (billing authority)
    node_count: int = 0             # SymPy nodes processed


class MathEngine:
    """
    SymPy-powered symbolic math computation engine.

    When SYMPY_SUBPROCESS_ENABLED is True (production):
      All operations route through SympySandbox subprocess isolation.
      SymPy runs in a separate process with memory/CPU/timeout limits.

    When SYMPY_SUBPROCESS_ENABLED is False (development):
      Operations execute directly in-process with a threading.Timer soft guard.
      WARNING: No memory isolation in this mode.
    """

    TRANSFORMATIONS = standard_transformations + (
        implicit_multiplication_application,
        convert_xor,
    )

    def parse_symbolic_expression(self, expr_str: str):
        """Parse a symbolic expression with the engine's standard transformations."""
        return parse_expr(expr_str, transformations=self.TRANSFORMATIONS)

    async def solve_expression_sandboxed(self, expr_str: str) -> MathResult:
        """Parse and simplify a mathematical expression via sandbox."""
        return await self._run_sandboxed("simplify", expr_str)

    async def differentiate_sandboxed(self, expr_str: str, var: str = "x") -> MathResult:
        """Compute the derivative of an expression via sandbox."""
        return await self._run_sandboxed("differentiate", expr_str, var)

    async def integrate_expr_sandboxed(self, expr_str: str, var: str = "x", bounds: list | None = None) -> MathResult:
        """Compute the indefinite/definite integral via sandbox."""
        extra = {}
        if bounds and len(bounds) == 2:
            extra["bounds"] = bounds
        return await self._run_sandboxed("integrate", expr_str, var, extra)

    async def solve_equation_sandboxed(self, equation_str: str, var: str = "x") -> MathResult:
        """Solve an equation for a given variable via sandbox."""
        return await self._run_sandboxed("solve", equation_str, var)

    async def evaluate_expr_sandboxed(self, expr_str: str) -> MathResult:
        """Evaluate a symbolic or numeric expression via sandbox."""
        return await self._run_sandboxed("evaluate", expr_str)

    async def limit_expr_sandboxed(self, expr_str: str, var: str = "x", to_value: str = "0") -> MathResult:
        """Compute the limit of an expression via sandbox."""
        return await self._run_sandboxed("limit", expr_str, var, {"to": to_value})

    async def _run_sandboxed(
        self,
        operation: str,
        expression: str,
        variable: str = "x",
        extra: dict | None = None,
    ) -> MathResult:
        """
        Route an operation through the SymPy sandbox.

        Returns MathResult with measured compute_seconds from the sandbox.
        """
        from services.sympy_sandbox import sympy_sandbox

        sandbox_result = await sympy_sandbox.execute_guarded(
            operation=operation,
            expression=expression,
            variable=variable,
            extra=extra,
        )

        if sandbox_result.killed:
            logger.warning(
                "math_engine_sandbox_killed",
                operation=operation,
                expression=expression[:100],
                kill_reason=sandbox_result.kill_reason,
                compute_seconds=sandbox_result.compute_seconds,
            )
            return MathResult(
                expression=expression,
                result="",
                latex_result="",
                steps=[],
                success=False,
                error=sandbox_result.error or f"Computation killed: {sandbox_result.kill_reason}",
                compute_seconds=sandbox_result.compute_seconds,
                node_count=sandbox_result.node_count,
            )

        return MathResult(
            expression=expression,
            result=sandbox_result.result_text,
            latex_result=sandbox_result.latex_result,
            steps=list(sandbox_result.steps),
            success=sandbox_result.success,
            error=sandbox_result.error,
            compute_seconds=sandbox_result.compute_seconds,
            node_count=sandbox_result.node_count,
        )

    # ── Legacy synchronous methods (preserved for backward compatibility) ──
    # These are used by code paths that don't need sandbox isolation
    # (e.g., numeric_check in hybrid_math_parser, verify_solution in symbolic_solver).
    # They run in-process without resource limits — only safe for SMALL expressions
    # that have already passed AST guard validation.

    def solve_expression(self, expr_str: str) -> MathResult:
        """Parse and simplify a mathematical expression."""
        try:
            expr = self.parse_symbolic_expression(expr_str)
            result = factor(simplify(expr))
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
            expr = self.parse_symbolic_expression(expr_str)
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
            expr = self.parse_symbolic_expression(expr_str)
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
                expr = self.parse_symbolic_expression(lhs) - self.parse_symbolic_expression(rhs)
            else:
                expr = self.parse_symbolic_expression(equation_str)

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

    def evaluate_expr(self, expr_str: str) -> MathResult:
        """Evaluate a symbolic or numeric expression."""
        try:
            expr = self.parse_symbolic_expression(expr_str)
            result = expr.evalf() if expr.free_symbols == set() else simplify(expr)
            return MathResult(
                expression=expr_str,
                result=str(result),
                latex_result=latex(result),
                steps=[f"Expression: {expr}", f"Evaluated: {result}"],
                success=True,
            )
        except Exception as e:
            return MathResult(
                expression=expr_str, result="", latex_result="",
                steps=[], success=False, error=str(e),
            )

    def limit_expr(self, expr_str: str, var: str = "x", to_value: str = "0") -> MathResult:
        """Compute the limit of an expression."""
        try:
            x = symbols(var)
            expr = self.parse_symbolic_expression(expr_str)
            approach = self.parse_symbolic_expression(to_value)
            result = limit(expr, x, approach)
            return MathResult(
                expression=f"limit({expr_str}, {var}, {to_value})",
                result=str(result),
                latex_result=latex(result),
                steps=[
                    f"Expression: {expr}",
                    f"Variable: {var}",
                    f"Approach value: {approach}",
                    f"Limit: {result}",
                ],
                success=True,
            )
        except Exception as e:
            return MathResult(
                expression=expr_str, result="", latex_result="",
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
