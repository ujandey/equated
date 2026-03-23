"""
Gateway — Auth Middleware

Verifies Supabase JWT on every request. Populates request.state.user_id
for downstream services. Skips auth for public routes (health, docs).

Uses local JWT validation (no HTTP call per request) for production performance.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from services.auth import auth_service

# Public paths that don't require authentication
PUBLIC_PATHS = {
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Validates Supabase JWT from the Authorization header.

    Flow:
      1. Extract Bearer token
      2. Verify JWT signature locally (sub-ms) or via Supabase fallback
      3. Set request.state.user_id on success
      4. Return 401 on failure (except for public paths)
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

        # Extract token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "missing_token", "message": "Authorization header required."},
            )

        token = auth_header.removeprefix("Bearer ").strip()

        # Verify locally (fast path) or via Supabase (fallback)
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
        except Exception:
            pass  # Non-fatal: user creation might fail if DB is down, but let the request continue

        return await call_next(request)
