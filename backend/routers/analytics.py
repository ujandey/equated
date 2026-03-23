"""
Router — Analytics Endpoints

/api/v1/analytics — user-facing usage statistics, streaks, and breakdowns.
"""

from fastapi import APIRouter, Depends

from core.dependencies import get_current_user, require_admin
from services.analytics import analytics_service

router = APIRouter()


@router.get("/analytics/my-usage")
async def get_my_usage(user_id: str = Depends(get_current_user)):
    """Get the current user's overall usage statistics."""
    return await analytics_service.get_usage_stats(user_id)


@router.get("/analytics/streak")
async def get_streak(user_id: str = Depends(get_current_user)):
    """Get the current user's activity streak."""
    return await analytics_service.get_streak(user_id)


@router.get("/analytics/subjects")
async def get_subjects(user_id: str = Depends(get_current_user)):
    """Get solve count breakdown by subject."""
    return await analytics_service.get_subject_breakdown(user_id)


@router.get("/analytics/model-usage")
async def get_model_usage(user_id: str = Depends(get_current_user)):
    """Get which AI models were used for this user's solves."""
    return await analytics_service.get_model_usage_summary(user_id)


@router.get("/analytics/weekly-summary")
async def get_weekly_summary(user_id: str = Depends(get_current_user)):
    """Get a 7-day activity summary."""
    return await analytics_service.get_weekly_summary(user_id)


@router.get("/analytics/credit-usage")
async def get_credit_usage(user_id: str = Depends(get_current_user)):
    """Get credit usage breakdown (spent, purchased, earned from ads)."""
    return await analytics_service.get_credit_usage(user_id)


# ── Admin Endpoints ─────────────────────────────────
@router.get("/analytics/cache-hit-rate")
async def get_cache_hit_rate(admin_id: str = Depends(require_admin)):
    """Get global cache hit/miss rate (admin only)."""
    return await analytics_service.get_cache_hit_rate()


@router.get("/analytics/ai-costs")
async def get_ai_costs(admin_id: str = Depends(require_admin)):
    """Get today's AI cost breakdown by model (admin only)."""
    return await analytics_service.get_ai_costs_summary()
