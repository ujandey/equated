"""
Workers — Worker Entry Point

Start with:
  celery -A workers.worker worker --loglevel=info -Q embeddings,analytics,cache
"""

from workers.queue import celery_app
import workers.tasks  # noqa: F401 — register all tasks
