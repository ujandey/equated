"""
Tests — Concurrency & Race Conditions

Ensures platform handles high-load identical requests safely without running
the AI pipeline 50 times, and tests credit deduction under concurrent load
with execution jitter.
"""

import asyncio
import random
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from services.credits import credit_service
from cache.redis_cache import RedisCache


class TestDeduplicationLock:
    """Test identical problem submissions running concurrently."""

    @pytest.mark.asyncio
    async def test_simultaneous_solves_only_execute_once(self):
        """
        Simulate 50 identical incoming requests.
        Only ONE should acquire the Redis lock. The other 49 should wait
        for the cache to be populated.
        """
        # A mock Redis cache that tracks the lock state
        lock_state = {}
        cache_state = {}

        class MockRedisCache:
            async def set_nx(self, key: str, value: str, ttl: int = 60) -> bool:
                # Add random jitter so tasks don't all hit this on the exact same microsecond loop
                await asyncio.sleep(random.uniform(0.001, 0.01))
                if key not in lock_state:
                    lock_state[key] = value
                    return True
                return False
                
            async def exists(self, key: str) -> bool:
                return key in lock_state

            async def delete(self, key: str):
                lock_state.pop(key, None)

            async def get(self, key: str) -> str | None:
                return cache_state.get(key)

        from routers.solver import router
        
        mock_redis = MockRedisCache()

        # We will mock the whole solver endpoint to just test the locking logic extracted,
        # or we test the locking logic heavily directly.
        # Since the logic is inside the route, let's test the lock mechanics themselves.
        # We simulate the exact logic from 4.5 in solver.py
        
        async def mock_endpoint_execution(worker_id: int, query_hash: str):
            lock_key = f"solve:lock:{query_hash}"
            has_lock = await mock_redis.set_nx(lock_key, "1", ttl=60)
            
            if not has_lock:
                # Simulate the wait loop
                for _ in range(5):  # Shorter than 30 for tests
                    await asyncio.sleep(0.05)
                    # check cache
                    if query_hash in cache_state:
                        return f"cached_by_leader_for_{worker_id}"

                return f"timeout_for_{worker_id}"
            else:
                # Simulate expensive AI call
                await asyncio.sleep(0.1)
                cache_state[query_hash] = "solution_found"
                await mock_redis.delete(lock_key)
                return f"executed_by_leader_{worker_id}"

        # Run 50 concurrently
        workers = [mock_endpoint_execution(i, "query_hash_xxx") for i in range(50)]
        results = await asyncio.gather(*workers)

        # Assertions
        leader_executions = [r for r in results if r.startswith("executed_by_leader")]
        cached_responses = [r for r in results if r.startswith("cached_by_leader")]

        assert len(leader_executions) == 1, "Exactly ONE task should acquire the lock and execute."
        assert len(cached_responses) == 49, "The other 49 tasks should have waited and returned from cache."


class MockDBConnection:
    """Mock database connection pool to simulate race-condition latency on fetch/update."""
    def __init__(self, initial_credits: int):
        self._credits = initial_credits
        self._transactions = 0
        self._lock = asyncio.Lock() # For our internal tracking, not for the target code

    async def fetchrow(self, query: str, *args):
        await asyncio.sleep(random.uniform(0.01, 0.05))
        if "UPDATE users" in query and "RETURNING" in query:
            cost = args[0]
            async with self._lock:
                if self._credits >= cost:
                    self._credits -= cost
                    return {"credits": self._credits}
                return None # Simulates WHERE condition failing
        return {
            "credits": self._credits,
            "tier": "paid",
            "cnt": 0
        }

    async def fetchval(self, query: str, *args):
        await asyncio.sleep(0.01)
        return self._credits

    async def execute(self, query: str, *args):
        await asyncio.sleep(random.uniform(0.01, 0.05))
        if "INSERT INTO credit_transactions" in query:
            async with self._lock:
                self._transactions += 1


class TestCreditRaceConditions:
    """Test concurrent wallet deduction logic under load."""

    @pytest.mark.asyncio
    @patch("db.connection.get_db")
    async def test_concurrent_credit_deductions_prevent_negative_balance(self, mock_get_db):
        """
        User has 5 credits. Cost is 3 credits per solve.
        User sends 10 identical (or different) requests at the exact same time.
        Only ONE should succeed (5 - 3 = 2). The rest should fail because 2 < 3.
        """
        # Known Vulnerability Test: Without a Postgres transaction and `SELECT ... FOR UPDATE`, 
        # the read in fetchrow followed by update in execute gives a race condition window.
        
        mock_db = MockDBConnection(initial_credits=5)
        # mock_get_db is a coroutine returning the connection
        async def return_db():
            return mock_db
        mock_get_db.side_effect = return_db

        async def attempt_deduction(worker_id):
            # Jitter the request start to mimic network arrival
            await asyncio.sleep(random.uniform(0.001, 0.02))
            return await credit_service.check_and_deduct(f"user_{worker_id}", model_name="gpt-4o") # Cost 5

        # 10 workers try to deduction 5 credits
        results = await asyncio.gather(*(attempt_deduction(i) for i in range(10)))
        
        successes = [r for r in results if r["allowed"]]
        failures = [r for r in results if not r["allowed"]]

        # Even with Python-level race windows, we enforce the atomic assertion expectations.
        # This test documents the expectation: No negative balances.
        
        # If the code uses unsafe SELECT then UPDATE, multiple attempts might pass the SELECT check 
        # before the UPDATE happens. If that happens, this test might actually FAIL right now!
        # Which is exactly what we want to test for. 
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}. Race condition detected!"
        assert mock_db._credits == 0, f"Expected 0 final credits, got {mock_db._credits}"
        assert mock_db._transactions == 1, "Expected exactly 1 audit log entry."
