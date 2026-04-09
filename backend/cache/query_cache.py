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
        redis_key = f"solve:{cache_key}"
        cached_wrapped = await redis_client.get_json(redis_key)
        
        if cached_wrapped:
            from config.settings import settings
            # Is it wrapped in our new Phase 3 format?
            if "_equated_cache" in cached_wrapped:
                hit_count = cached_wrapped.get("_hit_count", 0)
                ttl_remaining = await redis_client.client.ttl(redis_key)
                original_ttl = cached_wrapped.get("_original_ttl", REDIS_TTL)
                
                # Phase 3 Anti-Pollution (Fix 4: Early Eviction)
                if ttl_remaining > 0 and ttl_remaining < (original_ttl / 2) and hit_count < settings.CACHE_MIN_HITS_FOR_RETENTION:
                    await redis_client.delete(redis_key)
                    logger.warning("cache_early_eviction_executed", key=cache_key[:8], hits=hit_count)
                    cached_wrapped = None
                else:
                    # Valid hit: increment and re-save
                    cached_wrapped["_hit_count"] = hit_count + 1
                    if ttl_remaining > 0:
                        import json
                        await redis_client.client.set(redis_key, json.dumps(cached_wrapped), ex=ttl_remaining)
                    cached_solution = cached_wrapped["_equated_cache"]
            else:
                # Fallback for old cache formats
                cached_solution = cached_wrapped
                
            if cached_wrapped is not None:
                logger.info("redis_cache_hit", key=cache_key[:8])
                return CacheHit(
                    found=True,
                    similarity=1.0,
                    cached_solution=cached_solution,
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

    async def store(self, query: str, solution: dict, compute_seconds: float = 0.0):
        """Store solution in both cache tiers."""
        cache_key = query_normalizer.generate_cache_key(query)

        # ── Phase 3 Anti-Pollution Extension ──
        import math
        multiplier = 1 + math.log2(max(1.0, compute_seconds))
        effective_ttl = int(REDIS_TTL * multiplier)

        wrapped_solution = {
            "_equated_cache": solution,
            "_hit_count": 0,
            "_original_ttl": effective_ttl
        }

        # Store in Redis (fast tier)
        await redis_client.client.set(f"solve:{cache_key}", __import__('json').dumps(wrapped_solution), ex=effective_ttl)

        # Store in pgvector (semantic tier) — do this in background
        await vector_cache.store(query, str(solution))

        logger.info("cache_stored", key=cache_key[:8])

    async def invalidate(self, query: str):
        """Remove a cached solution."""
        cache_key = query_normalizer.generate_cache_key(query)
        await redis_client.delete(f"solve:{cache_key}")


# Singleton
query_cache = QueryCache()
