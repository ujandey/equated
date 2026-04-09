"""
Services — AST Guard

Two-tier mathematical expression validation that runs BEFORE SymPy execution.

Design constraints (from adversarial review):
  - HARD limits are deterministic (no jitter) — absolute ceilings
  - MARGIN limits are jittered — breaching escalates cost category, doesn't reject
  - Expansion estimation is CUMULATIVE across all Pow nodes (not per-node)
  - Expansion thresholds are split: per-node cap and total cap (R3-3 fix)
"""

from __future__ import annotations

import math
import random
import re
from typing import Sequence

import structlog

from config.settings import settings
from core.contracts import ASTAnalysis

logger = structlog.get_logger("equated.services.ast_guard")


# ── Operator / depth counting patterns ─────────────

_OPERATOR_PATTERN = re.compile(r"[\+\-\*/]|\*\*")
_FUNCTION_CALL_PATTERN = re.compile(
    r"\b(?:sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|asin|acos|atan|"
    r"sinh|cosh|tanh|log|ln|exp|sqrt|abs|sign|Integral|limit|solve|"
    r"diff|integrate|factor|simplify|expand)\s*\(",
    re.IGNORECASE,
)
_EXPONENT_PATTERN = re.compile(r"\*\*")


class ASTGuard:
    """
    Two-tier expression validation.

    Tier 1 — HARD limits (deterministic):
      Breach → category='rejected', safe=False. Expression never reaches SymPy.
      - MAX_OPERATOR_COUNT: total arithmetic + function operators
      - MAX_EXPONENT_NESTING: depth of chained ** operators
      - MAX_EXPRESSION_DEPTH: parenthetical nesting depth
      - MAX_SINGLE_EXPANSION: any single Pow(base, n) expansion factor
      - MAX_INTERMEDIATE_NODES: upper bound on total estimated nodes

    Tier 2 — MARGIN limits (jittered):
      Breach → category='heavy', category_weight=5. Expression proceeds
      but with higher reservation cost in Phase 2.
      - MARGIN_OPERATOR_COUNT: the soft zone below the hard ceiling
      - MARGIN_EXPRESSION_DEPTH: the soft zone below the hard ceiling
    """

    def validate(self, expression: str, strict_mode: bool = False) -> ASTAnalysis:
        """
        Validate an expression and return an immutable ASTAnalysis contract.

        Returns:
          ASTAnalysis with safe=True/False, category, weight, and diagnostics.
        """
        if not expression or not expression.strip():
            return ASTAnalysis(
                safe=False,
                category="rejected",
                category_weight=0,
                violations=("Empty expression",),
                warnings=(),
                operator_count=0,
                exponent_depth=0,
                expression_depth=0,
                estimated_expansion=0,
            )

        # ── Measure structural properties ──
        operator_count = self._count_operators(expression)
        exponent_depth = self._measure_exponent_nesting(expression)
        expression_depth = self._measure_depth(expression)
        single_expansions, total_expansion = self._estimate_expansion(expression)

        # ── Tier 1: Hard limits (deterministic, no jitter) ──
        violations: list[str] = []

        # Fix 6: Dynamic Tightening
        limit_ops = settings.MAX_OPERATOR_COUNT
        limit_exp_total = settings.MAX_TOTAL_EXPANSION
        
        if strict_mode:
            limit_ops = max(10, limit_ops // 2)
            limit_exp_total = max(100, limit_exp_total // 2)

        if operator_count > limit_ops:
            violations.append(
                f"Operator count {operator_count} exceeds hard limit {limit_ops}"
            )
        if exponent_depth > settings.MAX_EXPONENT_NESTING:
            violations.append(
                f"Exponent nesting depth {exponent_depth} exceeds hard limit {settings.MAX_EXPONENT_NESTING}"
            )
        if expression_depth > settings.MAX_EXPRESSION_DEPTH:
            violations.append(
                f"Expression depth {expression_depth} exceeds hard limit {settings.MAX_EXPRESSION_DEPTH}"
            )
        # Per-node expansion cap
        for factor_val in single_expansions:
            if factor_val > settings.MAX_SINGLE_EXPANSION:
                violations.append(
                    f"Single expansion factor {factor_val} exceeds limit {settings.MAX_SINGLE_EXPANSION}"
                )
        # Total cumulative expansion cap
        if total_expansion > limit_exp_total:
            violations.append(
                f"Total expansion factor {total_expansion} exceeds limit {limit_exp_total}"
            )

        if violations:
            logger.warning(
                "ast_guard_rejected",
                expression=expression[:200],
                violations=violations,
            )
            return ASTAnalysis(
                safe=False,
                category="rejected",
                category_weight=0,
                violations=tuple(violations),
                warnings=(),
                operator_count=operator_count,
                exponent_depth=exponent_depth,
                expression_depth=expression_depth,
                estimated_expansion=total_expansion,
            )

        # ── Tier 2: Margin limits (jittered) ──
        warnings: list[str] = []

        margin_ops = self._jitter(settings.MARGIN_OPERATOR_COUNT, strict_mode=strict_mode)
        if operator_count > margin_ops:
            warnings.append(
                f"Operator count {operator_count} exceeds margin threshold ~{settings.MARGIN_OPERATOR_COUNT}"
            )

        margin_depth = self._jitter(settings.MARGIN_EXPRESSION_DEPTH, strict_mode=strict_mode)
        if expression_depth > margin_depth:
            warnings.append(
                f"Expression depth {expression_depth} exceeds margin threshold ~{settings.MARGIN_EXPRESSION_DEPTH}"
            )

        # ── Classify ──
        category = "heavy" if warnings else "light"
        weight = settings.WFQ_HEAVY_WEIGHT if category == "heavy" else settings.WFQ_LIGHT_WEIGHT

        if warnings:
            logger.info(
                "ast_guard_heavy",
                expression=expression[:200],
                warnings=warnings,
            )

        return ASTAnalysis(
            safe=True,
            category=category,
            category_weight=weight,
            violations=(),
            warnings=tuple(warnings),
            operator_count=operator_count,
            exponent_depth=exponent_depth,
            expression_depth=expression_depth,
            estimated_expansion=total_expansion,
        )

    # ── Structural analysis methods ──────────────────

    def _count_operators(self, expr: str) -> int:
        """Count arithmetic operators and function calls."""
        arith_count = len(_OPERATOR_PATTERN.findall(expr))
        func_count = len(_FUNCTION_CALL_PATTERN.findall(expr))
        return arith_count + func_count

    def _measure_exponent_nesting(self, expr: str) -> int:
        """
        Measure maximum depth of chained ** (exponentiation).

        Example: ((x**2)**2)**2 → depth 3
        """
        max_depth = 0
        current_depth = 0
        i = 0
        while i < len(expr) - 1:
            if expr[i] == "*" and expr[i + 1] == "*":
                current_depth += 1
                max_depth = max(max_depth, current_depth)
                i += 2
            elif expr[i] in "+-*/(),= ":
                # Reset depth at expression boundaries (not inside nested exponents)
                if expr[i] in "+-(,= ":
                    current_depth = 0
                i += 1
            else:
                i += 1
        return max_depth

    def _measure_depth(self, expr: str) -> int:
        """Measure maximum parenthetical nesting depth."""
        max_depth = 0
        current = 0
        for char in expr:
            if char == "(":
                current += 1
                max_depth = max(max_depth, current)
            elif char == ")":
                current = max(0, current - 1)
        return max_depth

    def _estimate_expansion(self, expr: str) -> tuple[list[int], int]:
        """
        Estimate symbolic expansion factor for Pow nodes.

        Returns (per_node_factors, cumulative_total).

        Catches semantic bombs like:
          (x+1)**500 → single node = 501 terms
          (x+1)**100 + (x+1)**100 + (x+1)**100 → cumulative = 303

        R3-3 fix: cumulative sum, not per-node max.
        R3-suggestion: split thresholds (MAX_SINGLE_EXPANSION, MAX_TOTAL_EXPANSION).

        Estimation heuristic:
          For base**exp where base contains free symbols:
            expansion ≈ C(len(base_terms) + exp - 1, exp)
            Simplified: if base has k additive terms, expansion ≈ (k+exp-1 choose exp)
            For practical purposes: expansion ≈ exp + 1 when k=2 (binomial)
        """
        per_node: list[int] = []

        # Find patterns like (...)**number or (...)**number
        # This regex catches: (expr)**N, func(expr)**N, var**N
        pow_pattern = re.compile(
            r"""
            (?:                         # Base group:
                \([^()]*\)              #   parenthesized expression
                |                       #   OR
                [a-zA-Z_]\w*            #   variable/function name
            )
            \s*\*\*\s*                  # ** operator
            (\d+)                       # Exponent (captured)
            """,
            re.VERBOSE,
        )

        for match in pow_pattern.finditer(expr):
            exponent = int(match.group(1))
            full_match = match.group(0)

            # Determine if base has additive terms (indicates polynomial expansion)
            base_part = full_match[: match.start(1) - 2].rstrip("* ")
            if base_part.startswith("(") and "+" in base_part or "-" in base_part:
                # Polynomial base — expansion is approximately exponent + 1 terms
                expansion = exponent + 1
            else:
                # Simple base (single variable/function) — no expansion blowup
                expansion = 1

            per_node.append(expansion)

        total = sum(per_node)
        return per_node, total

    def _jitter(self, base_val: int, strict_mode: bool = False) -> int:
        """Add ±15% jitter to thresholds to prevent boundary gaming. Stripped in strict mode."""
        if strict_mode:
            return base_val
        jitter = random.gauss(0, base_val * settings.HEURISTIC_JITTER_STDDEV)
        return max(1, round(base_val + jitter))


# Singleton
ast_guard = ASTGuard()
