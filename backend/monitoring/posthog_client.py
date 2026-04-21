"""
Monitoring — PostHog Analytics Client

Tracks behavioral events for product analytics:
  - Solve completions (model, latency, intent, cache source)
  - Chat messages
  - Errors and rate limits
  - User identification

All events are fire-and-forget (no await) to avoid blocking request paths.
"""

import posthog
import structlog

from config.settings import settings

logger = structlog.get_logger("equated.monitoring.posthog")


def init_posthog():
    """Initialize PostHog with the project API key."""
    if not settings.POSTHOG_API_KEY or settings.POSTHOG_API_KEY.startswith("your-"):
        logger.warning("posthog_disabled", reason="POSTHOG_API_KEY not configured")
        return

    posthog.api_key = settings.POSTHOG_API_KEY
    posthog.host = settings.POSTHOG_HOST
    # Disable in non-production to avoid polluting analytics with dev traffic
    if settings.APP_ENV != "production":
        posthog.disabled = False  # keep enabled so devs can verify events locally


def track(distinct_id: str, event: str, properties: dict | None = None):
    """
    Fire-and-forget event capture.

    distinct_id: Supabase user UUID (or 'anonymous' for unauthed requests)
    """
    if not settings.POSTHOG_API_KEY or settings.POSTHOG_API_KEY.startswith("your-"):
        return
    try:
        posthog.capture(distinct_id, event, properties or {})
    except Exception as exc:
        # Never let analytics failures surface to the user
        logger.warning("posthog_capture_failed", event=event, error=str(exc))


def identify(distinct_id: str, traits: dict | None = None):
    """Link a user ID to properties (called after auth)."""
    if not settings.POSTHOG_API_KEY or settings.POSTHOG_API_KEY.startswith("your-"):
        return
    try:
        posthog.identify(distinct_id, traits or {})
    except Exception as exc:
        logger.warning("posthog_identify_failed", error=str(exc))
