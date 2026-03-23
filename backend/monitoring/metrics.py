"""
Monitoring — Prometheus Metrics

Exposes application metrics for Prometheus scraping:
  - Request count/latency
  - Model call count/latency
  - Cache hit/miss rates
  - Active connections
"""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response


# ── Counters ────────────────────────────────────────
REQUEST_COUNT = Counter(
    "equated_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

MODEL_CALLS = Counter(
    "equated_model_calls_total",
    "Total AI model API calls",
    ["provider", "model"],
)

CACHE_LOOKUPS = Counter(
    "equated_cache_lookups_total",
    "Total cache lookups",
    ["tier", "result"],  # tier: redis/vector, result: hit/miss
)

SOLVES_TOTAL = Counter(
    "equated_solves_total",
    "Total problems solved",
    ["source"],  # source: cache/ai
)


# ── Histograms ──────────────────────────────────────
REQUEST_LATENCY = Histogram(
    "equated_request_duration_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

MODEL_LATENCY = Histogram(
    "equated_model_call_duration_seconds",
    "AI model call latency",
    ["provider"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)


# ── Gauges ──────────────────────────────────────────
ACTIVE_CONNECTIONS = Gauge(
    "equated_active_connections",
    "Number of active connections",
)

DAILY_COST_USD = Gauge(
    "equated_daily_cost_usd",
    "Today's total AI API cost in USD",
)


def init_metrics():
    """Initialize metrics (called on app startup)."""
    pass  # Prometheus client auto-registers metrics


def metrics_endpoint() -> Response:
    """Generate Prometheus metrics response."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
