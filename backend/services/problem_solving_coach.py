"""
Services - Problem Solving Coach

Rule-based metacognitive coaching that helps students improve
their problem-solving process, not just the final answer.
"""

from __future__ import annotations

from typing import Any
import re


STRATEGY_GUESS_AND_CHECK = "guess_and_check"
STRATEGY_ALGEBRAIC = "algebraic_manipulation"
STRATEGY_ARITHMETIC_ONLY = "arithmetic_only"
STRATEGY_DIAGRAM_BASED = "diagram_based"
STRATEGY_KNOWNS_UNKNOWNS = "knowns_unknowns"
STRATEGY_FORMULA_FIRST = "formula_first"
STRATEGY_NO_CLEAR_STRATEGY = "no_clear_strategy"

_UNIT_RE = re.compile(
    r"\b(cm|mm|m|km|kg|g|mg|s|sec|seconds|minutes|min|hours|hr|n|newton|j|joule|pa|volt|v|a|amp|%|degree|degrees)\b",
    re.IGNORECASE,
)
_GEOMETRY_RE = re.compile(
    r"\b(triangle|circle|rectangle|angle|polygon|radius|diameter|area|perimeter|diagram|draw|sketch)\b",
    re.IGNORECASE,
)
_PHYSICS_VISUAL_RE = re.compile(
    r"\b(force|velocity|acceleration|projectile|inclined plane|circuit|ray|lens|motion|vector)\b",
    re.IGNORECASE,
)
_FORMULA_RE = re.compile(
    r"\b(formula|equation|use|substitute|plug in|let|therefore)\b|[a-zA-Z]\s*=",
    re.IGNORECASE,
)
_GUESS_RE = re.compile(
    r"\b(i guess|guess|maybe|probably|i think|trial|random)\b",
    re.IGNORECASE,
)
_DIAGRAM_RE = re.compile(r"\b(diagram|draw|sketch|figure|free body)\b", re.IGNORECASE)
_KNOWN_UNKNOWN_RE = re.compile(
    r"\b(given|known|unknown|let x be|find x|assume|required)\b",
    re.IGNORECASE,
)
_ATTEMPT_SIGNAL_RE = re.compile(
    r"\b(i tried|my attempt|my work|i got|i did|i solved|i used|then i|after that)\b|=",
    re.IGNORECASE,
)
_MATH_TOKEN_RE = re.compile(r"(?:\d|=|[\+\-\*/^])")


class ProblemSolvingCoachService:
    """Heuristics for diagnosing strategy and suggesting next-process improvements."""

    def detect_strategy(self, user_attempt: str) -> dict[str, Any]:
        text = self._normalize(user_attempt)
        if not text:
            return self._decision(STRATEGY_NO_CLEAR_STRATEGY, "No attempt text provided.", 0.1)

        if _DIAGRAM_RE.search(text):
            return self._decision(
                STRATEGY_DIAGRAM_BASED,
                "The student is using a visual representation such as a diagram or sketch.",
                0.88,
            )

        if _KNOWN_UNKNOWN_RE.search(text):
            return self._decision(
                STRATEGY_KNOWNS_UNKNOWNS,
                "The student is explicitly identifying givens, unknowns, or variable definitions.",
                0.86,
            )

        if _GUESS_RE.search(text):
            return self._decision(
                STRATEGY_GUESS_AND_CHECK,
                "The language suggests a trial-and-error approach rather than a structured plan.",
                0.83,
            )

        if _FORMULA_RE.search(text):
            if any(op in text for op in ("+", "-", "*", "/", "^", "=")):
                return self._decision(
                    STRATEGY_ALGEBRAIC,
                    "The attempt shows symbolic manipulation or equation-based solving.",
                    0.82,
                )
            return self._decision(
                STRATEGY_FORMULA_FIRST,
                "The student appears to start from a formula and substitute values.",
                0.74,
            )

        math_tokens = len(_MATH_TOKEN_RE.findall(text))
        words = len(text.split())
        if math_tokens >= 4 and words <= 18:
            return self._decision(
                STRATEGY_ARITHMETIC_ONLY,
                "The attempt is mostly computations, with little planning or interpretation visible.",
                0.79,
            )

        return self._decision(
            STRATEGY_NO_CLEAR_STRATEGY,
            "A stable problem-solving strategy is not clearly visible in the attempt.",
            0.45,
        )

    def suggest_improvement(self, problem: str, attempt: str) -> dict[str, Any]:
        """
        Return practical process-oriented coaching suggestions.

        Output contract:
        {
            "strategy": str,
            "reason": str,
            "confidence": float,
            "suggestions": list[str],
            "integration_prompt": str,
        }
        """
        strategy, suggestions = self._analyze(problem, attempt)
        return {
            **strategy,
            "suggestions": suggestions,
            "integration_prompt": self._format_coaching_prompt(strategy, suggestions),
        }

    def build_coaching_system_prompt(self, problem: str, attempt: str) -> str:
        strategy, suggestions = self._analyze(problem, attempt)
        return self._format_coaching_prompt(strategy, suggestions)

    def should_coach(self, text: str | None) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        if _ATTEMPT_SIGNAL_RE.search(normalized):
            return True
        return len(_MATH_TOKEN_RE.findall(normalized)) >= 5 and len(normalized.split()) >= 6

    def _problem_has_units(self, text: str) -> bool:
        return bool(_UNIT_RE.search(text))

    def _attempt_mentions_units(self, text: str) -> bool:
        return bool(_UNIT_RE.search(text))

    def _benefits_from_diagram(self, text: str) -> bool:
        return bool(_GEOMETRY_RE.search(text) or _PHYSICS_VISUAL_RE.search(text))

    def _analyze(self, problem: str, attempt: str) -> tuple[dict[str, Any], list[str]]:
        strategy = self.detect_strategy(attempt)
        suggestions: list[str] = []
        problem_text = self._normalize(problem)
        attempt_text = self._normalize(attempt)

        if self._problem_has_units(problem_text) and not self._attempt_mentions_units(attempt_text):
            suggestions.append("You didn't check units. Track the units through each step and attach them to the final answer.")

        if self._benefits_from_diagram(problem_text) and not _DIAGRAM_RE.search(attempt_text):
            suggestions.append("Try drawing a diagram before solving. A quick sketch can reveal relationships faster than calculation alone.")

        if not _KNOWN_UNKNOWN_RE.search(attempt_text):
            suggestions.append("Identify knowns and unknowns first. List what is given, what is missing, and what the variable represents.")

        if strategy["strategy"] == STRATEGY_GUESS_AND_CHECK:
            suggestions.append("Move from guessing to a rule-based plan. Pick a formula, equation, or principle before testing values.")
        elif strategy["strategy"] == STRATEGY_ARITHMETIC_ONLY:
            suggestions.append("Pause before calculating. Name the concept or formula you are using so the arithmetic has a clear purpose.")
        elif strategy["strategy"] == STRATEGY_ALGEBRAIC:
            suggestions.append("Check whether each algebra step preserves the meaning of the equation, not just the symbols.")
        elif strategy["strategy"] == STRATEGY_FORMULA_FIRST:
            suggestions.append("Before substituting numbers, explain why that formula fits this problem.")
        elif strategy["strategy"] == STRATEGY_NO_CLEAR_STRATEGY:
            suggestions.append("Start with a simple plan: understand the problem, choose a method, then compute.")

        if not suggestions:
            suggestions.append("Your overall approach is reasonable. After solving, do a quick sanity check on units, signs, and whether the answer fits the question.")

        return strategy, suggestions[:3]

    def _format_coaching_prompt(self, strategy: dict[str, Any], suggestions: list[str]) -> str:
        suggestion_text = " ".join(f"- {item}" for item in suggestions)
        return (
            "Metacognitive coaching mode: teach the student how to think about the problem. "
            f"Detected strategy: {strategy['strategy']}. "
            f"Reason: {strategy['reason']} "
            "Include 1-3 practical process-focused coaching points before or alongside the solution. "
            f"Coaching suggestions: {suggestion_text}"
        )

    def _decision(self, strategy: str, reason: str, confidence: float) -> dict[str, Any]:
        return {
            "strategy": strategy,
            "reason": reason,
            "confidence": round(max(0.0, min(confidence, 1.0)), 2),
        }

    def _normalize(self, text: str | None) -> str:
        return " ".join((text or "").strip().split())


problem_solving_coach = ProblemSolvingCoachService()
