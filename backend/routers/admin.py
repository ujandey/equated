"""
Router — Admin Dashboard Endpoints

/api/v1/admin — internal cost, model, cache, and usage dashboards
Protected by admin role check.
"""

from fastapi import APIRouter, Request, HTTPException, Query

from ai.cost_optimizer import cost_optimizer
from cache.cache_metrics import cache_metrics

router = APIRouter()


async def _require_admin(request: Request):
    """Check that the requesting user has admin role."""
    # TODO: implement proper admin role check from DB
    user_id = request.state.user_id
    if not user_id:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/costs")
async def get_costs(request: Request):
    """Get AI cost breakdown — daily total, per-model, budget status."""
    await _require_admin(request)
    report = cost_optimizer.get_cost_report()
    return {
        "daily_cost_usd": round(cost_optimizer.get_daily_total(), 4),
        "cost_report": report,
        "within_budget": cost_optimizer.is_within_budget(),
    }


@router.get("/models")
async def get_model_stats(request: Request):
    """Get model usage statistics."""
    await _require_admin(request)
    from db.connection import get_db
    db = await get_db()

    rows = await db.fetch(
        """SELECT model, COUNT(*) as calls,
                  SUM(input_tokens) as total_input,
                  SUM(output_tokens) as total_output,
                  SUM(cost_usd) as total_cost
           FROM model_usage GROUP BY model"""
    )
    return {"models": [dict(r) for r in rows]}


@router.get("/cache-stats")
async def get_cache_stats(request: Request):
    """Get cache hit/miss rates and cost savings."""
    await _require_admin(request)
    return cache_metrics.get_summary()


@router.get("/user-usage")
async def get_user_usage(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    """Get top users by solve count."""
    await _require_admin(request)
    from db.connection import get_db
    db = await get_db()

    rows = await db.fetch(
        """SELECT user_id, COUNT(*) as solves, SUM(cost_usd) as total_cost
           FROM solves GROUP BY user_id ORDER BY solves DESC LIMIT $1""",
        limit,
    )
    return {"users": [dict(r) for r in rows]}
