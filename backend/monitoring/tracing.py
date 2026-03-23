"""
Monitoring — Distributed Tracing

Sentry integration for error tracking and performance monitoring.
"""

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration

from config.settings import settings


def init_tracing():
    """Initialize Sentry for error tracking and performance monitoring."""
    if not settings.SENTRY_DSN:
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        traces_sample_rate=0.1 if settings.APP_ENV == "production" else 1.0,
        profiles_sample_rate=0.1,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            AsyncioIntegration(),
        ],
        send_default_pii=False,
    )


def capture_exception(error: Exception, context: dict = None):
    """Capture an exception with optional context."""
    if context:
        sentry_sdk.set_context("equated", context)
    sentry_sdk.capture_exception(error)


def set_user_context(user_id: str):
    """Set user context for Sentry events."""
    sentry_sdk.set_user({"id": user_id})
