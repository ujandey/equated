"""
Services — Hybrid Math Parser

Three-layer parser for converting natural-language math prompts into
SymPy-executable structured operations.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from sympy import Abs, N, symbols, solve

from ai.models import get_model
from config.settings import settings
from services.math_engine import MathResult, math_engine

logger = structlog.get_logger("equated.hybrid_math_parser")

# Lazy import to avoid circular dependency at module level
_ast_guard = None

def _get_ast_guard():
    global _ast_guard
    if _ast_guard is None:
        from services.ast_guard import ast_guard
        _ast_guard = ast_guard
    return _ast_guard

PARSER_PROMPT_TEMPLATE = """You are a mathematical parser.

Convert the user query into STRICT JSON for symbolic computation.

Rules:

Output ONLY valid JSON
No explanations
Use SymPy-compatible syntax
Identify operation type

Supported operations:

solve
differentiate
integrate
simplify
evaluate
limit

Schema:
{
"operation": "...",
"expression": "...",
"variable": "...",
"bounds": null or [a, b],
"extra": {}
}

Examples:

Input: solve x^2 - 5x + 6 = 0
Output:
{
"operation": "solve",
"expression": "x^2 - 5*x + 6",
"variable": "x",
"bounds": null,
"extra": {}
}

Input: find derivative of sin(x^2)
Output:
{
"operation": "differentiate",
"expression": "sin(x^2)",
"variable": "x",
"bounds": null,
"extra": {}
}

Now parse:
{{USER_INPUT}}"""


@dataclass
class StructuredMathParse:
    operation: str
    expression: str
    variable: str | None = "x"
    bounds: list[Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class HybridParseResult:
    parsed: StructuredMathParse | None
    confidence: str
    source: str
    parse_ok: bool
    execution_ok: bool
    math_result: MathResult | None = None
    numeric_verified: bool = False
    raw_llm_output: str | None = None


class HybridMathParser:
    """Hybrid heuristic + LLM parser for symbolic math queries."""

    SUPPORTED_OPERATIONS = {
        "solve",
        "differentiate",
        "integrate",
        "simplify",
        "evaluate",
        "limit",
    }

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

    def detect_incomplete_request(self, user_input: str) -> str | None:
        """Return a clarification message when the math task lacks an expression."""
        text = user_input.strip()
        if not text:
            return None

        lowered = text.lower().strip().rstrip("?.!")

        if (
            re.search(r"\b(?:double|second)\s+(?:derivative|differentiation)\b", lowered)
            and not self._EXPRESSION_HINT_PATTERN.search(lowered)
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

    def _is_abstract_math_placeholder(self, text: str) -> bool:
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        tokens = [token for token in cleaned.split() if token]
        if not tokens:
            return True
        if self._EXPRESSION_HINT_PATTERN.search(text):
            return False
        return all(token in self._ABSTRACT_OPERATION_TOKENS for token in tokens)

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

    def heuristic_parse(self, user_input: str) -> StructuredMathParse | None:
        """Fast-path parser for common symbolic math prompts."""
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
            confidence = "high" if "=" in expression or "root" in lowered else "medium"
            return StructuredMathParse(
                operation="solve",
                expression=expression,
                variable=self._infer_variable(expression),
                extra={"heuristic_confidence": confidence},
            )

        derivative_match = re.match(
            r"^(?:find\s+)?(?:the\s+)?(?:derivative|differentiate)(?:\s+of)?\s+(.+)$",
            lowered,
        )
        if derivative_match:
            expression = self._normalize_expression(derivative_match.group(1))
            return StructuredMathParse(
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
            return StructuredMathParse(
                operation="integrate",
                expression=expression,
                variable=self._infer_variable(expression),
                extra={"heuristic_confidence": "high"},
            )

        simplify_match = re.match(r"^(?:please\s+)?simplify\s+(.+)$", lowered)
        if simplify_match:
            expression = self._normalize_expression(simplify_match.group(1))
            return StructuredMathParse(
                operation="simplify",
                expression=expression,
                variable=self._infer_variable(expression),
                extra={"heuristic_confidence": "high"},
            )

        evaluate_match = re.match(r"^(?:please\s+)?(?:evaluate|calculate|compute)\s+(.+)$", lowered)
        if evaluate_match:
            expression = self._normalize_expression(evaluate_match.group(1))
            confidence = "high" if re.fullmatch(r"[\d\+\-\*/\^\(\)\.\s]+", expression) else "medium"
            return StructuredMathParse(
                operation="evaluate",
                expression=expression,
                variable=self._infer_variable(expression),
                extra={"heuristic_confidence": confidence},
            )

        limit_match = re.match(
            r"^(?:find\s+)?(?:the\s+)?limit\s+of\s+(.+?)\s+as\s+([a-z])\s*->\s*([^\s]+)$",
            lowered,
        )
        if limit_match:
            expression = self._normalize_expression(limit_match.group(1))
            variable = limit_match.group(2)
            approach = self._normalize_expression(limit_match.group(3))
            return StructuredMathParse(
                operation="limit",
                expression=expression,
                variable=variable,
                extra={"to": approach, "heuristic_confidence": "high"},
            )

        return None

    async def hybrid_parse(self, user_input: str) -> HybridParseResult:
        """Run the full heuristic → LLM → validation pipeline."""
        heuristic = self.heuristic_parse(user_input)
        heuristic_conf = self._heuristic_confidence(heuristic)

        if heuristic and heuristic_conf == "high":
            math_result = self.dry_run(heuristic)
            execution_ok = bool(math_result and math_result.success)
            confidence = self.score_pipeline(heuristic_conf, False, True, execution_ok)
            numeric_verified = self.numeric_check(heuristic) if execution_ok else False
            return HybridParseResult(
                parsed=heuristic,
                confidence=confidence,
                source="heuristic",
                parse_ok=True,
                execution_ok=execution_ok,
                math_result=math_result,
                numeric_verified=numeric_verified,
            )

        try:
            llm_output = await self.call_llm_parser(user_input)
        except Exception as exc:
            logger.warning("llm_parse_unavailable", error=str(exc)[:200])
            if heuristic:
                math_result = self.dry_run(heuristic)
                execution_ok = bool(math_result and math_result.success)
                return HybridParseResult(
                    parsed=heuristic,
                    confidence=self.score_pipeline(heuristic_conf, False, True, execution_ok),
                    source="heuristic_fallback",
                    parse_ok=True,
                    execution_ok=execution_ok,
                    math_result=math_result,
                    numeric_verified=self.numeric_check(heuristic) if execution_ok else False,
                )
            return HybridParseResult(
                parsed=None,
                confidence="low",
                source="failed",
                parse_ok=False,
                execution_ok=False,
            )
        parsed_json = self.safe_json_load(llm_output)
        if not self.validate_json(parsed_json):
            return HybridParseResult(
                parsed=None,
                confidence="low",
                source="failed",
                parse_ok=False,
                execution_ok=False,
                raw_llm_output=llm_output,
            )

        # ── Strict LLM output validation ──
        strict_errors = self._validate_llm_json_strict(parsed_json)
        if strict_errors:
            logger.warning("llm_strict_validation_failed", errors=strict_errors)
            return HybridParseResult(
                parsed=None,
                confidence="low",
                source="failed",
                parse_ok=False,
                execution_ok=False,
                raw_llm_output=llm_output,
            )

        parsed = self._from_json(parsed_json)
        if not self.safe_parse(parsed.expression):
            return HybridParseResult(
                parsed=None,
                confidence="low",
                source="invalid_expr",
                parse_ok=True,
                execution_ok=False,
                raw_llm_output=llm_output,
            )

        math_result = self.dry_run(parsed)
        execution_ok = bool(math_result and math_result.success)
        confidence = self.score_pipeline(heuristic_conf, True, True, execution_ok)
        numeric_verified = self.numeric_check(parsed) if execution_ok else False

        return HybridParseResult(
            parsed=parsed,
            confidence=confidence,
            source="llm",
            parse_ok=True,
            execution_ok=execution_ok,
            math_result=math_result,
            numeric_verified=numeric_verified,
            raw_llm_output=llm_output,
        )

    async def call_llm_parser(self, user_input: str) -> str:
        """Use a cheap model to convert free-form math into strict JSON."""
        prompt = PARSER_PROMPT_TEMPLATE.replace("{{USER_INPUT}}", user_input)
        provider, model_name = self._select_parser_model()
        model = get_model(provider, model_name)
        response = await model.generate(
            [{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.0,
        )
        return response.content.strip()

    def validate_json(self, parsed: dict[str, Any] | None) -> bool:
        required = ["operation", "expression"]
        if not isinstance(parsed, dict):
            return False
        if not all(key in parsed and parsed[key] is not None for key in required):
            return False
        operation = str(parsed.get("operation", "")).strip().lower()
        return operation in self.SUPPORTED_OPERATIONS

    # ── Strict LLM Validation Layer ──────────────────────

    # Allowed tokens in a mathematical expression
    _VALID_EXPR_PATTERN = re.compile(
        r"^[\d\s\+\-\*/\^\(\)\[\]\{\}=<>!.,;:'"
        r"xyzwtnabcdefghijklmnopqrsuvXYZWTNABCDEFGHIJKLMNOPQRSUV"
        r"sincotaglherpINFNANEPi_|&]+$"
    )

    # Known safe math function names
    _SAFE_FUNCTIONS = {
        "sin", "cos", "tan", "cot", "sec", "csc",
        "arcsin", "arccos", "arctan", "asin", "acos", "atan",
        "sinh", "cosh", "tanh",
        "log", "ln", "exp", "sqrt", "abs", "sign",
        "pi", "inf", "nan", "oo",
        "Integral", "integral",
    }

    def _validate_llm_json_strict(self, parsed: dict[str, Any]) -> list[str]:
        """
        Strict validation of LLM-generated JSON before accepting it.
        Returns a list of error strings. Empty list = valid.
        """
        errors = []

        # 1. Type checks
        operation = str(parsed.get("operation", "")).strip().lower()
        expression = str(parsed.get("expression", "")).strip()
        variable = parsed.get("variable")
        bounds = parsed.get("bounds")

        if not expression:
            errors.append("Empty expression")
            return errors

        # 2. Expression sanitization: reject text words
        sanitization_errors = self._sanitize_expression_strict(expression)
        errors.extend(sanitization_errors)

        # 3. Variable validation
        if variable is not None:
            var_str = str(variable).strip()
            if len(var_str) > 2 or not re.match(r'^[a-zA-Z]$', var_str):
                errors.append(f"Invalid variable: '{var_str}' (must be single letter)")

        # 4. Bounds validation
        if bounds is not None:
            if not isinstance(bounds, list) or len(bounds) != 2:
                errors.append(f"Invalid bounds: must be [a, b] list, got {type(bounds).__name__}")

        # 5. Operation-specific validation
        if operation == "solve":
            eq_count = expression.count("=")
            # Allow 0 (implicit =0) or exactly 1
            if eq_count > 1:
                errors.append(f"Solve expression has {eq_count} '=' signs (expected 0 or 1)")

        return errors

    def _sanitize_expression_strict(self, expression: str) -> list[str]:
        """
        Reject expressions containing natural language text tokens.
        Only allow: digits, variables, operators, math functions, whitespace.
        """
        errors = []
        # Split into tokens and check each word-like token
        tokens = re.findall(r'[a-zA-Z_]+', expression)
        for token in tokens:
            # Single letter variables are fine
            if len(token) == 1:
                continue
            # Known math function names are fine
            if token.lower() in self._SAFE_FUNCTIONS:
                continue
            # SymPy-compatible names
            if token in {'Abs', 'Rational', 'Symbol', 'oo', 'pi', 'zoo', 'nan'}:
                continue
            # Reject everything else — it's probably natural language
            errors.append(f"Suspicious token in expression: '{token}'")

        return errors

    def safe_json_load(self, raw_output: str) -> dict[str, Any] | None:
        """Parse plain JSON or fenced JSON output safely."""
        if not raw_output:
            return None

        content = raw_output.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    def safe_parse(self, expr: str):
        """Validate a candidate SymPy expression before execution."""
        normalized = self._normalize_expression(expr)

        # AST guard pre-check: reject expressions that exceed complexity limits
        guard = _get_ast_guard()
        analysis = guard.validate(normalized)
        if not analysis.safe:
            logger.warning(
                "safe_parse_ast_rejected",
                expression=normalized[:100],
                violations=analysis.violations,
            )
            return None

        try:
            return math_engine.parse_symbolic_expression(normalized)
        except Exception:
            return None

    def dry_run(self, parsed: StructuredMathParse) -> MathResult | None:
        """Execute the parsed operation against the SymPy engine."""
        operation = parsed.operation
        expression = self._normalize_expression(parsed.expression)
        variable = parsed.variable or self._infer_variable(expression)

        # AST guard: validate and tag compute category for WFQ (Phase 2)
        guard = _get_ast_guard()
        analysis = guard.validate(expression)
        if not analysis.safe:
            logger.warning(
                "dry_run_ast_rejected",
                operation=operation,
                expression=expression[:100],
                violations=analysis.violations,
            )
            return None

        # Tag compute metadata in extra for downstream WFQ consumption
        parsed.extra["compute_category"] = analysis.category
        parsed.extra["compute_weight"] = analysis.category_weight
        parsed.extra["ast_expansion"] = analysis.estimated_expansion

        try:
            if operation == "solve":
                target = expression
                if "=" not in target and parsed.extra.get("rhs") is not None:
                    target = f"{target} = {parsed.extra['rhs']}"
                return math_engine.solve_equation(target, variable or "x")
            if operation == "differentiate":
                return math_engine.differentiate(expression, variable or "x")
            if operation == "integrate":
                bounds = parsed.bounds
                if bounds and len(bounds) == 2:
                    bound_expr = f"Integral({expression}, ({variable or 'x'}, {bounds[0]}, {bounds[1]}))"
                    return math_engine.evaluate_expr(bound_expr)
                return math_engine.integrate_expr(expression, variable or "x")
            if operation == "simplify":
                return math_engine.solve_expression(expression)
            if operation == "evaluate":
                return math_engine.evaluate_expr(expression)
            if operation == "limit":
                to_value = str(parsed.extra.get("to", 0))
                return math_engine.limit_expr(expression, variable or "x", to_value)
        except Exception as exc:
            logger.warning("dry_run_failed", operation=operation, error=str(exc)[:200])
            return None

        return None

    def score_pipeline(
        self,
        heuristic_conf: str,
        llm_used: bool,
        parse_ok: bool,
        execution_ok: bool,
    ) -> str:
        """Score overall confidence for the hybrid pipeline."""
        if heuristic_conf == "high" and execution_ok:
            return "high"
        if parse_ok and execution_ok:
            return "medium" if llm_used else "high"
        return "low"

    def numeric_check(self, parsed: StructuredMathParse) -> bool:
        """Numerically verify solve outputs by plugging roots back in."""
        if parsed.operation != "solve":
            return False

        equation = self._normalize_expression(parsed.expression)
        variable_name = parsed.variable or self._infer_variable(equation) or "x"
        symbol = symbols(variable_name)

        try:
            if "=" in equation:
                lhs, rhs = equation.split("=", 1)
                residual = math_engine.parse_symbolic_expression(lhs) - math_engine.parse_symbolic_expression(rhs)
            else:
                residual = math_engine.parse_symbolic_expression(equation)

            solutions = solve(residual, symbol)
            if not solutions:
                return False

            for candidate in solutions:
                if Abs(N(residual.subs(symbol, candidate))) >= 1e-6:
                    return False
            return True
        except Exception:
            return False

    def _from_json(self, parsed_json: dict[str, Any]) -> StructuredMathParse:
        operation = str(parsed_json.get("operation", "")).strip().lower()
        expression = self._normalize_expression(str(parsed_json.get("expression", "")).strip())
        variable = parsed_json.get("variable") or self._infer_variable(expression)
        bounds = parsed_json.get("bounds")
        extra = parsed_json.get("extra") or {}

        return StructuredMathParse(
            operation=operation,
            expression=expression,
            variable=variable,
            bounds=bounds,
            extra=extra,
        )

    def _heuristic_confidence(self, parsed: StructuredMathParse | None) -> str:
        if not parsed:
            return "low"
        return str(parsed.extra.get("heuristic_confidence", "medium"))

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
        expr = re.sub(r"\s+", " ", expr).strip()
        return expr

    def _select_parser_model(self) -> tuple[str, str]:
        if settings.GROQ_API_KEY:
            return "groq", "llama-3.3-70b-versatile"
        if settings.OPENAI_API_KEY:
            return "openai", "gpt-4o-mini"
        if settings.DEEPSEEK_API_KEY:
            return "deepseek", "deepseek-chat"
        raise RuntimeError("No parser LLM provider configured for hybrid math parsing.")


hybrid_math_parser = HybridMathParser()
