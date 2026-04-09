"""
Services - Symbolic Solver

Deterministic SymPy-first solver for math problems.
The LLM may only explain a verified symbolic result; it must never invent
or infer the underlying equation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

from sympy import Abs, N, simplify, symbols
from sympy.core.expr import Expr
from sympy.core.relational import Relational

import structlog
from services.confidence import ConfidenceLevel
from services.math_engine import MathResult, math_engine
from services.math_intent_detector import is_math_like

logger = structlog.get_logger("equated.services.symbolic_solver")

# Lazy import to avoid circular dependency
_ast_guard = None

def _get_ast_guard():
    global _ast_guard
    if _ast_guard is None:
        from services.ast_guard import ast_guard
        _ast_guard = ast_guard
    return _ast_guard


_RAW_EXPRESSION_PATTERN = re.compile(
    r"^[\s\da-zA-Z\+\-\*/\^\(\)=\.,]+$"
)
_EXPRESSION_HINT_PATTERN = re.compile(
    r"\d|[+\-*/=^()]|\b(?:x|y|z|t|w)\b|"
    r"\b(?:sin|cos|tan|cot|sec|csc|log|ln|exp|sqrt|abs|pi|e)\b",
    re.IGNORECASE,
)
_ABSTRACT_OPERATION_TOKENS = {
    "a", "an", "the", "double", "second", "first",
    "derivative", "differentiate", "differentiation",
    "integral", "integrate", "integration",
    "equation", "expression", "function", "limit",
    "problem", "sum", "product", "value",
}


@dataclass(frozen=True)
class ExtractedExpression:
    operation: str
    expression: str | None = None
    variable: str | None = "x"
    bounds: list[Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    needs_clarification: bool = False
    clarification_message: str | None = None


@dataclass(frozen=True)
class SymbolicSolution:
    request: ExtractedExpression
    math_result: MathResult | None
    success: bool
    verified: bool
    verification_confidence: ConfidenceLevel
    method: str
    error: str | None = None


class SymbolicSolver:
    """Deterministic symbolic solver built on SymPy and heuristic parsing."""

    def detect_math_problem(self, query: str) -> bool:
        return is_math_like(query)

    def extract_expression(self, query: str) -> ExtractedExpression:
        cleaned = (query or "").strip()
        if not cleaned:
            return ExtractedExpression(
                operation="unknown",
                needs_clarification=True,
                clarification_message="Please provide the full mathematical expression you want solved.",
            )

        clarification = self._detect_incomplete_request(cleaned)
        if clarification:
            return ExtractedExpression(
                operation="clarify",
                needs_clarification=True,
                clarification_message=clarification,
            )

        parsed = self._heuristic_parse(cleaned)
        if parsed:
            return parsed

        fallback = self._extract_raw_expression(cleaned)
        if fallback:
            return fallback

        return ExtractedExpression(
            operation="clarify",
            needs_clarification=True,
            clarification_message="Please provide a specific equation or expression so I can solve it exactly.",
        )

    def solve_expression(self, expr: ExtractedExpression | str) -> SymbolicSolution:
        request = expr if isinstance(expr, ExtractedExpression) else self.extract_expression(expr)
        if request.needs_clarification:
            return SymbolicSolution(
                request=request,
                math_result=None,
                success=False,
                verified=False,
                verification_confidence=ConfidenceLevel.LOW,
                method="none",
                error=request.clarification_message,
            )

        math_result = self._execute(request)
        if not math_result or not math_result.success:
            return SymbolicSolution(
                request=request,
                math_result=math_result,
                success=False,
                verified=False,
                verification_confidence=ConfidenceLevel.LOW,
                method="none",
                error=math_result.error if math_result else "Failed to solve expression.",
            )

        verified = self.verify_solution(request, math_result)
        return SymbolicSolution(
            request=request,
            math_result=math_result,
            success=True,
            verified=verified,
            verification_confidence=ConfidenceLevel.HIGH if verified else ConfidenceLevel.LOW,
            method="symbolic" if verified else "none",
            error=None,
        )

    def verify_solution(self, expr: ExtractedExpression | str, solution: SymbolicSolution | MathResult | str) -> bool:
        request = expr if isinstance(expr, ExtractedExpression) else self.extract_expression(expr)
        if request.needs_clarification:
            return False

        math_result = self._coerce_math_result(solution)
        if not math_result or not math_result.success:
            return False

        try:
            operation = request.operation
            if operation == "solve":
                return self._verify_solve_request(request, math_result)

            expected = self._execute(request)
            if not expected or not expected.success:
                return False

            return self._equivalent_result(expected.result, math_result.result)
        except Exception:
            return False

    def build_explanation_messages(
        self,
        query: str,
        solution: SymbolicSolution,
    ) -> list[dict[str, str]]:
        if not solution.math_result:
            raise ValueError("A successful symbolic solution is required to build explanation messages.")

        from ai.prompts import EXPLANATION_ONLY_SYSTEM_PROMPT

        result = solution.math_result
        steps = "\n".join(result.steps) if result.steps else "No intermediate symbolic steps available."
        user_prompt = (
            "Explain the solved math problem using the deterministic result below.\n\n"
            f"Original problem: {query}\n"
            f"Operation: {solution.request.operation}\n"
            f"Parsed expression: {solution.request.expression}\n"
            f"Verified result: {result.result}\n"
            f"LaTeX result: {result.latex_result or result.result}\n"
            f"Deterministic steps:\n{steps}\n\n"
            "Do not change the equation, result, variable, or operation. "
            "If the symbolic result is a list of solutions, explain that exact list."
        )
        return [
            {"role": "system", "content": EXPLANATION_ONLY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def _extract_raw_expression(self, query: str) -> ExtractedExpression | None:
        candidate = query.strip().rstrip("?.")
        if not _RAW_EXPRESSION_PATTERN.fullmatch(candidate):
            return None

        normalized = self._normalize_expression(candidate)
        if "=" in normalized:
            return ExtractedExpression(
                operation="solve",
                expression=normalized,
                variable=self._infer_variable(normalized),
            )

        try:
            parsed_expr = math_engine.parse_symbolic_expression(normalized)
        except Exception:
            return None

        operation = "evaluate" if not parsed_expr.free_symbols else "simplify"
        return ExtractedExpression(
            operation=operation,
            expression=normalized,
            variable=self._infer_variable(normalized),
        )

    def _execute(self, request: ExtractedExpression) -> MathResult | None:
        expression = request.expression or ""
        variable = request.variable or self._infer_variable(expression) or "x"

        # AST guard: validate before dispatching to SymPy
        guard = _get_ast_guard()
        analysis = guard.validate(expression)
        if not analysis.safe:
            logger.warning(
                "symbolic_solver_ast_rejected",
                operation=request.operation,
                expression=expression[:100],
                violations=analysis.violations,
            )
            return MathResult(
                expression=expression,
                result="",
                latex_result="",
                steps=[],
                success=False,
                error=f"Expression exceeds complexity limits: {'; '.join(analysis.violations)}",
            )

        if request.operation == "solve":
            return math_engine.solve_equation(expression, variable)
        if request.operation == "differentiate":
            return math_engine.differentiate(expression, variable)
        if request.operation == "integrate":
            if request.bounds and len(request.bounds) == 2:
                bound_expr = f"Integral({expression}, ({variable}, {request.bounds[0]}, {request.bounds[1]}))"
                return math_engine.evaluate_expr(bound_expr)
            return math_engine.integrate_expr(expression, variable)
        if request.operation == "simplify":
            return math_engine.solve_expression(expression)
        if request.operation == "evaluate":
            return math_engine.evaluate_expr(expression)
        if request.operation == "limit":
            to_value = str(request.extra.get("to", 0))
            return math_engine.limit_expr(expression, variable, to_value)
        return None

    def _coerce_math_result(self, solution: SymbolicSolution | MathResult | str) -> MathResult | None:
        if isinstance(solution, SymbolicSolution):
            return solution.math_result
        if isinstance(solution, MathResult):
            return solution
        if isinstance(solution, str):
            return MathResult(
                expression="",
                result=solution,
                latex_result=solution,
                steps=[],
                success=True,
            )
        return None

    def _verify_solve_request(self, request: ExtractedExpression, math_result: MathResult) -> bool:
        expression = request.expression or ""
        variable_name = request.variable or self._infer_variable(expression) or "x"
        symbol = symbols(variable_name)

        if "=" in expression:
            lhs, rhs = expression.split("=", 1)
            residual = math_engine.parse_symbolic_expression(lhs) - math_engine.parse_symbolic_expression(rhs)
        else:
            residual = math_engine.parse_symbolic_expression(expression)

        solutions = self._parse_solution_list(math_result.result)
        if not solutions:
            return False

        for candidate in solutions:
            if float(Abs(N(residual.subs(symbol, candidate)))) > 1e-6:
                return False
        return True

    def _parse_solution_list(self, raw_result: str) -> list[Any]:
        text = (raw_result or "").strip()
        if not text:
            return []

        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1].strip()
            if not inner:
                return []
            return [
                math_engine.parse_symbolic_expression(part.strip())
                for part in inner.split(",")
                if part.strip()
            ]

        return [math_engine.parse_symbolic_expression(text)]

    def _equivalent_result(self, expected: str, actual: str) -> bool:
        if expected.strip() == actual.strip():
            return True
        try:
            expected_expr = math_engine.parse_symbolic_expression(expected)
            actual_expr = math_engine.parse_symbolic_expression(actual)
            if isinstance(expected_expr, Relational) or isinstance(actual_expr, Relational):
                return str(expected_expr) == str(actual_expr)
            if isinstance(expected_expr, Expr) and isinstance(actual_expr, Expr):
                return simplify(expected_expr - actual_expr) == 0
        except Exception:
            return False
        return False

    def _detect_incomplete_request(self, user_input: str) -> str | None:
        lowered = user_input.lower().strip().rstrip("?.!")

        if (
            re.search(r"\b(?:double|second)\s+(?:derivative|differentiation)\b", lowered)
            and not _EXPRESSION_HINT_PATTERN.search(lowered)
        ):
            return self._clarification_message("differentiate", second_order=True)

        direct_match = re.match(
            r"^(?:please\s+)?(?P<op>solve|differentiate|derivative|integrate|integral|"
            r"simplify|evaluate|calculate|compute|limit)(?:\s+(?:of|for))?\s*(?P<rest>.*)$",
            lowered,
        )
        if direct_match:
            rest = direct_match.group("rest").strip()
            operation = direct_match.group("op")
            if not rest or self._is_abstract_math_placeholder(rest):
                return self._clarification_message(operation)

        solve_match = re.match(
            r"^(?:please\s+)?(?:solve|find|compute|calculate)\s+(?P<rest>.+)$",
            lowered,
        )
        if solve_match and self._is_abstract_math_placeholder(solve_match.group("rest")):
            return self._clarification_message("solve")

        return None

    def _heuristic_parse(self, user_input: str) -> ExtractedExpression | None:
        text = user_input.strip()
        lowered = text.lower().strip()
        if not text:
            return None

        solve_match = re.match(
            r"^(?:please\s+)?(?:solve|find\s+roots\s+of|find\s+the\s+roots\s+of)\s+(.+)$",
            lowered,
        )
        if solve_match:
            expression = self._normalize_expression(solve_match.group(1))
            return ExtractedExpression(
                operation="solve",
                expression=expression,
                variable=self._infer_variable(expression),
                extra={"heuristic_confidence": "high" if "=" in expression else "medium"},
            )

        derivative_match = re.match(
            r"^(?:find\s+)?(?:the\s+)?(?:derivative|differentiate)(?:\s+of)?\s+(.+)$",
            lowered,
        )
        if derivative_match:
            expression = self._normalize_expression(derivative_match.group(1))
            return ExtractedExpression(
                operation="differentiate",
                expression=expression,
                variable=self._infer_variable(expression),
                extra={"heuristic_confidence": "high"},
            )

        integral_match = re.match(
            r"^(?:find\s+)?(?:the\s+)?(?:integral|integrate)(?:\s+of)?\s+(.+)$",
            lowered,
        )
        if integral_match:
            expression = self._normalize_expression(integral_match.group(1))
            return ExtractedExpression(
                operation="integrate",
                expression=expression,
                variable=self._infer_variable(expression),
                extra={"heuristic_confidence": "high"},
            )

        simplify_match = re.match(r"^(?:please\s+)?simplify\s+(.+)$", lowered)
        if simplify_match:
            expression = self._normalize_expression(simplify_match.group(1))
            return ExtractedExpression(
                operation="simplify",
                expression=expression,
                variable=self._infer_variable(expression),
            )

        evaluate_match = re.match(r"^(?:please\s+)?(?:evaluate|calculate|compute)\s+(.+)$", lowered)
        if evaluate_match:
            expression = self._normalize_expression(evaluate_match.group(1))
            return ExtractedExpression(
                operation="evaluate",
                expression=expression,
                variable=self._infer_variable(expression),
            )

        limit_match = re.match(
            r"^(?:find\s+)?(?:the\s+)?limit\s+of\s+(.+?)\s+as\s+([a-z])\s*->\s*([^\s]+)$",
            lowered,
        )
        if limit_match:
            expression = self._normalize_expression(limit_match.group(1))
            variable = limit_match.group(2)
            approach = self._normalize_expression(limit_match.group(3))
            return ExtractedExpression(
                operation="limit",
                expression=expression,
                variable=variable,
                extra={"to": approach},
            )

        return None

    def _is_abstract_math_placeholder(self, text: str) -> bool:
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        tokens = [token for token in cleaned.split() if token]
        if not tokens:
            return True
        if _EXPRESSION_HINT_PATTERN.search(text):
            return False
        return all(token in _ABSTRACT_OPERATION_TOKENS for token in tokens)

    def _clarification_message(self, operation: str, second_order: bool = False) -> str:
        operation = operation.lower()
        if second_order or operation in {"differentiate", "derivative"}:
            return "Please provide the function or expression to differentiate. For a double differentiation, include the expression explicitly, like 'differentiate x^3 + 2x twice'."
        if operation in {"integrate", "integral"}:
            return "Please provide the expression you want to integrate, like 'integrate sin(x)'."
        if operation == "solve":
            return "Please provide the equation or expression to solve, like 'solve x^2 - 5x + 6 = 0'."
        if operation in {"evaluate", "calculate", "compute"}:
            return "Please provide the expression you want to evaluate, like 'calculate (3 + 5) * 2'."
        if operation == "simplify":
            return "Please provide the expression you want to simplify, like 'simplify (x^2 - 1)/(x - 1)'."
        if operation == "limit":
            return "Please provide the full limit expression, like 'limit of sin(x)/x as x -> 0'."
        return "Please provide the full mathematical expression you want solved."

    def _infer_variable(self, expression: str) -> str | None:
        match = re.search(r"\b([xyzwt])\b", expression)
        if match:
            return match.group(1)
        for variable in ("x", "y", "z", "t", "w"):
            if variable in expression:
                return variable
        return "x"

    def _normalize_expression(self, expression: str) -> str:
        expr = expression.strip().rstrip("?.")
        expr = expr.replace("^", "**")
        expr = re.sub(r"\bplus\b", "+", expr)
        expr = re.sub(r"\bminus\b", "-", expr)
        expr = re.sub(r"\btimes\b", "*", expr)
        expr = re.sub(r"\bmultiplied by\b", "*", expr)
        expr = re.sub(r"\bdivided by\b", "/", expr)
        expr = re.sub(r"(?<=\d)\s*(?=[a-zA-Z(])", "*", expr)
        expr = re.sub(r"\s+", " ", expr).strip()
        return expr


symbolic_solver = SymbolicSolver()
