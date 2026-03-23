"""
Workers — AI Request Queue

Redis-backed queue for AI model requests.
Prevents API spikes by serializing concurrent requests through workers.

Flow:
  request → enqueue AI job → worker executes → store result → notify caller

Uses the shared event loop and connection pool from workers.pool.
"""

import time
import structlog

from workers.queue import celery_app
from workers.pool import run_async

logger = structlog.get_logger("equated.workers.ai_queue")


@celery_app.task(
    name="workers.ai_queue.process_ai_request",
    bind=True,
    max_retries=2,
    default_retry_delay=3,
    time_limit=120,          # Hard timeout: 2 minutes
    soft_time_limit=90,      # Soft timeout: 1.5 minutes
)
def process_ai_request(self, request_id: str, messages: list[dict], provider: str,
                       model_name: str, max_tokens: int, temperature: float):
    """
    Execute an AI model call in a background worker.

    Steps:
      1. Load the model for the given provider
      2. Call generate() with the messages
      3. Store the result in Redis keyed by request_id
      4. Log usage metrics
    """
    async def _execute():
        from ai.models import get_model
        from cache.redis_cache import redis_client

        start = time.perf_counter()

        try:
            model = get_model(provider)
            response = await model.generate(messages, max_tokens, temperature)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)

            # Store result in Redis for the API to pick up
            result = {
                "status": "completed",
                "content": response.content,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_cost_usd": response.total_cost_usd,
                "finish_reason": response.finish_reason,
                "duration_ms": duration_ms,
            }

            if not redis_client.client:
                await redis_client.connect()
            await redis_client.set_json(
                f"ai_result:{request_id}",
                result,
                ttl=600,  # Keep result for 10 minutes
            )

            logger.info(
                "ai_job_completed",
                request_id=request_id,
                provider=provider,
                model=model_name,
                duration_ms=duration_ms,
                tokens=response.input_tokens + response.output_tokens,
            )

        except Exception as e:
            # Store error result
            error_result = {
                "status": "failed",
                "error": str(e),
                "provider": provider,
            }

            try:
                if not redis_client.client:
                    await redis_client.connect()
                await redis_client.set_json(
                    f"ai_result:{request_id}",
                    error_result,
                    ttl=300,
                )
            except Exception:
                pass

            logger.error("ai_job_failed", request_id=request_id, error=str(e))
            raise self.retry(exc=e)

    run_async(_execute())


@celery_app.task(name="workers.ai_queue.check_ai_health")
def check_ai_health(provider: str) -> dict:
    """Health check task for AI providers."""
    async def _check():
        from ai.models import get_model
        try:
            model = get_model(provider)
            response = await model.generate(
                [{"role": "user", "content": "Say OK"}],
                max_tokens=5,
                temperature=0.0,
            )
            return {"provider": provider, "status": "healthy", "model": response.model}
        except Exception as e:
            return {"provider": provider, "status": "unhealthy", "error": str(e)}

    return run_async(_check())


def enqueue_ai_request(request_id: str, messages: list[dict], provider: str,
                       model_name: str, max_tokens: int = 4096,
                       temperature: float = 0.3) -> str:
    """
    Enqueue an AI request for background processing.
    Returns the Celery task ID for status polling.
    """
    task = process_ai_request.apply_async(
        args=[request_id, messages, provider, model_name, max_tokens, temperature],
        queue="ai_requests",
    )
    logger.info(
        "ai_job_enqueued",
        request_id=request_id,
        task_id=task.id,
        provider=provider,
    )
    return task.id
