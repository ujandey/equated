"""
Services - Context Policy

Decides whether a new user query should continue the current session
or start a fresh thread.

Primary signal:
  - Embedding similarity between the last user question and the new one

Fallback signals:
  - Follow-up language ("what about that?", "continue", etc.)
  - Subject/intent mismatch
  - Lexical overlap between meaningful tokens
"""

from dataclasses import dataclass
import math
import re
import structlog

from ai.classifier import classifier
from cache.embeddings import embedding_generator

logger = structlog.get_logger("equated.services.context_policy")


FOLLOW_UP_PATTERN = re.compile(
    r"\b(what about|and what about|also|now|continue|go on|same|that|those|it|this one|next step|"
    r"can you explain that|why is that|how about|then what|use that|from above)\b",
    re.IGNORECASE,
)

TOKEN_PATTERN = re.compile(r"\b[a-zA-Z]{3,}\b")


@dataclass
class ContextDecision:
    should_reset: bool
    reason: str
    similarity: float | None = None


class ContextPolicy:
    EMBEDDING_RESET_THRESHOLD = 0.42
    TOKEN_OVERLAP_RESET_THRESHOLD = 0.18

    async def decide(self, previous_question: str | None, new_question: str) -> ContextDecision:
        """Return whether the new question should start a fresh thread."""
        if not previous_question or not previous_question.strip():
            return ContextDecision(False, "no_previous_question")

        previous = previous_question.strip()
        current = new_question.strip()

        if FOLLOW_UP_PATTERN.search(current):
            return ContextDecision(False, "explicit_follow_up")

        previous_classification = classifier.classify(previous)
        current_classification = classifier.classify(current)

        # Strong subject shift with almost no lexical overlap is a good
        # reset signal even without embeddings.
        token_overlap = self._token_overlap(previous, current)

        similarity = await self._embedding_similarity(previous, current)
        if similarity is not None:
            if similarity < self.EMBEDDING_RESET_THRESHOLD:
                logger.info(
                    "context_reset_decision",
                    reason="low_embedding_similarity",
                    similarity=round(similarity, 4),
                    token_overlap=round(token_overlap, 4),
                )
                return ContextDecision(True, "low_embedding_similarity", similarity=similarity)

            return ContextDecision(False, "embedding_similarity_kept", similarity=similarity)

        if (
            previous_classification.subject != current_classification.subject
            and token_overlap < self.TOKEN_OVERLAP_RESET_THRESHOLD
        ):
            return ContextDecision(True, "subject_shift_low_overlap")

        if token_overlap < self.TOKEN_OVERLAP_RESET_THRESHOLD:
            return ContextDecision(True, "low_token_overlap")

        return ContextDecision(False, "lexical_overlap_kept")

    async def _embedding_similarity(self, previous: str, current: str) -> float | None:
        prev_embedding = await embedding_generator.generate(previous)
        curr_embedding = await embedding_generator.generate(current)
        if not prev_embedding or not curr_embedding:
            return None
        return self._cosine_similarity(prev_embedding, curr_embedding)

    def _token_overlap(self, previous: str, current: str) -> float:
        prev_tokens = set(TOKEN_PATTERN.findall(previous.lower()))
        curr_tokens = set(TOKEN_PATTERN.findall(current.lower()))
        if not prev_tokens or not curr_tokens:
            return 0.0

        intersection = len(prev_tokens & curr_tokens)
        union = len(prev_tokens | curr_tokens)
        return intersection / union if union else 0.0

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)


context_policy = ContextPolicy()
