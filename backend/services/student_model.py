"""
Services - Student Model Service

Persistent student modeling for adaptive tutoring:
  - per-topic mastery tracking
  - repeated weakness detection
  - mistake-pattern memory
  - learning-velocity estimation
  - interaction signal logging
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from db.connection import get_db

logger = structlog.get_logger("equated.services.student_model")


class StudentModelService:
    DEFAULT_MASTERY = 0.35
    DEFAULT_ASSUMED_LEVEL = 0.5
    SUCCESS_STREAK_ACCELERATION_THRESHOLD = 3
    WEAK_TOPIC_FAILURE_THRESHOLD = 3
    MAX_PATTERN_EVIDENCE = 8

    SIMPLE_EXPLANATION_RE = re.compile(
        r"\b(explain simply|explain simpler|simple words|simplify|easier way|dumb it down|basic version)\b",
        re.IGNORECASE,
    )
    UNCERTAINTY_RE = re.compile(
        r"\b(not sure|confused|don't understand|stuck|guess|maybe)\b",
        re.IGNORECASE,
    )
    UNIT_RE = re.compile(
        r"\b(cm|mm|m|km|kg|g|mg|s|sec|seconds|minutes|min|hours|hr|rs|rupees|%|degree|degrees)\b",
        re.IGNORECASE,
    )
    ARITHMETIC_CLAIM_RE = re.compile(
        r"(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)"
    )

    async def get_student_state(self, user_id: str) -> dict[str, Any]:
        db = await get_db()

        mastery_rows = await db.fetch(
            """
            SELECT *
            FROM user_topic_mastery
            WHERE user_id = $1
            ORDER BY is_weak DESC, mastery_score ASC, updated_at DESC
            """,
            user_id,
        )
        pattern_rows = await db.fetch(
            """
            SELECT *
            FROM user_mistake_patterns
            WHERE user_id = $1
            ORDER BY frequency DESC, last_seen_at DESC
            LIMIT 20
            """,
            user_id,
        )
        signal_rows = await db.fetch(
            """
            SELECT
                COUNT(*) AS total_events,
                COALESCE(SUM(hints_used), 0) AS total_hints_used,
                COALESCE(SUM(retry_count), 0) AS total_retries,
                COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) AS total_successes,
                COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) AS total_failures,
                COALESCE(AVG(mastery_after - mastery_before), 0) AS avg_delta
            FROM user_learning_events
            WHERE user_id = $1
            """,
            user_id,
        )

        topics = [self._serialize_mastery_row(row) for row in mastery_rows]
        weak_areas = [
            {
                "topic": row["topic"],
                "subject": row["subject"],
                "mastery": round(float(row["mastery_score"]), 4),
                "failures": row["failures"],
                "consecutive_failures": row["consecutive_failures"],
                "learning_velocity": round(float(row["learning_velocity"]), 4),
            }
            for row in mastery_rows
            if row["is_weak"]
        ]
        mistake_patterns = [self._serialize_pattern_row(row) for row in pattern_rows]
        interaction = signal_rows[0] if signal_rows else None

        return {
            "user_id": user_id,
            "topics": topics,
            "weak_areas": weak_areas,
            "mistake_patterns": mistake_patterns,
            "learning_velocity": {
                "overall": round(float(interaction["avg_delta"] or 0.0), 4) if interaction else 0.0,
                "topics_tracked": len(topics),
                "improving_topics": sum(1 for topic in topics if topic["learning_velocity"] > 0),
                "declining_topics": sum(1 for topic in topics if topic["learning_velocity"] < 0),
            },
            "interaction_signals": {
                "total_events": int(interaction["total_events"] or 0) if interaction else 0,
                "hints_used": int(interaction["total_hints_used"] or 0) if interaction else 0,
                "retries": int(interaction["total_retries"] or 0) if interaction else 0,
                "failures": int(interaction["total_failures"] or 0) if interaction else 0,
                "successes": int(interaction["total_successes"] or 0) if interaction else 0,
            },
        }

    async def update_from_interaction(
        self,
        user_id: str,
        question: str,
        response: str,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        subject = outcome.get("subject")
        topic = outcome.get("topic") or self._derive_topic(question, subject)
        session_id = outcome.get("session_id")
        success = bool(outcome.get("success"))
        hints_used = self._non_negative_int(outcome.get("hints_used", 0))
        retry_count = self._non_negative_int(outcome.get("retries", outcome.get("retry_count", 0)))
        asked_for_simple = bool(
            outcome.get("asked_for_simple")
            or self._requests_simpler_explanation(question)
            or self._requests_simpler_explanation(response)
        )
        failure_reason = outcome.get("failure_reason")
        confidence = self._safe_float(outcome.get("confidence"), default=0.5)
        assistant_response = outcome.get("assistant_response")

        detected_patterns = outcome.get("detected_patterns")
        if detected_patterns is None and (not success or self.UNCERTAINTY_RE.search(response or "")):
            detected_patterns = self.detect_mistake_patterns(question, response)
        detected_patterns = detected_patterns or []

        mastery_result = await self.update_mastery(
            user_id=user_id,
            topic=topic,
            success=success,
            subject=subject,
            hints_used=hints_used,
            retry_count=retry_count,
            asked_for_simple=asked_for_simple,
            confidence=confidence,
        )

        await self._insert_learning_event(
            user_id=user_id,
            session_id=session_id,
            topic_mastery_id=mastery_result["topic_mastery_id"],
            subject=subject,
            topic=topic,
            question=question,
            user_answer=response,
            assistant_response=assistant_response,
            success=success,
            hints_used=hints_used,
            retry_count=retry_count,
            failure_reason=failure_reason,
            interaction_signals={
                "asked_for_simple": asked_for_simple,
                "confidence": confidence,
                "source": outcome.get("source", "chat_pipeline"),
                "failure_reason": failure_reason,
            },
            detected_patterns=detected_patterns,
            mastery_before=mastery_result["mastery_before"],
            mastery_after=mastery_result["mastery_after"],
        )

        if detected_patterns:
            await self._upsert_mistake_patterns(
                user_id=user_id,
                subject=subject,
                topic=topic,
                question=question,
                user_answer=response,
                patterns=detected_patterns,
            )

        return {
            "topic": topic,
            "subject": subject,
            "mastery": mastery_result,
            "detected_patterns": detected_patterns,
            "student_state": await self.get_student_state(user_id),
        }

    def detect_mistake_patterns(self, question: str, user_answer: str) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        answer = (user_answer or "").strip()
        prompt = (question or "").strip()
        lowered_answer = answer.lower()
        lowered_prompt = prompt.lower()

        if re.search(r"\b(minus|negative)\b", lowered_prompt) and re.search(r"(\+\-)|(\-\-)|(\-\+)|(\+\+)", answer):
            patterns.append(self._pattern("sign_error", "Sign handling error", answer))

        if self._contains_incorrect_arithmetic_claim(answer):
            patterns.append(self._pattern("arithmetic_error", "Arithmetic computation error", answer))

        if re.search(r"[a-zA-Z]", prompt) and re.search(r"\b(cancel|cancelled|divide by x|cross multiply)\b", lowered_answer):
            patterns.append(self._pattern("algebra_error", "Algebraic manipulation mistake", answer))

        if self.UNIT_RE.search(prompt) and not self.UNIT_RE.search(answer):
            patterns.append(self._pattern("unit_error", "Dropped or inconsistent units", answer))

        if self.UNCERTAINTY_RE.search(answer):
            patterns.append(self._pattern("concept_confusion", "Conceptual confusion", answer))

        seen_codes: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for pattern in patterns:
            if pattern["mistake_code"] in seen_codes:
                continue
            seen_codes.add(pattern["mistake_code"])
            deduped.append(pattern)
        return deduped

    async def update_mastery(
        self,
        user_id: str,
        topic: str,
        success: bool,
        subject: str | None = None,
        hints_used: int = 0,
        retry_count: int = 0,
        asked_for_simple: bool = False,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        db = await get_db()
        row = await db.fetchrow(
            """
            SELECT *
            FROM user_topic_mastery
            WHERE user_id = $1 AND topic = $2
            """,
            user_id,
            topic,
        )

        previous = dict(row) if row else {}
        mastery_before = self._safe_float(previous.get("mastery_score"), self.DEFAULT_MASTERY)
        assumed_level_before = self._safe_float(previous.get("assumed_level"), self.DEFAULT_ASSUMED_LEVEL)
        attempts_before = int(previous.get("attempts") or 0)
        successes_before = int(previous.get("successes") or 0)
        failures_before = int(previous.get("failures") or 0)
        consecutive_successes_before = int(previous.get("consecutive_successes") or 0)
        consecutive_failures_before = int(previous.get("consecutive_failures") or 0)
        hint_uses_before = int(previous.get("hint_uses") or 0)
        retry_count_before = int(previous.get("retry_count") or 0)
        ask_simple_count_before = int(previous.get("ask_simple_count") or 0)
        velocity_before = self._safe_float(previous.get("learning_velocity"), 0.0)

        mastery_after = self._compute_new_mastery(
            current_mastery=mastery_before,
            success=success,
            hints_used=hints_used,
            retry_count=retry_count,
            consecutive_successes=consecutive_successes_before,
            consecutive_failures=consecutive_failures_before,
            confidence=confidence,
        )
        assumed_level_after = self._compute_assumed_level(
            current_assumed_level=assumed_level_before,
            success=success,
            asked_for_simple=asked_for_simple,
            hints_used=hints_used,
        )
        learning_velocity_after = round((velocity_before * 0.7) + ((mastery_after - mastery_before) * 0.3), 4)

        attempts_after = attempts_before + 1
        successes_after = successes_before + (1 if success else 0)
        failures_after = failures_before + (0 if success else 1)
        consecutive_successes_after = consecutive_successes_before + 1 if success else 0
        consecutive_failures_after = 0 if success else consecutive_failures_before + 1
        ask_simple_count_after = ask_simple_count_before + (1 if asked_for_simple else 0)
        is_weak = bool(
            consecutive_failures_after >= self.WEAK_TOPIC_FAILURE_THRESHOLD
            or (failures_after >= self.WEAK_TOPIC_FAILURE_THRESHOLD and mastery_after < 0.55)
        )

        topic_mastery_id = previous.get("id") or str(uuid4())
        now = datetime.now(timezone.utc)

        await db.execute(
            """
            INSERT INTO user_topic_mastery (
                id, user_id, subject, topic, mastery_score, assumed_level, learning_velocity,
                attempts, successes, failures, consecutive_successes, consecutive_failures,
                hint_uses, retry_count, ask_simple_count, is_weak,
                last_interacted_at, created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11, $12,
                $13, $14, $15, $16,
                $17, $18, $19
            )
            ON CONFLICT (user_id, topic) DO UPDATE
            SET
                subject = COALESCE(EXCLUDED.subject, user_topic_mastery.subject),
                mastery_score = EXCLUDED.mastery_score,
                assumed_level = EXCLUDED.assumed_level,
                learning_velocity = EXCLUDED.learning_velocity,
                attempts = EXCLUDED.attempts,
                successes = EXCLUDED.successes,
                failures = EXCLUDED.failures,
                consecutive_successes = EXCLUDED.consecutive_successes,
                consecutive_failures = EXCLUDED.consecutive_failures,
                hint_uses = EXCLUDED.hint_uses,
                retry_count = EXCLUDED.retry_count,
                ask_simple_count = EXCLUDED.ask_simple_count,
                is_weak = EXCLUDED.is_weak,
                last_interacted_at = EXCLUDED.last_interacted_at,
                updated_at = EXCLUDED.updated_at
            """,
            topic_mastery_id,
            user_id,
            subject,
            topic,
            mastery_after,
            assumed_level_after,
            learning_velocity_after,
            attempts_after,
            successes_after,
            failures_after,
            consecutive_successes_after,
            consecutive_failures_after,
            hint_uses_before + hints_used,
            retry_count_before + retry_count,
            ask_simple_count_after,
            is_weak,
            now,
            previous.get("created_at") or now,
            now,
        )

        return {
            "topic_mastery_id": topic_mastery_id,
            "topic": topic,
            "subject": subject,
            "mastery_before": round(mastery_before, 4),
            "mastery_after": round(mastery_after, 4),
            "assumed_level_before": round(assumed_level_before, 4),
            "assumed_level_after": round(assumed_level_after, 4),
            "learning_velocity": learning_velocity_after,
            "is_weak": is_weak,
            "consecutive_successes": consecutive_successes_after,
            "consecutive_failures": consecutive_failures_after,
        }

    def build_personalization_prompt(
        self,
        student_state: dict[str, Any],
        active_topic: str | None = None,
    ) -> str | None:
        weak_areas = student_state.get("weak_areas") or []
        mistake_patterns = student_state.get("mistake_patterns") or []
        topics = student_state.get("topics") or []

        lines: list[str] = []
        if active_topic:
            active_match = next((topic for topic in topics if topic["topic"] == active_topic), None)
            if active_match:
                lines.append(
                    f"Student mastery for '{active_topic}' is {active_match['mastery']:.2f}; tailor depth to level {active_match['assumed_level']:.2f}."
                )
                if active_match["is_weak"]:
                    lines.append("This topic is currently weak. Slow down, use explicit steps, and check for repeated misconceptions.")

        if weak_areas:
            lines.append("Recent weak areas: " + ", ".join(area["topic"] for area in weak_areas[:3]) + ".")
        if mistake_patterns:
            lines.append("Frequent mistake patterns: " + ", ".join(pattern["mistake_label"] for pattern in mistake_patterns[:3]) + ".")

        return "\n".join(lines) if lines else None

    def build_curriculum_guidance(
        self,
        student_state: dict[str, Any],
        target_topic: str | None = None,
    ) -> dict[str, Any]:
        """
        Integrate curriculum graph signals with the existing student model shape.

        Returns unmet prerequisites for a target topic, plus a next-topic suggestion.
        """
        try:
            from knowledge.curriculum_graph import find_knowledge_gaps, suggest_next_topic
        except Exception:
            return {
                "target_topic": target_topic,
                "knowledge_gaps": [],
                "next_topic": None,
            }

        gaps = find_knowledge_gaps(target_topic, student_state) if target_topic else []
        next_topic = suggest_next_topic(student_state)
        return {
            "target_topic": target_topic,
            "knowledge_gaps": gaps,
            "next_topic": next_topic,
        }

    def build_chat_interaction_outcome(
        self,
        *,
        user_message: str,
        assistant_response: str,
        subject: str | None,
        topic: str | None,
        session_id: str | None,
        follow_up_anchor_kind: str | None,
        topic_decision_type: str,
        topic_question_count: int = 0,
        confidence: float = 0.5,
        verified: bool | None = None,
        source: str = "chat_pipeline",
    ) -> dict[str, Any]:
        asked_for_simple = (
            follow_up_anchor_kind == "simplify_request"
            or self._requests_simpler_explanation(user_message)
        )
        uncertainty = bool(self.UNCERTAINTY_RE.search(user_message or ""))
        retry_count = 0
        if topic_decision_type in {"follow_up", "same_topic_new_question", "reopen_topic"}:
            retry_count = max(topic_question_count, 1)

        hints_used = 1 if asked_for_simple else 0
        success = not asked_for_simple and not uncertainty
        if verified is False:
            success = False

        failure_reason = None
        if asked_for_simple:
            failure_reason = "requested_simpler_explanation"
        elif uncertainty:
            failure_reason = "expressed_uncertainty"
        elif verified is False:
            failure_reason = "low_response_reliability"

        return {
            "session_id": session_id,
            "subject": subject,
            "topic": topic,
            "success": success,
            "confidence": confidence if success else min(confidence, 0.4),
            "hints_used": hints_used,
            "retry_count": retry_count,
            "asked_for_simple": asked_for_simple,
            "failure_reason": failure_reason,
            "assistant_response": assistant_response,
            "source": source,
        }

    def _compute_new_mastery(
        self,
        current_mastery: float,
        success: bool,
        hints_used: int,
        retry_count: int,
        consecutive_successes: int,
        consecutive_failures: int,
        confidence: float,
    ) -> float:
        confidence = max(0.0, min(confidence, 1.0))
        hint_penalty = min(hints_used * 0.015, 0.06)
        retry_penalty = min(retry_count * 0.02, 0.08)

        if success:
            delta = 0.08 + (0.04 * confidence)
            if consecutive_successes + 1 >= self.SUCCESS_STREAK_ACCELERATION_THRESHOLD:
                delta *= 1.4
            delta -= hint_penalty
            delta -= retry_penalty
        else:
            delta = -(0.10 + (0.04 * (1.0 - confidence)))
            delta -= hint_penalty * 0.5
            delta -= retry_penalty * 0.8
            if consecutive_failures + 1 >= self.WEAK_TOPIC_FAILURE_THRESHOLD:
                delta -= 0.03

        if confidence < 0.4:
            delta *= 0.6

        return round(max(0.0, min(1.0, current_mastery + delta)), 4)

    def _compute_assumed_level(
        self,
        current_assumed_level: float,
        success: bool,
        asked_for_simple: bool,
        hints_used: int,
    ) -> float:
        new_level = current_assumed_level
        if success:
            new_level += 0.02
        else:
            new_level -= 0.03
        if asked_for_simple:
            new_level -= 0.08
        if hints_used > 0:
            new_level -= min(hints_used * 0.02, 0.06)
        return round(max(0.0, min(1.0, new_level)), 4)

    async def _insert_learning_event(
        self,
        user_id: str,
        session_id: str | None,
        topic_mastery_id: str | None,
        subject: str | None,
        topic: str,
        question: str,
        user_answer: str,
        assistant_response: str | None,
        success: bool,
        hints_used: int,
        retry_count: int,
        failure_reason: str | None,
        interaction_signals: dict[str, Any],
        detected_patterns: list[dict[str, Any]],
        mastery_before: float,
        mastery_after: float,
    ) -> None:
        db = await get_db()
        await db.execute(
            """
            INSERT INTO user_learning_events (
                id, user_id, session_id, topic_mastery_id, subject, topic, event_type,
                question_text, user_answer, assistant_response, success, hints_used, retry_count,
                failure_reason, interaction_signals, detected_patterns, mastery_before, mastery_after, created_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11, $12, $13,
                $14, $15, $16, $17, $18, $19
            )
            """,
            str(uuid4()),
            user_id,
            session_id,
            topic_mastery_id,
            subject,
            topic,
            "practice_interaction",
            question,
            user_answer,
            assistant_response,
            success,
            hints_used,
            retry_count,
            failure_reason,
            json.dumps(interaction_signals),
            json.dumps(detected_patterns),
            mastery_before,
            mastery_after,
            datetime.now(timezone.utc),
        )

    async def _upsert_mistake_patterns(
        self,
        user_id: str,
        subject: str | None,
        topic: str,
        question: str,
        user_answer: str,
        patterns: list[dict[str, Any]],
    ) -> None:
        db = await get_db()
        for pattern in patterns:
            row = await db.fetchrow(
                """
                SELECT id, frequency, evidence_json
                FROM user_mistake_patterns
                WHERE user_id = $1 AND topic = $2 AND mistake_label = $3
                """,
                user_id,
                topic,
                pattern["mistake_label"],
            )
            evidence = self._load_json_value(row["evidence_json"]) if row else []
            evidence.append(
                {
                    "question_excerpt": self._trim(question, 160),
                    "answer_excerpt": self._trim(user_answer, 160),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            evidence = evidence[-self.MAX_PATTERN_EVIDENCE :]

            await db.execute(
                """
                INSERT INTO user_mistake_patterns (
                    id, user_id, subject, topic, mistake_code, mistake_label,
                    frequency, evidence_json, last_seen_at, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW(), NOW())
                ON CONFLICT (user_id, topic, mistake_label) DO UPDATE
                SET
                    subject = COALESCE(EXCLUDED.subject, user_mistake_patterns.subject),
                    mistake_code = COALESCE(EXCLUDED.mistake_code, user_mistake_patterns.mistake_code),
                    frequency = user_mistake_patterns.frequency + 1,
                    evidence_json = EXCLUDED.evidence_json,
                    last_seen_at = NOW(),
                    updated_at = NOW()
                """,
                row["id"] if row else str(uuid4()),
                user_id,
                subject,
                topic,
                pattern.get("mistake_code"),
                pattern["mistake_label"],
                (row["frequency"] + 1) if row else 1,
                json.dumps(evidence),
            )

    def _contains_incorrect_arithmetic_claim(self, answer: str) -> bool:
        for match in self.ARITHMETIC_CLAIM_RE.finditer(answer or ""):
            left = float(match.group(1))
            op = match.group(2)
            right = float(match.group(3))
            claimed = float(match.group(4))
            if op == "+":
                actual = left + right
            elif op == "-":
                actual = left - right
            elif op == "*":
                actual = left * right
            else:
                if right == 0:
                    continue
                actual = left / right
            if round(actual, 6) != round(claimed, 6):
                return True
        return False

    def _derive_topic(self, question: str, subject: str | None) -> str:
        cleaned = " ".join((question or "").split())
        prefix = f"{subject}: " if subject else ""
        return f"{prefix}{self._trim(cleaned, 120)}"

    def _pattern(self, code: str, label: str, answer: str) -> dict[str, Any]:
        return {
            "mistake_code": code,
            "mistake_label": label,
            "evidence": self._trim(answer, 200),
        }

    def _requests_simpler_explanation(self, text: str | None) -> bool:
        return bool(text and self.SIMPLE_EXPLANATION_RE.search(text))

    def _serialize_mastery_row(self, row: Any) -> dict[str, Any]:
        return {
            "topic": row["topic"],
            "subject": row["subject"],
            "mastery": round(float(row["mastery_score"]), 4),
            "assumed_level": round(float(row["assumed_level"]), 4),
            "learning_velocity": round(float(row["learning_velocity"]), 4),
            "attempts": row["attempts"],
            "successes": row["successes"],
            "failures": row["failures"],
            "consecutive_successes": row["consecutive_successes"],
            "consecutive_failures": row["consecutive_failures"],
            "hints_used": row["hint_uses"],
            "retry_count": row["retry_count"],
            "ask_simple_count": row["ask_simple_count"],
            "is_weak": row["is_weak"],
            "last_interacted_at": row["last_interacted_at"].isoformat() if row["last_interacted_at"] else None,
        }

    def _serialize_pattern_row(self, row: Any) -> dict[str, Any]:
        return {
            "topic": row["topic"],
            "subject": row["subject"],
            "mistake_code": row["mistake_code"],
            "mistake_label": row["mistake_label"],
            "frequency": row["frequency"],
            "last_seen_at": row["last_seen_at"].isoformat() if row["last_seen_at"] else None,
            "evidence": self._load_json_value(row["evidence_json"]),
        }

    def _load_json_value(self, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []
        return value

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _non_negative_int(self, value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _trim(self, value: str | None, limit: int) -> str:
        text = (value or "").strip()
        return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


student_model_service = StudentModelService()
