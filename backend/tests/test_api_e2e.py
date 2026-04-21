from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core.exceptions import AIServiceError
from main import app
from services.master_controller import ControllerResponse, ControllerResult, DecisionTrace


def _controller_result(*, final_answer: str = "x = 2", confidence: float = 0.95, clarification: str | None = None) -> ControllerResult:
    response = ControllerResponse(
        final_answer=final_answer if clarification is None else "",
        steps=[{"step": 1, "explanation": "Subtract 2 from both sides."}] if clarification is None else [],
        concept="Linear equations" if clarification is None else "",
        simple_explanation=clarification or "Solve using inverse operations.",
        coach_feedback="Show the balancing step clearly.",
        confidence=confidence,
        raw_text=clarification or "x = 2",
        quick_summary=clarification or "x = 2",
        model_used="adaptive_explainer",
        parser_source="symbolic_solver",
        verification_confidence="high" if clarification is None else "low",
        verified=clarification is None,
        math_check_passed=clarification is None,
        math_engine_result="[2]" if clarification is None else None,
        clarification_request=clarification,
        credits_remaining=99,
    )
    trace = DecisionTrace(
        intent="solve",
        strategy="step_by_step",
        block_id=None,
        tool_used="sympy" if clarification is None else "validation",
        validation_passed=clarification is None,
    )
    return ControllerResult(response=response, trace=trace, session_id=None, block_id=None)


@pytest.mark.asyncio
async def test_solve_happy_path_uses_master_controller():
    with patch("routers.solver.user_rate_limiter.check_limit", new_callable=AsyncMock) as mock_limit, patch(
        "routers.solver.master_controller.handle_query",
        new_callable=AsyncMock,
    ) as mock_handle:
        mock_limit.return_value = {"allowed": True, "remaining": 99, "message": "OK"}
        mock_handle.return_value = _controller_result()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/solve", json={"question": "solve x + 2 = 4", "stream": False})

        assert response.status_code == 200
        payload = response.json()
        assert payload["final_answer"] == "x = 2"
        assert payload["verified"] is True
        assert payload["math_engine_result"] == "[2]"
        mock_handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_solve_rate_limit_failure_short_circuits_controller():
    with patch("routers.solver.user_rate_limiter.check_limit", new_callable=AsyncMock) as mock_limit, patch(
        "routers.solver.master_controller.handle_query",
        new_callable=AsyncMock,
    ) as mock_handle:
        mock_limit.return_value = {"allowed": False, "remaining": 0, "message": "No credits"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/solve", json={"question": "solve x + 2 = 4"})

        assert response.status_code == 429
        assert "No credits" in response.json()["detail"]
        mock_handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_solve_controller_outage_returns_503():
    with patch("routers.solver.user_rate_limiter.check_limit", new_callable=AsyncMock) as mock_limit, patch(
        "routers.solver.master_controller.handle_query",
        new_callable=AsyncMock,
    ) as mock_handle:
        mock_limit.return_value = {"allowed": True, "remaining": 99, "message": "OK"}
        mock_handle.side_effect = AIServiceError("All AI models unavailable")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/solve", json={"question": "solve x + 3 = 7"})

        assert response.status_code == 503
        assert response.json()["message"] == "All AI models unavailable"


@pytest.mark.asyncio
async def test_solve_validation_gate_response_shape():
    with patch("routers.solver.user_rate_limiter.check_limit", new_callable=AsyncMock) as mock_limit, patch(
        "routers.solver.master_controller.handle_query",
        new_callable=AsyncMock,
    ) as mock_handle:
        mock_limit.return_value = {"allowed": True, "remaining": 99, "message": "OK"}
        mock_handle.return_value = _controller_result(clarification="Please provide the function")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/solve", json={"question": "Solve derivative"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["final_answer"] == "Please provide the function"
        assert payload["verified"] is False
        assert payload["math_check_passed"] is False
