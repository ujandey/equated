"""
Pedagogical Router

Decides how the tutor should teach based on the student's request and
their current learning signals.
"""

from __future__ import annotations

from typing import Any
import re


STRATEGY_SOCRATIC = "socratic"
STRATEGY_SCAFFOLDED = "scaffolded"
STRATEGY_WORKED_EXAMPLE = "worked_example"
STRATEGY_ANALOGY = "analogy"
STRATEGY_REMEDIAL = "remedial"

QUESTION_CONCEPTUAL = "conceptual"
QUESTION_PROCEDURAL = "procedural"
QUESTION_EXPLICIT_SOLUTION = "explicit_solution_request"
QUESTION_HOMEWORK_DUMP = "homework_dump"
QUESTION_HELP_SEEKING = "help_seeking"
QUESTION_UNKNOWN = "unknown"

DECISION_LOGIC_TABLE: list[dict[str, str]] = [
    {
        "priority": "1",
        "condition": "estimated mastery < 0.25",
        "strategy": STRATEGY_REMEDIAL,
        "reason": "Severe gap detected; teach prerequisite before solving.",
    },
    {
        "priority": "2",
        "condition": "explicit 'just solve' or answer-only request",
        "strategy": STRATEGY_WORKED_EXAMPLE,
        "reason": "Student explicitly requested a direct solution.",
    },
    {
        "priority": "3",
        "condition": "homework dump detected",
        "strategy": STRATEGY_WORKED_EXAMPLE,
        "reason": "Large pasted task is best handled with one representative worked path.",
    },
    {
        "priority": "4",
        "condition": "repeated mistakes / repeated failures / weak topic",
        "strategy": STRATEGY_SCAFFOLDED,
        "reason": "Student needs incremental support with checkpoints.",
    },
    {
        "priority": "5",
        "condition": "conceptual question",
        "strategy": STRATEGY_ANALOGY,
        "reason": "Intuition-first teaching helps conceptual understanding.",
    },
    {
        "priority": "6",
        "condition": "estimated mastery < 0.40",
        "strategy": STRATEGY_REMEDIAL,
        "reason": "Foundational understanding is still below threshold.",
    },
    {
        "priority": "7",
        "condition": "procedural multi-step question or user asks for steps",
        "strategy": STRATEGY_SCAFFOLDED,
        "reason": "Stepwise execution with checks fits procedural tasks.",
    },
    {
        "priority": "8",
        "condition": "default",
        "strategy": STRATEGY_SOCRATIC,
        "reason": "Use guided questioning when no stronger signal applies.",
    },
]


_CONCEPTUAL_RE = re.compile(
    r"\b(why|how does|what does .* mean|intuition|concept|understand|difference between|explain)\b",
    re.IGNORECASE,
)
_PROCEDURAL_RE = re.compile(
    r"\b(solve|calculate|compute|derive|evaluate|integrate|differentiate|find|step by step|steps)\b",
    re.IGNORECASE,
)
_DIRECT_SOLUTION_RE = re.compile(
    r"\b(just solve|solve it|give (?:me )?(?:the )?answer|answer only|only answer|final answer|do it for me|show full solution)\b",
    re.IGNORECASE,
)
_HELP_SEEKING_RE = re.compile(
    r"\b(help|hint|guide me|walk me through|i am stuck|stuck|check my work)\b",
    re.IGNORECASE,
)
_HOMEWORK_DUMP_RE = re.compile(
    r"\b(worksheet|assignment|homework|question \d+|q\d+|part [a-z]|section [a-z0-9]+)\b",
    re.IGNORECASE,
)
_LINE_ITEM_RE = re.compile(r"(?m)^\s*(?:\d+[\.\)]|[a-zA-Z][\.\)])\s+")
_MATH_TOKEN_RE = re.compile(r"(?:=|[\+\-\*/^]|\\frac|\\sqrt|\d)")
_TOPIC_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

_STRATEGY_PROMPTS: dict[str, str] = {
    STRATEGY_SOCRATIC: (
        "Pedagogical strategy: socratic. Lead with 1-2 targeted guiding questions before presenting conclusions. "
        "Nudge the student to infer the next step instead of immediately revealing the full answer."
    ),
    STRATEGY_SCAFFOLDED: (
        "Pedagogical strategy: scaffolded. Break the solution into small ordered steps. "
        "After each major step, add a quick comprehension check or checkpoint before moving on."
    ),
    STRATEGY_WORKED_EXAMPLE: (
        "Pedagogical strategy: worked_example. Provide a complete worked solution, but keep the reasoning explicit. "
        "Model the full path clearly enough that the student can imitate it on a similar problem."
    ),
    STRATEGY_ANALOGY: (
        "Pedagogical strategy: analogy. Start with an intuitive analogy or concrete mental model, then map it back "
        "to the formal concept and answer the student's question."
    ),
    STRATEGY_REMEDIAL: (
        "Pedagogical strategy: remedial. Identify the missing prerequisite, teach that prerequisite briefly first, "
        "then reconnect it to the original question with a simpler entry point."
    ),
}


def classify_question_type(query: str) -> str:
    """Classify the student's request style for pedagogical routing."""
    text = _normalize_query(query)
    if not text:
        return QUESTION_UNKNOWN
    if detect_homework_dump(text):
        return QUESTION_HOMEWORK_DUMP
    if _DIRECT_SOLUTION_RE.search(text):
        return QUESTION_EXPLICIT_SOLUTION
    if _CONCEPTUAL_RE.search(text):
        return QUESTION_CONCEPTUAL
    if _HELP_SEEKING_RE.search(text):
        return QUESTION_HELP_SEEKING
    if _PROCEDURAL_RE.search(text):
        return QUESTION_PROCEDURAL
    return QUESTION_UNKNOWN


def detect_homework_dump(query: str) -> bool:
    """Detect pasted multi-part assignments or answer-seeking dumps."""
    text = _normalize_query(query)
    if not text:
        return False

    numbered_items = len(_LINE_ITEM_RE.findall(text))
    newline_count = text.count("\n")
    math_tokens = len(_MATH_TOKEN_RE.findall(text))
    word_count = len(text.split())

    if _HOMEWORK_DUMP_RE.search(text) and (numbered_items >= 2 or newline_count >= 3):
        return True
    if numbered_items >= 3 and math_tokens >= 6:
        return True
    if newline_count >= 5 and word_count >= 45:
        return True
    if word_count >= 120 and math_tokens >= 10:
        return True
    return False


def route(query: str, student_state: dict[str, Any] | None) -> dict[str, Any]:
    """
    Return a teaching strategy decision.

    Output contract:
    {
        "strategy": str,
        "reason": str,
        "confidence": float,
    }
    """
    normalized_query = _normalize_query(query)
    question_type = classify_question_type(normalized_query)
    homework_dump = detect_homework_dump(normalized_query)
    mastery = _estimate_mastery(normalized_query, student_state)
    repeated_mistakes = _has_repeated_mistakes(student_state)

    if mastery < 0.25:
        return _decision(
            STRATEGY_REMEDIAL,
            f"Estimated mastery is {mastery:.2f}, which indicates a prerequisite gap.",
            0.93,
        )

    if question_type == QUESTION_EXPLICIT_SOLUTION:
        return _decision(
            STRATEGY_WORKED_EXAMPLE,
            "The student explicitly asked for a direct solve/full answer.",
            0.95,
        )

    if question_type == QUESTION_HOMEWORK_DUMP or homework_dump:
        return _decision(
            STRATEGY_WORKED_EXAMPLE,
            "The query looks like a pasted multi-part assignment, so a representative worked example is the clearest entry point.",
            0.88,
        )

    if repeated_mistakes:
        return _decision(
            STRATEGY_SCAFFOLDED,
            "Student history shows repeated mistakes or repeated failures, so stepwise support with checks is safer.",
            0.89,
        )

    if question_type == QUESTION_CONCEPTUAL:
        return _decision(
            STRATEGY_ANALOGY,
            "The query is conceptual, so intuition-first explanation is the best fit.",
            0.86,
        )

    if mastery < 0.40:
        return _decision(
            STRATEGY_REMEDIAL,
            f"Estimated mastery is {mastery:.2f}, below the remedial threshold of 0.40.",
            0.84,
        )

    if question_type in {QUESTION_PROCEDURAL, QUESTION_HELP_SEEKING}:
        return _decision(
            STRATEGY_SCAFFOLDED,
            "The student is asking for procedural help, which maps best to incremental scaffolding.",
            0.8,
        )

    return _decision(
        STRATEGY_SOCRATIC,
        "No stronger remediation or direct-answer signal was detected, so guided questioning is the default.",
        0.68,
    )


def build_strategy_system_prompt(decision: dict[str, Any]) -> str:
    """Convert a routing decision into a system instruction for the chat pipeline."""
    strategy = str(decision.get("strategy") or STRATEGY_SOCRATIC)
    base_prompt = _STRATEGY_PROMPTS.get(strategy, _STRATEGY_PROMPTS[STRATEGY_SOCRATIC])
    reason = str(decision.get("reason") or "").strip()
    confidence = _clamp_float(decision.get("confidence"), default=0.5)
    return f"{base_prompt} Routing reason: {reason} Confidence: {confidence:.2f}."


def _estimate_mastery(query: str, student_state: dict[str, Any] | None) -> float:
    if not student_state:
        return 0.5

    topics = student_state.get("topics") or []
    weak_areas = student_state.get("weak_areas") or []
    interaction_signals = student_state.get("interaction_signals") or {}

    matched_scores: list[float] = []
    for topic in topics:
        topic_name = str(topic.get("topic") or "")
        score = topic.get("mastery")
        if _topic_matches_query(topic_name, query):
            matched_scores.append(_clamp_float(score, default=0.5))

    if matched_scores:
        return min(matched_scores)

    weak_scores = [_clamp_float(area.get("mastery"), default=0.35) for area in weak_areas]
    if weak_scores:
        return min(weak_scores)

    total_events = _safe_int(interaction_signals.get("total_events"))
    successes = _safe_int(interaction_signals.get("successes"))
    failures = _safe_int(interaction_signals.get("failures"))
    if total_events > 0:
        empirical = successes / max(successes + failures, 1)
        return round((0.5 * 0.4) + (empirical * 0.6), 4)

    return 0.5


def _has_repeated_mistakes(student_state: dict[str, Any] | None) -> bool:
    if not student_state:
        return False

    for area in student_state.get("weak_areas") or []:
        if _safe_int(area.get("consecutive_failures")) >= 2:
            return True
        if _safe_int(area.get("failures")) >= 3:
            return True

    for pattern in student_state.get("mistake_patterns") or []:
        if _safe_int(pattern.get("frequency")) >= 2:
            return True

    interaction_signals = student_state.get("interaction_signals") or {}
    if _safe_int(interaction_signals.get("retries")) >= 3:
        return True
    if _safe_int(interaction_signals.get("failures")) >= 3:
        return True
    return False


def _topic_matches_query(topic: str, query: str) -> bool:
    topic_tokens = set(_TOPIC_TOKEN_RE.findall((topic or "").lower()))
    query_tokens = set(_TOPIC_TOKEN_RE.findall((query or "").lower()))
    if not topic_tokens or not query_tokens:
        return False
    overlap = topic_tokens & query_tokens
    return len(overlap) >= min(2, len(topic_tokens))


def _decision(strategy: str, reason: str, confidence: float) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "reason": reason,
        "confidence": round(max(0.0, min(confidence, 1.0)), 2),
    }


def _normalize_query(query: str | None) -> str:
    return (query or "").strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clamp_float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default

