"""
Services — Anti Gaming (Abuse Throttler)

Visible penalty box mechanisms. Transparently identifies and throttles 
adversarial behaviors without ghost-banning accounts outright to facilitate debugging.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio
import structlog

from config.settings import settings
from cache.redis_cache import redis_client

logger = structlog.get_logger("equated.middleware.anti_gaming")

class AbuseThrottleMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # We only throttle the actual math endpoints to avoid slowing down static assets
        if not request.url.path.startswith("/api/v1/solve"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        # Very rough user tracking layer here as we run before full fastAPI router
        user_id = self._extract_identifier(auth_header, request)

        if await self._should_throttle(user_id):
            logger.warning("abuse_throttle_active", target=user_id)
            # ── Execute penalty delay (Fix 3: Jitter) ──
            import random
            delay = random.uniform(settings.ABUSE_THROTTLE_DELAY_MIN_S, settings.ABUSE_THROTTLE_DELAY_MAX_S)
            await asyncio.sleep(delay)
            
            # Send through the stack
            response = await call_next(request)
            
            # Warn the client transparently so they know they are in the penalty box
            response.headers["X-Throttled"] = "true"
            # It's difficult to append text to a streaming response body dynamically via middleware
            # without buffering the whole response. Headers are safe.
            return response

        return await call_next(request)

    def _extract_identifier(self, auth_header: str, request: Request) -> str:
        """Get best identifying information (Token or IP)"""
        # Note: In a deployed system behind Cloudflare, use CF-Connecting-IP
        if auth_header.startswith("Bearer "):
             return "user_authenticated" # Fallback mapping proxy
        
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        return request.client.host if request.client else "unknown"

    async def _should_throttle(self, identifier: str) -> bool:
        """
        Check if user breached AST rejection limits.
        (Kill storm checks are processed deeper in the router usually, but we check AST rejects here)
        """
        if identifier == "unknown":
             return False
             
        # Pull abuse markers
        ast_key = f"abuse:ast_rejects:{identifier}"
        kill_key = f"abuse:kills:{identifier}" 
        
        pipe = redis_client.client.pipeline()
        pipe.get(ast_key)
        pipe.get(kill_key)
        res = await pipe.execute()
        
        ast_count = int(res[0] or 0)
        kill_count = int(res[1] or 0)

        if ast_count >= settings.ABUSE_TRIGGER_AST_REJECTIONS:
             base_prob = 1.0
        elif kill_count >= settings.ABUSE_TRIGGER_KILLS:
             base_prob = 1.0
        elif ast_count > 0 or kill_count > 0:
             base_prob = 0.2 # Edge case fuzzing
        else:
             return False
             
        import random
        # Fix 5: Probabilistic throttling prevents exact threshold discovery
        return random.random() < base_prob

    @staticmethod
    async def record_ast_rejection(user_id_or_ip: str):
        """Mark an AST rejection against an identifier."""
        key = f"abuse:ast_rejects:{user_id_or_ip}"
        pipe = redis_client.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 300) # 5 minutes rolling window
        await pipe.execute()
