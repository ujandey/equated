"""
Core — Exception Hierarchy & Global Error Handler

Centralized exception system with automatic HTTP status mapping.
Every exception carries a machine-readable error code and human message.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger("equated.core.exceptions")


# ── Base Exception ──────────────────────────────────
class EquatedError(Exception):
    """Base exception for all Equated errors."""
    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str = "An unexpected error occurred.", detail: dict | None = None):
        self.message = message
        self.detail = detail or {}
        super().__init__(self.message)


# ── Auth ────────────────────────────────────────────
class AuthError(EquatedError):
    status_code = 401
    error_code = "auth_error"

    def __init__(self, message: str = "Authentication failed."):
        super().__init__(message)


class ForbiddenError(EquatedError):
    status_code = 403
    error_code = "forbidden"

    def __init__(self, message: str = "You do not have permission to access this resource."):
        super().__init__(message)


# ── Rate Limiting ───────────────────────────────────
class RateLimitError(EquatedError):
    status_code = 429
    error_code = "rate_limit_exceeded"

    def __init__(self, message: str = "Too many requests.", retry_after: int = 60):
        super().__init__(message, detail={"retry_after_seconds": retry_after})


# ── Credits ─────────────────────────────────────────
class CreditError(EquatedError):
    status_code = 402
    error_code = "insufficient_credits"

    def __init__(self, message: str = "Insufficient credits.", remaining: int = 0):
        super().__init__(message, detail={"credits_remaining": remaining})


# ── AI Service ──────────────────────────────────────
class AIServiceError(EquatedError):
    status_code = 503
    error_code = "ai_service_unavailable"

    def __init__(self, message: str = "AI service is currently unavailable.", provider: str = ""):
        super().__init__(message, detail={"provider": provider})


# ── Cache ───────────────────────────────────────────
class CacheError(EquatedError):
    status_code = 500
    error_code = "cache_error"

    def __init__(self, message: str = "Cache operation failed."):
        super().__init__(message)


# ── Validation ──────────────────────────────────────
class ValidationError(EquatedError):
    status_code = 422
    error_code = "validation_error"

    def __init__(self, message: str = "Input validation failed.", fields: dict | None = None):
        super().__init__(message, detail={"fields": fields or {}})


class InputTooLargeError(EquatedError):
    status_code = 413
    error_code = "input_too_large"

    def __init__(self, message: str = "Input exceeds maximum allowed size."):
        super().__init__(message)


class PromptInjectionError(EquatedError):
    status_code = 400
    error_code = "prompt_injection_detected"

    def __init__(self, message: str = "Potentially malicious input detected."):
        super().__init__(message)


# ── Not Found ───────────────────────────────────────
class NotFoundError(EquatedError):
    status_code = 404
    error_code = "not_found"

    def __init__(self, resource: str = "Resource"):
        super().__init__(f"{resource} not found.")


# ── Global Exception Handler ───────────────────────
def register_exception_handlers(app: FastAPI):
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(EquatedError)
    async def equated_error_handler(request: Request, exc: EquatedError):
        logger.warning(
            "handled_error",
            error_code=exc.error_code,
            status=exc.status_code,
            message=exc.message,
            path=str(request.url.path),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                **exc.detail,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_error",
            error=str(exc),
            error_type=type(exc).__name__,
            path=str(request.url.path),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred. Please try again.",
            },
        )
