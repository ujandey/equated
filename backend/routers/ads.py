"""
Router — Ads Endpoints

/api/v1/ads — ad eligibility, completion tracking, and config.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from core.dependencies import get_current_user
from services.ads import ads_service

router = APIRouter()


@router.get("/ads/should-show")
async def should_show_ad(user_id: str = Depends(get_current_user)):
    """Check if an ad should be shown to the current user."""
    return await ads_service.should_show_ad(user_id)


@router.post("/ads/watched")
async def ad_watched(
    user_id: str = Depends(get_current_user),
    ad_type: str = Query(default="rewarded_video"),
):
    """Record a completed ad watch and award credits."""
    if ad_type != "rewarded_video":
        raise HTTPException(status_code=400, detail="Invalid ad type")
    return await ads_service.record_ad_watched(user_id, ad_type)


@router.get("/ads/config")
async def get_ad_config():
    """Get current ad configuration (for frontend)."""
    return await ads_service.get_ad_config()
