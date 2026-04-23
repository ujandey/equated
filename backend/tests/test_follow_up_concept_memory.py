from types import SimpleNamespace

import pytest

from services.master_controller import master_controller
from services.topic_blocks import AnchorMatch, TopicRoutingDecision, topic_block_service


def _routing(block_id: str, decision_type: str = "new_topic", anchor_kind: str | None = None) -> TopicRoutingDecision:
    return TopicRoutingDecision(
        block_id=block_id,
        decision_type=decision_type,
        reason="test",
        is_new_block=decision_type == "new_topic",
        scores={},
        thresholds={},
        anchor=AnchorMatch(kind=anchor_kind, text=None, confidence=0.93 if anchor_kind else 0.0),
        subject="physics",
    )


@pytest.mark.asyncio
async def test_follow_up_formula_query_includes_topic_memory(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="Gauss's law formula: Phi_E = Qenc/epsilon0",
                steps=[],
                concept_used="Electrostatics",
                quick_summary="Flux equals enclosed charge over permittivity.",
                problem_interpretation="Explain Gauss law",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
            "mock explanation text",
        )

    async def _get_block(_block_id: str):
        return SimpleNamespace(
            topic_label="physics: Explain Gauss law",
            summary="User asked about Gauss law and then requested simpler explanations.",
        )

    async def _context_messages(_block_id: str, max_messages: int = 4):
        return [
            {"role": "user", "content": "Explain Gauss law"},
            {"role": "assistant", "content": "Gauss law connects electric flux to enclosed charge."},
            {"role": "user", "content": "Explain simply"},
            {"role": "assistant", "content": "It says the total field leaving a closed surface depends on how much charge is inside."},
        ]

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "conceptual"})
    monkeypatch.setattr("services.master_controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="physics")))
    monkeypatch.setattr("services.master_controller.model_router.route", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr("services.master_controller.topic_block_service.get_block", _get_block)
    monkeypatch.setattr("services.master_controller.topic_block_service.get_context_messages", _context_messages)
    async def _route(**_kwargs):
        return _routing("block-gauss", "follow_up", anchor_kind="concept_reference")

    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr("services.master_controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    captured = {}

    async def _fallback(messages, *_args, **_kwargs):
        captured["messages"] = messages
        return SimpleNamespace(content="Gauss law formula is Phi_E = Qenc/epsilon0", model="mock-model")

    monkeypatch.setattr("services.master_controller.fallback_handler.generate_with_fallback", _fallback)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Now give formula",
    )

    assert result.trace.intent == "follow_up"
    assert "Qenc" in result.response.final_answer
    assert any("Current topic: physics: Explain Gauss law" in message["content"] for message in captured["messages"] if message["role"] == "system")
    assert any(message["content"] == "Explain Gauss law" for message in captured["messages"] if message["role"] == "user")


def test_concept_reference_anchor_detects_formula_request():
    anchor = topic_block_service.extract_anchor("Now give formula")

    assert anchor.kind == "concept_reference"
    assert anchor.confidence >= 0.9
