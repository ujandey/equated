"""
Config — Application Settings

Single source of truth for all environment variables.
Uses Pydantic Settings for validation and type coercion.
"""

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
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ── Auth / JWT ──────────────────────────
    SUPABASE_JWT_SECRET: str = ""           # Supabase JWT signing secret (from project settings)
    JWT_ALGORITHM: str = "HS256"            # JWT signing algorithm
    JWT_ISSUER: str = ""                    # Expected issuer in JWT claims

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

    # ── Monitoring ──────────────────────────
    SENTRY_DSN: str = ""
    POSTHOG_API_KEY: str = ""
    POSTHOG_HOST: str = "https://app.posthog.com"

    # ── Rate Limiting ───────────────────────
    RATE_LIMIT_PER_MINUTE: int = 30
    FREE_TIER_DAILY_SOLVES: int = 5

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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Singleton instance — import this everywhere
settings = Settings()
