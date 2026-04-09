import re
import structlog
from typing import Literal
from services.math_intent_detector import is_math_like
from ai.classifier import Classification, ComplexityLevel, SubjectCategory
from services.topic_blocks import AnchorMatch, TopicRoutingDecision

logger = structlog.get_logger("equated.services.intent_classifier")

QueryIntent = Literal["solve", "explain", "follow_up", "unclear"]

_SOLVE_RE = re.compile(r"\b(solve|find|compute|calculate|differentiate|derivative|integrate|integral|simplify|evaluate|limit)\b", re.IGNORECASE)
_EXPLAIN_RE = re.compile(r"\b(explain|why|how|intuition|what is|meaning|simplify|simple|simply)\b", re.IGNORECASE)
_FOLLOW_UP_RE = re.compile(
    r"\b(it|this|that|again|next step|continue|using that|from above|formula|equation|expression|result)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_RE = re.compile(r"^\s*(help|please help|can you help|what about this)\s*$", re.IGNORECASE)


class IntentClassifier:
    """Handles classification of user query intent."""

    @staticmethod
    def classify_intent(query: str) -> QueryIntent:
        if _AMBIGUOUS_RE.search(query):
            return "unclear"
        if _SOLVE_RE.search(query) and is_math_like(query):
            return "solve"
        if _EXPLAIN_RE.search(query):
            return "explain"
        if _FOLLOW_UP_RE.search(query):
            return "follow_up"
        return "unclear"

    @staticmethod
    def resolve_intent(intent: QueryIntent, anchor: AnchorMatch | None) -> QueryIntent:
        if anchor and anchor.kind in {
            "simplify_request",
            "explanation_request",
            "continuation",
            "pronoun_reference",
            "concept_reference",
        }:
            return "follow_up"
        return intent

    @staticmethod
    def contextualize_classification(
        classification: Classification,
        routing: TopicRoutingDecision | None,
    ) -> Classification:
        follow_up_modes = {"follow_up", "same_topic_new_question", "reopen_topic"}
        if not routing or routing.decision_type not in follow_up_modes or not routing.subject:
            return classification

        try:
            routed_subject = SubjectCategory(routing.subject)
        except ValueError:
            return classification

        if not hasattr(classification, "subject") or not hasattr(classification, "complexity"):
            return classification

        adjusted_complexity = (
            ComplexityLevel.MEDIUM
            if classification.complexity == ComplexityLevel.LOW
            else classification.complexity
        )
        adjusted_tokens = max(
            getattr(classification, "tokens_est", 0),
            1500 if routed_subject != SubjectCategory.GENERAL else 800,
        )

        if classification.subject == routed_subject and adjusted_complexity == classification.complexity:
            return classification

        logger.info(
            "classification_context_override",
            original_subject=classification.subject.value,
            routed_subject=routed_subject.value,
            decision_type=routing.decision_type,
        )
        return Classification(
            subject=routed_subject,
            complexity=adjusted_complexity,
            confidence=max(classification.confidence, 0.85),
            tokens_est=adjusted_tokens,
            needs_steps=(routed_subject != SubjectCategory.GENERAL),
        )

intent_classifier_service = IntentClassifier()
