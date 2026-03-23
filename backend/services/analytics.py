"""
Services — Analytics Service

Event tracking and usage aggregation for user-facing analytics.
Tracks solve events, streaks, subject breakdowns, and weekly summaries.
"""

import structlog
from datetime import date, timedelta

logger = structlog.get_logger("equated.services.analytics")


class AnalyticsService:
    """
    Handles analytics event tracking and reporting.

    Tracks:
      - Solve events (subject, model, cost, cache status)
      - User streaks (consecutive days with activity)
      - Subject breakdowns
      - Weekly/monthly summaries
    """

    async def track_event(self, event_type: str, user_id: str, data: dict):
        """Log an analytics event."""
        from db.connection import get_db

        try:
            db = await get_db()
            await db.execute(
                """INSERT INTO analytics_events (event_type, user_id, data, created_at)
                   VALUES ($1, $2, $3, NOW())""",
                event_type, user_id, str(data),
            )
        except Exception as e:
            logger.error("analytics_track_failed", error=str(e), event_type=event_type)

    async def get_usage_stats(self, user_id: str) -> dict:
        """Get the user's overall usage statistics."""
        from db.connection import get_db
        db = await get_db()

        total_solves = await db.fetchval(
            "SELECT COUNT(*) FROM solves WHERE user_id = $1", user_id
        )
        top_subjects = await db.fetch(
            """SELECT subject, COUNT(*) as count FROM solves
               WHERE user_id = $1 GROUP BY subject ORDER BY count DESC LIMIT 5""",
            user_id,
        )

        return {
            "total_solves": total_solves or 0,
            "top_subjects": [dict(r) for r in top_subjects],
        }

    async def get_streak(self, user_id: str) -> dict:
        """
        Calculate the user's current activity streak.
        A streak is consecutive days with at least one solve.
        """
        from db.connection import get_db
        db = await get_db()

        # Get distinct dates with activity, ordered descending
        rows = await db.fetch(
            """SELECT DISTINCT DATE(created_at) as solve_date
               FROM solves WHERE user_id = $1
               ORDER BY solve_date DESC LIMIT 365""",
            user_id,
        )

        if not rows:
            return {"current_streak": 0, "longest_streak": 0, "total_active_days": 0}

        dates = [row["solve_date"] for row in rows]
        today = date.today()

        # Calculate current streak
        current_streak = 0
        check_date = today
        for d in dates:
            if d == check_date:
                current_streak += 1
                check_date -= timedelta(days=1)
            elif d == check_date - timedelta(days=1):
                # Allow gap of one day (yesterday counts)
                check_date = d
                current_streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        # Calculate longest streak
        longest_streak = 1
        current_run = 1
        for i in range(1, len(dates)):
            if dates[i - 1] - dates[i] == timedelta(days=1):
                current_run += 1
                longest_streak = max(longest_streak, current_run)
            else:
                current_run = 1

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak if dates else 0,
            "total_active_days": len(dates),
        }

    async def get_subject_breakdown(self, user_id: str) -> dict:
        """Get solve count breakdown by subject."""
        from db.connection import get_db
        db = await get_db()

        rows = await db.fetch(
            """SELECT COALESCE(subject, 'general') as subject,
                      COUNT(*) as count,
                      AVG(cost_usd) as avg_cost
               FROM solves WHERE user_id = $1
               GROUP BY subject ORDER BY count DESC""",
            user_id,
        )

        total = sum(r["count"] for r in rows)

        return {
            "total": total,
            "subjects": [
                {
                    "subject": r["subject"],
                    "count": r["count"],
                    "percentage": round(r["count"] / total * 100, 1) if total > 0 else 0,
                    "avg_cost_usd": round(float(r["avg_cost"] or 0), 6),
                }
                for r in rows
            ],
        }

    async def get_model_usage_summary(self, user_id: str) -> dict:
        """Get model usage breakdown for a user."""
        from db.connection import get_db
        db = await get_db()

        rows = await db.fetch(
            """SELECT model, COUNT(*) as calls,
                      SUM(cost_usd) as total_cost,
                      AVG(latency_ms) as avg_latency
               FROM model_usage WHERE user_id = $1
               GROUP BY model ORDER BY calls DESC""",
            user_id,
        )

        return {
            "models": [
                {
                    "model": r["model"],
                    "calls": r["calls"],
                    "total_cost_usd": round(float(r["total_cost"] or 0), 6),
                    "avg_latency_ms": round(float(r["avg_latency"] or 0), 2),
                }
                for r in rows
            ]
        }

    async def get_weekly_summary(self, user_id: str) -> dict:
        """Get a summary of the user's activity over the past 7 days."""
        from db.connection import get_db
        db = await get_db()

        rows = await db.fetch(
            """SELECT DATE(created_at) as day,
                      COUNT(*) as solves,
                      SUM(cost_usd) as cost
               FROM solves
               WHERE user_id = $1 AND created_at > NOW() - INTERVAL '7 days'
               GROUP BY DATE(created_at)
               ORDER BY day""",
            user_id,
        )

        return {
            "period": "7d",
            "days": [
                {
                    "date": r["day"].isoformat(),
                    "solves": r["solves"],
                    "cost_usd": round(float(r["cost"] or 0), 6),
                }
                for r in rows
            ],
            "total_solves": sum(r["solves"] for r in rows),
            "total_cost_usd": round(sum(float(r["cost"] or 0) for r in rows), 6),
        }

    async def get_cache_hit_rate(self) -> dict:
        """Get global cache hit rate statistics."""
        from cache.cache_metrics import cache_metrics
        return cache_metrics.get_summary()

    async def get_credit_usage(self, user_id: str) -> dict:
        """Get credit usage summary for a user."""
        from db.connection import get_db
        db = await get_db()

        # Total credits spent
        spent = await db.fetchval(
            """SELECT COALESCE(SUM(ABS(amount)), 0) FROM credit_transactions
               WHERE user_id = $1 AND type = 'deduction'""",
            user_id,
        )

        # Total credits purchased
        purchased = await db.fetchval(
            """SELECT COALESCE(SUM(amount), 0) FROM credit_transactions
               WHERE user_id = $1 AND type = 'purchase'""",
            user_id,
        )

        # Total credits from ads
        from_ads = await db.fetchval(
            """SELECT COALESCE(SUM(amount), 0) FROM credit_transactions
               WHERE user_id = $1 AND type = 'ad_reward'""",
            user_id,
        )

        return {
            "user_id": user_id,
            "credits_spent": spent,
            "credits_purchased": purchased,
            "credits_from_ads": from_ads,
        }

    async def get_ai_costs_summary(self) -> dict:
        """Get global AI cost summary (admin)."""
        from services.model_usage_tracker import model_usage_tracker
        return await model_usage_tracker.get_daily_costs()


# Singleton
analytics_service = AnalyticsService()
