"""
Services — Auth Service

Centralized authentication logic used by middleware and routers.
Uses local JWT validation (no HTTP roundtrip per request).
Falls back to Supabase GoTrue API if JWT secret is not configured.
"""

import structlog
import httpx

from services.jwt_validator import jwt_validator
from config.settings import settings

logger = structlog.get_logger("equated.services.auth")


class AuthService:
    """
    Handles authentication and user identity.

    Primary:   Local JWT decode (fast, no network)
    Fallback:  Supabase GoTrue /user endpoint (if JWT secret missing)
    """

    async def verify_token(self, token: str) -> str | None:
        """
        Verify a bearer token and return the user_id.
        Returns None if token is invalid.
        """
        # Primary: local JWT validation (sub-millisecond)
        if settings.SUPABASE_JWT_SECRET:
            user_id = jwt_validator.get_user_id(token)
            if user_id:
                logger.debug("auth_local_jwt_ok", user_id=user_id[:8])
                return user_id
            return None

        # Fallback: Supabase GoTrue API (adds ~100ms latency)
        return await self._verify_via_supabase(token)

    async def _verify_via_supabase(self, token: str) -> str | None:
        """Verify token by calling Supabase's GoTrue API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.SUPABASE_URL}/auth/v1/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
                    },
                )
            if response.status_code == 200:
                data = response.json()
                user_id = data.get("id")
                logger.debug("auth_supabase_ok", user_id=user_id[:8] if user_id else "none")
                return user_id
            return None
        except Exception as e:
            logger.error("auth_supabase_error", error=str(e))
            return None

    async def get_user_profile(self, user_id: str) -> dict | None:
        """Fetch user profile from the database."""
        from db.connection import get_db
        db = await get_db()

        row = await db.fetchrow(
            "SELECT id, email, name, tier, credits, created_at FROM users WHERE id = $1",
            user_id,
        )
        if not row:
            return None
        return dict(row)

    async def ensure_user_exists(self, user_id: str, email: str = "", name: str = ""):
        """Create user record if it doesn't exist (first login)."""
        from db.connection import get_db
        db = await get_db()

        existing = await db.fetchval("SELECT id FROM users WHERE id = $1", user_id)
        if not existing:
            await db.execute(
                """INSERT INTO users (id, email, name, tier, credits, created_at)
                   VALUES ($1, $2, $3, 'free', 0, NOW())
                   ON CONFLICT (id) DO NOTHING""",
                user_id, email, name,
            )
            logger.info("user_created", user_id=user_id[:8])


# Singleton
auth_service = AuthService()
