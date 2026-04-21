"""
Gateway — Request Logger Middleware

Logs every request with method, path, status code, duration, and user_id.
Uses structlog for structured JSON logging in production.
"""

import time
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from monitoring.metrics import REQUEST_COUNT, REQUEST_LATENCY

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

        duration_s = time.perf_counter() - start_time
        duration_ms = round(duration_s * 1000, 2)
        user_id = getattr(request.state, "user_id", None)

        # Collapse path params to low-cardinality endpoint label (e.g. /api/v1/chat/stream)
        endpoint = str(request.url.path)

        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration_s)

        logger.info(
            "http_request",
            method=request.method,
            path=endpoint,
            query=str(request.url.query),
            status=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
            client_ip=request.client.host if request.client else "unknown",
        )

        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response
