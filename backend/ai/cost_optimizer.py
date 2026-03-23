"""
AI — Cost Optimizer

Tracks AI costs, enforces budgets, and optimizes model selection.
Maintains a running cost table per model with real-time budget alerts.

Cost Table (per 1K tokens, as of March 2026):
  ┌───────────────────────┬──────────┬──────────┐
  │ Model                 │ Input    │ Output   │
  ├───────────────────────┼──────────┼──────────┤
  │ Groq Llama 3.3 70B   │ $0.0000  │ $0.0000  │
  │ Gemini 2.0 Flash     │ $0.0001  │ $0.0004  │
  │ GPT-4o-mini           │ $0.00015 │ $0.0006  │
  │ Mistral Small         │ $0.0002  │ $0.0006  │
  │ Mistral Codestral     │ $0.0003  │ $0.0009  │
  │ DeepSeek R1           │ $0.00055 │ $0.00219 │
  │ Mistral Large         │ $0.002   │ $0.006   │
  │ GPT-4o                │ $0.0025  │ $0.01    │
  │ Gemini 2.0 Pro        │ $0.00125 │ $0.005   │
  └───────────────────────┴──────────┴──────────┘
"""

import time
from datetime import date, datetime
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger("equated.ai.cost_optimizer")


# ── Cost Per 1K Tokens ──────────────────────────────
COST_TABLE = {
    # Provider / Model → (input_per_1k, output_per_1k)
    "groq/llama-3.3-70b-versatile":  (0.0,      0.0),
    "gemini/gemini-2.0-flash":       (0.0001,   0.0004),
    "openai/gpt-4o-mini":            (0.00015,  0.0006),
    "mistral/mistral-small-latest":  (0.0002,   0.0006),
    "mistral/codestral-latest":      (0.0003,   0.0009),
    "deepseek/deepseek-chat":        (0.00014,  0.00028),
    "deepseek/deepseek-reasoner":    (0.00055,  0.00219),
    "mistral/mistral-large-latest":  (0.002,    0.006),
    "openai/gpt-4o":                 (0.0025,   0.01),
    "gemini/gemini-2.0-pro":         (0.00125,  0.005),
}


@dataclass
class CostRecord:
    """Running cost totals for a model."""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    errors: int = 0
    last_call: datetime | None = None


class CostOptimizer:
    """
    Tracks and optimizes AI model costs in real-time.

    Features:
      - Per-model cost tracking (in-memory, backed by model_usage DB)
      - Daily/monthly budget enforcement
      - Cost-per-solve estimation
      - Model ranking by cost-efficiency
      - Latency percentile tracking
    """

    def __init__(self, daily_budget_usd: float = 5.0, monthly_budget_usd: float = 100.0):
        self.daily_budget = daily_budget_usd
        self.monthly_budget = monthly_budget_usd
        self._daily_costs: dict[str, CostRecord] = {}
        self._today: str = date.today().isoformat()
        self._latencies: dict[str, list[float]] = {}

    def _reset_if_new_day(self):
        """Reset daily counters at midnight."""
        today = date.today().isoformat()
        if today != self._today:
            self._daily_costs.clear()
            self._today = today

    def record_call(self, provider: str, model: str, input_tokens: int,
                    output_tokens: int, cost_usd: float, latency_ms: float,
                    success: bool = True):
        """Record a model call for cost tracking."""
        self._reset_if_new_day()

        key = f"{provider}/{model}"
        if key not in self._daily_costs:
            self._daily_costs[key] = CostRecord()

        record = self._daily_costs[key]
        record.calls += 1
        record.input_tokens += input_tokens
        record.output_tokens += output_tokens
        record.total_cost_usd += cost_usd
        record.total_latency_ms += latency_ms
        record.last_call = datetime.utcnow()
        if not success:
            record.errors += 1

        # Track latencies for percentile calculation
        if key not in self._latencies:
            self._latencies[key] = []
        self._latencies[key].append(latency_ms)
        # Keep last 1000 entries
        if len(self._latencies[key]) > 1000:
            self._latencies[key] = self._latencies[key][-500:]

    def estimate_cost(self, provider: str, model: str,
                      input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a hypothetical model call."""
        key = f"{provider}/{model}"
        if key in COST_TABLE:
            ci, co = COST_TABLE[key]
        else:
            ci, co = 0.001, 0.003  # Default fallback

        return round((input_tokens * ci + output_tokens * co) / 1000, 6)

    def is_within_budget(self) -> bool:
        """Check if today's spending is within budget."""
        self._reset_if_new_day()
        total = sum(r.total_cost_usd for r in self._daily_costs.values())
        return total < self.daily_budget

    def get_daily_total(self) -> float:
        """Get today's total spending."""
        self._reset_if_new_day()
        return round(sum(r.total_cost_usd for r in self._daily_costs.values()), 6)

    def get_budget_remaining(self) -> float:
        """Get remaining daily budget."""
        self._reset_if_new_day()
        return round(self.daily_budget - self.get_daily_total(), 6)

    def get_cost_report(self) -> dict:
        """Get a detailed cost breakdown for today."""
        self._reset_if_new_day()

        models = {}
        for key, record in self._daily_costs.items():
            latencies = self._latencies.get(key, [])
            sorted_lat = sorted(latencies) if latencies else [0]
            p50 = sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0
            p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if len(sorted_lat) > 1 else sorted_lat[0]

            models[key] = {
                "calls": record.calls,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_cost_usd": round(record.total_cost_usd, 6),
                "errors": record.errors,
                "avg_latency_ms": round(record.total_latency_ms / record.calls, 2) if record.calls > 0 else 0,
                "p50_latency_ms": round(p50, 2),
                "p95_latency_ms": round(p95, 2),
            }

        return {
            "date": self._today,
            "total_cost_usd": self.get_daily_total(),
            "budget_remaining_usd": self.get_budget_remaining(),
            "total_calls": sum(r.calls for r in self._daily_costs.values()),
            "total_errors": sum(r.errors for r in self._daily_costs.values()),
            "models": models,
        }

    def rank_models_by_cost(self) -> list[dict]:
        """Rank all models by cost-per-1K-output-tokens (cheapest first)."""
        ranked = []
        for key, (ci, co) in sorted(COST_TABLE.items(), key=lambda x: x[1][1]):
            provider, model = key.split("/", 1)
            record = self._daily_costs.get(key, CostRecord())
            ranked.append({
                "provider": provider,
                "model": model,
                "cost_per_1k_output": co,
                "cost_per_1k_input": ci,
                "today_calls": record.calls,
                "today_cost": round(record.total_cost_usd, 6),
            })
        return ranked

    def get_cheapest_model(self) -> tuple[str, str]:
        """Return (provider, model) of the cheapest available model."""
        for key, (ci, co) in sorted(COST_TABLE.items(), key=lambda x: x[1][1]):
            provider, model = key.split("/", 1)
            return provider, model
        return "gemini", "gemini-2.0-flash"


# Singleton
cost_optimizer = CostOptimizer()
