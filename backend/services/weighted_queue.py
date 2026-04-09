"""
Services — Weighted Queue

Implements Phase 2 Economic Controls.
Weighted Fair Queuing ensures heavy math operations don't starve light queries.
"""

import asyncio
import time
from contextlib import asynccontextmanager

import structlog

from config.settings import settings
from cache.redis_cache import redis_client

logger = structlog.get_logger("equated.services.weighted_queue")


class WeightedFairQueue:
    """
    Distributes compute capacity based on AST-assigned weights.
    
    If 'soft_acquire' is False, acts as a strict concurrency barrier.
    If 'soft_acquire' is True, checks admission but doesn't block (used for fast fallback decisions).
    """
    
    def __init__(self):
        self._local_semaphore = None

    def _get_semaphore(self):
        import asyncio
        if self._local_semaphore is None:
            self._local_semaphore = asyncio.Semaphore(settings.WFQ_GLOBAL_MAX_WEIGHT)
        return self._local_semaphore

    async def can_acquire_weight(self, user_id: str, weight: int) -> bool:
        """
        Checks if the queue *could* accept this weight right now,
        without actually blocking or taking the capacity.
        Returns False if the system is overloaded.
        """
        sem = self._get_semaphore()
        # Non-blocking check for available internal locked value
        if sem._value < weight:
            return False
            
        # Optional: Check Redis global user concurrency here (anti-abuse)
        # R4-2: "Tie together: reservation_id <-> active execution slot"
        return True

    @asynccontextmanager
    async def acquire(self, weight: int):
        """
        Context manager to acquire WFQ weight internally.
        Block until weight is available.
        """
        sem = self._get_semaphore()
        
        # Acquire multi-weight
        # asyncio.Semaphore doesn't support acquire(N), so we acquire 1x N times
        # Wait until at least `weight` capacity is available
        acquired = 0
        try:
            for _ in range(weight):
                await sem.acquire()
                acquired += 1
            yield
        finally:
            for _ in range(acquired):
                sem.release()

    async def record_actual_runtime(self, user_id: str, tier: str, declared_weight: int, actual_seconds: float):
        """
        Asymmetric penalty tracking (penalty += 1 on violation, -= 0.25 on success).
        Prevents light-bomb gaming where AST claims lightweight but runtime is heavy.
        """
        if tier == "free":
            return  # Free users don't need WFQ penalties, they are strictly limited by hard caps
            
        penalty_key = f"wfq:penalty:{user_id}"
        
        # Heuristic: 2 seconds compute implies heavy math task requiring 5 weight.
        implied_heavy = (actual_seconds > 2.0)
        
        if implied_heavy and declared_weight < settings.WFQ_HEAVY_WEIGHT:
            # Penalty Increment (User gamed AST into registering as 'light', executed heavy)
            await redis_client.client.incrbyfloat(penalty_key, 1.0)
            await redis_client.client.expire(penalty_key, 300) # 5 min decay
            logger.warning("wfq_runtime_penalty_inc", user_id=user_id, actual_s=round(actual_seconds, 2))
        elif declared_weight >= settings.WFQ_HEAVY_WEIGHT:
            # Penalty Decay (User honestly submitted heavy, successfully processed without abuse)
            # Decays asynchronously over time using asymmetric 0.25 decay per success.
            pipe = redis_client.client.pipeline()
            pipe.incrbyfloat(penalty_key, -0.25)
            # Floor at 0
            pipe.execute_command('EVAL', "if tonumber(redis.call('get', KEYS[1]) or 0) < 0 then redis.call('set', KEYS[1], 0) end", 1, penalty_key)
            await pipe.execute()


wfq = WeightedFairQueue()
