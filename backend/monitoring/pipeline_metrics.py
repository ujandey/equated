"""
Monitoring — Pipeline Metrics

Prometheus counters and histograms specific to the solve/verification pipeline.
Tracks parser usage, confidence distributions, verification outcomes, and
math intent filtering.

Import and use these from routers:
    from monitoring.pipeline_metrics import pipeline_metrics
    pipeline_metrics.record_parse("heuristic")
    pipeline_metrics.record_confidence("high")
"""

from prometheus_client import Counter


# ── Parser Metrics ──────────────────────────────────
PARSER_USAGE = Counter(
    "equated_parser_usage_total",
    "Parser source used for problem solving",
    ["source"],  # heuristic | llm | heuristic_fallback | failed | skipped
)

# ── Confidence Metrics ──────────────────────────────
CONFIDENCE_DISTRIBUTION = Counter(
    "equated_confidence_total",
    "Overall confidence level of solutions",
    ["level"],  # high | medium | low
)

# ── Verification Metrics ────────────────────────────
VERIFICATION_RESULT = Counter(
    "equated_verification_result_total",
    "Verification outcomes",
    ["result"],  # passed | failed | skipped
)

VERIFICATION_METHOD = Counter(
    "equated_verification_method_total",
    "Verification method used",
    ["method"],  # symbolic | numeric | none
)

# ── Parse Failures ──────────────────────────────────
PARSE_FAILURES = Counter(
    "equated_parse_failure_total",
    "Number of parse failures",
    ["reason"],  # invalid_json | invalid_expression | validation_failed | no_intent
)

# ── Math Intent ─────────────────────────────────────
MATH_INTENT = Counter(
    "equated_math_intent_total",
    "Math intent detection results",
    ["is_math"],  # true | false
)


class PipelineMetricsCollector:
    """Convenience wrapper for recording pipeline metrics."""

    @staticmethod
    def record_parse(source: str):
        PARSER_USAGE.labels(source=source).inc()

    @staticmethod
    def record_confidence(level: str):
        CONFIDENCE_DISTRIBUTION.labels(level=level).inc()

    @staticmethod
    def record_verification(result: str, method: str = "none"):
        VERIFICATION_RESULT.labels(result=result).inc()
        VERIFICATION_METHOD.labels(method=method).inc()

    @staticmethod
    def record_parse_failure(reason: str):
        PARSE_FAILURES.labels(reason=reason).inc()

    @staticmethod
    def record_math_intent(is_math: bool):
        MATH_INTENT.labels(is_math=str(is_math).lower()).inc()


# Singleton
pipeline_metrics = PipelineMetricsCollector()
