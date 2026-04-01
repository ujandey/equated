import pytest

from ai.classifier import Classification, ComplexityLevel, SubjectCategory
from services.topic_blocks import AnchorMatch, TopicBlock, topic_block_service


def _block(block_id: str, embedding: list[float], status: str = "active") -> TopicBlock:
    return TopicBlock(
        id=block_id,
        session_id="session-1",
        status=status,
        subject="math",
        topic_label="math block",
        summary=None,
        centroid_embedding=embedding,
        last_question_embedding=embedding,
        question_count=1,
    )


@pytest.mark.asyncio
async def test_route_query_prefers_anchor_on_active_block(monkeypatch):
    active = _block("block-active", [1.0, 0.0])
    logged = {}

    async def fake_embed(_text: str):
        return [0.55, 0.45]

    async def fake_get_active_block(_session_id: str):
        return active

    async def fake_get_recent_blocks(_session_id: str, limit: int = 5):
        return [active]

    async def fake_set_active_block(block_id: str):
        logged["active_block"] = block_id

    async def fake_log_decision(session_id: str, query: str, decision):
        logged["decision"] = decision
        logged["query"] = query

    monkeypatch.setattr(
        "services.topic_blocks.embedding_generator.generate",
        fake_embed,
    )
    monkeypatch.setattr(
        "services.topic_blocks.classifier.classify",
        lambda _query: Classification(subject=SubjectCategory.MATH, complexity=ComplexityLevel.MEDIUM),
    )
    monkeypatch.setattr(topic_block_service, "get_active_block", fake_get_active_block)
    monkeypatch.setattr(topic_block_service, "get_recent_blocks", fake_get_recent_blocks)
    monkeypatch.setattr(topic_block_service, "set_active_block", fake_set_active_block)
    monkeypatch.setattr(topic_block_service, "log_decision", fake_log_decision)
    monkeypatch.setattr(
        topic_block_service,
        "extract_anchor",
        lambda _query: AnchorMatch(kind="step_reference", text="step 2", confidence=0.95),
    )

    decision = await topic_block_service.route_query("session-1", "Why in step 2?")

    assert decision.block_id == "block-active"
    assert decision.decision_type == "follow_up"
    assert decision.reason == "anchor:step_reference"
    assert logged["active_block"] == "block-active"
    assert logged["decision"].scores["sim_active_block"] > 0


@pytest.mark.asyncio
async def test_route_query_simplify_request_overrides_low_similarity(monkeypatch):
    active = _block("block-active", [1.0, 0.0])
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
        lambda _query: Classification(subject=SubjectCategory.MATH, complexity=ComplexityLevel.MEDIUM),
    )
    monkeypatch.setattr(topic_block_service, "get_active_block", fake_get_active_block)
    monkeypatch.setattr(topic_block_service, "get_recent_blocks", fake_get_recent_blocks)
    monkeypatch.setattr(topic_block_service, "set_active_block", fake_set_active_block)
    monkeypatch.setattr(topic_block_service, "log_decision", fake_log_decision)

    decision = await topic_block_service.route_query("session-1", "Explain it simply")

    assert decision.block_id == "block-active"
    assert decision.decision_type == "follow_up"
    assert decision.reason == "anchor:simplify_request_override"
    assert seen["block_id"] == "block-active"
    assert seen["decision"].anchor.kind == "simplify_request"


@pytest.mark.asyncio
async def test_route_query_creates_new_block_when_similarity_is_low(monkeypatch):
    active = _block("block-old", [1.0, 0.0])
    new_block = _block("block-new", [0.0, 1.0])
    calls = {"created": 0}

    async def fake_embed(_text: str):
        return [0.0, 1.0]

    async def fake_get_active_block(_session_id: str):
        return active

    async def fake_get_recent_blocks(_session_id: str, limit: int = 5):
        return [active]

    async def fake_create_block(session_id: str, subject: str, topic_label: str, query_embedding: list[float] | None):
        calls["created"] += 1
        return new_block

    async def fake_set_active_block(_block_id: str):
        return None

    async def fake_log_decision(session_id: str, query: str, decision):
        return None

    monkeypatch.setattr("services.topic_blocks.embedding_generator.generate", fake_embed)
    monkeypatch.setattr(
        "services.topic_blocks.classifier.classify",
        lambda _query: Classification(subject=SubjectCategory.MATH, complexity=ComplexityLevel.MEDIUM),
    )
    monkeypatch.setattr(topic_block_service, "extract_anchor", lambda _query: AnchorMatch())
    monkeypatch.setattr(topic_block_service, "get_active_block", fake_get_active_block)
    monkeypatch.setattr(topic_block_service, "get_recent_blocks", fake_get_recent_blocks)
    monkeypatch.setattr(topic_block_service, "create_block", fake_create_block)
    monkeypatch.setattr(topic_block_service, "set_active_block", fake_set_active_block)
    monkeypatch.setattr(topic_block_service, "log_decision", fake_log_decision)

    decision = await topic_block_service.route_query("session-1", "Explain projectile motion")

    assert decision.block_id == "block-new"
    assert decision.decision_type == "new_topic"
    assert decision.is_new_block is True
    assert calls["created"] == 1


@pytest.mark.asyncio
async def test_route_query_reopens_best_recent_block(monkeypatch):
    active = _block("block-active", [0.0, 1.0])
    best_recent = _block("block-reopen", [0.8, 0.2], status="closed")
    other_recent = _block("block-other", [0.1, 0.9], status="closed")
    seen = {}

    async def fake_embed(_text: str):
        return [0.82, 0.18]

    async def fake_get_active_block(_session_id: str):
        return active

    async def fake_get_recent_blocks(_session_id: str, limit: int = 5):
        return [active, best_recent, other_recent]

    async def fake_set_active_block(block_id: str):
        seen["block_id"] = block_id

    async def fake_log_decision(session_id: str, query: str, decision):
        seen["decision"] = decision

    monkeypatch.setattr("services.topic_blocks.embedding_generator.generate", fake_embed)
    monkeypatch.setattr(
        "services.topic_blocks.classifier.classify",
        lambda _query: Classification(subject=SubjectCategory.MATH, complexity=ComplexityLevel.MEDIUM),
    )
    monkeypatch.setattr(topic_block_service, "extract_anchor", lambda _query: AnchorMatch())
    monkeypatch.setattr(topic_block_service, "get_active_block", fake_get_active_block)
    monkeypatch.setattr(topic_block_service, "get_recent_blocks", fake_get_recent_blocks)
    monkeypatch.setattr(topic_block_service, "set_active_block", fake_set_active_block)
    monkeypatch.setattr(topic_block_service, "log_decision", fake_log_decision)

    decision = await topic_block_service.route_query("session-1", "Can we return to that earlier quadratic?")

    assert decision.block_id == "block-reopen"
    assert decision.decision_type == "reopen_topic"
    assert seen["block_id"] == "block-reopen"
    assert seen["decision"].scores["best_recent_block_id"] == "block-reopen"
