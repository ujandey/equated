"""
Tests — Image OCR Pipeline

Covers:
  • Single question extraction → SolveResponse
  • Multi-question extraction → MultiQuestionResponse
  • Low-confidence fallback → 422 low_confidence
  • Wrong file type rejection → 415
  • File too large rejection → 413
  • /solve/image/select happy path → SolveResponse
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from services.image_parser import LowConfidenceError, NoQuestionsError, ParseResult
from services.master_controller import ControllerResponse, ControllerResult, DecisionTrace


# ── Shared fixtures ───────────────────────────────────────────────────────────


def _make_controller_result(answer: str = "x = 3") -> ControllerResult:
    response = ControllerResponse(
        final_answer=answer,
        steps=[{"step": 1, "explanation": "Solved."}],
        concept="Algebra",
        simple_explanation="Solved using inverse operations.",
        coach_feedback="Good attempt.",
        confidence=0.95,
        raw_text=answer,
        quick_summary=answer,
        model_used="adaptive_explainer",
        parser_source="symbolic_solver",
        verification_confidence="high",
        verified=True,
        math_check_passed=True,
        math_engine_result="[3]",
        credits_remaining=50,
    )
    trace = DecisionTrace(
        intent="solve",
        strategy="step_by_step",
        block_id=None,
        tool_used="sympy",
        validation_passed=True,
    )
    return ControllerResult(response=response, trace=trace, session_id=None, block_id=None)


def _single_parse_result() -> ParseResult:
    return ParseResult(
        questions=["Solve x + 3 = 6"],
        latex_versions=["x + 3 = 6"],
        engine_used="gemini",
        confidence=0.92,
        subject_hints=["algebra"],
        raw_output='{"questions":[{"id":"1","text":"Solve x + 3 = 6","latex":"x + 3 = 6","subject_hint":"algebra"}],"overall_confidence":0.92}',
    )


def _multi_parse_result() -> ParseResult:
    return ParseResult(
        questions=["Solve x^2 - 4 = 0", "Differentiate sin(x)"],
        latex_versions=["x^2 - 4 = 0", r"\frac{d}{dx}\sin(x)"],
        engine_used="gemini",
        confidence=0.88,
        subject_hints=["algebra", "calculus"],
        raw_output="{}",
    )


def _low_confidence_result() -> ParseResult:
    return ParseResult(
        questions=["[UNCLEAR] something equals [UNCLEAR]"],
        latex_versions=["[UNCLEAR]"],
        engine_used="tesseract",
        confidence=0.35,
        subject_hints=["algebra"],
        raw_output="garbled text",
    )


def _minimal_png() -> bytes:
    """A 1×1 white PNG — valid image for content-type sniffing."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# ── Test: wrong file type → 415 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_file_type_returns_415():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/solve/image",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert response.status_code == 415
    assert "JPG" in response.json()["detail"] or "PNG" in response.json()["detail"]


# ── Test: file too large → 413 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_too_large_returns_413():
    big_bytes = b"\x00" * (11 * 1024 * 1024)  # 11 MB
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/solve/image",
            files={"file": ("big.png", big_bytes, "image/png")},
        )
    assert response.status_code == 413
    assert "10MB" in response.json()["detail"]


# ── Test: single question → SolveResponse ────────────────────────────────────


@pytest.mark.asyncio
async def test_single_question_returns_solve_response():
    with (
        patch("routers.solver.route_and_parse", new_callable=AsyncMock) as mock_parse,
        patch("routers.solver.master_controller.handle_query", new_callable=AsyncMock) as mock_solve,
        patch("routers.solver.user_rate_limiter.check_limit", new_callable=AsyncMock) as mock_limit,
    ):
        mock_parse.return_value = _single_parse_result()
        mock_solve.return_value = _make_controller_result("x = 3")
        mock_limit.return_value = {"allowed": True, "remaining": 50, "message": "OK"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/solve/image",
                files={"file": ("eq.png", _minimal_png(), "image/png")},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["final_answer"] == "x = 3"
    assert body["parser_source"] == "gemini"
    mock_solve.assert_awaited_once()


# ── Test: multi question → MultiQuestionResponse ──────────────────────────────


@pytest.mark.asyncio
async def test_multi_question_returns_selector_response():
    with patch("routers.solver.route_and_parse", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = _multi_parse_result()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/solve/image",
                files={"file": ("page.png", _minimal_png(), "image/png")},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "multi_question"
    assert len(body["questions"]) == 2
    assert body["questions"][0]["text"] == "Solve x^2 - 4 = 0"
    assert body["questions"][1]["subject_hint"] == "calculus"
    assert body["engine_used"] == "gemini"


# ── Test: low confidence → 422 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_returns_422():
    partial = _low_confidence_result()

    with patch("routers.solver.route_and_parse", new_callable=AsyncMock) as mock_parse:
        mock_parse.side_effect = LowConfidenceError(
            message="Could not read this image clearly.",
            partial_result=partial,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/solve/image",
                files={"file": ("blurry.png", _minimal_png(), "image/png")},
            )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "low_confidence"
    assert "partial_questions" in detail
    assert len(detail["partial_questions"]) == 1


# ── Test: /solve/image/select happy path ──────────────────────────────────────


@pytest.mark.asyncio
async def test_image_select_returns_solve_response():
    with (
        patch("routers.solver.master_controller.handle_query", new_callable=AsyncMock) as mock_solve,
        patch("routers.solver.user_rate_limiter.check_limit", new_callable=AsyncMock) as mock_limit,
    ):
        mock_solve.return_value = _make_controller_result("x = ±2")
        mock_limit.return_value = {"allowed": True, "remaining": 49, "message": "OK"}

        payload = {
            "question_id": "1",
            "questions": [
                {"id": "1", "text": "Solve x^2 - 4 = 0", "latex": "x^2 - 4 = 0", "subject_hint": "algebra"},
                {"id": "2", "text": "Differentiate sin(x)", "latex": r"\sin(x)", "subject_hint": "calculus"},
            ],
            "user_id": "test-user",
        }

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/solve/image/select", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["final_answer"] == "x = ±2"
    call_kwargs = mock_solve.call_args.kwargs
    assert call_kwargs["query"] == "Solve x^2 - 4 = 0"


# ── Test: invalid question_id in select → 400 ────────────────────────────────


@pytest.mark.asyncio
async def test_image_select_bad_id_returns_400():
    payload = {
        "question_id": "99",
        "questions": [
            {"id": "1", "text": "Solve x + 1 = 2", "latex": "x + 1 = 2", "subject_hint": "algebra"},
        ],
        "user_id": "test-user",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/solve/image/select", json=payload)

    assert response.status_code == 400
