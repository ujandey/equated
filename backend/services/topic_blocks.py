"""
Services - Topic Blocks

Routes chat queries to scoped topic blocks so we only send relevant
context to the model. This keeps unrelated questions from bleeding
into the active prompt and records a decision log for debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import re
from typing import Any
from uuid import uuid4

import structlog

from ai.classifier import classifier
from cache.embeddings import embedding_generator
from db.connection import get_db

logger = structlog.get_logger("equated.services.topic_blocks")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from", "give", "i",
    "in", "is", "it", "me", "my", "now", "of", "on", "or", "please", "show", "that",
    "the", "this", "to", "us", "we", "what", "why", "with", "write", "you",
}
_GENERIC_FOLLOW_UP_TOKENS = {
    "again", "answer", "brief", "continue", "definition", "derive", "detail", "details",
    "equation", "explain", "expression", "formula", "intuition", "law", "meaning",
    "mathematical", "mathematically", "proof", "recap", "relation", "result", "rule",
    "short", "shorter", "simple", "simpler", "simplify", "state", "statement", "step",
    "summarize", "summary", "theorem",
}


ANCHOR_PATTERNS: list[tuple[str, str, float]] = [
    (r"\b(step\s+\d+)\b", "step_reference", 0.95),
    (r"\b(using that|use that|that value|this value|from above)\b", "value_reference", 0.9),
    (
        r"\b(now\s+)?(give|show|share|tell me|what is)(\s+the)?\s+"
        r"(formula|equation|expression|result|answer|law|theorem|rule)\b",
        "concept_reference",
        0.93,
    ),
    (
        r"\b(formula|equation|expression|result|answer)\s+(for|of|behind|used here)\b",
        "concept_reference",
        0.91,
    ),
    (
        r"\b(explain( it| this| that)? simply|explain( it| this| that)? simpler|simplify|simpler|in short|again|"
        r"dumb it down|make it simple|easy version|short version|explain in simple words)\b",
        "simplify_request",
        0.97,
    ),
    (r"\b(why|how)\b", "explanation_request", 0.82),
    (r"\b(continue|go on|next step)\b", "continuation", 0.92),
    (r"\b(this|that|it|same method)\b", "pronoun_reference", 0.7),
]


@dataclass
class AnchorMatch:
    kind: str | None = None
    text: str | None = None
    confidence: float = 0.0


@dataclass
class TopicBlock:
    id: str
    session_id: str
    status: str
    subject: str | None
    topic_label: str | None
    summary: str | None
    centroid_embedding: list[float] | None
    last_question_embedding: list[float] | None
    question_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class TopicRoutingDecision:
    block_id: str
    decision_type: str
    reason: str
    is_new_block: bool
    scores: dict[str, Any]
    thresholds: dict[str, float]
    anchor: AnchorMatch
    subject: str


class TopicBlockService:
    """
    Production-safe context routing:
      - score only the active block and recent prior blocks
      - prefer isolation when uncertain
      - write a decision log for every query
    """

    THRESHOLD_PROFILES: dict[str, dict[str, float]] = {
        "math": {"follow_up": 0.78, "same_topic": 0.60, "reopen": 0.74, "margin": 0.05, "anchor_min": 0.45, "lexical_follow_up": 0.72},
        "physics": {"follow_up": 0.74, "same_topic": 0.56, "reopen": 0.70, "margin": 0.05, "anchor_min": 0.42, "lexical_follow_up": 0.70},
        "chemistry": {"follow_up": 0.72, "same_topic": 0.54, "reopen": 0.68, "margin": 0.04, "anchor_min": 0.40, "lexical_follow_up": 0.68},
        "general": {"follow_up": 0.76, "same_topic": 0.58, "reopen": 0.72, "margin": 0.05, "anchor_min": 0.45, "lexical_follow_up": 0.72},
    }
    EMBEDDING_MODEL_VERSION = embedding_generator.MODEL
    MAX_CONTEXT_MESSAGES = 6
    MAX_SUMMARY_MESSAGES = 8

    async def route_query(self, session_id: str, query: str) -> TopicRoutingDecision:
        query_embedding = await embedding_generator.generate(query)
        classification = classifier.classify(query)
        subject = classification.subject.value
        thresholds = self._get_thresholds(subject)
        anchor = self.extract_anchor(query)

        active_block = await self.get_active_block(session_id)
        recent_blocks = await self.get_recent_blocks(session_id, limit=5)
        recent_blocks = [block for block in recent_blocks if not active_block or block.id != active_block.id]

        sim_active = self._embedding_similarity(query_embedding, active_block.centroid_embedding if active_block else None)
        sim_last_turn = self._embedding_similarity(
            query_embedding,
            active_block.last_question_embedding if active_block else None,
        )
        lexical_follow_up_score = self._lexical_follow_up_score(query, active_block) if active_block else 0.0

        scored_recent: list[tuple[TopicBlock, float]] = [
            (block, self._embedding_similarity(query_embedding, block.centroid_embedding))
            for block in recent_blocks
        ]
        scored_recent.sort(key=lambda item: item[1], reverse=True)
        best_recent_block = scored_recent[0][0] if scored_recent else None
        best_recent_score = scored_recent[0][1] if scored_recent else 0.0
        runner_up_score = scored_recent[1][1] if len(scored_recent) > 1 else 0.0
        margin = best_recent_score - runner_up_score

        decision_type = "new_topic"
        reason = "no_matching_block"
        selected_block = active_block
        is_new_block = False

        if active_block and anchor.kind == "simplify_request":
            decision_type = "follow_up"
            reason = "anchor:simplify_request_override"
            selected_block = active_block
        elif active_block and anchor.confidence >= 0.8 and (
            sim_active == 0.0 or sim_active >= thresholds["anchor_min"]
        ):
            decision_type = "follow_up"
            reason = f"anchor:{anchor.kind}"
            selected_block = active_block
        elif active_block and lexical_follow_up_score >= thresholds["lexical_follow_up"]:
            decision_type = "follow_up"
            reason = "active_block_lexical_follow_up"
            selected_block = active_block
        elif active_block and sim_active >= thresholds["follow_up"]:
            decision_type = "follow_up"
            reason = "active_block_follow_up_similarity"
            selected_block = active_block
        elif active_block and sim_active >= thresholds["same_topic"]:
            decision_type = "same_topic_new_question"
            reason = "active_block_same_topic_similarity"
            selected_block = active_block
        elif best_recent_block and best_recent_score >= thresholds["reopen"] and margin >= thresholds["margin"]:
            decision_type = "reopen_topic"
            reason = "recent_block_reopen_similarity"
            selected_block = best_recent_block
        else:
            selected_block = await self.create_block(
                session_id=session_id,
                subject=subject,
                topic_label=self._topic_label(query, subject),
                query_embedding=query_embedding,
            )
            decision_type = "new_topic"
            reason = "new_block_created"
            is_new_block = True

        if selected_block:
            await self.set_active_block(selected_block.id)

        scores = {
            "sim_active_block": round(sim_active, 4),
            "sim_last_turn": round(sim_last_turn, 4),
            "lexical_follow_up_score": round(lexical_follow_up_score, 4),
            "best_recent_score": round(best_recent_score, 4),
            "runner_up_recent_score": round(runner_up_score, 4),
            "recent_margin": round(margin, 4),
            "active_block_id": active_block.id if active_block else None,
            "best_recent_block_id": best_recent_block.id if best_recent_block else None,
            "anchor_kind": anchor.kind,
            "anchor_confidence": round(anchor.confidence, 4),
        }

        decision = TopicRoutingDecision(
            block_id=selected_block.id,
            decision_type=decision_type,
            reason=reason,
            is_new_block=is_new_block,
            scores=scores,
            thresholds=thresholds,
            anchor=anchor,
            subject=subject,
        )
        await self.log_decision(session_id=session_id, query=query, decision=decision)
        return decision

    async def create_block(
        self,
        session_id: str,
        subject: str,
        topic_label: str,
        query_embedding: list[float] | None,
    ) -> TopicBlock:
        db = await get_db()
        row = await db.fetchrow(
            """
            INSERT INTO topic_blocks (
                id, session_id, status, subject, topic_label,
                centroid_embedding, last_question_embedding,
                question_count, created_at, updated_at
            )
            VALUES ($1, $2, 'active', $3, $4, $5::vector, $5::vector, 0, NOW(), NOW())
            RETURNING *
            """,
            str(uuid4()),
            session_id,
            subject,
            topic_label,
            self._vector_param(query_embedding),
        )
        return self._row_to_block(row)

    async def get_active_block(self, session_id: str) -> TopicBlock | None:
        db = await get_db()
        row = await db.fetchrow(
            """
            SELECT * FROM topic_blocks
            WHERE session_id = $1 AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            session_id,
        )
        return self._row_to_block(row) if row else None

    async def get_block(self, block_id: str) -> TopicBlock | None:
        db = await get_db()
        row = await db.fetchrow(
            "SELECT * FROM topic_blocks WHERE id = $1",
            block_id,
        )
        return self._row_to_block(row) if row else None

    async def get_recent_blocks(self, session_id: str, limit: int = 5) -> list[TopicBlock]:
        db = await get_db()
        rows = await db.fetch(
            """
            SELECT * FROM topic_blocks
            WHERE session_id = $1
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )
        return [self._row_to_block(row) for row in rows]

    async def set_active_block(self, block_id: str):
        db = await get_db()
        row = await db.fetchrow("SELECT session_id FROM topic_blocks WHERE id = $1", block_id)
        if not row:
            return
        session_id = row["session_id"]
        await db.execute(
            "UPDATE topic_blocks SET status = 'closed', updated_at = NOW() WHERE session_id = $1 AND id <> $2 AND status = 'active'",
            session_id,
            block_id,
        )
        await db.execute(
            "UPDATE topic_blocks SET status = 'active', updated_at = NOW() WHERE id = $1",
            block_id,
        )

    async def attach_message_to_block(self, message_id: str, block_id: str):
        db = await get_db()
        await db.execute(
            "UPDATE messages SET block_id = $1 WHERE id = $2",
            block_id,
            message_id,
        )

    async def register_user_turn(self, block_id: str, question: str):
        db = await get_db()
        new_embedding = await embedding_generator.generate(question)
        row = await db.fetchrow(
            "SELECT centroid_embedding, question_count, subject FROM topic_blocks WHERE id = $1",
            block_id,
        )
        if not row:
            return

        existing_centroid = self._parse_vector(row["centroid_embedding"])
        question_count = int(row["question_count"] or 0)
        centroid = self._merge_embeddings(existing_centroid, new_embedding, question_count)

        await db.execute(
            """
            UPDATE topic_blocks
            SET centroid_embedding = $2::vector,
                last_question_embedding = $3::vector,
                question_count = question_count + 1,
                topic_label = COALESCE(topic_label, $4),
                updated_at = NOW()
            WHERE id = $1
            """,
            block_id,
            self._vector_param(centroid),
            self._vector_param(new_embedding),
            self._topic_label(question, row["subject"] or "general"),
        )

    async def refresh_block_summary(self, block_id: str):
        db = await get_db()
        rows = await db.fetch(
            """
            SELECT role, content
            FROM messages
            WHERE block_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            block_id,
            self.MAX_SUMMARY_MESSAGES,
        )
        if not rows:
            return

        summary = self._build_summary(list(reversed(rows)))
        await db.execute(
            "UPDATE topic_blocks SET summary = $2, updated_at = NOW() WHERE id = $1",
            block_id,
            summary,
        )

    async def get_context_messages(self, block_id: str, max_messages: int | None = None) -> list[dict[str, str]]:
        db = await get_db()
        limit = max_messages or self.MAX_CONTEXT_MESSAGES
        rows = await db.fetch(
            """
            SELECT role, content
            FROM messages
            WHERE block_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            block_id,
            limit,
        )
        context = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

        summary_row = await db.fetchrow(
            "SELECT summary FROM topic_blocks WHERE id = $1",
            block_id,
        )
        summary = summary_row["summary"] if summary_row else None
        if summary and len(context) >= limit:
            context = [{"role": "system", "content": f"[Topic summary]\n{summary}"}] + context
        return context

    async def log_decision(self, session_id: str, query: str, decision: TopicRoutingDecision):
        db = await get_db()
        await db.execute(
            """
            INSERT INTO topic_routing_decisions (
                id, session_id, block_id, query_text, decision_type, reason,
                scores_json, thresholds_json, anchors_json, model_versions_json, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            """,
            str(uuid4()),
            session_id,
            decision.block_id,
            query,
            decision.decision_type,
            decision.reason,
            json.dumps(decision.scores),
            json.dumps(decision.thresholds),
            json.dumps(
                {
                    "kind": decision.anchor.kind,
                    "text": decision.anchor.text,
                    "confidence": decision.anchor.confidence,
                }
            ),
            json.dumps({"embedding": self.EMBEDDING_MODEL_VERSION}),
        )

    def extract_anchor(self, query: str) -> AnchorMatch:
        lowered = query.strip().lower()
        for pattern, kind, confidence in ANCHOR_PATTERNS:
            match = re.search(pattern, lowered, re.IGNORECASE)
            if match:
                return AnchorMatch(kind=kind, text=match.group(0), confidence=confidence)
        return AnchorMatch()

    def _build_summary(self, messages: list[Any]) -> str:
        lines: list[str] = []
        for row in messages:
            role = row["role"] if isinstance(row, dict) else row["role"]
            content = row["content"] if isinstance(row, dict) else row["content"]
            if role == "user":
                lines.append(f"User asked: {self._trim(content, 140)}")
            elif role == "assistant":
                lines.append(f"Assistant answered: {self._trim(content, 180)}")
        return "\n".join(lines[-6:])

    def _trim(self, text: str, length: int) -> str:
        stripped = text.strip()
        return stripped if len(stripped) <= length else f"{stripped[:length].rstrip()}..."

    def _topic_label(self, query: str, subject: str) -> str:
        lowered = query.strip().replace("\n", " ")
        return f"{subject}: {self._trim(lowered, 80)}"

    def _lexical_follow_up_score(self, query: str, block: TopicBlock | None) -> float:
        if not block:
            return 0.0

        query_tokens = self._content_tokens(query)
        if not query_tokens:
            return 1.0

        context_text = " ".join(filter(None, [block.topic_label, block.summary]))
        context_tokens = set(self._content_tokens(context_text))
        overlap = len(set(query_tokens) & context_tokens) / max(len(set(query_tokens)), 1)
        generic_ratio = sum(1 for token in query_tokens if token in _GENERIC_FOLLOW_UP_TOKENS) / max(len(query_tokens), 1)
        short_bonus = 0.15 if len(query_tokens) <= 3 else 0.0
        return min(1.0, (overlap * 0.55) + (generic_ratio * 0.55) + short_bonus)

    def _content_tokens(self, text: str) -> list[str]:
        return [
            token
            for token in _TOKEN_RE.findall((text or "").lower())
            if len(token) > 1 and token not in _STOPWORDS
        ]

    def _get_thresholds(self, subject: str) -> dict[str, float]:
        profile = self.THRESHOLD_PROFILES.get(subject, self.THRESHOLD_PROFILES["general"])
        return dict(profile)

    def _merge_embeddings(
        self,
        existing: list[float] | None,
        new: list[float] | None,
        existing_count: int,
    ) -> list[float] | None:
        if not existing:
            return new
        if not new:
            return existing
        total = max(existing_count, 1)
        return [
            ((old * total) + fresh) / (total + 1)
            for old, fresh in zip(existing, new)
        ]

    def _embedding_similarity(self, left: list[float] | None, right: list[float] | None) -> float:
        if not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def _vector_param(self, embedding: list[float] | None) -> str | None:
        if not embedding:
            return None
        return str(embedding)

    def _parse_vector(self, raw: Any) -> list[float] | None:
        if raw is None:
            return None
        if isinstance(raw, list):
            return [float(x) for x in raw]
        if isinstance(raw, str):
            stripped = raw.strip("[]")
            if not stripped:
                return None
            return [float(part) for part in stripped.split(",")]
        return None

    def _row_to_block(self, row) -> TopicBlock:
        return TopicBlock(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            status=row["status"],
            subject=row["subject"],
            topic_label=row["topic_label"],
            summary=row["summary"],
            centroid_embedding=self._parse_vector(row["centroid_embedding"]),
            last_question_embedding=self._parse_vector(row["last_question_embedding"]),
            question_count=row["question_count"] or 0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


topic_block_service = TopicBlockService()
