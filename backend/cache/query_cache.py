"""
Cache — Query Cache

Two-tier caching strategy:
  1. Redis (fast, exact match by normalized hash)
  2. pgvector (slower, semantic similarity match)

This module orchestrates both layers.
"""

import structlog

from cache.redis_cache import redis_client
from cache.vector_cache import vector_cache, CacheHit
from services.query_normalizer import query_normalizer

logger = structlog.get_logger("equated.cache.query")

REDIS_TTL = 86400  # 24 hours


class QueryCache:
    """
    Two-tier question→solution cache.

    Lookup order:
      1. Redis exact match (normalized query hash)
      2. pgvector semantic similarity
      3. Miss → proceed to AI pipeline
    """

    async def lookup(self, query: str) -> CacheHit:
        """Search both cache tiers for a matching solution."""

        # Tier 1: Redis exact match (fast)
        cache_key = query_normalizer.generate_cache_key(query)
        cached = await redis_client.get_json(f"solve:{cache_key}")
        if cached:
            logger.info("redis_cache_hit", key=cache_key[:8])
            return CacheHit(
                found=True,
                similarity=1.0,
                cached_solution=cached,
                cache_key=cache_key,
            )

        # Tier 2: pgvector semantic match (slower)
        vector_hit = await vector_cache.lookup(query)
        if vector_hit.found:
            # Promote to Redis for faster future hits
            await redis_client.set_json(
                f"solve:{cache_key}",
                vector_hit.cached_solution,
                ttl=REDIS_TTL,
            )
            return vector_hit

        # Cache miss
        return CacheHit(found=False, similarity=0.0, cached_solution=None, cache_key=cache_key)

    async def store(self, query: str, solution: dict):
        """Store solution in both cache tiers."""
        cache_key = query_normalizer.generate_cache_key(query)

        # Store in Redis (fast tier)
        await redis_client.set_json(f"solve:{cache_key}", solution, ttl=REDIS_TTL)

        # Store in pgvector (semantic tier) — do this in background
        await vector_cache.store(query, str(solution))

        logger.info("cache_stored", key=cache_key[:8])

    async def invalidate(self, query: str):
        """Remove a cached solution."""
        cache_key = query_normalizer.generate_cache_key(query)
        await redis_client.delete(f"solve:{cache_key}")


# Singleton
query_cache = QueryCache()
