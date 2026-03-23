"""
Services — Context Compressor

Compresses long conversation histories to reduce LLM token costs.
When a chat session exceeds MAX_CONTEXT_MESSAGES, older messages are
summarized into a single context block.

Target: 40-60% token reduction on long conversations.
"""

import structlog

logger = structlog.get_logger("equated.services.context_compressor")


class ContextCompressor:
    """
    Compresses conversation history for efficient LLM context windows.

    Strategies:
      1. Keep last N messages verbatim (most recent context)
      2. Summarize older messages into a condensed block
      3. Preserve key mathematical expressions and answers
      4. Remove redundant greetings and filler
    """

    MAX_VERBATIM_MESSAGES: int = 8       # Keep last 8 messages as-is
    MAX_SUMMARY_CHARS: int = 1000        # Max chars for summary block
    MIN_MESSAGES_TO_COMPRESS: int = 12   # Don't compress if fewer than this

    def compress(self, messages: list[dict]) -> list[dict]:
        """
        Compress a message list for the AI context window.

        Returns optimized message list with system + summary + recent messages.
        """
        if len(messages) <= self.MIN_MESSAGES_TO_COMPRESS:
            return messages

        # Separate system messages from conversation
        system_msgs = [m for m in messages if m.get("role") == "system"]
        conversation = [m for m in messages if m.get("role") != "system"]

        if len(conversation) <= self.MAX_VERBATIM_MESSAGES:
            return messages

        # Split into old (to summarize) and recent (keep verbatim)
        old_messages = conversation[:-self.MAX_VERBATIM_MESSAGES]
        recent_messages = conversation[-self.MAX_VERBATIM_MESSAGES:]

        # Generate summary of old messages
        summary = self._summarize(old_messages)

        # Build compressed message list
        compressed = system_msgs + [
            {
                "role": "system",
                "content": f"[Previous conversation summary — {len(old_messages)} messages]\n{summary}",
            }
        ] + recent_messages

        original_chars = sum(len(m.get("content", "")) for m in messages)
        compressed_chars = sum(len(m.get("content", "")) for m in compressed)
        reduction = round((1 - compressed_chars / original_chars) * 100, 1) if original_chars > 0 else 0

        logger.info(
            "context_compressed",
            original_messages=len(messages),
            compressed_messages=len(compressed),
            reduction_pct=reduction,
        )

        return compressed

    def _summarize(self, messages: list[dict]) -> str:
        """
        Create a concise summary of messages.

        Preserves:
          - Questions asked
          - Key answers / results
          - Mathematical expressions
          - Important context
        """
        summaries = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                # Extract the core question
                question = self._extract_question(content)
                summaries.append(f"• User asked: {question}")
            elif role == "assistant":
                # Extract the key answer
                answer = self._extract_answer(content)
                summaries.append(f"• Assistant answered: {answer}")

        # Join and truncate
        summary = "\n".join(summaries)
        if len(summary) > self.MAX_SUMMARY_CHARS:
            # Keep most recent summaries within limit
            lines = summary.split("\n")
            truncated = []
            char_count = 0
            for line in reversed(lines):
                if char_count + len(line) > self.MAX_SUMMARY_CHARS:
                    break
                truncated.insert(0, line)
                char_count += len(line) + 1
            summary = "\n".join(truncated)

        return summary

    def _extract_question(self, content: str) -> str:
        """Extract the core question from user input."""
        # Take first 150 chars, try to end at a sentence boundary
        truncated = content[:150]
        for end_char in ["?", ".", "\n"]:
            idx = truncated.find(end_char)
            if idx > 20:
                return truncated[:idx + 1]
        return truncated + "..." if len(content) > 150 else content

    def _extract_answer(self, content: str) -> str:
        """Extract the key answer from assistant output."""
        import re

        # Look for "Final Answer" section
        final_match = re.search(r"(?:final answer|result|solution)\s*[:\n]\s*(.*?)(?:\n\n|\Z)", content, re.IGNORECASE | re.DOTALL)
        if final_match:
            answer = final_match.group(1).strip()[:200]
            return answer

        # Fallback: first 120 chars
        truncated = content[:120]
        return truncated + "..." if len(content) > 120 else content

    def estimate_savings(self, original: list[dict], compressed: list[dict]) -> dict:
        """Calculate token savings from compression."""
        orig_chars = sum(len(m.get("content", "")) for m in original)
        comp_chars = sum(len(m.get("content", "")) for m in compressed)
        saved = orig_chars - comp_chars
        # Rough token estimate: 1 token ≈ 4 chars
        return {
            "original_tokens_est": orig_chars // 4,
            "compressed_tokens_est": comp_chars // 4,
            "tokens_saved_est": saved // 4,
            "reduction_pct": round((saved / orig_chars) * 100, 1) if orig_chars > 0 else 0,
        }


# Singleton
context_compressor = ContextCompressor()
