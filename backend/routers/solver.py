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
from core.exceptions import CreditError

router = APIRouter()


@router.post("/solve", response_model=SolveResponse)
async def solve_problem(req: SolveRequest, request: Request):
    user_id = request.state.user_id

    limit_result = await user_rate_limiter.check_limit(user_id)
    if not limit_result["allowed"]:
        raise HTTPException(status_code=429, detail=limit_result["message"])

    try:
        result = await master_controller.handle_query(
            user_id=user_id,
            query=req.question,
            source="solve",
            session_id=req.session_id,
            credits_remaining=limit_result["remaining"],
        )
    except Exception as e:
        import structlog
        log = structlog.get_logger("equated.routers.solver")
        log.error("solve_failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Solve failed")

    # ONLY DEDUCT CREDITS AFTER SUCCESSFUL SOLVE
    try:
        cost = MODEL_CREDIT_COSTS.get(result.response.model_used, 3)
        await credit_service.deduct_credits(
            user_id=user_id,
            cost=cost,
            solve_id=result.session_id,  # session_id uniquely identifies solve context
            model_name=result.response.model_used
        )
    except CreditError:
        from db.connection import get_db
        db = await get_db()
        await db.execute("DELETE FROM solves WHERE session_id = $1", result.session_id)
        raise HTTPException(status_code=402, detail="Insufficient credits")

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
    )
