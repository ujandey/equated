"""
Cache — Metrics Collector

Tracks cache performance for the admin dashboard:
  - Hit/miss rates (Redis + vector)
  - Latency per lookup
  - Cost savings estimate
"""

from dataclasses import dataclass, field
from collections import defaultdict
from datetime import date


@dataclass
class CacheMetrics:
    """Aggregated cache performance metrics."""
    redis_hits: int = 0
    redis_misses: int = 0
    vector_hits: int = 0
    vector_misses: int = 0
    total_lookups: int = 0
    avg_lookup_ms: float = 0.0

    @property
    def total_hits(self) -> int:
        return self.redis_hits + self.vector_hits

    @property
    def hit_rate(self) -> float:
        if self.total_lookups == 0:
            return 0.0
        return self.total_hits / self.total_lookups

    @property
    def estimated_savings_usd(self) -> float:
        """Estimated cost savings based on avoided API calls."""
        avg_cost_per_call = 0.001
        return self.total_hits * avg_cost_per_call


class CacheMetricsCollector:
    """Collects and reports cache performance metrics."""

    def __init__(self):
        self._daily_metrics: dict[str, CacheMetrics] = defaultdict(CacheMetrics)

    def record_redis_hit(self):
        today = self._today()
        self._daily_metrics[today].redis_hits += 1
        self._daily_metrics[today].total_lookups += 1

    def record_redis_miss(self):
        today = self._today()
        self._daily_metrics[today].redis_misses += 1

    def record_vector_hit(self):
        today = self._today()
        self._daily_metrics[today].vector_hits += 1
        self._daily_metrics[today].total_lookups += 1

    def record_vector_miss(self):
        today = self._today()
        self._daily_metrics[today].vector_misses += 1
        self._daily_metrics[today].total_lookups += 1

    def get_today(self) -> CacheMetrics:
        return self._daily_metrics[self._today()]

    def get_summary(self) -> dict:
        metrics = self.get_today()
        return {
            "date": self._today(),
            "total_lookups": metrics.total_lookups,
            "total_hits": metrics.total_hits,
            "hit_rate_pct": round(metrics.hit_rate * 100, 1),
            "redis_hits": metrics.redis_hits,
            "vector_hits": metrics.vector_hits,
            "estimated_savings_usd": round(metrics.estimated_savings_usd, 4),
        }

    def _today(self) -> str:
        return date.today().isoformat()


# Singleton
cache_metrics = CacheMetricsCollector()
