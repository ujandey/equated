from dataclasses import dataclass, field
from typing import Any, Literal
from services.confidence import ConfidenceReport
from services.problem_solving_coach import problem_solving_coach
from services.master_controller.intent_classifier import QueryIntent

@dataclass
class DecisionTrace:
    intent: QueryIntent
    strategy: str
    block_id: str | None
    tool_used: str
    validation_passed: bool
    mode: str = "new_topic"
    normalized_query: str = ""
    subject: str | None = None
    clarification: str | None = None

@dataclass
class ControllerResponse:
    final_answer: str
    steps: list[dict]
    concept: str
    simple_explanation: str
    coach_feedback: str
    confidence: float
    raw_text: str
    problem_interpretation: str = ""
    quick_summary: str = ""
    alternative_method: str | None = None
    common_mistakes: str | None = None
    parser_source: str | None = None
    verification_confidence: str | None = None
    verified: bool = False
    math_check_passed: bool = False
    math_engine_result: str | None = None
    model_used: str = ""
    clarification_request: str | None = None
    credits_remaining: int | None = None

@dataclass
class ControllerResult:
    response: ControllerResponse
    trace: DecisionTrace
    session_id: str | None = None
    block_id: str | None = None
    topic_mode: str = "new_topic"
    pedagogical_decision: dict[str, Any] = field(default_factory=dict)
    coaching_decision: dict[str, Any] = field(default_factory=dict)

class ResponseAssembler:
    """Handles response formatting, construction, and confidence aggregation."""

    def assemble_response(
        self,
        *,
        structured,
        confidence: ConfidenceReport,
        coach_feedback: str,
        model_used: str,
        math_engine_result: str | None,
        credits_remaining: int | None,
        raw_text_override: str | None = None,
    ) -> ControllerResponse:
        raw_text = (
            raw_text_override.strip()
            if raw_text_override is not None
            else self.render_response_text(
                problem_interpretation=structured.problem_interpretation,
                concept=structured.concept_used,
                steps=structured.steps,
                final_answer=structured.final_answer,
                simple_explanation=structured.quick_summary,
                coach_feedback=coach_feedback,
            )
        )
        return ControllerResponse(
            final_answer=structured.final_answer,
            steps=structured.steps,
            concept=structured.concept_used,
            simple_explanation=structured.quick_summary,
            coach_feedback=coach_feedback,
            confidence=self.confidence_to_float(confidence.overall_confidence.value),
            raw_text=raw_text,
            problem_interpretation=structured.problem_interpretation,
            quick_summary=structured.quick_summary,
            alternative_method=structured.alternative_method,
            common_mistakes=structured.common_mistakes,
            parser_source=confidence.parser_source,
            verification_confidence=confidence.verification_confidence.value,
            verified=confidence.verified,
            math_check_passed=confidence.verified,
            math_engine_result=math_engine_result,
            model_used=model_used,
            credits_remaining=credits_remaining,
        )

    @staticmethod
    def render_response_text(
        *,
        problem_interpretation: str,
        concept: str,
        steps: list[dict],
        final_answer: str,
        simple_explanation: str,
        coach_feedback: str,
    ) -> str:
        lines = [
            "**Problem Interpretation**",
            problem_interpretation,
            "",
            "**Concept Used**",
            concept,
            "",
            "**Step-by-Step Solution**",
        ]
        for step in steps:
            lines.append(f"Step {step['step']}: {step['explanation']}")
        lines.extend(["", "**Final Answer**", final_answer, "", "**Quick Summary**", simple_explanation])
        if coach_feedback:
            lines.extend(["", "**Coach Feedback**", coach_feedback])
        return "\n".join(lines).strip()

    @staticmethod
    def symbolic_payload(symbolic_solution) -> str:
        result = symbolic_solution.math_result
        if not result:
            return ""
        steps = "\n".join(result.steps) if result.steps else "No intermediate steps available."
        return f"Verified result: {result.result}\nDeterministic steps:\n{steps}"

    @staticmethod
    def hydrate_structured_explanation(structured, raw_text: str, query: str):
        text = (raw_text or "").strip()
        if not structured.problem_interpretation:
            structured.problem_interpretation = query
        if not structured.concept_used:
            structured.concept_used = query
        if not structured.steps:
            structured.steps = [{"step": 1, "rule": "", "explanation": ResponseAssembler.trim_text(text, 500)}]
        if not structured.final_answer:
            structured.final_answer = text
        if not structured.quick_summary:
            structured.quick_summary = ResponseAssembler.trim_text(text, 280)
        return structured

    @staticmethod
    def trim_text(text: str, limit: int) -> str:
        cleaned = (text or "").strip()
        return cleaned if len(cleaned) <= limit else f"{cleaned[:limit].rstrip()}..."

    @staticmethod
    def build_coaching(query: str) -> dict[str, Any]:
        if problem_solving_coach.should_coach(query):
            return problem_solving_coach.suggest_improvement(query, query)
        return {}

    @staticmethod
    def coach_feedback(coaching_decision: dict[str, Any]) -> str:
        return " ".join(coaching_decision.get("suggestions") or [])

    @staticmethod
    def confidence_to_float(level: str) -> float:
        return {"high": 0.95, "medium": 0.7, "low": 0.35}.get(level, 0.35)

response_assembler_service = ResponseAssembler()
