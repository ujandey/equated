"""
Router - Solver Endpoint

Simplified pipeline: Rate Limit → Execute → Respond.
Economic defenses (kill-storm, WFQ, compute budget) are disabled
in this phase to maximize solve rate and UX for real students.
"""

import asyncio
import time

import structlog
from fastapi import APIRouter, HTTPException, Request

from core.exceptions import EquatedError
from db.models import SolveRequest, SolveResponse
from monitoring.metrics import SOLVES_TOTAL
from monitoring.posthog_client import track
from services.master_controller import master_controller
from services.rate_limiter import user_rate_limiter
from services.streaming_service import streaming_service
from services.ast_guard import ast_guard

router = APIRouter()
logger = structlog.get_logger("equated.routers.solver")


@router.post("/solve", response_model=SolveResponse)
async def solve_problem(req: SolveRequest, request: Request):
    user_id = request.state.user_id

    # ── Gate 1: Rate Limit (the only hard gate) ──
    limit_result = await user_rate_limiter.check_limit(user_id)
    if not limit_result["allowed"]:
        raise HTTPException(status_code=429, detail=limit_result["message"])

    # ── Soft Check: AST Guard (warn-only, never blocks) ──
    try:
        analysis = ast_guard.validate(req.question)
        if not analysis.safe:
            logger.warning(
                "ast_guard_soft_warning",
                user_id=user_id[:8],
                violations=analysis.violations,
                query_preview=req.question[:80],
            )
            # Continue anyway — let the solver try. Students type messy inputs.
    except Exception:
        pass  # AST guard failure should never block a solve

    # ── Execute ──
    try:
        start_time = time.perf_counter()

        result = await master_controller.handle_query(
            user_id=user_id,
            query=req.question,
            source="solve",
            session_id=req.session_id,
            credits_remaining=limit_result.get("remaining"),
        )

        exec_time = time.perf_counter() - start_time
        logger.info(
            "solve_completed",
            user_id=user_id[:8],
            exec_seconds=round(exec_time, 2),
            model=result.response.model_used,
            intent=result.trace.intent,
        )

        source = "cache" if result.response.cached else "ai"
        SOLVES_TOTAL.labels(source=source).inc()
        track(user_id, "solve_completed", {
            "model": result.response.model_used,
            "intent": result.trace.intent,
            "strategy": result.trace.strategy,
            "source": source,
            "latency_ms": round(exec_time * 1000),
            "verified": result.trace.validation_passed,
        })

    except EquatedError:
        raise  # global handler maps to the right status code (e.g. 503 for AIServiceError)
    except Exception as e:
        logger.error("solve_failed", user_id=user_id[:8], error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while solving your problem. Please try again.",
        )

    # ── Respond ──
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
                **({**result.debug_plan, "execution_echo": result.execution_echo} if req.debug else {}),
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
