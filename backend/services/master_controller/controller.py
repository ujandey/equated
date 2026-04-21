from __future__ import annotations

import structlog
from typing import Any

from ai.classifier import classifier
from ai.pedagogical_router import build_strategy_system_prompt, route as route_pedagogy
from ai.prompts import build_chat_system_prompt, SOLVER_SYSTEM_PROMPT
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
from services.master_controller.query_splitter import QueryExecutionPlan, query_splitter
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
        split_decision = query_splitter.analyze(validated_query)
        execution_query = split_decision.primary_clause.raw_clause if split_decision.primary_clause and not split_decision.should_clarify else validated_query
        execution_plan = split_decision.query_execution_plan
        qep_trace = execution_plan.to_trace(input_text=validated_query, clause_intents=split_decision.clause_intents)
        safe_debug_plan = execution_plan.to_safe_debug()
        execution_echo = execution_plan.build_execution_echo()

        if split_decision.should_clarify:
            clarification = split_decision.clarification_message or "Please ask one task at a time."
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
                intent="unclear",
                strategy="query_splitter",
                block_id=None,
                tool_used="validation",
                validation_passed=False,
                mode="new_topic",
                normalized_query=validated_query,
                clarification=clarification,
            )
            self._log_trace(trace)
            return ControllerResult(response=response, trace=trace, session_id=session_id, block_id=None, topic_mode="new_topic", qep_trace=qep_trace, debug_plan=safe_debug_plan, execution_echo=execution_echo)

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
            import asyncio
            # Schedule heavy database writes in background to prevent proxy socket timeout
            asyncio.create_task(
                self._update_state(
                    source=source,
                    user_id=user_id,
                    session_id=session_id,
                    routing=routing,
                    query=validated_query,
                    response=response,
                    trace=trace,
                )
            )
            self._log_trace(trace)
            return ControllerResult(response=response, trace=trace, session_id=session_id, block_id=routing.block_id if routing else None, topic_mode=routing.decision_type if routing else "new_topic", qep_trace=qep_trace, debug_plan=safe_debug_plan, execution_echo=execution_echo)

        pedagogical_decision = self._apply_execution_modifiers(route_pedagogy(validated_query, student_state), execution_plan)
        coaching_decision = response_assembler_service.build_coaching(validated_query)
        classification = intent_classifier_service.contextualize_classification(classifier.classify(validated_query), routing)

        if intent == "solve":
            response, tool_used = await self._handle_solve(
                query=execution_query,
                presentation_query=validated_query,
                user_id=user_id,
                student_state=student_state,
                pedagogical_decision=pedagogical_decision,
                coaching_decision=coaching_decision,
                classification=classification,
                credits_remaining=credits_remaining,
                execution_plan=execution_plan,
                session_id=session_id,
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
                session_id=session_id,
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
        import asyncio
        asyncio.create_task(
            self._update_state(
                source=source,
                user_id=user_id,
                session_id=session_id,
                routing=routing,
                query=validated_query,
                response=response,
                trace=trace,
            )
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
            qep_trace=qep_trace,
            debug_plan=safe_debug_plan,
            execution_echo=execution_echo,
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
        presentation_query: str,
        user_id: str,
        student_state: dict[str, Any] | None,
        pedagogical_decision: dict[str, Any],
        coaching_decision: dict[str, Any],
        classification,
        credits_remaining: int | None,
        execution_plan: QueryExecutionPlan,
        session_id: str | None,
    ) -> tuple[ControllerResponse, str]:
        if not query.strip():
            raise ValueError("Validation must run before solve pipeline")
        if not is_math_like(query):
            raise ValueError("Solve pipeline received non-math input")

        extracted = symbolic_solver.extract_expression(query)
        symbolic_solution = symbolic_solver.solve_expression(extracted)
        if symbolic_solution.success and symbolic_solution.math_result:

            # ── Algorithmic tutoring layer ──────────────────────────────
            llm_prompt_override: str | None = None
            socratic_probe = None
            try:
                from services.concept_graph import get_concept_graph
                from services.diagnosis_engine import diagnosis_engine
                from services.explanation_path_builder import explanation_path_builder
                from services.socratic_loop import socratic_loop as _socratic_loop

                _cg = get_concept_graph()
                _topic = (symbolic_solution.request.operation or "algebra").lower()

                _student_profile = await diagnosis_engine.diagnose(
                    user_id=user_id,
                    topic=_topic,
                    concept_graph=_cg,
                )
                _script = explanation_path_builder.build(
                    problem=presentation_query,
                    sympy_result=symbolic_solution,
                    student_profile=_student_profile,
                    concept_graph=_cg,
                )
                llm_prompt_override = _script.llm_prompt
                socratic_probe = _socratic_loop.generate_probe(
                    presentation_query, symbolic_solution
                )
            except Exception as _tutor_exc:
                logger.warning(
                    "tutoring_layer_failed",
                    error=str(_tutor_exc),
                    user_id=user_id[:8],
                )
            # ── End algorithmic tutoring layer ──────────────────────────

            try:
                preferred_provider = model_router.route(classification).provider.value
            except Exception:
                pass

            structured, _ = await adaptive_explainer.generate_structured_explanation(
                problem=presentation_query,
                solution=response_assembler_service.symbolic_payload(symbolic_solution),
                student_model=student_state,
                preferred_provider=preferred_provider,
                teaching_directives=self._teaching_directives(execution_plan),
                prompt_override=llm_prompt_override,
            )
            structured = response_assembler_service.hydrate_structured_explanation(
                structured, structured.final_answer or response_assembler_service.symbolic_payload(symbolic_solution), presentation_query
            )
            confidence = compute_confidence_report(
                parse_confidence="high",
                verification_confidence="high" if symbolic_solution.verified else "low",
                method="symbolic" if symbolic_solution.verified else "none",
                parser_source="symbolic_solver",
                math_check_passed=symbolic_solution.verified,
            )

            # Store in session state for multi-turn chat context
            if session_id:
                from cache.redis_cache import redis_client
                try:
                    await redis_client.client.setex(f"session:{session_id}:last_problem", 3600, presentation_query)
                    if structured.quick_summary:
                        await redis_client.client.setex(f"session:{session_id}:last_summary", 3600, structured.quick_summary)
                except Exception as e:
                    logger.warning("failed_to_save_session_context", error=str(e), session_id=session_id)

            raw_result = symbolic_solution.math_result.result
            math_engine_str = str(raw_result) if raw_result is not None else None
            _assembled = response_assembler_service.assemble_response(
                structured=structured,
                confidence=confidence,
                coach_feedback=response_assembler_service.coach_feedback(coaching_decision),
                model_used="adaptive_explainer",
                math_engine_result=math_engine_str,
                credits_remaining=credits_remaining,
            )

            # Append Socratic probe question to the response when available.
            if socratic_probe is not None:
                _probe_text = (
                    f"\n\n---\n**Practice check:** {socratic_probe.question_text}"
                )
                _assembled.raw_text = (_assembled.raw_text or "") + _probe_text
                _assembled.coach_feedback = (
                    (_assembled.coach_feedback or "")
                    + f"\n\n{socratic_probe.question_text}"
                ).strip()

            return _assembled, "sympy"
            
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
        session_id: str | None,
    ) -> tuple[ControllerResponse, str]:
        decision = model_router.route(classification)
        
        last_problem = None
        last_summary = None
        if session_id:
            from cache.redis_cache import redis_client
            try:
                raw_prob = await redis_client.client.get(f"session:{session_id}:last_problem")
                raw_sum = await redis_client.client.get(f"session:{session_id}:last_summary")
                if raw_prob: last_problem = raw_prob.decode("utf-8") if isinstance(raw_prob, bytes) else raw_prob
                if raw_sum: last_summary = raw_sum.decode("utf-8") if isinstance(raw_sum, bytes) else raw_sum
            except Exception as e:
                logger.warning("failed_to_load_session_context", error=str(e), session_id=session_id)

        messages = [
            {"role": "system", "content": build_chat_system_prompt(last_problem, last_summary)},
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

    @staticmethod
    def _apply_execution_modifiers(pedagogical_decision: dict[str, Any], execution_plan: QueryExecutionPlan) -> dict[str, Any]:
        if not execution_plan or not execution_plan.steps:
            return pedagogical_decision

        updated = dict(pedagogical_decision or {})
        reason = str(updated.get("reason") or "").strip()
        confidence = float(updated.get("confidence") or 0.5)
        solve_step = execution_plan.solve_step
        explain_step = execution_plan.explain_step

        if solve_step and solve_step.mode == "scaffolded":
            updated["strategy"] = "scaffolded"
            updated["reason"] = (reason + " User explicitly asked for detailed step-by-step execution.").strip()
            updated["confidence"] = max(confidence, 0.92)
        elif explain_step and explain_step.mode == "scaffolded" and explain_step.depends_on == 0:
            updated["strategy"] = "scaffolded"
            updated["reason"] = (reason + " User asked for a detailed walkthrough of the solve steps.").strip()
            updated["confidence"] = max(confidence, 0.9)
        elif solve_step and solve_step.mode == "minimal":
            updated["strategy"] = "worked_example"
            updated["reason"] = (reason + " User asked for a brief explanation style.").strip()
            updated["confidence"] = max(confidence, 0.8)
        elif solve_step and solve_step.mode == "guided":
            updated["strategy"] = "worked_example" if updated.get("strategy") == "analogy" else updated.get("strategy", "worked_example")

        return updated

    @staticmethod
    def _teaching_directives(execution_plan: QueryExecutionPlan) -> list[str]:
        directives: list[str] = []
        solve_step = execution_plan.solve_step
        explain_step = execution_plan.explain_step
        if solve_step and solve_step.mode == "scaffolded":
            directives.append("Explain each algebraic step in detail and do not skip intermediate transformations.")
            directives.append("Make the step sequence explicit, with clear reasoning for why each step is valid.")
        elif solve_step and solve_step.mode == "minimal":
            directives.append("Keep the solve explanation concise and avoid unnecessary elaboration.")
        elif solve_step and solve_step.mode == "guided":
            directives.append("Show the main steps clearly, but keep the explanation light and readable.")
        if explain_step and explain_step.mode == "minimal":
            directives.append("Keep any attached conceptual explanation brief and focused on the key reason only.")
        elif explain_step and explain_step.mode == "scaffolded":
            if explain_step.depends_on == 0:
                directives.append("Explain each algebraic step in detail and connect it to the reasoning behind the result.")
            directives.append("For the attached conceptual explanation, unpack the reasoning in detail.")
        elif explain_step and explain_step.mode == "guided":
            directives.append("For the attached conceptual explanation, give a short but clear reason for why the result makes sense.")
        return directives

master_controller = MasterController()
