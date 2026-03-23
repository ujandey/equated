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
from config.feature_flags import flags

router = APIRouter()


# ── Request / Response Models ───────────────────────
class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    stream: bool = False


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
    session_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """
    Send a message and stream the AI response via SSE.

    Flow:
      1. Validate input
      2. Get/create session
      3. Build context window (with compression)
      4. Route to AI model
      5. Stream tokens back via SSE
      6. Save messages to session
    """
    # 1. Validate input
    cleaned = input_validator.validate_query(req.content)

    # 2. Get or create session
    if not session_id:
        session = await session_manager.create_session(user_id)
        session_id = session.id

    # 3. Save user message
    await session_manager.add_message(session_id, "user", cleaned)

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
    from ai.models import get_model

    classification = classifier.classify(cleaned)
    decision = model_router.route(classification)

    try:
        model = get_model(decision.provider.value)
        token_stream = model.stream(
            messages,
            max_tokens=decision.max_tokens,
            temperature=decision.temperature,
        )

        async def cache_and_stream(stream, query, sess_id):
            full_response = []
            async for token in stream:
                full_response.append(token)
                yield token
            
            if full_response:
                content = "".join(full_response)
                # Store in cache and session history via Celery workers
                from workers.tasks import save_chat_message, index_cache_entry
                index_cache_entry.delay(query, content)
                save_chat_message.delay(
                    sess_id, "assistant", content,
                    {"model": decision.model_name, "cached": False}
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
