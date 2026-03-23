"""
Services — Input Validator

Sanitizes and validates all user input before processing.
Prevents prompt injection, oversized payloads, and malicious strings.
"""

import re
import structlog

from core.exceptions import ValidationError, InputTooLargeError, PromptInjectionError
from config.settings import settings

logger = structlog.get_logger("equated.services.input_validator")


# ── Prompt Injection Patterns ───────────────────────
# Common prompt manipulation attempts
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?your\s+(instructions|rules|guidelines)",
    r"you\s+are\s+now\s+(a|an)\s+\w+",
    r"act\s+as\s+(a|an)\s+\w+",
    r"pretend\s+(to\s+be|you\s+are)",
    r"system\s*:\s*",
    r"\[INST\]",
    r"<\|im_start\|>",
    r"<\|system\|>",
    r"```\s*system",
]

# Dangerous content patterns
MALICIOUS_PATTERNS = [
    r"<script[^>]*>",           # XSS
    r"javascript\s*:",          # JS protocol
    r"on\w+\s*=\s*[\"']",      # Event handlers
    r"data\s*:\s*text/html",    # Data URI
    r"eval\s*\(",               # Code execution
    r"__import__\s*\(",         # Python import injection
    r"exec\s*\(",               # Python exec
    r"subprocess",              # Shell injection
]


class InputValidator:
    """
    Validates and sanitizes all user input.

    Checks:
      1. Input size limits
      2. Prompt injection detection
      3. Malicious string patterns
      4. Character encoding validation
      5. Basic content quality
    """

    def validate_query(self, text: str) -> str:
        """
        Full validation pipeline for query text input.
        Returns cleaned text or raises an exception.
        """
        # 1. Size check
        if len(text) > settings.MAX_INPUT_LENGTH:
            raise InputTooLargeError(
                f"Input exceeds maximum length of {settings.MAX_INPUT_LENGTH} characters."
            )

        if len(text.strip()) == 0:
            raise ValidationError("Query cannot be empty.")

        # 2. Prompt injection check
        self._check_prompt_injection(text)

        # 3. Malicious content check
        self._check_malicious_content(text)

        # 4. Sanitize
        cleaned = self._sanitize(text)

        return cleaned

    def validate_image_size(self, size_bytes: int):
        """Validate image upload size."""
        max_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
        if size_bytes > max_bytes:
            raise InputTooLargeError(
                f"Image exceeds maximum size of {settings.MAX_IMAGE_SIZE_MB}MB."
            )

    def _check_prompt_injection(self, text: str):
        """Detect prompt injection attempts."""
        text_lower = text.lower()
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                logger.warning(
                    "prompt_injection_detected",
                    pattern=pattern,
                    input_preview=text[:100],
                )
                raise PromptInjectionError()

    def _check_malicious_content(self, text: str):
        """Detect XSS, script injection, and other malicious content."""
        for pattern in MALICIOUS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(
                    "malicious_content_detected",
                    pattern=pattern,
                    input_preview=text[:100],
                )
                raise ValidationError("Input contains disallowed content.")

    def _sanitize(self, text: str) -> str:
        """Clean input text while preserving mathematical content."""
        # Remove null bytes
        text = text.replace("\x00", "")

        # Normalize unicode
        import unicodedata
        text = unicodedata.normalize("NFKC", text)

        # Collapse excessive whitespace (but preserve single newlines for formatting)
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        text = re.sub(r" {3,}", "  ", text)

        return text.strip()


# Singleton
input_validator = InputValidator()
