"""
Config — Application Settings

Single source of truth for all environment variables.
Uses Pydantic Settings for validation and type coercion.
"""

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    All environment variables used by the backend.
    Loaded from .env file or system environment.
    """

    # ── App ─────────────────────────────────
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    API_VERSION: str = "v1"
    FRONTEND_URL: str = "http://localhost:3000"

    # ── Database ────────────────────────────
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/equated"
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_SECRET_KEY: str = ""

    # ── Auth / JWT ──────────────────────────
    # JWT verification uses JWKS (RS256 public keys) fetched automatically
    # from {SUPABASE_URL}/auth/v1/.well-known/jwks.json — no secret needed.

    # ── Redis ───────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── AI Models ───────────────────────────
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    MISTRAL_API_KEY: str = ""
    MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    GEMINI_API_KEY: str = ""

    # ── Payments ────────────────────────────
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""  # For webhook signature verification

    # ── Monitoring ──────────────────────────
    SENTRY_DSN: str = ""
    POSTHOG_API_KEY: str = ""
    POSTHOG_HOST: str = "https://app.posthog.com"

    # ── Rate Limiting ───────────────────────
    RATE_LIMIT_PER_MINUTE: int = 30
    FREE_TIER_DAILY_SOLVES: int = 5

    # Development fallback
    DEV_PRIMARY_PROVIDER: str = "auto"

    # ── Feature Flags ───────────────────────
    ENABLE_STREAMING: bool = True
    ENABLE_ADS: bool = False
    ENABLE_HINT_MODE: bool = False
    ENABLE_VECTOR_CACHE: bool = True
    ENABLE_FAST_MODEL: bool = True          # Use Groq for low-complexity queries

    # ── Ads ──────────────────────────────────
    ADS_CREDIT_REWARD: int = 1              # Credits earned per ad watched
    ADS_DAILY_LIMIT: int = 5                # Max ads per user per day
    ADS_COOLDOWN_SECONDS: int = 300         # Minimum time between ad rewards

    # ── Analytics ────────────────────────────
    ANALYTICS_RETENTION_DAYS: int = 90      # Days to keep analytics data

    # ── Input Validation ─────────────────────
    MAX_INPUT_LENGTH: int = 10000           # Max chars for query input
    MAX_IMAGE_SIZE_MB: int = 10             # Max image upload size

    # ── Placeholder detection ────────────────
    _PLACEHOLDER_VALUES: set = {
        "your-deepseek-key", "your-groq-key", "your-openai-key",
        "your-mistral-key", "your-gemini-key",
        "your-razorpay-key", "your-razorpay-secret",
        "your-posthog-key", "your-sentry-dsn",
        "your-publishable-key", "your-secret-key",
    }

    def _is_placeholder(self, value: str) -> bool:
        """Check if a value looks like an unfilled placeholder."""
        return value.lower() in self._PLACEHOLDER_VALUES or value.startswith("your-")

    def _is_set(self, value: str) -> bool:
        """Check if a value is non-empty and not a placeholder."""
        return bool(value) and not self._is_placeholder(value)

    @property
    def has_any_ai_provider(self) -> bool:
        """True if at least one AI provider API key is configured."""
        return any(self._is_set(k) for k in [
            self.DEEPSEEK_API_KEY, self.GROQ_API_KEY,
            self.MISTRAL_API_KEY, self.OPENAI_API_KEY,
            self.GEMINI_API_KEY,
        ])

    @property
    def razorpay_configured(self) -> bool:
        """True if Razorpay is fully configured for payments."""
        return all(self._is_set(k) for k in [
            self.RAZORPAY_KEY_ID, self.RAZORPAY_KEY_SECRET,
            self.RAZORPAY_WEBHOOK_SECRET,
        ])

    def validate_critical_env(self) -> None:
        """
        Validate environment configuration at startup.
        Fails fast on critical missing values, warns on optional ones.
        """
        import logging
        logger = logging.getLogger("equated.config")
        errors: list[str] = []
        warnings: list[str] = []

        # ── Critical: At least one AI provider ──
        if not self.has_any_ai_provider:
            errors.append(
                "No AI provider API keys configured. Set at least one of: "
                "DEEPSEEK_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, MISTRAL_API_KEY, GEMINI_API_KEY"
            )

        # ── Critical: Database ──
        if self._is_placeholder(self.DATABASE_URL) or self.DATABASE_URL == "postgresql://postgres:password@localhost:5432/equated":
            warnings.append("DATABASE_URL is still using the default/placeholder value")

        # ── Optional: Supabase Auth ──
        if not self._is_set(self.SUPABASE_URL):
            warnings.append("SUPABASE_URL not set — JWT auth will be disabled")

        # ── Optional: Redis ──
        if self.REDIS_URL == "redis://localhost:6379/0":
            warnings.append("REDIS_URL is default localhost — ensure Redis is running or set Upstash URL")

        # ── Optional: Payments ──
        if not self.razorpay_configured:
            warnings.append("Razorpay not fully configured — payment features will be disabled")

        # ── Optional: Monitoring ──
        if not self._is_set(self.SENTRY_DSN):
            warnings.append("SENTRY_DSN not set — error tracking disabled")

        # ── Optional: Embeddings require OpenAI ──
        if not self._is_set(self.OPENAI_API_KEY) and self.ENABLE_VECTOR_CACHE:
            warnings.append(
                "OPENAI_API_KEY not set but ENABLE_VECTOR_CACHE=true — "
                "vector cache will be non-functional (embeddings require OpenAI)"
            )

        # ── Log warnings ──
        for w in warnings:
            logger.warning(f"ENV: {w}")

        # ── Fail fast on errors ──
        if errors:
            for e in errors:
                logger.error(f"ENV CRITICAL: {e}")
            raise SystemExit(
                f"Startup aborted: {len(errors)} critical environment error(s). "
                "Check logs above and fix your .env file."
            )

        logger.info(f"Environment validated ({len(warnings)} warning(s))")

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Singleton instance — import this everywhere
settings = Settings()
