"""
Cache — Embedding Generator

Generates vector embeddings for semantic similarity cache.
Uses OpenAI text-embedding-3-small (1536 dimensions, $0.02/1M tokens).

Previously used DeepSeek's /embeddings endpoint with deepseek-chat,
but that model does not support embeddings — API returns errors.
"""

import time
import httpx
import structlog

from config.settings import settings

logger = structlog.get_logger("equated.cache.embeddings")


class EmbeddingGenerator:
    """
    Generates text embeddings for semantic similarity search.

    Provider: OpenAI text-embedding-3-small
    Dimension: 1536 (matches pgvector schema)
    Cost: ~$0.02 per 1M tokens
    """

    EMBEDDING_DIMENSION = 1536
    MODEL = "text-embedding-3-small"

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._disabled_until_monotonic: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        """Reuse a single httpx client for connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.OPENAI_BASE_URL.rstrip("/"),
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                timeout=1.5,
            )
        return self._client

    async def generate(self, text: str) -> list[float] | None:
        """Generate an embedding vector for the given text."""
        import asyncio
        if not settings.OPENAI_API_KEY:
            logger.warning("embedding_skipped", reason="OPENAI_API_KEY not set")
            return None

        if self._disabled_until_monotonic > time.monotonic():
            logger.warning("embedding_skipped", reason="embedding_provider_temporarily_disabled")
            return None

        try:
            client = await self._get_client()
            response = await asyncio.wait_for(
                client.post(
                    "/embeddings",
                    json={
                        "model": self.MODEL,
                        "input": text[:8000],  # Truncate to safe input length
                    },
                ),
                timeout=2.0
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]

        except (asyncio.TimeoutError, httpx.TimeoutException):
            self._disabled_until_monotonic = time.monotonic() + 600
            logger.warning("embedding_rate_limited", cooldown_seconds=600, model=self.MODEL, reason="timeout")
            return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                self._disabled_until_monotonic = time.monotonic() + 600
                logger.warning("embedding_rate_limited", cooldown_seconds=600, model=self.MODEL)
                return None
            logger.error("embedding_failed", error=str(e), model=self.MODEL)
            return None
        except Exception as e:
            logger.error("embedding_failed", error=str(e), model=self.MODEL)
            return None

    async def generate_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for multiple texts in a single API call."""
        import asyncio
        if not settings.OPENAI_API_KEY:
            return [None] * len(texts)

        try:
            client = await self._get_client()
            response = await asyncio.wait_for(
                client.post(
                    "/embeddings",
                    json={
                        "model": self.MODEL,
                        "input": [t[:8000] for t in texts],
                    },
                ),
                timeout=2.0
            )
            response.raise_for_status()
            data = response.json()
            # Sort by index to maintain order
            sorted_embeddings = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_embeddings]

        except Exception as e:
            logger.error("batch_embedding_failed", error=str(e), count=len(texts))
            # Fall back to individual calls
            results = []
            for text in texts:
                embedding = await self.generate(text)
                results.append(embedding)
            return results


# Singleton
embedding_generator = EmbeddingGenerator()
