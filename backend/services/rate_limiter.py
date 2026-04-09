"""
Services — Per-User Rate Limiter

Prevents abuse by enforcing:
  - Daily solve limits (free tier: 5-7/day)
  - Credit deduction for paid users
  - Cooldown periods after limit exceeded
"""

from datetime import date
from config.settings import settings


class UserRateLimiter:
    """
    Per-user rate limiting tied to the credit system.

    Checks:
      1. Free tier: count today's solves → allow if < daily limit
      2. Paid tier: check credit balance → deduct 1 credit per solve
      3. Exhausted: return block + remaining time / purchase prompt
    """

    async def check_and_deduct(self, user_id: str) -> dict:
        """
        Check if user can solve, and deduct credit if applicable.

        Returns:
          {"allowed": bool, "remaining": int, "tier": str, "message": str}
        """
        from db.connection import get_db
        db = await get_db()

        # Get user's credit info
        user = await db.fetchrow(
            "SELECT credits, tier FROM users WHERE id = $1", user_id
        )
        if not user:
            return {"allowed": False, "remaining": 0, "tier": "unknown", "message": "User not found"}

        tier = user["tier"] or "free"
        credits = user["credits"] or 0

        if tier == "free":
            return await self._check_free_tier(db, user_id)
        else:
            return await self._check_paid_tier(db, user_id, credits)

    async def check_limit(self, user_id: str) -> dict:
        """
        Check if user can solve WITHOUT deducting credits.
        """
        from db.connection import get_db
        db = await get_db()

        user = await db.fetchrow(
            "SELECT credits, tier FROM users WHERE id = $1", user_id
        )
        if not user:
            return {"allowed": False, "remaining": 0, "tier": "unknown", "message": "User not found"}

        tier = user["tier"] or "free"
        credits = user["credits"] or 0

        if tier == "free":
            return await self._check_free_tier(db, user_id)
        else:
            if credits <= 0:
                return {
                    "allowed": False,
                    "remaining": 0,
                    "tier": "paid",
                    "message": "No credits remaining. Purchase a credit pack.",
                }
            return {
                "allowed": True,
                "remaining": credits,
                "tier": "paid",
                "message": f"{credits} credits remaining.",
            }

    async def _check_free_tier(self, db, user_id: str) -> dict:
        """Check free tier daily limit."""
        today = date.today()
        row = await db.fetchrow(
            """SELECT COUNT(*) as solve_count FROM solves
               WHERE user_id = $1 AND DATE(created_at) = $2""",
            user_id, today,
        )
        solve_count = row["solve_count"] if row else 0
        daily_limit = settings.FREE_TIER_DAILY_SOLVES

        if solve_count >= daily_limit:
            return {
                "allowed": False,
                "remaining": 0,
                "tier": "free",
                "message": f"Daily limit reached ({daily_limit} solves). Purchase credits for more.",
            }

        return {
            "allowed": True,
            "remaining": daily_limit - solve_count - 1,
            "tier": "free",
            "message": f"{daily_limit - solve_count - 1} free solves remaining today.",
        }

    async def _check_paid_tier(self, db, user_id: str, credits: int) -> dict:
        """
        Check and atomically deduct from paid credits.
        
        Uses a WHERE clause to prevent race conditions where two concurrent
        requests both read the same balance and both deduct. Only deducts if
        credits > 0 at time of UPDATE.
        """
        if credits <= 0:
            return {
                "allowed": False,
                "remaining": 0,
                "tier": "paid",
                "message": "No credits remaining. Purchase a credit pack.",
            }

        # ATOMIC DEDUCTION: Only deduct if credits > 0 at update time
        # This prevents race conditions where multiple concurrent requests
        # all deduct from the same balance
        result = await db.execute(
            "UPDATE users SET credits = credits - 1 WHERE id = $1 AND credits > 0",
            user_id
        )

        # Check if the UPDATE actually affected a row
        # asyncpg returns a string like "UPDATE 1" or "UPDATE 0"
        rows_affected = int(result.split()[-1]) if result else 0

        if rows_affected == 0:
            # No rows updated: another request already depleted credits
            return {
                "allowed": False,
                "remaining": 0,
                "tier": "paid",
                "message": "No credits remaining. Purchase a credit pack.",
            }

        # Fetch the new credit balance
        user = await db.fetchrow(
            "SELECT credits FROM users WHERE id = $1", user_id
        )
        remaining = user["credits"] if user else 0

        # Log the transaction
        await db.execute(
            """INSERT INTO credit_transactions (user_id, amount, type, description)
               VALUES ($1, -1, 'deduction', 'Problem solve')""",
            user_id,
        )

        return {
            "allowed": True,
            "remaining": remaining,
            "tier": "paid",
            "message": f"{remaining} credits remaining.",
        }


# Singleton
user_rate_limiter = UserRateLimiter()
