"""
Equated Backend — FastAPI Application Entry Point

Mounts all routers, applies gateway middleware (auth, rate limiting, logging),
registers exception handlers, and configures CORS + observability.

Uses lifespan context manager for startup/shutdown events.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from core.exceptions import register_exception_handlers
from gateway.auth_middleware import AuthMiddleware
from gateway.rate_limit import RateLimitMiddleware
from gateway.request_logger import RequestLoggerMiddleware


# ── Lifespan (startup + shutdown) ──────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down services."""
    import logging
    logger = logging.getLogger("equated.startup")

    # ── Startup ─────────────────────────────
    # Validate environment FIRST — fail fast before connecting to anything
    from config.settings import settings as _settings
    _settings.validate_critical_env()

    from monitoring.json_logger import configure_json_logging
    from monitoring.tracing import init_tracing
    from monitoring.metrics import init_metrics
    from cache.redis_cache import redis_client
    from db.connection import init_db

    configure_json_logging()
    init_tracing()
    init_metrics()

    # Connect to Redis (non-fatal if unavailable)
    try:
        await redis_client.connect()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection failed (app will run without cache): {e}")

    # Connect to database (non-fatal if unavailable)
    try:
        await init_db()
        logger.info("Database connected")
    except Exception as e:
        logger.warning(f"Database connection failed (some features unavailable): {e}")

    yield

    # ── Shutdown ────────────────────────────
    from cache.redis_cache import redis_client as _redis
    from db.connection import close_db
    from ai.models import close_all_clients

    try:
        await close_all_clients()
    except Exception as e:
        logger.error(f"HTTP client shutdown failed: {e}", exc_info=True)
    try:
        await _redis.disconnect()
    except Exception as e:
        logger.error(f"Redis disconnect failed: {e}", exc_info=True)
    try:
        await close_db()
    except Exception as e:
        logger.error(f"Database disconnect failed: {e}", exc_info=True)


# ── App Factory ─────────────────────────────────────
app = FastAPI(
    title="Equated API",
    description="AI STEM Learning Assistant — Backend Service",
    version=settings.API_VERSION,
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url="/redoc" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)


# ── Exception Handlers ─────────────────────────────
register_exception_handlers(app)


# ── Middleware Stack (order matters: last added = outermost = runs first) ──
# Starlette processes middleware in reverse order of add_middleware calls.
# CORS must be outermost so it can add headers to ALL responses (including 401s).
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggerMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time"],
)


# ── Routers ─────────────────────────────────────────
from routers import health, solver, auth, chat, credits, analytics, ads, admin

app.include_router(health.router,     prefix="/api",          tags=["Health"])
app.include_router(auth.router,       prefix="/api/v1",       tags=["Auth"])
app.include_router(solver.router,     prefix="/api/v1",       tags=["Solver"])
app.include_router(chat.router,       prefix="/api/v1",       tags=["Chat"])
app.include_router(credits.router,    prefix="/api/v1",       tags=["Credits"])
app.include_router(analytics.router,  prefix="/api/v1",       tags=["Analytics"])
app.include_router(ads.router,        prefix="/api/v1",       tags=["Ads"])
app.include_router(admin.router,      prefix="/api/v1/admin", tags=["Admin"])


# ── Prometheus Metrics Endpoint ─────────────────────
from monitoring.metrics import metrics_endpoint

@app.get("/metrics", include_in_schema=False)
async def metrics():
    return metrics_endpoint()
