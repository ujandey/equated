"""
DB — Pydantic Models

Data models used across the API layer.
These are Pydantic models for request/response validation,
NOT ORM models (we use raw asyncpg queries).
"""

from typing import Literal

from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4


# ── Solver Models ───────────────────────────────────

class SolveRequest(BaseModel):
    """Incoming solve request."""
    question: str = Field(..., min_length=1, max_length=10000)
    session_id: str | None = None
    image_base64: str | None = None
    input_type: str = "text"           # "text" | "image" | "latex"
    stream: bool = False               # Enable SSE streaming
    debug: bool = False


class SolutionStep(BaseModel):
    """A single step in a structured solution."""
    number: int
    title: str
    explanation: str
    equation: str | None = None
    # Legacy fields for backward compatibility
    step: int | None = None
    rule: str | None = None


class SolveResponse(BaseModel):
    """Structured solve response."""
    solve_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str | None = None
    problem_interpretation: str = ""
    concept_used: str = ""
    concept_explanation: str = ""
    subject_hint: str = ""
    steps: list[dict] = []
    final_answer: str = ""           # LaTeX only for structured responses
    quick_summary: str = ""
    answer_summary: str = ""         # One plain English sentence
    alternative_method: str | None = None
    common_mistakes: str | None = None
    model_used: str = ""
    parser_source: str | None = None
    parser_confidence: str | None = None
    verified: bool = False
    verification_confidence: str | None = None
    verification_status: Literal["verified", "unverified", "partial"] = "unverified"
    math_check_passed: bool = False
    math_engine_result: str | None = None
    confidence: float = 0.0
    cached: bool = False
    credits_remaining: int | None = None
    debug: dict | None = None


# ── Credit Models ──────────────────────────────────

class CreditBalance(BaseModel):
    """User's credit balance."""
    user_id: str
    credits: int
    tier: str                          # "free" | "paid"
    daily_solves_used: int
    daily_limit: int


class CreditPurchaseRequest(BaseModel):
    """Credit pack purchase request."""
    pack_id: str                       # "basic" | "standard" | "premium"
    payment_id: str                    # Razorpay payment ID
    order_id: str = ""
    signature: str = ""


# ── User Models ─────────────────────────────────────

class UserProfile(BaseModel):
    """User profile data."""
    id: str
    email: str
    name: str | None = None
    tier: str = "free"
    credits: int = 0
    created_at: datetime | None = None


# ── Chat Models ─────────────────────────────────────

class ChatMessage(BaseModel):
    """Single chat message."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: str = "user"
    content: str
    created_at: datetime | None = None


class ChatSession(BaseModel):
    """Chat session summary."""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


# ── Analytics Models ────────────────────────────────

class StreakData(BaseModel):
    """User activity streak."""
    current_streak: int
    longest_streak: int
    total_active_days: int


class SubjectBreakdown(BaseModel):
    """Solve count by subject."""
    subject: str
    count: int
    percentage: float
    avg_cost_usd: float


# ── Health Models ───────────────────────────────────

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "1.0.0"
    services: dict = {}


# ── Admin Models ────────────────────────────────────

class AdminCostReport(BaseModel):
    """Admin cost dashboard data."""
    date: str
    total_solves: int
    total_cost_usd: float
    avg_cost_per_solve: float
    cost_by_model: dict
    cache_hit_rate: float
    credits_sold: int


# ── Image Solve Models ──────────────────────────────

class QuestionOption(BaseModel):
    """A single question extracted from an image."""
    id: str
    text: str
    latex: str
    subject_hint: str


class MultiQuestionResponse(BaseModel):
    """Returned when an image contains more than one detectable question."""
    status: Literal["multi_question"] = "multi_question"
    questions: list[QuestionOption]
    image_type: str
    engine_used: str


# ── Ads Models ──────────────────────────────────────

class AdEligibility(BaseModel):
    """Ad eligibility response."""
    show: bool
    reason: str
    ad_type: str
    reward_credits: int = 0


class AdWatchResult(BaseModel):
    """Ad watch completion result."""
    success: bool
    credits_awarded: int
    new_balance: int = 0
