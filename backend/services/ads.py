"""
Services — Ads Service

Ad decision engine for the watch-to-earn model.
Determines when to show ads, tracks watch completion,
and awards credits for completed views.
"""

import time
import structlog
from datetime import date

from config.settings import settings
from config.feature_flags import flags

logger = structlog.get_logger("equated.services.ads")


class AdsService:
    """
    Manages the ad-based credit earning system.

    Rules:
      - Free users see ads after every N solves
      - Users can watch ads voluntarily to earn credits
      - Daily limit on ad rewards (prevent abuse)
      - Cooldown between ad watches
      - Ads can be disabled globally via feature flag
    """

    async def should_show_ad(self, user_id: str) -> dict:
        """
        Decide whether to show an ad to the user.

        Returns:
          {"show": bool, "reason": str, "ad_type": str}
        """
        if not flags.ads_enabled:
            return {"show": False, "reason": "ads_disabled", "ad_type": "none"}

        from db.connection import get_db
        db = await get_db()

        # Check user tier
        user = await db.fetchrow(
            "SELECT tier, credits FROM users WHERE id = $1", user_id
        )
        if not user:
            return {"show": False, "reason": "user_not_found", "ad_type": "none"}

        # Paid users with credits don't see ads
        if user["tier"] == "paid" and (user["credits"] or 0) > 0:
            return {"show": False, "reason": "paid_user", "ad_type": "none"}

        # Check daily ad limit
        today = date.today().isoformat()
        ad_count = await db.fetchval(
            """SELECT COUNT(*) FROM ad_watches
               WHERE user_id = $1 AND DATE(created_at) = $2""",
            user_id, today,
        )
        if ad_count >= settings.ADS_DAILY_LIMIT:
            return {"show": False, "reason": "daily_limit_reached", "ad_type": "none"}

        # Check cooldown
        last_watch = await db.fetchval(
            """SELECT created_at FROM ad_watches
               WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1""",
            user_id,
        )
        if last_watch:
            elapsed = (time.time() - last_watch.timestamp())
            if elapsed < settings.ADS_COOLDOWN_SECONDS:
                remaining = int(settings.ADS_COOLDOWN_SECONDS - elapsed)
                return {
                    "show": False,
                    "reason": "cooldown_active",
                    "ad_type": "none",
                    "cooldown_remaining_seconds": remaining,
                }

        return {
            "show": True,
            "reason": "eligible",
            "ad_type": "rewarded_video",
            "reward_credits": settings.ADS_CREDIT_REWARD,
        }

    async def record_ad_watched(self, user_id: str, ad_type: str = "rewarded_video") -> dict:
        """
        Record a completed ad watch and award credits.

        Returns:
          {"success": bool, "credits_awarded": int, "new_balance": int}
        """
        if not flags.ads_enabled:
            return {"success": False, "credits_awarded": 0, "reason": "ads_disabled"}

        # Verify eligibility (prevent client-side cheating)
        eligibility = await self.should_show_ad(user_id)
        if not eligibility["show"]:
            return {"success": False, "credits_awarded": 0, "reason": eligibility["reason"]}

        from db.connection import get_db
        db = await get_db()

        reward = settings.ADS_CREDIT_REWARD

        # Record ad watch
        await db.execute(
            """INSERT INTO ad_watches (user_id, ad_type, credits_awarded, created_at)
               VALUES ($1, $2, $3, NOW())""",
            user_id, ad_type, reward,
        )

        # Award credits
        await db.execute(
            "UPDATE users SET credits = credits + $1 WHERE id = $2",
            reward, user_id,
        )

        # Record transaction
        await db.execute(
            """INSERT INTO credit_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'ad_reward', 'Watched rewarded ad')""",
            user_id, reward,
        )

        # Get new balance
        new_balance = await db.fetchval(
            "SELECT credits FROM users WHERE id = $1", user_id
        )

        logger.info(
            "ad_reward_granted",
            user_id=user_id[:8],
            credits=reward,
            new_balance=new_balance,
        )

        return {
            "success": True,
            "credits_awarded": reward,
            "new_balance": new_balance or 0,
        }

    async def get_ad_config(self) -> dict:
        """Get current ad configuration (for frontend)."""
        return {
            "enabled": flags.ads_enabled,
            "credit_reward": settings.ADS_CREDIT_REWARD,
            "daily_limit": settings.ADS_DAILY_LIMIT,
            "cooldown_seconds": settings.ADS_COOLDOWN_SECONDS,
        }


# Singleton
ads_service = AdsService()
