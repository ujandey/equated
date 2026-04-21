"""
DB — Connection Manager

Async PostgreSQL connection pool using asyncpg.
Used by all services that need database access.

IMPORTANT: Supabase's pooler endpoint (pooler.supabase.com) runs PgBouncer in
transaction-pooling mode, which does NOT support prepared statements.
asyncpg uses prepared statements by default, so we must disable them
via ``statement_cache_size=0`` to avoid massive slowdowns and intermittent
"socket hang up" errors.
"""

import asyncpg
from config.settings import settings


def _uses_pgbouncer(dsn: str) -> bool:
    """Detect whether the DSN routes through Supabase's PgBouncer pooler."""
    return "pooler.supabase.com" in dsn or "pgbouncer" in dsn.lower()


class DatabasePool:
    """Singleton database connection pool."""
    
    _pool = None
    
    @classmethod
    async def get_pool(cls):
        if cls._pool is None:
            pool_kwargs: dict = dict(
                dsn=settings.DATABASE_URL,
                min_size=2,
                max_size=20,
                command_timeout=30,  # Fail quickly instead of hanging for 60+ seconds
                max_inactive_connection_lifetime=30,  # Recycle before Supabase ALB 60s idle timeout
            )

            # Since we are using Supavisor Session Pooling (port 5432), prepared statements are fully supported.
            # We purposely do not disable statement caching, which drops query latency by 5x.
            cls._pool = await asyncpg.create_pool(**pool_kwargs)
        return cls._pool
    
    @classmethod
    async def close(cls):
        if cls._pool:
            await cls._pool.close()
            cls._pool = None

# Backward compatibility functions
async def init_db():
    """Initialize the database connection pool."""
    await DatabasePool.get_pool()

async def get_db() -> asyncpg.Pool:
    """Get the database connection pool."""
    return await DatabasePool.get_pool()

async def close_db():
    """Close the database connection pool."""
    await DatabasePool.close()
