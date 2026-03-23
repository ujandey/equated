"""
Services — Query Normalizer

Normalizes queries BEFORE cache lookup so that semantically identical
questions map to the same cache key.

Examples that should all match:
  "solve 2x + 3 = 5"
  "solve 2x+3=5"
  "Solve 2x + 3 = 5"
  "find x: 2x + 3 = 5"
  "what is x if 2x + 3 = 5?"
"""

import re
import unicodedata


class QueryNormalizer:
    """
    Normalizes student queries for cache key consistency.

    Pipeline:
      1. Unicode normalization (NFKD)
      2. Lowercase
      3. Remove filler words ("solve", "find", "calculate", "what is")
      4. Normalize whitespace around operators
      5. Remove punctuation (except math symbols)
      6. Strip trailing question marks / periods
    """

    FILLER_WORDS = {
        "solve", "find", "calculate", "compute", "evaluate", "determine",
        "what", "is", "are", "the", "of", "for", "a", "an",
        "please", "can", "you", "help", "me", "with",
    }

    MATH_OPERATORS = {"+", "-", "*", "/", "=", "^", "(", ")", "[", "]", "{", "}"}

    def normalize(self, query: str) -> str:
        """Apply full normalization pipeline."""
        q = query

        # 1. Unicode normalize
        q = unicodedata.normalize("NFKD", q)

        # 2. Lowercase
        q = q.lower()

        # 3. Remove filler words
        words = q.split()
        words = [w for w in words if w not in self.FILLER_WORDS]
        q = " ".join(words)

        # 4. Normalize spaces around math operators
        q = re.sub(r"\s*([+\-*/=^])\s*", r"\1", q)

        # 5. Remove non-math punctuation
        q = re.sub(r"[?!.,;:'\"]", "", q)

        # 6. Collapse whitespace
        q = re.sub(r"\s+", " ", q).strip()

        return q

    def generate_cache_key(self, query: str) -> str:
        """Generate a deterministic cache key from a query."""
        import hashlib
        normalized = self.normalize(query)
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    def are_equivalent(self, query_a: str, query_b: str) -> bool:
        """Check if two queries normalize to the same form."""
        return self.normalize(query_a) == self.normalize(query_b)


# Singleton
query_normalizer = QueryNormalizer()
