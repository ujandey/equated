"""
Tests for services/diagnosis_engine.py

Pure unit tests — DB is mocked via AsyncMock.
No external API calls.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.diagnosis_engine import DiagnosisEngine, StudentProfile


# ── DB mock helpers ───────────────────────────────────────────────────────────

def _make_db(
    mastery_rows: list[dict] | None = None,
    event_rows: list[dict] | None = None,
    mistake_rows: list[dict] | None = None,
) -> AsyncMock:
    """Return a minimal asyncpg-compatible mock."""
    db = AsyncMock()

    mastery = mastery_rows or []
    events = event_rows or []
    mistakes = mistake_rows or []

    async def _fetch(query, *args):
        q = query.strip().lower()
        if "user_topic_mastery" in q:
            return [_row(r) for r in mastery]
        if "user_learning_events" in q:
            return [_row(r) for r in events]
        if "user_mistake_patterns" in q:
            return [_row(r) for r in mistakes]
        return []

    db.fetch = _fetch
    return db


def _row(d: dict) -> MagicMock:
    r = MagicMock()
    r.__getitem__ = lambda self, k: d[k]
    r.keys = lambda: d.keys()
    return r


# ── diagnose: strong / weak / unseen ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_strong_classification() -> None:
    engine = DiagnosisEngine()
    db = _make_db(mastery_rows=[
        {"topic": "linear_equations", "mastery_score": 0.85},
        {"topic": "quadratics", "mastery_score": 0.90},
    ])
    profile = await engine.diagnose("u1", "derivatives", db=db)
    assert "linear_equations" in profile.strong
    assert "quadratics" in profile.strong
    assert profile.weak == []


@pytest.mark.asyncio
async def test_weak_classification() -> None:
    engine = DiagnosisEngine()
    db = _make_db(mastery_rows=[
        {"topic": "limits", "mastery_score": 0.20},
        {"topic": "functions", "mastery_score": 0.30},
    ])
    profile = await engine.diagnose("u1", "derivatives", db=db)
    assert "limits" in profile.weak
    assert "functions" in profile.weak
    assert profile.strong == []


@pytest.mark.asyncio
async def test_unseen_from_concept_graph() -> None:
    engine = DiagnosisEngine()
    db = _make_db(mastery_rows=[
        {"topic": "arithmetic", "mastery_score": 0.8},
    ])

    from services.concept_graph import ConceptGraph
    cg = ConceptGraph()
    profile = await engine.diagnose("u1", "derivatives", db=db, concept_graph=cg)

    # Every node in the graph except "arithmetic" should be unseen.
    assert "arithmetic" not in profile.unseen
    assert len(profile.unseen) > 0
    assert "derivatives" in profile.unseen


@pytest.mark.asyncio
async def test_unseen_empty_when_no_concept_graph() -> None:
    engine = DiagnosisEngine()
    db = _make_db()
    profile = await engine.diagnose("u1", "derivatives", db=db, concept_graph=None)
    assert profile.unseen == []


# ── confusion_type inference ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_procedural_confusion_from_mistake_patterns() -> None:
    engine = DiagnosisEngine()
    db = _make_db(
        mastery_rows=[{"topic": "linear_equations", "mastery_score": 0.5}],
        mistake_rows=[
            {"mistake_code": "arithmetic_error", "frequency": 5},
            {"mistake_code": "sign_error", "frequency": 3},
        ],
    )
    profile = await engine.diagnose("u1", "linear_equations", db=db)
    assert profile.confusion_type == "procedural"


@pytest.mark.asyncio
async def test_conceptual_confusion_from_mistake_patterns() -> None:
    engine = DiagnosisEngine()
    db = _make_db(
        mastery_rows=[{"topic": "calculus", "mastery_score": 0.4}],
        mistake_rows=[
            {"mistake_code": "concept_confusion", "frequency": 4},
            {"mistake_code": "algebra_error", "frequency": 2},
        ],
    )
    profile = await engine.diagnose("u1", "derivatives", db=db)
    assert profile.confusion_type == "conceptual"


@pytest.mark.asyncio
async def test_unknown_confusion_when_no_history() -> None:
    engine = DiagnosisEngine()
    db = _make_db()
    profile = await engine.diagnose("u1", "integrals", db=db)
    assert profile.confusion_type == "unknown"


@pytest.mark.asyncio
async def test_procedural_wins_on_tie() -> None:
    engine = DiagnosisEngine()
    db = _make_db(
        mistake_rows=[
            {"mistake_code": "arithmetic_error", "frequency": 2},
            {"mistake_code": "concept_confusion", "frequency": 2},
        ],
    )
    profile = await engine.diagnose("u1", "algebra", db=db)
    # Equal scores → procedural wins (>=)
    assert profile.confusion_type == "procedural"


@pytest.mark.asyncio
async def test_confusion_inferred_from_event_detected_patterns() -> None:
    engine = DiagnosisEngine()
    patterns_json = json.dumps([{"mistake_code": "sign_error"}])
    db = _make_db(
        mastery_rows=[{"topic": "derivatives", "mastery_score": 0.4}],
        event_rows=[
            {"failure_reason": "wrong", "detected_patterns": patterns_json},
        ],
    )
    profile = await engine.diagnose("u1", "derivatives", db=db)
    assert profile.confusion_type == "procedural"


# ── confidence ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confidence_high_when_topic_mastery_known() -> None:
    engine = DiagnosisEngine()
    db = _make_db(mastery_rows=[
        {"topic": "derivatives", "mastery_score": 0.8},
    ])
    profile = await engine.diagnose("u1", "derivatives", db=db)
    assert profile.confidence > 0.7


@pytest.mark.asyncio
async def test_confidence_low_when_no_history() -> None:
    engine = DiagnosisEngine()
    db = _make_db()
    profile = await engine.diagnose("u1", "derivatives", db=db)
    assert profile.confidence == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_confidence_medium_when_other_topics_known() -> None:
    engine = DiagnosisEngine()
    db = _make_db(mastery_rows=[
        {"topic": "algebra", "mastery_score": 0.6},
    ])
    profile = await engine.diagnose("u1", "derivatives", db=db)
    # Should be between 0.2 and 0.85
    assert 0.2 < profile.confidence < 0.85


# ── StudentProfile dataclass ──────────────────────────────────────────────────

def test_student_profile_defaults() -> None:
    p = StudentProfile()
    assert p.strong == []
    assert p.weak == []
    assert p.unseen == []
    assert p.confusion_type == "unknown"
    assert p.confidence == 0.5


def test_student_profile_is_mutable() -> None:
    p = StudentProfile(strong=["a"], weak=["b"])
    p.strong.append("c")
    assert "c" in p.strong


# ── Private helpers ───────────────────────────────────────────────────────────

def test_compute_confidence_with_exact_match() -> None:
    engine = DiagnosisEngine()
    conf = engine._compute_confidence({"derivatives": 0.9}, "derivatives")
    assert conf > 0.7


def test_compute_confidence_no_history() -> None:
    engine = DiagnosisEngine()
    conf = engine._compute_confidence({}, "algebra")
    assert conf == pytest.approx(0.2)


def test_safe_json_handles_list() -> None:
    engine = DiagnosisEngine()
    assert engine._safe_json([{"a": 1}]) == [{"a": 1}]


def test_safe_json_handles_string() -> None:
    engine = DiagnosisEngine()
    assert engine._safe_json('[{"mistake_code": "sign_error"}]') == [
        {"mistake_code": "sign_error"}
    ]


def test_safe_json_handles_invalid_string() -> None:
    engine = DiagnosisEngine()
    assert engine._safe_json("not valid json {{{") == []
