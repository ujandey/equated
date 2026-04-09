from __future__ import annotations

import structlog
from typing import Any

from ai.classifier import classifier
from ai.pedagogical_router import build_strategy_system_prompt, route as route_pedagogy
from ai.prompts import CHAT_EXPLAIN_SYSTEM_PROMPT, SOLVER_SYSTEM_PROMPT
from ai.router import model_router

from services.adaptive_explainer import adaptive_explainer
from services.confidence import compute_confidence_report
from services.input_validator import input_validator
from services.math_intent_detector import is_math_like
from services.session_manager import session_manager
from services.student_model import student_model_service
from services.symbolic_solver import symbolic_solver
from services.topic_blocks import TopicRoutingDecision, topic_block_service

# Local Decoupled Modules
from services.master_controller.query_normalizer import query_normalizer
from services.master_controller.intent_classifier import intent_classifier_service
from services.master_controller.validation_gates import validation_gates_service
from services.master_controller.response_assembler import response_assembler_service, ControllerResponse, ControllerResult, DecisionTrace
from services.master_controller.fallback_handler import controller_fallback_handler


logger = structlog.get_logger("equated.services.master_controller")

class MasterController:
    """Lean orchestrator for normalization, validation, solving, explanation, and coaching."""

    async def handle_query(
        self,
        *,
        user_id: str,
        query: str,
        source: str,
        session_id: str | None = None,
        credits_remaining: int | None = None,
    ) -> ControllerResult:
        normalized_query = query_normalizer.normalize_input(query)
        validated_query = input_validator.validate_query(normalized_query)

        base_intent = intent_classifier_service.classify_intent(validated_query)
        session_id = await self._ensure_session(user_id=user_id, source=source, session_id=session_id)
        routing = await self._select_context(session_id=session_id, query=validated_query)
        student_state = await self._load_student_state(user_id)
        intent = intent_classifier_service.resolve_intent(base_intent, routing.anchor if routing else None)

        clarification = validation_gates_service.run_validation_gates(intent, validated_query)
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
        coaching_decision = response_assembler_service.build_coaching(validated_query)
        classification = intent_classifier_service.contextualize_classification(classifier.classify(validated_query), routing)

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
            
            preferred_provider = None
            try:
                preferred_provider = model_router.route(classification).provider.value
            except Exception:
                pass
                
            structured, _ = await adaptive_explainer.generate_structured_explanation(
                problem=query,
                solution=response_assembler_service.symbolic_payload(symbolic_solution),
                student_model=student_state,
                preferred_provider=preferred_provider,
            )
            structured = response_assembler_service.hydrate_structured_explanation(
                structured, structured.final_answer or response_assembler_service.symbolic_payload(symbolic_solution), query
            )
            confidence = compute_confidence_report(
                parse_confidence="high",
                verification_confidence="high" if symbolic_solution.verified else "low",
                method="symbolic" if symbolic_solution.verified else "none",
                parser_source="symbolic_solver",
                math_check_passed=symbolic_solution.verified,
            )
            return (
                response_assembler_service.assemble_response(
                    structured=structured,
                    confidence=confidence,
                    coach_feedback=response_assembler_service.coach_feedback(coaching_decision),
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
                coach_feedback=response_assembler_service.coach_feedback(coaching_decision),
                confidence=response_assembler_service.confidence_to_float(confidence.overall_confidence.value),
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
        
        # Invoke via new decoupled Circuit Breaker wrapper
        result = await controller_fallback_handler.generate_with_fallback(messages, decision, user_id)
        
        structured, _ = await adaptive_explainer.generate_structured_explanation(
            problem=query,
            solution=result.content,
            student_model=student_state,
            level="beginner" if routing and routing.anchor and routing.anchor.kind == "simplify_request" else None,
            preferred_provider=getattr(getattr(decision, "provider", None), "value", None),
            prefer_existing_text=True,
        )
        structured = response_assembler_service.hydrate_structured_explanation(structured, result.content, query)
        confidence = compute_confidence_report(
            parse_confidence="low",
            verification_confidence="low",
            method="none",
            parser_source="explanation_only",
            math_check_passed=False,
            failure_reason="non_math_explanation",
        )
        return (
            response_assembler_service.assemble_response(
                structured=structured,
                confidence=confidence,
                coach_feedback=response_assembler_service.coach_feedback(coaching_decision),
                model_used=result.model,
                math_engine_result=None,
                credits_remaining=credits_remaining,
                raw_text_override=result.content,
            ),
            "llm_explainer",
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
                follow_up_anchor_kind=routing.anchor.kind if routing.anchor else None,
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
