from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from routers import chat as chat_router
from routers import solver as solver_router
from services.master_controller import ControllerResponse, ControllerResult, DecisionTrace


def _result_for_router(*, intent: str = "solve", tool_used: str = "sympy") -> ControllerResult:
    return ControllerResult(
        response=ControllerResponse(
            final_answer="x = 2",
            steps=[{"step": 1, "explanation": "Subtract 3 from both sides."}],
            concept="Linear equations",
            simple_explanation="x = 2",
            coach_feedback="Check algebraic balance each step.",
            confidence=0.95,
            raw_text="Step 1: subtract 3\nFinal answer: x = 2",
            parser_source="symbolic_solver",
            verification_confidence="high",
            verified=True,
            math_check_passed=True,
            math_engine_result="[2]",
            model_used="adaptive_explainer",
        ),
        trace=DecisionTrace(
            intent=intent,
            strategy="step_by_step",
            block_id="block-1",
            tool_used=tool_used,
            validation_passed=True,
        ),
        session_id="session-1",
        block_id="block-1",
        topic_mode="follow_up",
    )


@pytest.mark.asyncio
async def test_solve_endpoint_delegates_to_master_controller():
    request = SimpleNamespace(state=SimpleNamespace(user_id="user-1"))
    req = SimpleNamespace(question="Solve 2*x + 3 = 7", stream=False, session_id=None)

    with patch.object(solver_router.user_rate_limiter, "check_and_deduct", new_callable=AsyncMock) as mock_limit, patch.object(
        solver_router.master_controller,
        "handle_query",
        new_callable=AsyncMock,
    ) as mock_handle:
        mock_limit.return_value = {"allowed": True, "remaining": 4, "message": ""}
        mock_handle.return_value = _result_for_router()

        response = await solver_router.solve_problem(req, request)

    assert response.final_answer == "x = 2"
    assert response.verified is True
    assert response.math_engine_result == "[2]"
    mock_handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_stream_delegates_to_master_controller():
    req = chat_router.SendMessageRequest(content="Solve 2*x + 3 = 7", session_id="session-1")
    captured = {}

    with patch.object(chat_router.master_controller, "handle_query", new_callable=AsyncMock) as mock_handle, patch.object(
        chat_router.streaming_service,
        "create_sse_response",
        side_effect=lambda token_stream, model_name, session_id, done_meta: {
            "model_name": model_name,
            "session_id": session_id,
            "done_meta": done_meta,
            "token_stream": token_stream,
        },
    ):
        mock_handle.return_value = _result_for_router(intent="follow_up")
        response = await chat_router.stream_chat(req, user_id="user-1")
        captured.update(response)

    assert captured["model_name"] == "adaptive_explainer"
    assert captured["session_id"] == "session-1"
    assert captured["done_meta"]["tool_used"] == "sympy"
    assert captured["done_meta"]["intent"] == "follow_up"
    assert captured["done_meta"]["validation_passed"] is True
