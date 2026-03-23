"""
AI — Prompt Optimizer

Reduces token usage (and therefore cost) by:
  1. Compressing chat history to essential context
  2. Removing redundant whitespace and formatting
  3. Summarizing long conversation histories
  4. Shortening system prompts without losing instruction quality

Target: 20-40% token reduction on average.
"""

import re


class PromptOptimizer:
    """
    Optimizes prompts before sending to AI models.

    Strategies:
      - Whitespace normalization
      - Chat history compression (keep last N turns + summary)
      - Template-based prompt shortening
    """

    MAX_HISTORY_TURNS = 5      # Keep last 5 turns verbatim
    MAX_PROMPT_CHARS = 8000    # Truncate if exceeding

    def optimize(self, messages: list[dict]) -> list[dict]:
        """Apply all optimization strategies to a message list."""
        messages = self._compress_history(messages)
        messages = [self._clean_message(m) for m in messages]
        return messages

    def _clean_message(self, message: dict) -> dict:
        """Remove redundant whitespace and normalize formatting."""
        content = message.get("content", "")
        # Collapse multiple spaces/newlines
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r" {2,}", " ", content)
        content = content.strip()
        return {**message, "content": content}

    def _compress_history(self, messages: list[dict]) -> list[dict]:
        """
        Keep system message + last N user/assistant turns.
        Summarize older turns into a single context message.
        """
        if len(messages) <= self.MAX_HISTORY_TURNS + 1:
            return messages

        system_msgs = [m for m in messages if m["role"] == "system"]
        non_system = [m for m in messages if m["role"] != "system"]

        if len(non_system) <= self.MAX_HISTORY_TURNS:
            return messages

        # Split into old and recent
        old_turns = non_system[:-self.MAX_HISTORY_TURNS]
        recent_turns = non_system[-self.MAX_HISTORY_TURNS:]

        # Summarize old turns
        summary = self._summarize_turns(old_turns)
        context_msg = {
            "role": "system",
            "content": f"[Previous conversation summary]\n{summary}",
        }

        return system_msgs + [context_msg] + recent_turns

    def _summarize_turns(self, turns: list[dict]) -> str:
        """Create a brief summary of older conversation turns."""
        summaries = []
        for turn in turns:
            role = turn["role"]
            content = turn["content"][:100]  # First 100 chars
            summaries.append(f"{role}: {content}...")
        return "\n".join(summaries[-3:])  # Keep last 3 summaries

    def estimate_savings(self, original: list[dict], optimized: list[dict]) -> dict:
        """Compare token counts before and after optimization."""
        orig_chars = sum(len(m.get("content", "")) for m in original)
        opt_chars = sum(len(m.get("content", "")) for m in optimized)
        saved = orig_chars - opt_chars
        return {
            "original_chars": orig_chars,
            "optimized_chars": opt_chars,
            "chars_saved": saved,
            "reduction_pct": round((saved / orig_chars) * 100, 1) if orig_chars > 0 else 0,
        }


# Singleton
prompt_optimizer = PromptOptimizer()
