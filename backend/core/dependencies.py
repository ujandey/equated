"""
Core — Dependency Injection

FastAPI Depends() functions for clean dependency injection.
Replaces ad-hoc request.state access across all routers.
"""

from fastapi import Depends, Request
import asyncpg

from core.exceptions import AuthError, ForbiddenError


# ── Current User ────────────────────────────────────
async def get_current_user(request: Request) -> str:
    """
    Extract authenticated user_id from request state.
    Raises AuthError if not authenticated.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise AuthError("Authentication required.")
    return user_id


async def get_optional_user(request: Request) -> str | None:
    """
    Extract user_id if present, return None for anonymous users.
    Used for endpoints that work with or without auth.
    """
    return getattr(request.state, "user_id", None)


# ── Database ────────────────────────────────────────
async def get_db_pool() -> asyncpg.Pool:
    """Get the active database connection pool."""
    from db.connection import get_db
    return await get_db()


# ── Redis ───────────────────────────────────────────
async def get_redis():
    """Get the active Redis client."""
    from cache.redis_cache import redis_client
    if not redis_client.client:
        raise Exception("Redis not connected")
    return redis_client


# ── Admin Role ──────────────────────────────────────
async def require_admin(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> str:
    """
    Verify that the current user has admin privileges.
    Checks the 'admins' table in the database.
    Returns user_id if admin, raises ForbiddenError otherwise.
    """
    from db.connection import get_db
    db = await get_db()

    is_admin = await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM admins WHERE user_id = $1)",
        user_id,
    )
    if not is_admin:
        raise ForbiddenError("Admin access required.")
    return user_id
