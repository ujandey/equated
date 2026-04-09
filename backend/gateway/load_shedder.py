"""
Gateway — Load Shedder

Implements Phase 2 Tiered Load Shedding.
Protects the system from overload by dropping requests strategically:
1. Rejects unknown/free tier immediately when overloaded.
2. Rebuffs paid tier requests only at extreme loads, but returns 200 with 
   X-Degraded header instead of 503, preserving UX transparency.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from config.settings import settings
from services.local_governor import local_governor
from cache.redis_cache import redis_client

logger = structlog.get_logger("equated.gateway.load_shedder")

class LoadSheddingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only apply load shedding to computationally expensive endpoints
        if not request.url.path.startswith("/api/v1/solve"):
            return await call_next(request)

        # ── Global "Oh-Shit" Circuit Breaker (protect against total collapse) ──
        import psutil
        cpu_load = psutil.cpu_percent()
        if cpu_load > 95.0:
            logger.critical("global_circuit_breaker_active", cpu=cpu_load)
            return Response(
                content='{"detail": "Critical system load. Compute unavailable. Please retry in 1 minute."}',
                status_code=503,
                media_type="application/json",
                headers={"Retry-After": "60"}
            )

        # 1. Capacity Check using local governor metrics
        metrics = local_governor.get_metrics()
        active = metrics["active"]
        limit = metrics["limit"]
        
        # Define severe threshold (e.g., 90% capacity)
        severe_load = active >= (limit * 0.9)

        if severe_load:
            # We are under heavy load, evaluate identity
            auth_header = request.headers.get("Authorization", "")
            user_id = self._extract_user_id(auth_header)
            
            # Fetch user tier (can be optimized with JWT claims or Redis later)
            tier = await self._get_user_tier(user_id) if user_id else "free"
            
            if tier == "free":
                # Immediately drop free tier during massive load
                logger.warning("load_shed_free", user_id=user_id, active=active, limit=limit)
                return Response(
                    content='{"detail": "System overloaded. Please try again later. Priority given to paid users."}',
                    status_code=503,
                    media_type="application/json"
                )
            else:
                # Paid tier requests are degraded but not dropped entirely unless at 100% capacity
                if active >= limit:
                    logger.warning("load_shed_paid_capacity", user_id=user_id, active=active, limit=limit)
                    return Response(
                         content='{"detail": "Absolute system capacity reached. Please retry in a few seconds."}',
                         status_code=503,
                         media_type="application/json",
                         headers={"Retry-After": "5"}
                    )
                
                logger.warning("load_shed_paid_degraded", user_id=user_id)
                # Let paid requests pass but inject signal header for UX notification
                request.state.is_degraded = True
                response = await call_next(request)
                response.headers["X-System-Degraded"] = "True"
                return response
        
        # Normal operation
        request.state.is_degraded = False     
        return await call_next(request)

    def _extract_user_id(self, auth_header: str) -> str | None:
        """Naive extraction, assumes real extraction handles JWT correctly."""
        # For this prototype we will assume the router extracts user_id natively.
        # But for middleware routing, we need the DB/Redis check.
        # Given we are operating *before* the router, we will proxy this lazily.
        # For now, it will look up if there's an auth header.
        if not auth_header.startswith("Bearer "):
             return None
        return "authenticated" # Temporary stub, full implementation uses decode

    async def _get_user_tier(self, user_id: str | None) -> str:
        """Fetch tier from DB or return free."""
        # TODO: Caching in Redis
        if not user_id:
            return "free"
        
        # During actual runtime we'd decode the JWT to check `user_metadata.tier` 
        # or use Supabase `auth.uid()`.
        # For now we assume if token is present, we permit it to pass to the router
        # which will perform the actual precise deduction rejection contextually.
        return "paid" # Fail-open for paid check during transit
