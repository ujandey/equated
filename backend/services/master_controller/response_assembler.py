import json
import re
from dataclasses import dataclass, field
from typing import Any
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
    # New structured fields for SolutionCard
    concept_explanation: str = ""
    subject_hint: str = ""
    answer_summary: str = ""
    verification_status: str = "unverified"
    cached: bool = False

@dataclass
class ControllerResult:
    response: ControllerResponse
    trace: DecisionTrace
    session_id: str | None = None
    block_id: str | None = None
    topic_mode: str = "new_topic"
    pedagogical_decision: dict[str, Any] = field(default_factory=dict)
    coaching_decision: dict[str, Any] = field(default_factory=dict)
    qep_trace: dict[str, Any] = field(default_factory=dict)
    debug_plan: dict[str, Any] = field(default_factory=dict)
    execution_echo: dict[str, Any] = field(default_factory=dict)


def parse_solution_response(raw_llm_output: str) -> dict:
    """
    Strictly parse and validate the LLM's JSON solution response.
    Raises ValueError with a clear message if the output is malformed.
    """
    import logging

    cleaned = raw_llm_output.strip()
    # Strip markdown fences (multiline-aware)
    cleaned = re.sub(r'^```json\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^```\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'```\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    # Fix common unescaped backslashes in LaTeX from LLMs while protecting already-escaped ones
    # 1. Temporarily protect valid double backslashes (like \\frac) by swapping them out
    cleaned = cleaned.replace(r'\\', '\x00')
    
    # 2. Escape any remaining single backslashes followed by invalid JSON escape characters
    cleaned = re.sub(r'\\(?![/"\\bfnrtu])', r'\\\\', cleaned)
    
    # 3. Escape valid JSON escape characters that are actually LaTeX commands (e.g. \f in \frac)
    for cmd in ["frac", "text", "theta", "begin", "beta", "right", "rho", "nabla", "nu"]:
        cleaned = re.sub(r'\\(' + cmd[0] + r')(?=' + cmd[1:] + r')', r'\\\\\1', cleaned)
        
    # 4. Restore the protected double backslashes
    cleaned = cleaned.replace('\x00', r'\\')

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Log the raw output so you can see exactly what the LLM returned
        logging.error(f"[parse_solution_response] JSON parse failed: {e}")
        logging.error(f"[parse_solution_response] Raw output (first 800 chars): {raw_llm_output[:800]}")
        # Re-raise so the controller knows parsing failed and can retry
        raise ValueError(f"LLM returned non-JSON output. Parse error: {e}")

    # Validate required keys exist
    required_keys = ["final_answer", "steps", "problem_interpretation", "concept_used"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"LLM JSON missing required keys: {missing}. Got keys: {list(data.keys())}")

    # Validate final_answer has no prose
    final_answer = data.get("final_answer", "")
    prose_indicators = [
        "the solution", "can be written", "notation", "meaning",
        "however", "following", "requested", "display", "format",
        "which can", " are ", "but for"
    ]
    for indicator in prose_indicators:
        if indicator.lower() in final_answer.lower():
            logging.warning(f"[parse_solution_response] Prose detected in final_answer: '{final_answer[:200]}'")
            raise ValueError(f"final_answer contains prose ('{indicator}'): {final_answer[:200]}")

    # Validate answer_summary is one sentence
    summary = data.get("answer_summary", "")
    if len(summary.split('.')) > 3:
        # Truncate to first sentence rather than failing hard
        data["answer_summary"] = summary.split('.')[0].strip() + '.'

    # Validate steps have titles
    steps = data.get("steps", [])
    for i, step in enumerate(steps):
        if not step.get("title"):
            step["title"] = f"Step {step.get('number', i+1)}"
        if not step.get("equation"):
            step["equation"] = None

    return data


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

    def assemble_structured_response(
        self,
        *,
        json_solution: dict,
        confidence: ConfidenceReport,
        coach_feedback: str,
        math_engine_result: str | None,
        credits_remaining: int | None,
        raw_text_override: str | None = None,
    ) -> ControllerResponse:
        """Assemble a ControllerResponse from the new structured JSON solution dict."""
        # Build steps in the legacy format for backwards compatibility
        legacy_steps = []
        for step in json_solution.get("steps", []):
            legacy_steps.append({
                "step": step.get("number", 1),
                "rule": step.get("title", ""),
                "explanation": step.get("explanation", ""),
                "equation": step.get("equation"),
                "title": step.get("title", ""),
                "number": step.get("number", 1),
            })

        final_answer = json_solution.get("final_answer", "")
        answer_summary = json_solution.get("answer_summary", "")
        model_used = json_solution.get("model_used", "")

        raw_text = raw_text_override or self.render_response_text(
            problem_interpretation=json_solution.get("problem_interpretation", ""),
            concept=json_solution.get("concept_used", ""),
            steps=legacy_steps,
            final_answer=final_answer,
            simple_explanation=answer_summary,
            coach_feedback=coach_feedback,
        )

        verification_status = json_solution.get("verification_status", "unverified")
        verified = verification_status == "verified" or confidence.verified

        return ControllerResponse(
            final_answer=final_answer,
            steps=legacy_steps,
            concept=json_solution.get("concept_used", ""),
            simple_explanation=answer_summary,
            coach_feedback=coach_feedback,
            confidence=json_solution.get("confidence", self.confidence_to_float(confidence.overall_confidence.value)),
            raw_text=raw_text,
            problem_interpretation=json_solution.get("problem_interpretation", ""),
            quick_summary=answer_summary,
            alternative_method=None,
            common_mistakes=None,
            parser_source=confidence.parser_source,
            verification_confidence=confidence.verification_confidence.value,
            verified=verified,
            math_check_passed=confidence.verified,
            math_engine_result=math_engine_result,
            model_used=model_used,
            credits_remaining=credits_remaining,
            concept_explanation=json_solution.get("concept_explanation", ""),
            subject_hint=json_solution.get("subject_hint", ""),
            answer_summary=answer_summary,
            verification_status=verification_status if verified else "unverified",
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
        """Return a clean, human-readable answer from SymPy computation (no raw SymPy syntax)."""
        result = symbolic_solution.math_result
        if not result:
            return ""
        raw = result.result
        if raw is None:
            return ""
        if isinstance(raw, list):
            if len(raw) == 1:
                return str(raw[0])
            return ", ".join(str(r) for r in raw)
        return str(raw)

    @staticmethod
    def hydrate_structured_explanation(structured, clean_answer: str, query: str):
        """Fill in any missing fields with safe fallbacks. `clean_answer` must be a
        short human-readable answer string, NOT raw SymPy text."""
        answer = (clean_answer or "").strip()
        if not structured.problem_interpretation:
            structured.problem_interpretation = query
        if not structured.concept_used:
            structured.concept_used = ""
        if not structured.steps:
            structured.steps = []
        if not structured.final_answer:
            structured.final_answer = answer
        if not structured.quick_summary:
            structured.quick_summary = answer
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
