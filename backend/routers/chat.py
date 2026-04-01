"""
Router — Chat Endpoints

/api/v1/chat — session management, messaging, and streaming.
Provides full CRUD for chat sessions and a streaming endpoint
for real-time token delivery.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.dependencies import get_current_user
from core.exceptions import NotFoundError, AIServiceError
from services.session_manager import session_manager
from services.context_compressor import context_compressor
from services.streaming_service import streaming_service
from services.input_validator import input_validator
from services.explanation import explanation_generator
from services.verification import verification_engine
from config.feature_flags import flags

router = APIRouter()


# ── Request / Response Models ───────────────────────
class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    stream: bool = False
    session_id: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


# ── Session Endpoints ──────────────────────────────
@router.post("/chat/sessions")
async def create_session(
    req: CreateSessionRequest,
    user_id: str = Depends(get_current_user),
):
    """Create a new chat session."""
    session = await session_manager.create_session(user_id, req.title)
    return {
        "session_id": session.id,
        "title": session.title,
        "created_at": session.created_at.isoformat(),
    }


@router.get("/chat/sessions")
async def list_sessions(
    user_id: str = Depends(get_current_user),
    limit: int = 20,
):
    """List the user's recent chat sessions."""
    sessions = await session_manager.list_sessions(user_id, limit)
    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "is_active": s.is_active,
            }
            for s in sessions
        ]
    }


@router.get("/chat/sessions/{session_id}")
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
):
    """Get a specific session with its messages."""
    session = await session_manager.get_session(session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Session")

    messages = await session_manager.get_context_messages(session_id, max_messages=50)

    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "messages": messages,
    }


@router.patch("/chat/sessions/{session_id}")
async def update_session(
    session_id: str,
    req: UpdateSessionRequest,
    user_id: str = Depends(get_current_user),
):
    """Rename a chat session."""
    session = await session_manager.get_session(session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Session")

    await session_manager.update_session_title(session_id, req.title)
    return {"success": True, "title": req.title}


@router.delete("/chat/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a chat session and all its messages."""
    session = await session_manager.get_session(session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Session")

    await session_manager.delete_session(session_id)
    return {"success": True}


@router.get("/chat/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    user_id: str = Depends(get_current_user),
    limit: int = 50,
):
    """Get messages for a session."""
    session = await session_manager.get_session(session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Session")

    messages = await session_manager.get_context_messages(session_id, max_messages=limit)
    return {"messages": messages}


# ── Streaming Chat Endpoint ────────────────────────
@router.post("/chat/stream")
async def stream_chat(
    req: SendMessageRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Send a message and stream the AI response via SSE.

    Flow:
      1. Validate input
      2. Get/create session
      3. Math intent check
      4. Build context window (with compression)
      5. Route to AI model
      6. Stream tokens back via SSE
      7. Verify + compute confidence
      8. Save messages to session
    """
    import structlog
    from services.confidence import compute_confidence_report
    from services.math_intent_detector import is_math_like
    from monitoring.pipeline_metrics import pipeline_metrics

    logger = structlog.get_logger("equated.routers.chat")

    # 1. Validate input
    cleaned = input_validator.validate_query(req.content)
    session_id = req.session_id

    # 2. Get or create session
    if not session_id:
        session = await session_manager.create_session(user_id)
        session_id = session.id

    # 3. Save user message
    await session_manager.add_message(session_id, "user", cleaned)

    # 3.5 Math intent check
    has_math_intent = is_math_like(cleaned)
    pipeline_metrics.record_math_intent(has_math_intent)

    # 4. Check Question Cache
    from cache.query_cache import query_cache
    from cache.cache_metrics import cache_metrics

    cache_hit = await query_cache.lookup(cleaned)
    if cache_hit.found:
        if cache_hit.similarity == 1.0:
            cache_metrics.record_redis_hit()
        else:
            cache_metrics.record_vector_hit()

        # Extract string content (vector_cache might return dict)
        cached_content = cache_hit.cached_solution
        if isinstance(cached_content, dict):
            cached_content = cached_content.get("solution", str(cached_content))

        async def simulate_stream(content: str):
            # Chunk it so it's not a single massive token (makes UI feel more alive)
            chunk_size = 50
            for i in range(0, len(content), chunk_size):
                import asyncio
                await asyncio.sleep(0.01)
                yield content[i:i+chunk_size]

        # Save the cache hit to the session history via Celery
        from workers.tasks import save_chat_message
        save_chat_message.delay(session_id, "assistant", cached_content, {"cached": True})

        logger.info(
            "chat_cache_hit",
            user_id=user_id[:8],
            session_id=session_id[:8],
        )

        return streaming_service.create_sse_response(
            simulate_stream(cached_content),
            model_name="cache-hit",
            session_id=session_id,
        )

    # Miss, record it
    cache_metrics.record_redis_miss()
    cache_metrics.record_vector_miss()

    # 5. Build context window
    context_messages = await session_manager.get_context_messages(session_id)
    context_messages = context_compressor.compress(context_messages)

    # 6. Add system prompt
    from ai.prompts import SOLVER_SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": SOLVER_SYSTEM_PROMPT},
    ] + context_messages

    # 7. Route to model and stream
    from ai.classifier import classifier
    from ai.router import model_router
    from ai.fallback import fallback_handler

    classification = classifier.classify(cleaned)
    decision = model_router.route(classification)

    try:
        token_stream = fallback_handler.stream_with_fallback(
            messages,
            decision,
            user_id=user_id,
        )

        async def cache_and_stream(stream, query, sess_id):
            full_response = []
            async for token in stream:
                full_response.append(token)
                yield token

            if full_response:
                content = "".join(full_response)

                # Run verification only if math intent detected
                if has_math_intent:
                    explanation = explanation_generator.generate(content, query)
                    answer_for_verification = explanation.final_answer or content
                    analysis = await verification_engine.analyze_problem(query)
                    math_result = analysis.math_result
                    verification = verification_engine.verify(query, answer_for_verification, math_result, parse_result=analysis)
                    confidence = compute_confidence_report(
                        parse_confidence=analysis.confidence,
                        verification_confidence=verification.confidence.value,
                        method=verification.method,
                        parser_source=analysis.source,
                        math_check_passed=verification.math_check_passed,
                    )
                    pipeline_metrics.record_parse(analysis.source)
                    pipeline_metrics.record_confidence(confidence.overall_confidence.value)
                    pipeline_metrics.record_verification(
                        "passed" if verification.is_verified else "failed",
                        verification.method,
                    )
                else:
                    confidence = compute_confidence_report(
                        parse_confidence="low",
                        verification_confidence="low",
                        method="none",
                        parser_source="skipped",
                        math_check_passed=False,
                        failure_reason="no_math_intent",
                    )
                    math_result = None
                    analysis = None
                    pipeline_metrics.record_parse("skipped")
                    pipeline_metrics.record_confidence("low")
                    pipeline_metrics.record_verification("skipped", "none")

                # Store in cache and session history via Celery workers
                from workers.tasks import save_chat_message, index_cache_entry
                index_cache_entry.delay(query, content)
                save_chat_message.delay(
                    sess_id, "assistant", content,
                    {
                        "model": decision.model_name,
                        "cached": False,
                        "verified": confidence.verified,
                        "overall_confidence": confidence.overall_confidence.value,
                        "verification_confidence": confidence.verification_confidence.value,
                        "math_check_passed": confidence.verified,
                        "math_engine_result": math_result.result if math_result and math_result.success else None,
                        "parser_source": confidence.parser_source,
                        "parse_confidence": confidence.parse_confidence.value,
                        "method": confidence.method,
                    }
                )

                # Structured log per chat response
                logger.info(
                    "chat_stream_complete",
                    user_id=user_id[:8],
                    session_id=sess_id[:8],
                    verified=confidence.verified,
                    overall_confidence=confidence.overall_confidence.value,
                    method=confidence.method,
                    parser_source=confidence.parser_source,
                    model=decision.model_name,
                    has_math_intent=has_math_intent,
                )

        return streaming_service.create_sse_response(
            cache_and_stream(token_stream, cleaned, session_id),
            model_name=decision.model_name,
            session_id=session_id,
        )
    except Exception as e:
        raise AIServiceError(
            f"Failed to stream response: {str(e)}",
            provider=decision.provider.value,
        )
