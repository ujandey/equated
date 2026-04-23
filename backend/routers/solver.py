"""
Router - Solver Endpoint

Simplified pipeline: Rate Limit → Execute → Respond.
Economic defenses (kill-storm, WFQ, compute budget) are disabled
in this phase to maximize solve rate and UX for real students.
"""

import asyncio
import time
from typing import Annotated

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from core.exceptions import AIServiceError, EquatedError
from db.models import MultiQuestionResponse, QuestionOption, SolveRequest, SolveResponse
from monitoring.metrics import SOLVES_TOTAL
from monitoring.posthog_client import track
from services.master_controller import master_controller
from services.rate_limiter import user_rate_limiter
from services.streaming_service import streaming_service
from services.ast_guard import ast_guard

router = APIRouter()
logger = structlog.get_logger("equated.routers.solver")

_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


class SelectQuestionRequest(BaseModel):
    question_id: str
    questions: list[QuestionOption]
    user_id: str
    session_id: str | None = None


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
    verification_status = "verified" if result.response.verified else "partial" if result.response.math_check_passed else "unverified"
    return SolveResponse(
        problem_interpretation=result.response.problem_interpretation,
        concept_used=result.response.concept,
        concept_explanation=getattr(result.response, 'concept_explanation', ''),
        subject_hint=getattr(result.response, 'subject_hint', ''),
        steps=result.response.steps,
        final_answer=result.response.final_answer or result.response.clarification_request or "",
        quick_summary=result.response.quick_summary or result.response.simple_explanation,
        answer_summary=getattr(result.response, 'answer_summary', '') or result.response.quick_summary or result.response.simple_explanation,
        alternative_method=result.response.alternative_method,
        common_mistakes=result.response.common_mistakes,
        model_used=result.response.model_used,
        parser_source=result.response.parser_source,
        parser_confidence=confidence_label,
        verified=result.response.verified,
        verification_confidence=result.response.verification_confidence,
        verification_status=verification_status,
        math_check_passed=result.response.math_check_passed,
        math_engine_result=result.response.math_engine_result,
        confidence=result.response.confidence,
        cached=False,
        credits_remaining=result.response.credits_remaining,
        debug={**result.debug_plan, "execution_echo": result.execution_echo} if req.debug else None,
    )


# ── Image solve endpoints ─────────────────────────────────────────────────────


@router.post("/solve/image")
async def solve_image(
    request: Request,
    file: Annotated[UploadFile, File()],
    session_id: Annotated[str | None, Form()] = None,
):
    """
    Accept a multipart image upload, extract STEM questions via multi-engine
    OCR, and either solve (single question) or return a selector (multi).
    """
    user_id = request.state.user_id

    # ── Validate content type ──
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Please upload a JPG, PNG, WebP, or HEIC image.",
        )

    image_bytes = await file.read()

    # ── Enforce 10 MB limit ──
    if len(image_bytes) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large. Max 10MB.")

    # ── Parse via OCR pipeline ──
    from services.image_parser import (
        LowConfidenceError,
        NoQuestionsError,
        route_and_parse,
    )
    from services.image_preprocessor import ImagePreprocessError

    try:
        parse_result = await route_and_parse(image_bytes)
    except ImagePreprocessError as exc:
        logger.warning("image_preprocess_failed", error=str(exc), user_id=user_id[:8])
        raise HTTPException(status_code=422, detail={
            "error": "preprocess_failed",
            "message": "Could not read this image. Try a clearer photo.",
        })
    except LowConfidenceError as exc:
        partial_questions = [
            {"id": str(i + 1), "text": q, "latex": exc.partial_result.latex_versions[i] if i < len(exc.partial_result.latex_versions) else ""}
            for i, q in enumerate(exc.partial_result.questions)
        ]
        raise HTTPException(status_code=422, detail={
            "error": "low_confidence",
            "message": exc.message,
            "partial_questions": partial_questions,
        })
    except NoQuestionsError:
        raise HTTPException(status_code=422, detail={
            "error": "no_questions",
            "message": "No math questions found. Try a clearer photo.",
        })
    except Exception as exc:
        logger.error("image_parse_failed", error=str(exc), user_id=user_id[:8])
        raise HTTPException(
            status_code=503,
            detail="Image parsing unavailable. Type your question instead.",
        )

    # ── Single question → run through solve pipeline ──
    if parse_result.question_count == 1:
        limit_result = await user_rate_limiter.check_limit(user_id)
        if not limit_result["allowed"]:
            raise HTTPException(status_code=429, detail=limit_result["message"])
        try:
            result = await master_controller.handle_query(
                user_id=user_id,
                query=parse_result.questions[0],
                source="solve",
                session_id=session_id,
                credits_remaining=limit_result.get("remaining"),
            )
        except EquatedError:
            raise
        except Exception as exc:
            logger.error("image_solve_failed", user_id=user_id[:8], error=str(exc))
            raise HTTPException(status_code=500, detail="Something went wrong while solving. Please try again.")

        confidence_label = (
            "high" if result.response.confidence >= 0.9
            else "medium" if result.response.confidence >= 0.6
            else "low"
        )
        img_verification_status = "verified" if result.response.verified else "partial" if result.response.math_check_passed else "unverified"
        return SolveResponse(
            problem_interpretation=result.response.problem_interpretation,
            concept_used=result.response.concept,
            concept_explanation=getattr(result.response, 'concept_explanation', ''),
            subject_hint=getattr(result.response, 'subject_hint', ''),
            steps=result.response.steps,
            final_answer=result.response.final_answer or result.response.clarification_request or "",
            quick_summary=result.response.quick_summary or result.response.simple_explanation,
            answer_summary=getattr(result.response, 'answer_summary', '') or result.response.quick_summary or result.response.simple_explanation,
            alternative_method=result.response.alternative_method,
            common_mistakes=result.response.common_mistakes,
            model_used=result.response.model_used,
            parser_source=parse_result.engine_used,
            parser_confidence=confidence_label,
            verified=result.response.verified,
            verification_confidence=result.response.verification_confidence,
            verification_status=img_verification_status,
            math_check_passed=result.response.math_check_passed,
            math_engine_result=result.response.math_engine_result,
            confidence=result.response.confidence,
            cached=False,
            credits_remaining=result.response.credits_remaining,
        )

    # ── Multiple questions → return selector payload ──
    triage_type = "mixed"  # already decided by OCR pipeline
    return MultiQuestionResponse(
        questions=[
            QuestionOption(
                id=str(i + 1),
                text=parse_result.questions[i],
                latex=parse_result.latex_versions[i] if i < len(parse_result.latex_versions) else "",
                subject_hint=parse_result.subject_hints[i] if i < len(parse_result.subject_hints) else "algebra",
            )
            for i in range(parse_result.question_count)
        ],
        image_type=triage_type,
        engine_used=parse_result.engine_used,
    )


@router.post("/solve/image/select", response_model=SolveResponse)
async def select_image_question(req: SelectQuestionRequest, request: Request):
    """
    Receive the user's question selection from the QuestionSelector UI and run
    it through the solve pipeline without re-parsing the image.
    """
    user_id = request.state.user_id

    selected = next((q for q in req.questions if q.id == req.question_id), None)
    if selected is None:
        raise HTTPException(status_code=400, detail="Invalid question_id.")

    limit_result = await user_rate_limiter.check_limit(user_id)
    if not limit_result["allowed"]:
        raise HTTPException(status_code=429, detail=limit_result["message"])

    try:
        result = await master_controller.handle_query(
            user_id=user_id,
            query=selected.text,
            source="solve",
            session_id=req.session_id,
            credits_remaining=limit_result.get("remaining"),
        )
    except EquatedError:
        raise
    except Exception as exc:
        logger.error("image_select_solve_failed", user_id=user_id[:8], error=str(exc))
        raise HTTPException(status_code=500, detail="Something went wrong while solving. Please try again.")

    confidence_label = (
        "high" if result.response.confidence >= 0.9
        else "medium" if result.response.confidence >= 0.6
        else "low"
    )
    sel_verification_status = "verified" if result.response.verified else "partial" if result.response.math_check_passed else "unverified"
    return SolveResponse(
        problem_interpretation=result.response.problem_interpretation,
        concept_used=result.response.concept,
        concept_explanation=getattr(result.response, 'concept_explanation', ''),
        subject_hint=getattr(result.response, 'subject_hint', ''),
        steps=result.response.steps,
        final_answer=result.response.final_answer or result.response.clarification_request or "",
        quick_summary=result.response.quick_summary or result.response.simple_explanation,
        answer_summary=getattr(result.response, 'answer_summary', '') or result.response.quick_summary or result.response.simple_explanation,
        alternative_method=result.response.alternative_method,
        common_mistakes=result.response.common_mistakes,
        model_used=result.response.model_used,
        parser_source="image_select",
        parser_confidence=confidence_label,
        verified=result.response.verified,
        verification_confidence=result.response.verification_confidence,
        verification_status=sel_verification_status,
        math_check_passed=result.response.math_check_passed,
        math_engine_result=result.response.math_engine_result,
        confidence=result.response.confidence,
        cached=False,
        credits_remaining=result.response.credits_remaining,
    )
