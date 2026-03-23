"""
DB — Connection Manager

Async PostgreSQL connection pool using asyncpg.
Used by all services that need database access.
"""

import asyncpg
from config.settings import settings

_pool: asyncpg.Pool | None = None


async def init_db():
    """Initialize the database connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        settings.DATABASE_URL,
        min_size=2,
        max_size=10,
    )


async def get_db() -> asyncpg.Pool:
    """Get the database connection pool."""
    if _pool is None:
        await init_db()
    return _pool


async def close_db():
    """Close the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
