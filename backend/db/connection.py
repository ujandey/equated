"""
DB — Connection Manager

Async PostgreSQL connection pool using asyncpg.
Used by all services that need database access.
"""

import asyncpg
from config.settings import settings

class DatabasePool:
    """Singleton database connection pool."""
    
    _pool = None
    
    @classmethod
    async def get_pool(cls):
        if cls._pool is None:
            cls._pool = await asyncpg.create_pool(
                dsn=settings.DATABASE_URL,
                min_size=5,
                max_size=20,
                command_timeout=60,
                max_inactive_connection_lifetime=300
            )
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
