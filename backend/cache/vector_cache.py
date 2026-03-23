"""
Cache — Vector Cache (pgvector)

Semantic similarity cache using Supabase pgvector.
Embeds questions and finds similar previously-solved problems
to avoid redundant AI API calls (target: 30-60% hit rate).
"""

import structlog
from dataclasses import dataclass

from cache.embeddings import embedding_generator
from config.feature_flags import flags

logger = structlog.get_logger("equated.cache.vector")

SIMILARITY_THRESHOLD = 0.88  # Cosine similarity threshold (lowered from 0.92)


@dataclass
class CacheHit:
    """Result of a vector cache lookup."""
    found: bool
    similarity: float
    cached_solution: dict | None
    cache_key: str


class VectorCache:
    """
    pgvector-based semantic cache.

    Flow:
      1. Generate embedding for the question
      2. Search pgvector for similar embeddings
      3. If similarity >= threshold → return cached solution
      4. If miss → return None (caller proceeds to AI pipeline)
      5. After solving → store new embedding + solution
    """

    async def lookup(self, query: str) -> CacheHit:
        """Search for a semantically similar cached solution."""
        if not flags.vector_cache_enabled:
            return CacheHit(found=False, similarity=0.0, cached_solution=None, cache_key="")

        # Generate embedding
        embedding = await embedding_generator.generate(query)
        if not embedding:
            return CacheHit(found=False, similarity=0.0, cached_solution=None, cache_key="")

        # Search pgvector
        from db.connection import get_db
        db = await get_db()

        row = await db.fetchrow(
            """SELECT id, solution, 1 - (embedding <=> $1::vector) as similarity
               FROM cache_entries
               WHERE 1 - (embedding <=> $1::vector) >= $2
               ORDER BY embedding <=> $1::vector
               LIMIT 1""",
            str(embedding), SIMILARITY_THRESHOLD,
        )

        if row:
            logger.info("vector_cache_hit", similarity=round(row["similarity"], 4))
            return CacheHit(
                found=True,
                similarity=row["similarity"],
                cached_solution={"solution": row["solution"]},
                cache_key=row["id"],
            )

        return CacheHit(found=False, similarity=0.0, cached_solution=None, cache_key="")

    async def store(self, query: str, solution: str, metadata: dict = None):
        """Store a new solution with its embedding in the vector cache."""
        embedding = await embedding_generator.generate(query)
        if not embedding:
            return

        from db.connection import get_db
        db = await get_db()

        await db.execute(
            """INSERT INTO cache_entries (query, solution, embedding, metadata)
               VALUES ($1, $2, $3::vector, $4)""",
            query, solution, str(embedding), str(metadata or {}),
        )
        logger.info("vector_cache_stored", query_length=len(query))


# Singleton
vector_cache = VectorCache()
