"""
Services — Streaming Service

Provides ChatGPT-style SSE (Server-Sent Events) streaming for real-time
token-by-token delivery across both /solve and /chat/stream endpoints.

Protocol:
  data: {"type": "token", "content": "..."}
  data: {"type": "step", "step": 1, "content": "..."}
  data: {"type": "thinking", "content": "..."}
  data: {"type": "done", "total_tokens": 123, "model": "..."}
  data: {"type": "error", "message": "..."}
  data: [DONE]
"""

import json
import time
import structlog
from typing import AsyncIterator

from fastapi.responses import StreamingResponse

logger = structlog.get_logger("equated.services.streaming")


class StreamingService:
    """
    Wraps model token streams into FastAPI-compatible SSE responses.
    Handles chunking, step detection, error recovery, and metrics.
    """

    def create_sse_response(
        self,
        token_stream: AsyncIterator[str],
        model_name: str = "",
        session_id: str | None = None,
        done_meta: dict | None = None,
    ) -> StreamingResponse:
        """Create an SSE StreamingResponse from an async token stream."""
        return StreamingResponse(
            self._sse_generator(token_stream, model_name, session_id, done_meta),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _sse_generator(
        self,
        token_stream: AsyncIterator[str],
        model_name: str,
        session_id: str | None,
        done_meta: dict | None,
    ):
        """Generate SSE events from a token stream with step detection."""
        total_tokens = 0
        current_step = 0
        buffer = ""
        start_time = time.perf_counter()

        step_markers = ["Step ", "**Step", "step ", "→"]

        try:
            async for token in token_stream:
                total_tokens += 1
                buffer += token

                # Detect step boundaries
                for marker in step_markers:
                    if marker in buffer[-len(marker) - 10:]:
                        current_step += 1
                        step_event = {"type": "step", "step": current_step}
                        yield f"data: {json.dumps(step_event)}\n\n"
                        break

                # Emit token
                token_event = {"type": "token", "content": token}
                yield f"data: {json.dumps(token_event)}\n\n"

            # Completion event
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            done_event = {
                "type": "done",
                "total_tokens": total_tokens,
                "total_steps": current_step,
                "model": model_name,
                "duration_ms": duration_ms,
            }
            if done_meta:
                done_event.update(done_meta)
            if session_id:
                done_event["session_id"] = session_id

            yield f"data: {json.dumps(done_event)}\n\n"
            yield "data: [DONE]\n\n"

            logger.info(
                "stream_completed",
                tokens=total_tokens,
                steps=current_step,
                duration_ms=duration_ms,
                model=model_name,
            )

        except Exception as e:
            logger.error(
                "stream_error",
                error=str(e),
                tokens_so_far=total_tokens,
                exc_info=True,
            )
            error_event = {"type": "error", "message": "An internal error occurred."}
            yield f"data: {json.dumps(error_event)}\n\n"
            yield "data: [DONE]\n\n"

    async def collect_stream(self, token_stream: AsyncIterator[str]) -> str:
        """
        Collect all tokens from a stream into a single string.
        Used when we need the full response (e.g., for caching).
        """
        collected = []
        async for token in token_stream:
            collected.append(token)
        return "".join(collected)


# Singleton
streaming_service = StreamingService()
