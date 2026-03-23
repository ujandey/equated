"""
Router — Auth Endpoints

/api/v1/auth — user authentication, profile, and token verification.
"""

from fastapi import APIRouter, Depends

from core.dependencies import get_current_user
from core.exceptions import NotFoundError
from services.auth import auth_service

router = APIRouter()


@router.get("/auth/me")
async def get_current_user_info(user_id: str = Depends(get_current_user)):
    """Get the authenticated user's profile."""
    profile = await auth_service.get_user_profile(user_id)
    if not profile:
        raise NotFoundError("User")
    return profile


@router.post("/auth/verify")
async def verify_token(user_id: str = Depends(get_current_user)):
    """
    Verify that the current token is valid.
    Returns 200 if valid, 401 otherwise (handled by middleware).
    """
    return {"valid": True, "user_id": user_id}


@router.get("/auth/profile")
async def get_profile(user_id: str = Depends(get_current_user)):
    """Get detailed user profile with usage stats."""
    profile = await auth_service.get_user_profile(user_id)
    if not profile:
        raise NotFoundError("User")

    from db.connection import get_db
    db = await get_db()

    # Get solve count
    total_solves = await db.fetchval(
        "SELECT COUNT(*) FROM solves WHERE user_id = $1", user_id
    )

    # Get session count
    total_sessions = await db.fetchval(
        "SELECT COUNT(*) FROM sessions WHERE user_id = $1", user_id
    )

    return {
        **profile,
        "stats": {
            "total_solves": total_solves or 0,
            "total_sessions": total_sessions or 0,
        },
    }
