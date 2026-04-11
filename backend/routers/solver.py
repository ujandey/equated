"""
Router - Solver Endpoint
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request

from db.models import SolveRequest, SolveResponse
from services.master_controller import master_controller
from services.rate_limiter import user_rate_limiter
from services.streaming_service import streaming_service
from services.credits import credit_service, MODEL_CREDIT_COSTS
from core.exceptions import CreditError, NodeCapacityError, ResourceExhaustionError

# Phase 2 Economic Controls
from services.local_governor import local_governor
from services.ast_guard import ast_guard
from services.compute_budget import compute_budget
from services.weighted_queue import wfq

# Phase 3 Adversarial Intelligence
from services.kill_storm_tracker import kill_storm_tracker
from services.anti_gaming import AbuseThrottleMiddleware

router = APIRouter()


@router.post("/solve", response_model=SolveResponse)
async def solve_problem(req: SolveRequest, request: Request):
    user_id = request.state.user_id

    limit_result = await user_rate_limiter.check_limit(user_id)
    if not limit_result["allowed"]:
        raise HTTPException(status_code=429, detail=limit_result["message"])

    # --- Phase 3: Kill-Storm Defense Check ---
    client_ip = request.client.host if request.client else "unknown"
    blackhole = await kill_storm_tracker.check_blackhole(client_ip, user_id)
    if blackhole.block:
        raise HTTPException(
            status_code=403, 
            detail="Access temporarily restricted due to network instability. Please contact support if this persists."
        )

    # --- Phase 2: Full 5-Gate Economic Pipeline ---
    
    # ── Gate 1: Local Governor (Capacity) ──
    if not await local_governor.acquire():
        raise HTTPException(status_code=503, detail="Server at absolute capacity. Try again shortly.")
        
    try:
        # Pre-execution Model Selection
        model_name = getattr(request.state, "fallback_model", "gemini-2.0-flash")
        tier = limit_result.get("tier", "free")

        # ── Gate 2: AST / Heuristics ──
        # Note: req.question might contain text so AST is a heuristic here.
        # Strict validation also runs inside symbolic_solver during actual compute.
        is_global_anomaly = (blackhole.reason == "global_anomaly_active")
        analysis = ast_guard.validate(req.question, strict_mode=is_global_anomaly)
        if not analysis.safe:
            # Phase 3: Record visible penalty box AST rejections
            await AbuseThrottleMiddleware.record_ast_rejection(user_id)
            raise HTTPException(status_code=429, detail=f"Request rejected due to complexity limits: {', '.join(analysis.violations)}")

        # ── Gate 3: Pre-WFQ Sanity Check & Acquire ──
        # Fix: Prevent empty users from trying to acquire a WFQ lock 
        # and then failing on DB Reservation, temporarily wasting throughput
        from config.settings import settings
        if limit_result["remaining"] < settings.MIN_REQUIRED_CREDITS_HINT and tier != "free":
             raise HTTPException(status_code=402, detail="Insufficient credits minimum floor. Please recharge to compute this request.")

        weight = analysis.category_weight
        if not await wfq.can_acquire_weight(user_id, weight):
            raise HTTPException(status_code=503, detail="Compute queue full for this operation size. Try again.", headers={"Retry-After": "3"})

        async with wfq.acquire(weight):
            
            # ── Gate 4: Compute Reservation ──
            try:
                reservation_id = await compute_budget.reserve(user_id, analysis, model_name)
            except NodeCapacityError as nce:
                raise HTTPException(status_code=503, detail=str(nce))
            except CreditError as ce:
                raise HTTPException(status_code=402, detail=str(ce))

            try:
                import time
                start_time = time.perf_counter()

                # Execution
                result = await master_controller.handle_query(
                    user_id=user_id,
                    query=req.question,
                    source="solve",
                    session_id=req.session_id,
                    credits_remaining=limit_result["remaining"],
                )
                
                # Check for runtime fallback model override (e.g. LLM decided to use GPT-4)
                if result and result.response and result.response.model_used:
                    model_name = result.response.model_used
                    
                exec_time = time.perf_counter() - start_time

            except Exception as e:
                import structlog
                log = structlog.get_logger("equated.routers.solver")
                log.error("solve_failed", user_id=user_id, error=str(e))
                # Refund automatically on crash
                await compute_budget.settle(reservation_id, user_id, None, model_name, False)
                
                # Phase 3: Record sandbox/system kill for anti-gaming and kill-storm
                await kill_storm_tracker.record_kill(client_ip, user_id, tier)
                raise HTTPException(status_code=500, detail="Solve failed")

            # ── Gate 5: Settlement ──
            # Reconstruct dummy SandboxResult for settlement cost since master_controller 
            # obscures the low level sandbox data from the router currently.
            from core.contracts import SandboxResult
            # We charge purely based on elapsed time here for the whole pipeline segment
            dummy_sandbox = SandboxResult(
                 success=True, result_text="", latex_result="", steps=(),
                 error=None, compute_seconds=exec_time, node_count=0, peak_memory_kb=0,
                 killed=False, kill_reason=None
            )
            
            await compute_budget.settle(
                reservation_id=reservation_id,
                user_id=user_id,
                sandbox_res=dummy_sandbox,
                model_name=model_name,
                has_llm_call=(result.response.model_used != "symbolic-engine")
            )

    finally:
        await local_governor.release()

    if req.stream:
        async def token_stream():
            text = result.response.raw_text
            for i in range(0, len(text), 80):
                await asyncio.sleep(0)
                yield text[i:i + 80]

        return streaming_service.create_sse_response(
            token_stream(),
            model_name=result.response.model_used,
            session_id=result.session_id,
            done_meta={
                "intent": result.trace.intent,
                "strategy": result.trace.strategy,
                "block_id": result.trace.block_id,
                "tool_used": result.trace.tool_used,
                "validation_passed": result.trace.validation_passed,
                **({"debug": {**result.debug_plan, "execution_echo": result.execution_echo}} if req.debug else {}),
            },
        )

    confidence_label = "high" if result.response.confidence >= 0.9 else "medium" if result.response.confidence >= 0.6 else "low"
    return SolveResponse(
        problem_interpretation=result.response.problem_interpretation,
        concept_used=result.response.concept,
        steps=result.response.steps,
        final_answer=result.response.final_answer or result.response.clarification_request or "",
        quick_summary=result.response.quick_summary or result.response.simple_explanation,
        alternative_method=result.response.alternative_method,
        common_mistakes=result.response.common_mistakes,
        model_used=result.response.model_used,
        parser_source=result.response.parser_source,
        parser_confidence=confidence_label,
        verified=result.response.verified,
        verification_confidence=result.response.verification_confidence,
        math_check_passed=result.response.math_check_passed,
        math_engine_result=result.response.math_engine_result,
        cached=False,
        credits_remaining=result.response.credits_remaining,
        debug={**result.debug_plan, "execution_echo": result.execution_echo} if req.debug else None,
    )
