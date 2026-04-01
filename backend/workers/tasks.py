"""
Workers — Background Tasks

Celery tasks that run outside the request cycle:
  - Embedding generation
  - Analytics logging
  - Cache indexing
  - Chat message persistence
  - Model usage tracking

All tasks use the shared event loop and connection pool from workers.pool
instead of creating new asyncio.run() / asyncpg.connect() per call.
"""

import json
import uuid
from datetime import datetime, timezone

from workers.queue import celery_app
from workers.pool import run_async, get_pool


@celery_app.task(name="workers.tasks.generate_embedding")
def generate_embedding(query: str, solution: str):
    """Generate and store embedding for a solved problem."""
    async def _work():
        import structlog
        logger = structlog.get_logger("equated.workers.tasks")
        try:
            from cache.vector_cache import vector_cache
            await vector_cache.store(query, solution)
        except Exception as e:
            logger.warning("embedding_task_skipped", reason=str(e))

    run_async(_work())


@celery_app.task(name="workers.tasks.log_analytics_event")
def log_analytics_event(event_type: str, data: dict):
    """Log an analytics event to the database."""
    async def _work():
        pool = await get_pool()
        await pool.execute(
            """INSERT INTO analytics_events (event_type, data, created_at)
               VALUES ($1, $2, NOW())""",
            event_type, json.dumps(data),
        )

    run_async(_work())


@celery_app.task(name="workers.tasks.index_cache_entry")
def index_cache_entry(query: str, solution: str, metadata: dict = None):
    """Index a cache entry in both Redis and pgvector."""
    async def _work():
        import structlog
        logger = structlog.get_logger("equated.workers.tasks")
        try:
            from cache.query_cache import query_cache
            await query_cache.store(query, {"solution": solution, **(metadata or {})})
        except Exception as e:
            logger.warning("index_cache_entry_skipped", reason=str(e))

    run_async(_work())


@celery_app.task(name="workers.tasks.log_model_usage")
def log_model_usage(user_id: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float):
    """Record model usage for cost tracking."""
    async def _work():
        pool = await get_pool()
        await pool.execute(
            """INSERT INTO model_usage (user_id, model, input_tokens, output_tokens, cost_usd, created_at)
               VALUES ($1, $2, $3, $4, $5, NOW())""",
            user_id, model, input_tokens, output_tokens, cost_usd,
        )

    run_async(_work())


@celery_app.task(name="workers.tasks.save_chat_message")
def save_chat_message(
    session_id: str,
    role: str,
    content: str,
    metadata: dict = None,
    block_id: str | None = None,
):
    """Save a chat message to the DB."""
    async def _work():
        pool = await get_pool()
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        await pool.execute(
            """INSERT INTO messages (id, session_id, block_id, role, content, metadata, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            msg_id, session_id, block_id, role,
            content, json.dumps(metadata or {}), now,
        )
        await pool.execute(
            "UPDATE sessions SET updated_at = $1 WHERE id = $2",
            now, session_id,
        )
        if block_id:
            from services.topic_blocks import topic_block_service
            await topic_block_service.refresh_block_summary(block_id)

    run_async(_work())

@celery_app.task(name="workers.tasks.evict_expired_cache")
def evict_expired_cache():
    """Delete cache entries older than 30 days with 0 hits."""
    async def _work():
        pool = await get_pool()
        result = await pool.execute(
            """
            DELETE FROM cache_entries
            WHERE created_at < now() - interval '30 days'
            AND hit_count = 0
            """
        )
        print(f"Cache Eviction: {result}")

    run_async(_work())
