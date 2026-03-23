"""
Gateway — Rate Limiting Middleware

Uses Redis sliding window counter to enforce per-user and global rate limits.
Applied as ASGI middleware before requests reach any router.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter backed by Redis.

    - Authenticated users: tracked by user_id
    - Anonymous users: tracked by IP address
    - Limit: settings.RATE_LIMIT_PER_MINUTE requests per 60s window
    """

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path.startswith("/api/health"):
            return await call_next(request)

        identifier = self._get_identifier(request)
        limit = settings.RATE_LIMIT_PER_MINUTE

        is_allowed = await self._check_rate_limit(identifier, limit)
        if not is_allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Limit: {limit}/minute.",
                    "retry_after_seconds": 60,
                },
            )

        response = await call_next(request)
        return response

    def _get_identifier(self, request: Request) -> str:
        """Extract user ID from auth header, or fall back to client IP."""
        user_id = request.state.__dict__.get("user_id")
        if user_id:
            return f"rate:user:{user_id}"
        client_ip = request.client.host if request.client else "unknown"
        return f"rate:ip:{client_ip}"

    async def _check_rate_limit(self, key: str, limit: int) -> bool:
        """
        Redis sliding window counter.
        Returns True if request is within limit.

        Implementation:
          - INCR key
          - If count == 1, SET EXPIRE 60s
          - If count > limit, reject
        """
        from cache.redis_cache import redis_client

        count = await redis_client.client.incr(key)
        if count == 1:
            await redis_client.client.expire(key, 60)
        return count <= limit
