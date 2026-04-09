"""
Cache — Redis Client

General-purpose Redis cache for:
  - Solution result caching (query hash → response)
  - Rate limit counters
  - Session temp data

Reports Redis health to LocalGovernor for split-brain resilience.
On Redis failure: governor tightens concurrency limits (8 → 4).
On Redis recovery: governor restores normal limits after hysteresis window.
"""

import json
import logging
import redis.asyncio as redis

from config.settings import settings

_logger = logging.getLogger("equated.cache.redis")

# Lazy reference to local governor — avoids circular imports
_governor = None


def _report_health(healthy: bool) -> None:
    """Report Redis health to the local governor (lazy-loaded)."""
    global _governor
    if _governor is None:
        try:
            from services.local_governor import local_governor
            _governor = local_governor
        except ImportError:
            return
    _governor.report_redis_health(healthy)


class RedisCache:
    """Async Redis client wrapper with health reporting."""

    def __init__(self):
        self.client: redis.Redis | None = None

    async def connect(self):
        """Initialize Redis connection."""
        kwargs = dict(
            encoding="utf-8",
            decode_responses=True,
        )
        # Upstash requires SSL but we need to skip cert verification
        if settings.REDIS_URL.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = None
        self.client = redis.from_url(
            settings.REDIS_URL,
            **kwargs,
        )
        _report_health(True)

    async def disconnect(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()

    async def get(self, key: str) -> str | None:
        """Get a value by key."""
        try:
            result = await self.client.get(key)
            _report_health(True)
            return result
        except Exception as e:
            _logger.error(f"Redis GET failed: {e}", exc_info=False)
            _report_health(False)
            return None

    async def set(self, key: str, value: str, ttl: int = 3600):
        """Set a value with TTL (default 1 hour)."""
        try:
            await self.client.set(key, value, ex=ttl)
            _report_health(True)
        except Exception as e:
            _logger.error(f"Redis SET failed: {e}", exc_info=False)
            _report_health(False)

    async def set_nx(self, key: str, value: str, ttl: int = 60) -> bool:
        """Set a value only if it does not exist (for locking). Returns True if set."""
        try:
            result = await self.client.set(key, value, nx=True, ex=ttl)
            _report_health(True)
            return bool(result)
        except Exception as e:
            _logger.error(f"Redis SET NX failed: {e}", exc_info=False)
            _report_health(False)
            return False

    async def get_json(self, key: str) -> dict | None:
        """Get and deserialize a JSON value."""
        try:
            raw = await self.client.get(key)
            _report_health(True)
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            _logger.error(f"Redis GET JSON failed: {e}", exc_info=False)
            _report_health(False)
            return None

    async def set_json(self, key: str, data: dict, ttl: int = 3600):
        """Serialize and store a JSON value."""
        try:
            await self.client.set(key, json.dumps(data), ex=ttl)
            _report_health(True)
        except Exception as e:
            _logger.error(f"Redis SET JSON failed: {e}", exc_info=False)
            _report_health(False)

    async def set_json_with_compute_weight(self, key: str, data: dict, compute_seconds: float, base_ttl: int = 3600):
        """
        Anti-Pollution Store (Phase 3).
        Scales TTL logarithmically based on compute expense.
        Expensive queries stay around much longer, preventing repeated heavy attacks.
        """
        import math
        # 0.5s -> multiplier = 1, 10s -> multiplier ~= 4
        multiplier = 1 + math.log2(max(1.0, compute_seconds))
        effective_ttl = int(base_ttl * multiplier)

        try:
            await self.client.set(key, json.dumps(data), ex=effective_ttl)
            _report_health(True)
        except Exception as e:
            _logger.error(f"Redis SET JSON WEIGHTED failed: {e}", exc_info=False)
            _report_health(False)

    async def delete(self, key: str):
        """Delete a key."""
        try:
            await self.client.delete(key)
            _report_health(True)
        except Exception as e:
            _logger.error(f"Redis DELETE failed: {e}", exc_info=False)
            _report_health(False)

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        try:
            result = await self.client.exists(key) > 0
            _report_health(True)
            return result
        except Exception as e:
            _logger.error(f"Redis EXISTS failed: {e}", exc_info=False)
            _report_health(False)
            return False

    async def incr(self, key: str) -> int:
        """Increment a counter."""
        try:
            result = await self.client.incr(key)
            _report_health(True)
            return result
        except Exception as e:
            _logger.error(f"Redis INCR failed: {e}", exc_info=False)
            _report_health(False)
            return 0


# Singleton
redis_client = RedisCache()
