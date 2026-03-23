"""
Monitoring — Structured Logging

Configures structlog for JSON-structured logging in production
and human-readable output in development.
"""

import structlog
from config.settings import settings


def configure_logging():
    """Configure structured logging based on environment."""
    if settings.APP_ENV == "production":
        # JSON output for production (parseable by log aggregators)
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO+
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )
    else:
        # Human-readable output for development
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="%H:%M:%S"),
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(10),  # DEBUG+
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )
