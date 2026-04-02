import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(TESTS_DIR)

from core.exceptions import ValidationError
from db.models import SolveRequest
from routers.solver import solve_problem


@pytest.mark.asyncio
async def test_incomplete_math_prompt_fails_before_cache_or_model():
    request = SimpleNamespace(state=SimpleNamespace(user_id="test-user-123"))
    req = SolveRequest(question="solve a double differentiation")

    with patch("routers.solver.user_rate_limiter.check_and_deduct", new_callable=AsyncMock) as mock_limit, \
         patch("routers.solver.query_cache.lookup", new_callable=AsyncMock) as mock_cache_lookup, \
         patch("routers.solver.fallback_handler.generate_with_fallback", new_callable=AsyncMock) as mock_fallback:
        mock_limit.return_value = {"allowed": True, "remaining": 99, "message": "OK"}

        with pytest.raises(ValidationError) as exc_info:
            await solve_problem(req, request)

    assert "differentiate" in exc_info.value.message.lower()
    mock_cache_lookup.assert_not_called()
    mock_fallback.assert_not_called()
