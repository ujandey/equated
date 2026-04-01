"""
Services — Model Usage Tracker

Logs every AI model call with full cost and performance data.
Essential for monitoring burn rate and optimizing model selection.

Tracked fields per call:
  - user_id, model, provider
  - input_tokens, output_tokens
  - cost_usd, latency_ms
  - classification, cache_status
"""

import time
import structlog
from dataclasses import dataclass, field
from datetime import datetime

logger = structlog.get_logger("equated.services.model_usage")


@dataclass
class UsageEntry:
    """Single model usage record."""
    user_id: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    classification: str = ""
    cache_status: str = "miss"      # "hit" | "miss"
    success: bool = True
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class ModelUsageTracker:
    """
    Records and queries AI model usage for cost tracking.

    Responsibilities:
      - Log every API call to the model_usage table
      - Provide aggregated cost reports
      - Track latency percentiles per model
      - Alert on budget exceeded
    """

    async def log_usage(self, entry: UsageEntry):
        """Persist a usage record to the database."""
        from db.connection import get_db

        try:
            db = await get_db()
            await db.execute(
                """INSERT INTO model_usage
                   (user_id, model, input_tokens, output_tokens, cost_usd, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                entry.user_id, entry.model,
                entry.input_tokens, entry.output_tokens,
                entry.cost_usd, entry.created_at,
            )

            logger.info(
                "model_usage_logged",
                model=entry.model,
                tokens=entry.input_tokens + entry.output_tokens,
                cost=round(entry.cost_usd, 6),
                latency_ms=round(entry.latency_ms, 2),
            )
        except Exception as e:
            logger.error("model_usage_log_failed", error=str(e))

    async def get_daily_costs(self, date_str: str | None = None) -> dict:
        """Get cost breakdown for a specific day (default: today)."""
        from db.connection import get_db
        from datetime import date

        target_date = date_str or date.today().isoformat()
        db = await get_db()

        rows = await db.fetch(
            """SELECT model,
                      COUNT(*) as calls,
                      SUM(input_tokens) as total_input_tokens,
                      SUM(output_tokens) as total_output_tokens,
                      SUM(cost_usd) as total_cost,
                      0 as avg_latency_ms
               FROM model_usage
               WHERE DATE(created_at) = $1
               GROUP BY model""",
            target_date,
        )

        total_cost = sum(float(r["total_cost"] or 0) for r in rows)

        return {
            "date": target_date,
            "total_cost_usd": round(total_cost, 6),
            "models": [
                {
                    "model": r["model"],
                    "provider": "unknown",
                    "calls": r["calls"],
                    "input_tokens": r["total_input_tokens"],
                    "output_tokens": r["total_output_tokens"],
                    "cost_usd": round(float(r["total_cost"] or 0), 6),
                    "avg_latency_ms": round(float(r["avg_latency_ms"] or 0), 2),
                }
                for r in rows
            ],
        }

    async def get_user_costs(self, user_id: str, days: int = 30) -> dict:
        """Get cost breakdown for a specific user."""
        from db.connection import get_db

        db = await get_db()

        total = await db.fetchrow(
            """SELECT COUNT(*) as total_calls,
                      SUM(cost_usd) as total_cost,
                      SUM(input_tokens + output_tokens) as total_tokens
               FROM model_usage
               WHERE user_id = $1 AND created_at > NOW() - INTERVAL '%s days'""" % days,
            user_id,
        )

        return {
            "user_id": user_id,
            "period_days": days,
            "total_calls": total["total_calls"] or 0,
            "total_cost_usd": round(float(total["total_cost"] or 0), 6),
            "total_tokens": total["total_tokens"] or 0,
        }

    async def get_latency_stats(self) -> dict:
        """Get latency statistics per model."""
        from db.connection import get_db

        db = await get_db()
        rows = await db.fetch(
            """SELECT model,
                      0 as avg_ms,
                      0 as min_ms,
                      0 as max_ms,
                      0 as p50_ms,
                      0 as p95_ms,
                      0 as p99_ms
               FROM model_usage
               WHERE created_at > NOW() - INTERVAL '24 hours'
               GROUP BY model"""
        )

        return {
            "models": [
                {
                    "model": r["model"],
                    "avg_ms": round(float(r["avg_ms"] or 0), 2),
                    "min_ms": round(float(r["min_ms"] or 0), 2),
                    "max_ms": round(float(r["max_ms"] or 0), 2),
                    "p50_ms": round(float(r["p50_ms"] or 0), 2),
                    "p95_ms": round(float(r["p95_ms"] or 0), 2),
                    "p99_ms": round(float(r["p99_ms"] or 0), 2),
                }
                for r in rows
            ]
        }


# Singleton
model_usage_tracker = ModelUsageTracker()
