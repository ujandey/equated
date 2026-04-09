"""
Core — Inter-Phase Contracts

Frozen dataclasses that define strict boundaries between defense system phases.
No phase may reinterpret or mutate these structures after creation.

Rules:
  - All contracts are frozen=True (immutable after creation)
  - Adding a field = bump CONTRACT_VERSION
  - Removing/renaming a field = major version bump
  - Downstream phases wrap contracts in their own types if they need extensions
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class ASTAnalysis:
    """
    Phase 1 → Phase 2 contract.

    Produced by: services.ast_guard.ASTGuard.validate()
    Consumed by: services.compute_budget (Phase 2), services.weighted_queue (Phase 2)

    Fields are intentionally flat and primitive-typed for serialization safety.
    """

    safe: bool
    category: str                   # "light" | "heavy" | "rejected"
    category_weight: int            # 1 (light) or 5 (heavy); 0 if rejected
    violations: tuple[str, ...]     # Hard limit violations → reject
    warnings: tuple[str, ...]       # Margin breaches → classify heavy
    operator_count: int
    exponent_depth: int
    expression_depth: int
    estimated_expansion: int        # Cumulative expansion factor across all Pow nodes


@dataclass(frozen=True)
class SandboxResult:
    """
    Phase 1 → Phase 2 contract.

    Produced by: services.sympy_sandbox.SympySandbox.execute_guarded()
    Consumed by: services.compute_budget (Phase 2), cache (Phase 3)

    compute_seconds is MEASURED runtime — the billing authority.
    Pre-estimation may only be used for admission hints, never for billing.
    """

    success: bool
    result_text: str
    latex_result: str
    steps: tuple[str, ...]
    error: str | None
    compute_seconds: float          # Measured wall-clock — billing authority
    node_count: int
    peak_memory_kb: int
    killed: bool
    kill_reason: str | None         # "timeout" | "memory" | "nodes" | "protocol_violation"


@dataclass(frozen=True)
class Settlement:
    """
    Phase 2 → Phase 3 contract.

    Produced by: services.compute_budget.ComputeBudgetManager.settle()
    Consumed by: cache eviction (Phase 3), analytics (Phase 3)

    final_cost = max(compute_cost, model_cost, token_cost)
    This is multi-dimensional billing — not just compute-seconds.
    """

    reservation_id: str
    user_id: str
    reserved_credits: int
    actual_compute_cost: int
    actual_model_cost: int
    actual_token_cost: int
    final_cost: int                 # max(compute, model, token)
    refunded_credits: int
    compute_seconds: float
    model_name: str
    billing_basis: str              # "compute" | "model" | "tokens"
