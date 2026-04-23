from types import SimpleNamespace
import asyncio

import pytest

from ai.classifier import Classification, ComplexityLevel, ProblemClassifier, SubjectCategory
from ai.models import ModelResponse
from services.adaptive_explainer import AdaptiveExplainerService
from services.explanation import StructuredExplanation
from services.master_controller import master_controller
from services.topic_blocks import AnchorMatch, TopicBlock, TopicRoutingDecision, topic_block_service


def _routing(block_id: str, decision_type: str = "follow_up", anchor_kind: str | None = None) -> TopicRoutingDecision:
    return TopicRoutingDecision(
        block_id=block_id,
        decision_type=decision_type,
        reason="test",
        is_new_block=False,
        scores={},
        thresholds={},
        anchor=AnchorMatch(kind=anchor_kind, text=None, confidence=0.95 if anchor_kind else 0.0),
        subject="physics",
    )


def _block(block_id: str, embedding: list[float]) -> TopicBlock:
    return TopicBlock(
        id=block_id,
        session_id="session-1",
        status="active",
        subject="physics",
        topic_label="physics: Explain Gauss law",
        summary="User asked about Gauss law and the assistant explained it simply.",
        centroid_embedding=embedding,
        last_question_embedding=embedding,
        question_count=2,
    )


def test_adaptive_explainer_falls_back_when_preferred_provider_fails(monkeypatch):
    service = AdaptiveExplainerService()

    class FailingModel:
        async def generate(self, *args, **kwargs):
            raise RuntimeError("provider temporarily unavailable")

    class WorkingModel:
        async def generate(self, *args, **kwargs):
            return ModelResponse(
                content="Gauss law relates electric flux to enclosed charge.",
                model="mock-model",
                provider="groq",
                input_tokens=10,
                output_tokens=20,
                total_cost_usd=0.0,
                finish_reason="stop",
            )

    monkeypatch.setattr(service, "_provider_sequence", lambda preferred_provider=None: ["openai", "groq"])
    monkeypatch.setattr(
        "services.adaptive_explainer.get_model",
        lambda provider: FailingModel() if provider == "openai" else WorkingModel(),
    )

    explanation = asyncio.run(
        service.generate_explanation(
            "Explain Gauss law",
            "Verified result",
            "intermediate",
            preferred_provider="openai",
        )
    )

    assert "Gauss law" in explanation


def test_classifier_recognizes_gauss_law_as_physics():
    classifier = ProblemClassifier()

    result = classifier.classify("Explain Gauss law")

    assert result.subject == SubjectCategory.PHYSICS


@pytest.mark.asyncio
async def test_master_controller_uses_follow_up_subject_for_routing(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _route(**_kwargs):
        return _routing("block-gauss", anchor_kind="concept_reference")

    captured = {}

    def _model_route(classification, *_args, **_kwargs):
        captured["subject"] = classification.subject
        captured["complexity"] = classification.complexity
        return SimpleNamespace(
            provider=SimpleNamespace(value="deepseek"),
            model_name="deepseek-chat",
            max_tokens=800,
            temperature=0.3,
            fallback_provider=None,
            fallback_model=None,
        )

    async def _fallback(messages, *_args, **_kwargs):
        captured["messages"] = messages
        return SimpleNamespace(content="The formula for Gauss law is Phi_E = Qenc/epsilon0.", model="mock-model")

    async def _structured_explanation(**_kwargs):
        return (
            StructuredExplanation(
                problem_interpretation="Explain Gauss law",
                concept_used="Gauss law",
                steps=[],
                final_answer="Phi_E = Qenc/epsilon0",
                quick_summary="Flux equals enclosed charge over permittivity.",
            ),
            "beginner",
            "mock explanation text",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr(
        "services.master_controller.classifier.classify",
        lambda *_args, **_kwargs: Classification(
            subject=SubjectCategory.REASONING,
            complexity=ComplexityLevel.LOW,
            confidence=0.6,
            tokens_est=400,
            needs_steps=False,
        ),
    )
    monkeypatch.setattr("services.master_controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "conceptual"})
    monkeypatch.setattr("services.master_controller.model_router.route", _model_route)
    monkeypatch.setattr("services.master_controller.fallback_handler.generate_with_fallback", _fallback)
    monkeypatch.setattr("services.master_controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="What is the formula",
    )

    assert captured["subject"] == SubjectCategory.PHYSICS
    assert captured["complexity"] == ComplexityLevel.MEDIUM
    assert result.response.raw_text == "The formula for Gauss law is Phi_E = Qenc/epsilon0."
    assert result.trace.subject == "physics"


@pytest.mark.asyncio
async def test_topic_blocks_use_lexical_follow_up_for_generic_short_queries(monkeypatch):
    active = _block("block-gauss", [1.0, 0.0])
    seen = {}

    async def fake_embed(_text: str):
        return [0.0, 1.0]

    async def fake_get_active_block(_session_id: str):
        return active

    async def fake_get_recent_blocks(_session_id: str, limit: int = 5):
        return [active]

    async def fake_set_active_block(block_id: str):
        seen["block_id"] = block_id

    async def fake_log_decision(session_id: str, query: str, decision):
        seen["decision"] = decision

    monkeypatch.setattr("services.topic_blocks.embedding_generator.generate", fake_embed)
    monkeypatch.setattr(
        "services.topic_blocks.classifier.classify",
        lambda _query: Classification(subject=SubjectCategory.PHYSICS, complexity=ComplexityLevel.MEDIUM),
    )
    monkeypatch.setattr(topic_block_service, "get_active_block", fake_get_active_block)
    monkeypatch.setattr(topic_block_service, "get_recent_blocks", fake_get_recent_blocks)
    monkeypatch.setattr(topic_block_service, "set_active_block", fake_set_active_block)
    monkeypatch.setattr(topic_block_service, "log_decision", fake_log_decision)

    decision = await topic_block_service.route_query("session-1", "State it mathematically")

    assert decision.block_id == "block-gauss"
    assert decision.decision_type == "follow_up"
    assert decision.reason == "active_block_lexical_follow_up"
    assert seen["decision"].scores["lexical_follow_up_score"] >= 0.7
