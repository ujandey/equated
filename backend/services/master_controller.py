"""
Services - Master Controller

Single authority for query handling across tutoring flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Literal

import structlog

from ai.classifier import Classification, ComplexityLevel, SubjectCategory, classifier
from ai.pedagogical_router import build_strategy_system_prompt, route as route_pedagogy
from ai.fallback import fallback_handler
from ai.prompts import CHAT_EXPLAIN_SYSTEM_PROMPT, SOLVER_SYSTEM_PROMPT
from ai.router import model_router
from core.exceptions import AIServiceError
from services.adaptive_explainer import adaptive_explainer
from services.confidence import ConfidenceReport, compute_confidence_report
from services.input_validator import input_validator
from services.math_intent_detector import is_math_like
from services.problem_solving_coach import problem_solving_coach
from services.session_manager import session_manager
from services.student_model import student_model_service
from services.symbolic_solver import symbolic_solver
from services.topic_blocks import AnchorMatch, TopicRoutingDecision, topic_block_service

logger = structlog.get_logger("equated.services.master_controller")

QueryIntent = Literal["solve", "explain", "follow_up", "unclear"]

_SUPERSCRIPT_TRANSLATION = str.maketrans({
    "\u00B2": "^2",
    "\u00B3": "^3",
    "\u2070": "^0",
    "\u00B9": "^1",
    "\u2074": "^4",
    "\u2075": "^5",
    "\u2076": "^6",
    "\u2077": "^7",
    "\u2078": "^8",
    "\u2079": "^9",
})
_SOLVE_RE = re.compile(r"\b(solve|find|compute|calculate|differentiate|derivative|integrate|integral|simplify|evaluate|limit)\b", re.IGNORECASE)
_EXPLAIN_RE = re.compile(r"\b(explain|why|how|intuition|what is|meaning|simplify|simple|simply)\b", re.IGNORECASE)
_FOLLOW_UP_RE = re.compile(
    r"\b(it|this|that|again|next step|continue|using that|from above|formula|equation|expression|result)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_RE = re.compile(r"^\s*(help|please help|can you help|what about this)\s*$", re.IGNORECASE)
_INCOMPLETE_DERIVATIVE_RE = re.compile(r"d\^?2?[a-z]/d[a-z]\^?2?$", re.IGNORECASE)
_MULTI_INTENT_RE = re.compile(r"\b(and|also|plus)\b", re.IGNORECASE)


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


class MasterController:
    """Single pipeline authority for normalization, validation, solving, explanation, and coaching."""

    async def handle_query(
        self,
        *,
        user_id: str,
        query: str,
        source: str,
        session_id: str | None = None,
        credits_remaining: int | None = None,
    ) -> ControllerResult:
        normalized_query = self.normalize_input(query)
        validated_query = input_validator.validate_query(normalized_query)

        base_intent = self.classify_intent(validated_query)
        session_id = await self._ensure_session(user_id=user_id, source=source, session_id=session_id)
        routing = await self._select_context(session_id=session_id, query=validated_query)
        student_state = await self._load_student_state(user_id)
        intent = self._resolve_intent(base_intent, routing.anchor if routing else None)

        clarification = self._run_validation_gates(intent, validated_query)
        if clarification:
            response = ControllerResponse(
                final_answer="",
                steps=[],
                concept="",
                simple_explanation=clarification,
                coach_feedback="",
                confidence=0.0,
                raw_text=clarification,
                clarification_request=clarification,
                credits_remaining=credits_remaining,
            )
            trace = DecisionTrace(
                intent=intent,
                strategy="validation_gate",
                block_id=routing.block_id if routing else None,
                tool_used="validation",
                validation_passed=False,
                mode=routing.decision_type if routing else "new_topic",
                normalized_query=validated_query,
                subject=routing.subject if routing else None,
                clarification=clarification,
            )
            await self._update_state(
                source=source,
                user_id=user_id,
                session_id=session_id,
                routing=routing,
                query=validated_query,
                response=response,
                trace=trace,
            )
            self._log_trace(trace)
            return ControllerResult(response=response, trace=trace, session_id=session_id, block_id=routing.block_id if routing else None, topic_mode=routing.decision_type if routing else "new_topic")

        pedagogical_decision = route_pedagogy(validated_query, student_state)
        coaching_decision = self._build_coaching(validated_query)
        classification = self._contextualize_classification(classifier.classify(validated_query), routing)

        if intent == "solve":
            response, tool_used = await self._handle_solve(
                query=validated_query,
                user_id=user_id,
                student_state=student_state,
                pedagogical_decision=pedagogical_decision,
                coaching_decision=coaching_decision,
                classification=classification,
                credits_remaining=credits_remaining,
            )
        else:
            response, tool_used = await self._handle_explain(
                query=validated_query,
                user_id=user_id,
                student_state=student_state,
                pedagogical_decision=pedagogical_decision,
                coaching_decision=coaching_decision,
                classification=classification,
                credits_remaining=credits_remaining,
                routing=routing,
            )

        trace = DecisionTrace(
            intent=intent,
            strategy=pedagogical_decision.get("strategy", "unknown"),
            block_id=routing.block_id if routing else None,
            tool_used=tool_used,
            validation_passed=True,
            mode=routing.decision_type if routing else "new_topic",
            normalized_query=validated_query,
            subject=routing.subject if routing else classification.subject.value,
        )
        await self._update_state(
            source=source,
            user_id=user_id,
            session_id=session_id,
            routing=routing,
            query=validated_query,
            response=response,
            trace=trace,
        )
        self._log_trace(trace)
        return ControllerResult(
            response=response,
            trace=trace,
            session_id=session_id,
            block_id=routing.block_id if routing else None,
            topic_mode=routing.decision_type if routing else "new_topic",
            pedagogical_decision=pedagogical_decision,
            coaching_decision=coaching_decision,
        )

    def normalize_input(self, query: str) -> str:
        text = (query or "").replace("\u00B2", "^2").replace("\u00B3", "^3")
        text = text.translate(_SUPERSCRIPT_TRANSLATION)
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
        text = text.replace("\u00D7", "*").replace("\u00B7", "*").replace("\u00F7", "/")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def classify_intent(self, query: str) -> QueryIntent:
        if _AMBIGUOUS_RE.search(query):
            return "unclear"
        if _SOLVE_RE.search(query) and is_math_like(query):
            return "solve"
        if _EXPLAIN_RE.search(query):
            return "explain"
        if _FOLLOW_UP_RE.search(query):
            return "follow_up"
        return "unclear"

    async def _ensure_session(self, *, user_id: str, source: str, session_id: str | None) -> str | None:
        if session_id:
            return session_id
        if source == "chat":
            session = await session_manager.create_session(user_id)
            return session.id
        return None

    async def _select_context(self, *, session_id: str | None, query: str) -> TopicRoutingDecision | None:
        if not session_id:
            return None
        return await topic_block_service.route_query(session_id, query)

    async def _load_student_state(self, user_id: str) -> dict[str, Any] | None:
        try:
            return await student_model_service.get_student_state(user_id)
        except Exception as exc:
            logger.warning("student_model_state_unavailable", error=str(exc), user_id=user_id[:8])
            return None

    def _contextualize_classification(
        self,
        classification: Classification,
        routing: TopicRoutingDecision | None,
    ) -> Classification:
        follow_up_modes = {"follow_up", "same_topic_new_question", "reopen_topic"}
        if not routing or routing.decision_type not in follow_up_modes or not routing.subject:
            return classification

        try:
            routed_subject = SubjectCategory(routing.subject)
        except ValueError:
            return classification

        if not hasattr(classification, "subject") or not hasattr(classification, "complexity"):
            return classification

        adjusted_complexity = (
            ComplexityLevel.MEDIUM
            if classification.complexity == ComplexityLevel.LOW
            else classification.complexity
        )
        adjusted_tokens = max(
            getattr(classification, "tokens_est", 0),
            1500 if routed_subject != SubjectCategory.GENERAL else 800,
        )

        if classification.subject == routed_subject and adjusted_complexity == classification.complexity:
            return classification

        logger.info(
            "classification_context_override",
            original_subject=classification.subject.value,
            routed_subject=routed_subject.value,
            decision_type=routing.decision_type,
        )
        return Classification(
            subject=routed_subject,
            complexity=adjusted_complexity,
            confidence=max(classification.confidence, 0.85),
            tokens_est=adjusted_tokens,
            needs_steps=(routed_subject != SubjectCategory.GENERAL),
        )

    def _resolve_intent(self, intent: QueryIntent, anchor: AnchorMatch | None) -> QueryIntent:
        if anchor and anchor.kind in {
            "simplify_request",
            "explanation_request",
            "continuation",
            "pronoun_reference",
            "concept_reference",
        }:
            return "follow_up"
        return intent

    def _run_validation_gates(self, intent: QueryIntent, query: str) -> str | None:
        if intent == "unclear":
            return "Please clarify whether you want me to solve, explain, or check a specific problem."
        if intent == "solve" and _EXPLAIN_RE.search(query) and _MULTI_INTENT_RE.search(query):
            return "Please ask one task at a time: either solve the math problem or request a concept explanation."
        if intent == "solve" and self._requires_function_clarification(query):
            return "Please provide the function"
        if intent == "solve":
            extracted = symbolic_solver.extract_expression(query)
            if extracted.needs_clarification or not extracted.expression:
                return extracted.clarification_message or "Please provide the full mathematical expression."
        return None

    async def _handle_solve(
        self,
        *,
        query: str,
        user_id: str,
        student_state: dict[str, Any] | None,
        pedagogical_decision: dict[str, Any],
        coaching_decision: dict[str, Any],
        classification,
        credits_remaining: int | None,
    ) -> tuple[ControllerResponse, str]:
        if not query.strip():
            raise ValueError("Validation must run before solve pipeline")
        if not is_math_like(query):
            raise ValueError("Solve pipeline received non-math input")

        extracted = symbolic_solver.extract_expression(query)
        symbolic_solution = symbolic_solver.solve_expression(extracted)
        if symbolic_solution.success and symbolic_solution.math_result:
            structured, _ = await adaptive_explainer.generate_structured_explanation(
                problem=query,
                solution=self._symbolic_payload(symbolic_solution),
                student_model=student_state,
                preferred_provider=self._preferred_provider_for_classification(classification),
            )
            structured = self._hydrate_structured_explanation(structured, structured.final_answer or self._symbolic_payload(symbolic_solution), query)
            confidence = compute_confidence_report(
                parse_confidence="high",
                verification_confidence="high" if symbolic_solution.verified else "low",
                method="symbolic" if symbolic_solution.verified else "none",
                parser_source="symbolic_solver",
                math_check_passed=symbolic_solution.verified,
            )
            return (
                self._assemble_response(
                    structured=structured,
                    confidence=confidence,
                    coach_feedback=self._coach_feedback(coaching_decision),
                    model_used="adaptive_explainer",
                    math_engine_result=symbolic_solution.math_result.result,
                    credits_remaining=credits_remaining,
                ),
                "sympy",
            )
        logger.warning(
            "solve_validation_failed_before_symbolic",
            user_id=user_id[:8],
            query=query[:120],
            reason=symbolic_solution.error or "symbolic_solver_failed",
        )
        confidence = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="low",
            method="none",
            parser_source="symbolic_solver",
            math_check_passed=False,
            failure_reason="symbolic_solver_failed",
        )
        clarification = symbolic_solution.error or "Please provide a valid mathematical expression so I can solve it deterministically."
        return (
            ControllerResponse(
                final_answer="",
                steps=[],
                concept="",
                simple_explanation=clarification,
                coach_feedback=self._coach_feedback(coaching_decision),
                confidence=self._confidence_to_float(confidence.overall_confidence.value),
                raw_text=clarification,
                parser_source=confidence.parser_source,
                verification_confidence=confidence.verification_confidence.value,
                verified=False,
                math_check_passed=False,
                model_used="symbolic_guardrail",
                clarification_request=clarification,
                credits_remaining=credits_remaining,
            ),
            "validation",
        )

    async def _handle_explain(
        self,
        *,
        query: str,
        user_id: str,
        student_state: dict[str, Any] | None,
        pedagogical_decision: dict[str, Any],
        coaching_decision: dict[str, Any],
        classification,
        credits_remaining: int | None,
        routing: TopicRoutingDecision | None,
    ) -> tuple[ControllerResponse, str]:
        decision = model_router.route(classification)
        messages = [
            {"role": "system", "content": CHAT_EXPLAIN_SYSTEM_PROMPT},
            {"role": "system", "content": build_strategy_system_prompt(pedagogical_decision)},
        ]
        if coaching_decision:
            messages.append({"role": "system", "content": coaching_decision["integration_prompt"]})
        if routing and routing.decision_type in {"follow_up", "same_topic_new_question", "reopen_topic"}:
            try:
                block = await topic_block_service.get_block(routing.block_id)
                if block and (block.topic_label or block.summary):
                    context_parts: list[str] = []
                    if block.topic_label:
                        context_parts.append(f"Current topic: {block.topic_label}")
                    if block.summary:
                        context_parts.append(f"Topic memory:\n{block.summary}")
                    context_parts.append("Use this topic context to resolve implicit follow-up references.")
                    messages.append({"role": "system", "content": "\n\n".join(context_parts)})

                context_messages = await topic_block_service.get_context_messages(routing.block_id, max_messages=4)
                if context_messages:
                    messages.append(
                        {
                            "role": "system",
                            "content": "The next user message is part of the active topic block. Resolve short references like 'formula' or 'result' using the prior topic context.",
                        }
                    )
                    messages.extend(context_messages)
            except Exception as exc:
                logger.warning(
                    "topic_context_unavailable",
                    block_id=routing.block_id,
                    decision_type=routing.decision_type,
                    error=str(exc),
                )
        if routing and routing.anchor and routing.anchor.kind == "simplify_request":
            messages.append({"role": "system", "content": "This is a follow-up simplification request. Re-explain the same topic in simpler, analogy-first language."})
        messages.append({"role": "user", "content": query})
        result = await fallback_handler.generate_with_fallback(messages, decision, user_id)
        if not result:
            raise AIServiceError("All AI models unavailable")
        structured, _ = await adaptive_explainer.generate_structured_explanation(
            problem=query,
            solution=result.content,
            student_model=student_state,
            level="beginner" if routing and routing.anchor and routing.anchor.kind == "simplify_request" else None,
            preferred_provider=getattr(getattr(decision, "provider", None), "value", None),
            prefer_existing_text=True,
        )
        structured = self._hydrate_structured_explanation(structured, result.content, query)
        confidence = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="low",
            method="none",
            parser_source="explanation_only",
            math_check_passed=False,
            failure_reason="non_math_explanation",
        )
        return (
            self._assemble_response(
                structured=structured,
                confidence=confidence,
                coach_feedback=self._coach_feedback(coaching_decision),
                model_used=result.model,
                math_engine_result=None,
                credits_remaining=credits_remaining,
                raw_text_override=result.content,
            ),
            "llm_explainer",
        )

    def _assemble_response(
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
            confidence=self._confidence_to_float(confidence.overall_confidence.value),
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

    async def _update_state(
        self,
        *,
        source: str,
        user_id: str,
        session_id: str | None,
        routing: TopicRoutingDecision | None,
        query: str,
        response: ControllerResponse,
        trace: DecisionTrace,
    ) -> None:
        if source != "chat" or not session_id or not routing:
            return
        user_message = await session_manager.add_message(
            session_id,
            "user",
            query,
            metadata={"intent": trace.intent, "normalized_query": trace.normalized_query},
            block_id=routing.block_id,
        )
        await topic_block_service.attach_message_to_block(user_message.id, routing.block_id)
        await topic_block_service.register_user_turn(routing.block_id, query)
        await session_manager.add_message(
            session_id,
            "assistant",
            response.raw_text,
            metadata={
                "intent": trace.intent,
                "strategy": trace.strategy,
                "tool_used": trace.tool_used,
                "validation_passed": trace.validation_passed,
            },
            block_id=routing.block_id,
        )
        await topic_block_service.refresh_block_summary(routing.block_id)
        try:
            interaction_outcome = student_model_service.build_chat_interaction_outcome(
                user_message=query,
                assistant_response=response.raw_text,
                subject=routing.subject,
                topic=query,
                session_id=session_id,
                follow_up_anchor_kind=routing.anchor.kind,
                topic_decision_type=routing.decision_type,
                topic_question_count=0,
                confidence=response.confidence,
                verified=response.verified,
                source="master_controller",
            )
            await student_model_service.update_from_interaction(
                user_id=user_id,
                question=query,
                response=query,
                outcome=interaction_outcome,
            )
        except Exception as exc:
            logger.warning("student_model_update_failed", error=str(exc), user_id=user_id[:8], source="master_controller")

    def render_response_text(
        self,
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

    def _symbolic_payload(self, symbolic_solution) -> str:
        result = symbolic_solution.math_result
        if not result:
            return ""
        steps = "\n".join(result.steps) if result.steps else "No intermediate steps available."
        return f"Verified result: {result.result}\nDeterministic steps:\n{steps}"

    def _hydrate_structured_explanation(self, structured, raw_text: str, query: str):
        text = (raw_text or "").strip()
        if not structured.problem_interpretation:
            structured.problem_interpretation = query
        if not structured.concept_used:
            structured.concept_used = query
        if not structured.steps:
            structured.steps = [{"step": 1, "rule": "", "explanation": self._trim_text(text, 500)}]
        if not structured.final_answer:
            structured.final_answer = text
        if not structured.quick_summary:
            structured.quick_summary = self._trim_text(text, 280)
        return structured

    def _preferred_provider_for_classification(self, classification) -> str | None:
        try:
            return model_router.route(classification).provider.value
        except Exception:
            return None

    def _trim_text(self, text: str, limit: int) -> str:
        cleaned = (text or "").strip()
        return cleaned if len(cleaned) <= limit else f"{cleaned[:limit].rstrip()}..."

    def _build_coaching(self, query: str) -> dict[str, Any]:
        if problem_solving_coach.should_coach(query):
            return problem_solving_coach.suggest_improvement(query, query)
        return {}

    def _coach_feedback(self, coaching_decision: dict[str, Any]) -> str:
        return " ".join(coaching_decision.get("suggestions") or [])

    def _requires_function_clarification(self, query: str) -> bool:
        lowered = query.lower().replace(" ", "")
        if "d^2" in lowered and _INCOMPLETE_DERIVATIVE_RE.search(lowered):
            return True
        return False

    def _confidence_to_float(self, level: str) -> float:
        return {"high": 0.95, "medium": 0.7, "low": 0.35}.get(level, 0.35)

    def _log_trace(self, trace: DecisionTrace) -> None:
        logger.info(
            "master_controller_trace",
            intent=trace.intent,
            strategy=trace.strategy,
            block_id=trace.block_id,
            tool_used=trace.tool_used,
            validation_passed=trace.validation_passed,
        )


master_controller = MasterController()

