"""
Services — Credits Service

Centralized credit management logic.
Handles balance queries, deductions, additions, and payment verification.
"""

import structlog
from datetime import date

from config.settings import settings
from core.exceptions import CreditError, NotFoundError

logger = structlog.get_logger("equated.services.credits")


CREDIT_PACKS = {
    "basic":    {"credits": 30,  "price_inr": 10,   "price_usd": 0.12},
    "standard": {"credits": 100, "price_inr": 25,   "price_usd": 0.30},
    "premium":  {"credits": 300, "price_inr": 50,   "price_usd": 0.60},
}

# Admin configurable credit pricing by model
MODEL_CREDIT_COSTS = {
    "gpt-4o": 5,
    "deepseek-reasoner": 4,
    "mistral-large-latest": 3,
    "gemini-2.0-pro": 3,
    "gpt-4o-mini": 1,
    "deepseek-chat": 1,
    "codestral-latest": 1,
    "gemini-2.0-flash": 1,
    "llama-3.3-70b-versatile": 0, # Free
}


class CreditService:
    """
    Manages the credit economy.

    Responsibilities:
      - Check balance (free tier daily limit or paid credits)
      - Deduct credits on solve
      - Add credits on purchase or ad completion
      - Verify Razorpay payments
      - Query transaction history
    """

    async def get_balance(self, user_id: str) -> dict:
        """Get user's current credit balance and usage stats."""
        from db.connection import get_db
        db = await get_db()

        user = await db.fetchrow(
            "SELECT credits, tier FROM users WHERE id = $1", user_id
        )
        if not user:
            raise NotFoundError("User")

        today = date.today()
        solves_row = await db.fetchrow(
            "SELECT COUNT(*) as cnt FROM solves WHERE user_id = $1 AND DATE(created_at) = $2",
            user_id, today,
        )

        return {
            "user_id": user_id,
            "credits": user["credits"] or 0,
            "tier": user["tier"] or "free",
            "daily_solves_used": solves_row["cnt"] if solves_row else 0,
            "daily_limit": settings.FREE_TIER_DAILY_SOLVES,
        }

    async def check_and_deduct(self, user_id: str, model_name: str = "gemini-2.0-flash") -> dict:
        """
        Check if user can solve, deduct credit if applicable based on model cost.
        Returns: {"allowed": bool, "remaining": int, "tier": str, "message": str}
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
        
        cost = MODEL_CREDIT_COSTS.get(model_name, 1)
        if cost == 0:
             return {
                "allowed": True, 
                "remaining": credits, 
                "tier": tier, 
                "message": "Free model used, no credits deducted."
            }

        if tier == "free":
            return await self._check_free_tier(db, user_id, cost)
        else:
            return await self._deduct_paid(db, user_id, credits, cost, model_name)

    async def _check_free_tier(self, db, user_id: str, cost: int) -> dict:
        """Check free tier daily limit."""
        today = date.today()
        row = await db.fetchrow(
            """SELECT COUNT(*) as cnt FROM solves
               WHERE user_id = $1 AND DATE(created_at) = $2""",
            user_id, today,
        )
        used = row["cnt"] if row else 0
        limit = settings.FREE_TIER_DAILY_SOLVES

        # Free tier users shouldn't use high-cost premium models
        if cost > 1:
            return {
                "allowed": False,
                "remaining": max(0, limit - used),
                "tier": "free",
                "message": "Premium models require a paid credit pack.",
            }

        if used >= limit:
            return {
                "allowed": False,
                "remaining": 0,
                "tier": "free",
                "message": f"Daily limit reached ({limit} solves). Purchase credits for more.",
            }

        return {
            "allowed": True,
            "remaining": limit - used - cost,
            "tier": "free",
            "message": f"{limit - used - cost} free solves remaining today.",
        }

    async def _deduct_paid(self, db, user_id: str, current_credits: int, cost: int, model_name: str) -> dict:
        """Check and deduct from paid credits using an atomic race-condition-safe query."""
        # Atomic check and deduct. Locks the row and aborts if credits < cost.
        result = await db.fetchrow(
            """UPDATE users 
               SET credits = credits - $1 
               WHERE id = $2 AND credits >= $1
               RETURNING credits""",
            cost, user_id
        )

        if not result:
            # Deduction failed because they don't have enough credits
            actual_credits = await db.fetchval("SELECT credits FROM users WHERE id = $1", user_id) or 0
            return {
                "allowed": False,
                "remaining": actual_credits,
                "tier": "paid",
                "message": f"Need {cost} credits for {model_name}, but you only have {actual_credits}. Purchase a credit pack.",
            }

        new_balance = result["credits"]

        await db.execute(
            """INSERT INTO credit_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'deduction', $3)""",
            user_id, -cost, f"Problem solve ({model_name})"
        )

        return {
            "allowed": True,
            "remaining": new_balance,
            "tier": "paid",
            "message": f"{new_balance} credits remaining (-{cost} for {model_name}).",
        }

    async def deduct_credits(self, user_id: str, cost: int, solve_id: str, model_name: str):
        """
        Atomically deduct credits after a successful solve.
        Raises CreditError if the user is out of credits.
        """
        from db.connection import get_db
        from core.exceptions import CreditError
        db = await get_db()
        
        user = await db.fetchrow("SELECT tier FROM users WHERE id = $1", user_id)
        if not user or user["tier"] == "free" or cost == 0:
            return  # Free tier users and free models do not deduct balance explicitly
            
        result = await db.fetchrow(
            """UPDATE users SET credits = credits - $1 
               WHERE id = $2 AND credits >= $1
               RETURNING credits""",
            cost, user_id
        )
        if not result:
            raise CreditError("Insufficient credits")
            
        await db.execute(
            """INSERT INTO credit_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'deduction', $3)""",
            user_id, -cost, f"Problem solve ({model_name})"
        )

    async def add_credits(self, user_id: str, amount: int, reason: str, payment_id: str = ""):
        """Add credits to a user's account."""
        from db.connection import get_db
        db = await get_db()

        # Idempotency check: prevent double-crediting for the same payment
        if payment_id:
            existing = await db.fetchrow(
                "SELECT id FROM credit_transactions WHERE payment_id = $1", payment_id
            )
            if existing:
                logger.warning("duplicate_payment_processed", user_id=user_id, payment_id=payment_id)
                return  # Skip silently to handle webhook & client race conditions gracefully

        await db.execute(
            "UPDATE users SET credits = credits + $1, tier = 'paid' WHERE id = $2",
            amount, user_id,
        )
        await db.execute(
            """INSERT INTO credit_transactions (user_id, amount, type, description, payment_id)
               VALUES ($1, $2, 'purchase', $3, $4)""",
            user_id, amount, reason, payment_id,
        )

        logger.info("credits_added", user_id=user_id[:8], amount=amount, reason=reason)

    async def create_razorpay_order(self, user_id: str, pack_id: str) -> dict:
        """
        Create a Razorpay order for a credit pack.
        Returns order details for the frontend checkout widget.
        """
        import httpx

        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise CreditError("Payment gateway not configured")

        if pack_id not in CREDIT_PACKS:
            raise CreditError(f"Invalid pack: {pack_id}")

        pack = CREDIT_PACKS[pack_id]
        amount_paise = pack["price_inr"] * 100  # Razorpay expects paise

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.razorpay.com/v1/orders",
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                json={
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": f"eq_{user_id[:8]}_{pack_id}",
                    "notes": {
                        "user_id": user_id,
                        "pack_id": pack_id,
                        "credits": pack["credits"],
                    },
                },
            )
            response.raise_for_status()
            order = response.json()

        logger.info(
            "razorpay_order_created",
            order_id=order["id"],
            user_id=user_id[:8],
            pack_id=pack_id,
            amount_paise=amount_paise,
        )

        return {
            "order_id": order["id"],
            "amount": amount_paise,
            "currency": "INR",
            "key_id": settings.RAZORPAY_KEY_ID,
            "pack_id": pack_id,
            "credits": pack["credits"],
        }

    async def verify_razorpay_payment(self, payment_id: str, order_id: str, signature: str) -> bool:
        """
        Verify a Razorpay payment signature.
        Returns True if payment is valid.
        """
        import hmac
        import hashlib

        if not settings.RAZORPAY_KEY_SECRET:
            logger.warning("razorpay_secret_not_configured")
            return False

        message = f"{order_id}|{payment_id}"
        expected = hmac.HMAC(
            settings.RAZORPAY_KEY_SECRET.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    async def get_transaction_history(self, user_id: str, limit: int = 20) -> list[dict]:
        """Get credit transaction history for a user."""
        from db.connection import get_db
        db = await get_db()

        rows = await db.fetch(
            """SELECT amount, type, description, payment_id, created_at
               FROM credit_transactions
               WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2""",
            user_id, limit,
        )
        return [dict(r) for r in rows]


# Singleton
credit_service = CreditService()
