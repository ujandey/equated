"""
Gateway — Request Logger Middleware

Logs every request with method, path, status code, duration, and user_id.
Uses structlog for structured JSON logging in production.
"""

import time
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = structlog.get_logger("equated.gateway")


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """
    Structured request/response logger.

    Logs:
      - method, path, query params
      - status code
      - response time in ms
      - user_id (if authenticated)
      - client IP
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        user_id = getattr(request.state, "user_id", None)

        logger.info(
            "http_request",
            method=request.method,
            path=str(request.url.path),
            query=str(request.url.query),
            status=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
            client_ip=request.client.host if request.client else "unknown",
        )

        # Add response timing header
        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response
