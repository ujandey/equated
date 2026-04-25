"""
Monitoring — Structured JSON Logger

Configures structured JSON logging for production observability.
Every log event includes: timestamp, level, event name, and context fields.

Example output:
  {"timestamp": "2026-03-09T21:00:00Z", "level": "info", "event": "ai_request",
   "model": "deepseek", "latency_ms": 1300, "cost_usd": 0.0003}
"""

import structlog
import logging
import sys

from config.settings import settings


def configure_json_logging():
    """
    Configure structured logging based on environment.

    Production:  JSON output (parseable by log aggregators: Datadog, CloudWatch, ELK)
    Development: Human-readable colored console output
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.APP_ENV == "production":
        # JSON output for production
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # Pretty console output for development
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(
                    colors=True,
                    exception_formatter=structlog.dev.better_traceback,
                ),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )

    # Also configure standard library logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO if settings.APP_ENV == "production" else logging.DEBUG,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str):
    """Get a structured logger with a specific name."""
    return structlog.get_logger(name)
