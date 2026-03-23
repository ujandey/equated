"""
Config — Feature Flags

Centralized feature flag system.
Reads from environment variables with runtime override capability.
Integrates with PostHog feature flags for A/B testing at scale.
"""

from dataclasses import dataclass
from config.settings import settings


@dataclass
class FeatureFlags:
    """
    All feature flags for the application.

    Flags can be:
      - Static (from env vars / config)
      - Dynamic (fetched from PostHog at runtime)
    """

    # ── Core Features ───────────────────────
    streaming_responses: bool = True
    ads_enabled: bool = False
    hint_mode: bool = False

    # ── AI Features ─────────────────────────
    cross_model_verification: bool = False   # Use 2 models and compare
    prompt_compression: bool = True          # Compress prompts to save tokens
    auto_classify: bool = True               # Auto-classify problem type
    enable_fast_model: bool = True           # Use Groq for low-complexity

    # ── Cache Features ──────────────────────
    vector_cache_enabled: bool = True
    redis_cache_enabled: bool = True
    cache_similarity_threshold: float = 0.92  # pgvector cosine threshold

    # ── Monetization ────────────────────────
    credit_system_enabled: bool = True
    free_daily_limit: int = 5

    # ── Experimental ────────────────────────
    practice_generator: bool = False         # Stage 4 feature
    visualization_engine: bool = False       # Stage 3 feature
    mistake_detection: bool = False          # Stage 5 feature

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        """Load flags from environment settings."""
        return cls(
            streaming_responses=settings.ENABLE_STREAMING,
            ads_enabled=settings.ENABLE_ADS,
            hint_mode=settings.ENABLE_HINT_MODE,
            free_daily_limit=settings.FREE_TIER_DAILY_SOLVES,
            vector_cache_enabled=settings.ENABLE_VECTOR_CACHE,
            enable_fast_model=settings.ENABLE_FAST_MODEL,
        )


# Singleton instance
flags = FeatureFlags.from_env()
