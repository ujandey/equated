"""
Router — Health Check Endpoints

/api/health — liveness, readiness, and per-service health probes.
Essential for container orchestration, load balancers, and uptime monitors.
"""

from fastapi import APIRouter
from db.models import HealthResponse
import structlog

logger = structlog.get_logger("equated.routers.health")

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Root health check — reports overall status and service health."""
    services = {}

    # Check Redis
    try:
        from cache.redis_cache import redis_client
        await redis_client.client.ping()
        services["redis"] = "ok"
    except Exception:
        services["redis"] = "down"

    # Check Database
    try:
        from db.connection import get_db
        db = await get_db()
        await db.fetchval("SELECT 1")
        services["database"] = "ok"
    except Exception:
        services["database"] = "down"

    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"

    return HealthResponse(status=overall, version="1.0.0", services=services)


@router.get("/health/db")
async def health_db():
    """Database health check — verifies connection pool and query execution."""
    try:
        from db.connection import get_db
        db = await get_db()
        row = await db.fetchrow("SELECT NOW() as server_time, current_database() as db_name")
        pool_size = db.get_size()
        pool_free = db.get_idle_size()
        return {
            "status": "ok",
            "database": row["db_name"],
            "server_time": str(row["server_time"]),
            "pool_size": pool_size,
            "pool_free": pool_free,
        }
    except Exception as e:
        logger.error("db_health_error", error=str(e), exc_info=True)
        return {"status": "down", "error": "An internal error occurred."}


@router.get("/health/redis")
async def health_redis():
    """Redis health check — verifies connection and basic operations."""
    try:
        from cache.redis_cache import redis_client
        info = await redis_client.client.info(section="server")
        await redis_client.client.ping()
        return {
            "status": "ok",
            "redis_version": info.get("redis_version", "unknown"),
            "uptime_seconds": info.get("uptime_in_seconds", 0),
            "connected_clients": info.get("connected_clients", 0),
        }
    except Exception as e:
        logger.error("redis_health_error", error=str(e), exc_info=True)
        return {"status": "down", "error": "An internal error occurred."}


@router.get("/health/ai")
async def health_ai():
    """AI model health check — verifies API connectivity for each provider."""
    results = {}

    # Check DeepSeek
    try:
        import httpx
        from config.settings import settings
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.DEEPSEEK_BASE_URL}/models",
                headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
            )
        results["deepseek"] = "ok" if response.status_code == 200 else f"error_{response.status_code}"
    except Exception as e:
        logger.error("deepseek_health_error", error=str(e), exc_info=True)
        results["deepseek"] = "down: An internal error occurred."

    # Check Groq
    try:
        import httpx
        from config.settings import settings
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.GROQ_BASE_URL}/models",
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            )
        results["groq"] = "ok" if response.status_code == 200 else f"error_{response.status_code}"
    except Exception as e:
        logger.error("groq_health_error", error=str(e), exc_info=True)
        results["groq"] = "down: An internal error occurred."

    overall = "ok" if all(v == "ok" for v in results.values()) else "degraded"
    return {"status": overall, "providers": results}
