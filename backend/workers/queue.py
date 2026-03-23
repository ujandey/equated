"""
Workers — Queue Configuration

Celery + Redis queue setup for background jobs.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from celery import Celery
from config.settings import settings

# Celery app instance
celery_app = Celery(
    "equated",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    imports=["workers.tasks", "workers.ai_queue"],

    task_routes={
        "workers.tasks.generate_embedding": {"queue": "embeddings"},
        "workers.tasks.log_analytics_event": {"queue": "analytics"},
        "workers.tasks.index_cache_entry": {"queue": "cache"},
    },

    # Celery Beat Schedule
    beat_schedule={
        "evict_expired_cache_daily": {
            "task": "workers.tasks.evict_expired_cache",
            "schedule": 86400.0,  # run every 24 hours
        },
    },
)
