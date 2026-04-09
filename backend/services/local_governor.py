"""
Services — Local Governor

In-process admission control, fully independent of Redis.

Security properties:
  - Atomic acquire via asyncio.Lock (no race condition — R2-5)
  - Redis health hysteresis prevents mode thrashing (R2-6)
  - Degraded Redis = STRICTER limits, not looser (R1-3)
  - Memory check prevents process from exceeding LOCAL_MAX_MEMORY_MB

This is the FIRST gate in the solve pipeline. It always runs,
even if Redis, Postgres, and every external service is dead.
"""

from __future__ import annotations

import asyncio
import time

import psutil
import structlog

from config.settings import settings

logger = structlog.get_logger("equated.services.local_governor")


class LocalGovernor:
    """
    Per-node admission control. No distributed state dependency.

    Two modes:
      NORMAL (Redis healthy):   limit = LOCAL_MAX_CONCURRENCY (8)
      DEGRADED (Redis down):    limit = LOCAL_MAX_CONCURRENCY_DEGRADED (4)

    Mode transitions require REDIS_HEALTH_HYSTERESIS_SECONDS (10s) of
    consistent health reports to prevent flip-flopping.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active: int = 0
        self._redis_healthy: bool = True

        # Hysteresis state (R2-6)
        self._redis_pending_state: bool | None = None
        self._redis_pending_since: float = 0.0

        # Process handle for memory checks
        self._process = psutil.Process()

    async def acquire(self) -> bool:
        """
        Attempt to acquire a compute slot.

        Returns True if slot granted, False if at capacity.
        Thread-safe via asyncio.Lock (R2-5 fix).
        """
        async with self._lock:
            effective_limit = self._effective_limit()

            if self._active >= effective_limit:
                logger.debug(
                    "local_governor_at_capacity",
                    active=self._active,
                    limit=effective_limit,
                    mode=self._mode_label(),
                )
                return False

            if not self._check_memory():
                logger.warning(
                    "local_governor_memory_exceeded",
                    rss_mb=self._current_rss_mb(),
                    limit_mb=settings.LOCAL_MAX_MEMORY_MB,
                )
                return False

            self._active += 1
            return True

    async def release(self) -> None:
        """Release a compute slot."""
        async with self._lock:
            self._active = max(0, self._active - 1)

    def report_redis_health(self, healthy: bool) -> None:
        """
        Report Redis health state. Mode switches only happen after
        REDIS_HEALTH_HYSTERESIS_SECONDS of consistent reports.

        This prevents oscillation from Redis flapping (R2-6).
        """
        now = time.monotonic()

        # Same as current state — reset any pending transition
        if healthy == self._redis_healthy:
            self._redis_pending_state = None
            return

        # New state reported — start or continue hysteresis timer
        if self._redis_pending_state is None or self._redis_pending_state != healthy:
            self._redis_pending_state = healthy
            self._redis_pending_since = now
            return

        # Pending state matches and enough time has passed — apply transition
        elapsed = now - self._redis_pending_since
        if elapsed >= settings.REDIS_HEALTH_HYSTERESIS_SECONDS:
            old_mode = self._mode_label()
            self._redis_healthy = healthy
            self._redis_pending_state = None
            new_mode = self._mode_label()

            logger.warning(
                "local_governor_mode_transition",
                old_mode=old_mode,
                new_mode=new_mode,
                hysteresis_seconds=round(elapsed, 1),
                old_limit=settings.LOCAL_MAX_CONCURRENCY if old_mode == "normal" else settings.LOCAL_MAX_CONCURRENCY_DEGRADED,
                new_limit=self._effective_limit(),
            )

    def get_metrics(self) -> dict:
        """Return current governor state for /health or Prometheus."""
        return {
            "active": self._active,
            "limit": self._effective_limit(),
            "mode": self._mode_label(),
            "redis_healthy": self._redis_healthy,
            "rss_mb": round(self._current_rss_mb(), 1),
            "memory_limit_mb": settings.LOCAL_MAX_MEMORY_MB,
        }

    # ── Private helpers ──

    def _effective_limit(self) -> int:
        """Current concurrency limit based on Redis health."""
        if self._redis_healthy:
            return settings.LOCAL_MAX_CONCURRENCY
        return settings.LOCAL_MAX_CONCURRENCY_DEGRADED

    def _mode_label(self) -> str:
        return "normal" if self._redis_healthy else "degraded"

    def _check_memory(self) -> bool:
        """Check if process RSS is within limits."""
        return self._current_rss_mb() < settings.LOCAL_MAX_MEMORY_MB

    def _current_rss_mb(self) -> float:
        """Current process RSS in megabytes."""
        try:
            return self._process.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0  # If psutil fails, allow the request


# Singleton
local_governor = LocalGovernor()
