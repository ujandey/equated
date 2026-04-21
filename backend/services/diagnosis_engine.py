"""
Services — Diagnosis Engine

Reads user history from the database and produces a StudentProfile that
classifies which topics are strong, weak, or unseen, and infers whether the
student's primary confusion pattern is procedural or conceptual.

No external AI API calls — pure algorithmic analysis of stored records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    from services.concept_graph import ConceptGraph

logger = structlog.get_logger("equated.services.diagnosis_engine")

# Mistake codes that signal procedural errors (right method, bad computation).
_PROCEDURAL_CODES: frozenset[str] = frozenset(
    {"arithmetic_error", "sign_error", "unit_error"}
)
# Mistake codes that signal conceptual errors (wrong method or approach).
_CONCEPTUAL_CODES: frozenset[str] = frozenset(
    {"concept_confusion", "algebra_error"}
)


@dataclass
class StudentProfile:
    """
    Snapshot of a student's knowledge state relative to a target topic.

    Attributes
    ----------
    strong:
        Topics where mastery_score > 0.75 — skip detailed explanation.
    weak:
        Topics where mastery_score < 0.40 — slow down and re-teach.
    unseen:
        Topics present in the concept graph but never attempted.
    confusion_type:
        Algorithmic classification of the dominant error pattern.
    confidence:
        Confidence in this diagnosis (0–1), higher when we have rich history.
    """

    strong: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    unseen: list[str] = field(default_factory=list)
    confusion_type: Literal["procedural", "conceptual", "unknown"] = "unknown"
    confidence: float = 0.5


class DiagnosisEngine:
    """
    Produces a StudentProfile from asyncpg DB records.

    The diagnosis covers:
    1. Mastery classification: strong / weak / unseen per concept graph.
    2. Confusion type: scans the last N learning events and all mistake
       patterns for the topic + its prerequisites.
    """

    STRONG_THRESHOLD: float = 0.75
    WEAK_THRESHOLD: float = 0.40
    RECENT_EVENTS: int = 5

    async def diagnose(
        self,
        user_id: str,
        topic: str,
        db: Any = None,
        concept_graph: "ConceptGraph | None" = None,
    ) -> StudentProfile:
        """
        Build a StudentProfile for (*user_id*, *topic*).

        Parameters
        ----------
        user_id:
            UUID of the student.
        topic:
            The concept currently being taught (should match a concept graph node id
            or a DB topic string).
        db:
            asyncpg connection / pool.  Calls get_db() internally when None.
        concept_graph:
            When provided, *unseen* will contain graph nodes not yet attempted.
        """
        if db is None:
            from db.connection import get_db
            db = await get_db()

        mastery_rows = await db.fetch(
            """
            SELECT topic, mastery_score
            FROM user_topic_mastery
            WHERE user_id = $1
            """,
            user_id,
        )
        mastery_map: dict[str, float] = {
            row["topic"]: float(row["mastery_score"]) for row in mastery_rows
        }

        strong = [t for t, s in mastery_map.items() if s > self.STRONG_THRESHOLD]
        weak = [t for t, s in mastery_map.items() if s < self.WEAK_THRESHOLD]

        if concept_graph is not None:
            seen_topics = set(mastery_map.keys())
            unseen = sorted(
                t for t in concept_graph.nodes if t not in seen_topics
            )
        else:
            unseen = []

        # Collect related topics (target + its prerequisites) for event/pattern lookup.
        related_topics: list[str] = [topic]
        if concept_graph is not None:
            related_topics += concept_graph.get_prerequisites(topic)

        event_rows = await db.fetch(
            """
            SELECT failure_reason, detected_patterns
            FROM user_learning_events
            WHERE user_id = $1 AND topic = ANY($2::text[])
            ORDER BY created_at DESC
            LIMIT $3
            """,
            user_id,
            related_topics,
            self.RECENT_EVENTS,
        )

        mistake_rows = await db.fetch(
            """
            SELECT mistake_code, frequency
            FROM user_mistake_patterns
            WHERE user_id = $1 AND topic = ANY($2::text[])
            ORDER BY frequency DESC
            """,
            user_id,
            related_topics,
        )

        confusion_type = self._infer_confusion_type(event_rows, mistake_rows)
        confidence = self._compute_confidence(mastery_map, topic)

        logger.debug(
            "diagnosis_complete",
            user_id=user_id[:8],
            topic=topic,
            strong_count=len(strong),
            weak_count=len(weak),
            unseen_count=len(unseen),
            confusion_type=confusion_type,
            confidence=confidence,
        )

        return StudentProfile(
            strong=strong,
            weak=weak,
            unseen=unseen,
            confusion_type=confusion_type,
            confidence=confidence,
        )

    # ------------------------------------------------------------------ #
    # Confusion-type inference                                             #
    # ------------------------------------------------------------------ #

    def _infer_confusion_type(
        self,
        event_rows: list[Any],
        mistake_rows: list[Any],
    ) -> Literal["procedural", "conceptual", "unknown"]:
        """
        Classify whether the student primarily makes procedural or conceptual errors.

        Procedural: right method, wrong computation (arithmetic_error, sign_error,
        unit_error dominate).
        Conceptual: wrong method entirely (concept_confusion, algebra_error dominate).
        """
        procedural_score = 0
        conceptual_score = 0

        # Mistake patterns are weighted by observed frequency.
        for row in mistake_rows:
            code: str = row["mistake_code"] or ""
            freq: int = int(row["frequency"] or 1)
            if code in _PROCEDURAL_CODES:
                procedural_score += freq
            elif code in _CONCEPTUAL_CODES:
                conceptual_score += freq

        # Recent learning events carry pattern lists serialised as JSONB.
        for row in event_rows:
            raw = row["detected_patterns"]
            patterns: list[Any] = (
                raw
                if isinstance(raw, list)
                else self._safe_json(raw)
            )
            for p in patterns:
                code = p.get("mistake_code", "") if isinstance(p, dict) else ""
                if code in _PROCEDURAL_CODES:
                    procedural_score += 1
                elif code in _CONCEPTUAL_CODES:
                    conceptual_score += 1

        if procedural_score == 0 and conceptual_score == 0:
            return "unknown"
        return "procedural" if procedural_score >= conceptual_score else "conceptual"

    # ------------------------------------------------------------------ #
    # Confidence                                                           #
    # ------------------------------------------------------------------ #

    def _compute_confidence(
        self, mastery_map: dict[str, float], topic: str
    ) -> float:
        """
        Confidence in the diagnosis:
        - High (up to 1.0) when we have mastery data for the exact topic.
        - Medium when we have data for other topics but not this one.
        - Low (0.2) when we have no history at all.
        """
        if topic in mastery_map:
            return round(min(1.0, 0.4 + mastery_map[topic] * 0.6), 4)
        if mastery_map:
            avg = sum(mastery_map.values()) / len(mastery_map)
            return round(0.2 + avg * 0.4, 4)
        return 0.2

    # ------------------------------------------------------------------ #
    # Utilities                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _safe_json(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return []
        return []


diagnosis_engine = DiagnosisEngine()
