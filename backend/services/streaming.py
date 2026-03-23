"""
Services — Streaming Response Handler

Provides ChatGPT-style Server-Sent Events (SSE) streaming
for real-time token-by-token response delivery.
"""

import json
import asyncio
from typing import AsyncIterator

from fastapi.responses import StreamingResponse


class StreamingHandler:
    """
    Wraps model streaming into FastAPI-compatible SSE responses.

    Protocol:
      data: {"type": "token", "content": "..."}\n\n
      data: {"type": "step", "step": 1, "content": "..."}\n\n
      data: {"type": "done", "total_tokens": 123}\n\n
      data: [DONE]\n\n
    """

    def create_sse_response(self, token_stream: AsyncIterator[str]) -> StreamingResponse:
        """Wrap an async token stream into an SSE StreamingResponse."""
        return StreamingResponse(
            self._sse_generator(token_stream),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    async def _sse_generator(self, token_stream: AsyncIterator[str]):
        """Generate SSE events from a token stream."""
        total_tokens = 0
        try:
            async for token in token_stream:
                total_tokens += 1
                event = {"type": "token", "content": token}
                yield f"data: {json.dumps(event)}\n\n"

            # Send completion event
            done_event = {"type": "done", "total_tokens": total_tokens}
            yield f"data: {json.dumps(done_event)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event)}\n\n"
            yield "data: [DONE]\n\n"

    async def stream_with_steps(
        self, token_stream: AsyncIterator[str], step_markers: list[str] | None = None
    ):
        """
        Enhanced streaming that detects step boundaries in the output
        and emits step events alongside token events.
        """
        buffer = ""
        current_step = 0
        step_markers = step_markers or ["Step ", "**Step"]

        async for token in token_stream:
            buffer += token

            # Check if we've entered a new step
            for marker in step_markers:
                if marker in buffer[-len(marker) - 5:]:
                    current_step += 1
                    step_event = {"type": "step", "step": current_step}
                    yield f"data: {json.dumps(step_event)}\n\n"

            token_event = {"type": "token", "content": token}
            yield f"data: {json.dumps(token_event)}\n\n"

        done_event = {"type": "done", "total_steps": current_step}
        yield f"data: {json.dumps(done_event)}\n\n"
        yield "data: [DONE]\n\n"


# Singleton
streaming_handler = StreamingHandler()
