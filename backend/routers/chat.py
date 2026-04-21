"""
Router - Chat Endpoints
"""

import asyncio

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.dependencies import get_current_user
from core.exceptions import NotFoundError
from services.master_controller import master_controller
from services.session_manager import session_manager
from services.streaming_service import streaming_service

router = APIRouter()


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    stream: bool = False
    session_id: str | None = None
    debug: bool = False


class UpdateSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


@router.post("/chat/sessions")
async def create_session(
    req: CreateSessionRequest,
    user_id: str = Depends(get_current_user),
):
    session = await session_manager.create_session(user_id, req.title)
    return {
        "session_id": session.id,
        "title": session.title,
        "created_at": session.created_at.isoformat(),
    }


@router.get("/chat/sessions")
async def list_sessions(
    user_id: str = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
):
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
    session = await session_manager.get_session(session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Session")

    await session_manager.delete_session(session_id)
    return {"success": True}


@router.get("/chat/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    user_id: str = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100),
):
    session = await session_manager.get_session(session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Session")

    messages = await session_manager.get_context_messages(session_id, max_messages=limit)
    return {"messages": messages}


@router.post("/chat/stream")
async def stream_chat(
    req: SendMessageRequest,
    user_id: str = Depends(get_current_user),
):
    import structlog
    logger = structlog.get_logger("equated.routers.chat")

    try:
        result = await master_controller.handle_query(
            user_id=user_id,
            query=req.content,
            source="chat",
            session_id=req.session_id,
        )
    except Exception as e:
        logger.error("chat_stream_failed", user_id=user_id[:8], error=str(e))

        # Return an SSE stream with a single error event so the frontend
        # error recovery UX can display the message and offer retry.
        import json as _json

        async def error_stream():
            error_event = {"type": "error", "message": "Something went wrong. Please try again."}
            yield f"data: {_json.dumps(error_event)}\n\n"
            yield "data: [DONE]\n\n"

        return streaming_service.create_sse_response(
            error_stream(),
            model_name="",
            session_id=req.session_id,
        )

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
            "block_id": result.trace.block_id,
            "topic_decision_type": result.topic_mode,
            "intent": result.trace.intent,
            "strategy": result.trace.strategy,
            "tool_used": result.trace.tool_used,
            "validation_passed": result.trace.validation_passed,
            "verified": result.response.verified,
            "verification_confidence": result.response.verification_confidence,
            "math_check_passed": result.response.math_check_passed,
            **({**result.debug_plan, "execution_echo": result.execution_echo} if req.debug else {}),
        },
    )
