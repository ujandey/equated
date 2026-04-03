from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from db.models import SolveRequest
from routers.solver import solve_problem
from services.master_controller import ControllerResponse, ControllerResult, DecisionTrace


@pytest.mark.asyncio
async def test_incomplete_math_prompt_returns_controller_clarification():
    request = SimpleNamespace(state=SimpleNamespace(user_id="test-user-123"))
    req = SolveRequest(question="solve a double differentiation")

    with patch("routers.solver.user_rate_limiter.check_and_deduct", new_callable=AsyncMock) as mock_limit, patch(
        "routers.solver.master_controller.handle_query",
        new_callable=AsyncMock,
    ) as mock_handle:
        mock_limit.return_value = {"allowed": True, "remaining": 99, "message": "OK"}
        mock_handle.return_value = ControllerResult(
            response=ControllerResponse(
                final_answer="",
                steps=[],
                concept="",
                simple_explanation="Please provide the function",
                coach_feedback="",
                confidence=0.0,
                raw_text="Please provide the function",
                clarification_request="Please provide the function",
                verified=False,
                math_check_passed=False,
                parser_source="symbolic_solver",
            ),
            trace=DecisionTrace(
                intent="solve",
                strategy="validation_gate",
                block_id=None,
                tool_used="validation",
                validation_passed=False,
            ),
        )

        response = await solve_problem(req, request)

    assert response.final_answer == "Please provide the function"
    assert response.verified is False
    assert response.math_check_passed is False
    mock_handle.assert_awaited_once()
