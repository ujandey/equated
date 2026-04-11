from __future__ import annotations

import re


TEACHING_MODES = {
    "minimal": "final answer, minimal steps",
    "guided": "steps with light explanation",
    "scaffolded": "deep step-by-step teaching",
}

_ROOTS_RE = re.compile(r"\b(find roots?|roots?)\b", re.IGNORECASE)
_DIRECT_COMPUTE_RE = re.compile(r"\b(find|compute|calculate|evaluate)\b", re.IGNORECASE)
_ADVANCED_RE = re.compile(r"\b(integrate|differentiate|derivative|integral|limit|matrix|system of equations|simultaneous)\b", re.IGNORECASE)
_QUADRATIC_RE = re.compile(r"\bquadratic\b|[a-z]\^2", re.IGNORECASE)
_EXPLAIN_RE = re.compile(r"\b(explain|why|how|justify|describe)\b", re.IGNORECASE)
_OPERATOR_RE = re.compile(r"[=+\-*/^]")


class TeachingPolicyEngine:
    """Resolves fallback teaching modes when the user gives no explicit modifier."""

    @staticmethod
    def select_mode(*, step_type: str, text: str, depends_on_primary: bool = False) -> str:
        return TeachingPolicyEngine._resolve(step_type=step_type, text=text, depends_on_primary=depends_on_primary)[0]

    @staticmethod
    def select_reason(*, step_type: str, text: str, depends_on_primary: bool = False) -> str:
        return TeachingPolicyEngine._resolve(step_type=step_type, text=text, depends_on_primary=depends_on_primary)[1]

    @staticmethod
    def _resolve(*, step_type: str, text: str, depends_on_primary: bool = False) -> tuple[str, str]:
        normalized = " ".join((text or "").split()).lower()
        if step_type == "explain":
            if depends_on_primary:
                return "guided", "bound_explanation_default_policy"
            if _EXPLAIN_RE.search(normalized):
                return "guided", "concept_explanation_default_policy"
            return "minimal", "minimal_explanation_default_policy"

        if _ADVANCED_RE.search(normalized):
            return "scaffolded", "advanced_problem_policy"

        operator_count = len(_OPERATOR_RE.findall(normalized))
        if operator_count >= 4:
            return "scaffolded", "multi_step_expression_policy"

        if _QUADRATIC_RE.search(normalized):
            return "guided", "quadratic_equation_default_policy"

        if _ROOTS_RE.search(normalized):
            return "minimal", "roots_request_minimal_policy"

        if _DIRECT_COMPUTE_RE.search(normalized) and operator_count <= 2:
            return "minimal", "direct_compute_minimal_policy"

        return "guided", "general_solve_default_policy"


teaching_policy_engine = TeachingPolicyEngine()
