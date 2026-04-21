"""
Gateway — Auth Middleware

Verifies Supabase JWT on every request. Populates request.state.user_id
for downstream services. Skips auth for public routes (health, docs).

Uses local JWT validation (no HTTP call per request) for production performance.

In development mode (APP_ENV=development) with no Supabase configured,
all requests are assigned a dev user ID so the app is fully testable
without any auth infrastructure.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings

# Public paths that don't require authentication
PUBLIC_PATHS = {
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/api/v1/credits/packs",
    "/api/v1/credits/webhook",
}

# Dev mode: skip auth entirely when Supabase is not configured
_DEV_MODE = (
    settings.APP_ENV == "development"
)
_DEV_USER_ID = "00000000-0000-0000-0000-000000000000"


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Validates Supabase JWT from the Authorization header.

    Flow:
      1. Extract Bearer token
      2. Verify JWT signature locally (sub-ms) or via Supabase fallback
      3. Set request.state.user_id on success
      4. Return 401 on failure (except for public paths)

    Dev Mode:
      When APP_ENV=development and SUPABASE_URL is not set, all requests
      are automatically assigned a dev user ID. This allows the full app
      to be tested locally without any auth infrastructure.
    """

    async def dispatch(self, request: Request, call_next):
        # Always allow CORS preflight requests through (they never carry auth)
        if request.method == "OPTIONS":
            request.state.user_id = None
            return await call_next(request)

        # Allow public routes through without auth
        if any(request.url.path.startswith(p) for p in PUBLIC_PATHS):
            request.state.user_id = None
            return await call_next(request)

        # ── Dev Mode Bypass ──
        if _DEV_MODE:
            request.state.user_id = _DEV_USER_ID
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            if settings.APP_ENV == "development":
                request.state.user_id = _DEV_USER_ID
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"error": "missing_token", "message": "Authorization header required."},
            )

        token = auth_header.removeprefix("Bearer ").strip()

        # Verify locally (fast path) or via Supabase (fallback)
        from services.auth import auth_service
        user_id = await auth_service.verify_token(token)
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "message": "Invalid or expired token."},
            )

        request.state.user_id = user_id

        # Auto-create user record on first authenticated request
        try:
            await auth_service.ensure_user_exists(user_id)
        except Exception as e:
            # Non-fatal: user creation might fail if DB is down, but let the request continue
            import logging
            log = logging.getLogger("equated.gateway.auth")
            log.warning(f"user_creation_failed for {user_id[:8]}: {e}")

        return await call_next(request)
