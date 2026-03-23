"""
Workers — Shared Async Runtime

Provides a persistent event loop and asyncpg connection pool that all
Celery tasks share. This avoids the anti-pattern of calling asyncio.run()
per task (which creates a new event loop + new DB connection each time).

Usage in tasks:
    from workers.pool import run_async, get_pool

    @celery_app.task
    def my_task():
        async def _work():
            pool = await get_pool()
            await pool.execute("INSERT INTO ...")
        run_async(_work())
"""

import asyncio
import threading
import asyncpg
import structlog

from config.settings import settings

logger = structlog.get_logger("equated.workers.pool")

# ── Module-level state (shared across all tasks in one worker process) ──
_loop: asyncio.AbstractEventLoop | None = None
_pool: asyncpg.Pool | None = None
_lock = threading.Lock()


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get or create a persistent event loop running in a background thread."""
    global _loop
    if _loop is not None and _loop.is_running():
        return _loop

    with _lock:
        # Double-check after acquiring lock
        if _loop is not None and _loop.is_running():
            return _loop

        _loop = asyncio.new_event_loop()

        def _run_loop(loop: asyncio.AbstractEventLoop):
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=_run_loop, args=(_loop,), daemon=True)
        thread.start()
        logger.info("worker_event_loop_started")
        return _loop


def run_async(coro) -> any:
    """
    Run an async coroutine on the shared event loop.
    Blocks the current (Celery) thread until the coroutine completes.
    """
    loop = _get_or_create_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=120)  # 2-minute hard timeout


async def get_pool() -> asyncpg.Pool:
    """
    Get or create the shared asyncpg connection pool.
    The pool is created once and reused across all tasks in this worker process.
    """
    global _pool
    if _pool is not None and not _pool._closed:
        return _pool

    _pool = await asyncpg.create_pool(
        settings.DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )
    logger.info("worker_db_pool_created", min_size=2, max_size=10)
    return _pool
