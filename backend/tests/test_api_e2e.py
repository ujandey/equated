"""
Tests — API End-to-End

Comprehensive E2E integration test for the primary /api/v1/solve endpoint.
Validates the full request pipeline, including deduplication locks, caching,
rate limiting blocks, and LLM fallback handling.
"""

from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from db.models import SolveResponse
from core.exceptions import AIServiceError

# We mock dependencies to run fast, deterministic E2E assertions
# without hitting actual Redis/Postgres/LLM networks.

@pytest.fixture
def mock_pipeline():
    # Setup wholesale mocking of the pipeline's external integrations
    with patch("routers.solver.user_rate_limiter.check_and_deduct", new_callable=AsyncMock) as mock_limit, \
         patch("routers.solver.query_cache.lookup", new_callable=AsyncMock) as mock_cache_lookup, \
         patch("routers.solver.query_cache.store", new_callable=AsyncMock) as mock_cache_store, \
         patch("routers.solver.redis_client.set_nx", new_callable=AsyncMock) as mock_redis_lock, \
         patch("routers.solver.redis_client.delete", new_callable=AsyncMock) as mock_redis_del, \
         patch("routers.solver.fallback_handler.generate_with_fallback", new_callable=AsyncMock) as mock_fallback, \
         patch("routers.solver.explanation_generator.generate") as mock_explanation, \
         patch("routers.solver.verification_engine.verify") as mock_verify, \
         patch("routers.solver.verification_engine.analyze_problem", new_callable=AsyncMock) as mock_analyze:
         
        # Default mock returns
        mock_limit.return_value = {"allowed": True, "remaining": 99, "message": "OK"}
        
        mock_cache_lookup_result = MagicMock()
        mock_cache_lookup_result.found = False
        mock_cache_lookup.return_value = mock_cache_lookup_result
        
        mock_redis_lock.return_value = True # Acquired deduplication lock
        
        mock_fallback_result = MagicMock()
        mock_fallback_result.content = "x = 2"
        mock_fallback_result.model = "mock-gpt-4o"
        mock_fallback_result.input_tokens = 10
        mock_fallback_result.output_tokens = 5
        mock_fallback_result.total_cost_usd = 0.0001
        mock_fallback.return_value = mock_fallback_result
        
        mock_explanation_result = MagicMock()
        mock_explanation_result.final_answer = "x = 2"
        mock_explanation_result.problem_interpretation = "mocked"
        mock_explanation_result.concept_used = "mocked"
        mock_explanation_result.steps = []
        mock_explanation_result.quick_summary = ""
        mock_explanation_result.alternative_method = None
        mock_explanation_result.common_mistakes = None
        mock_explanation.return_value = mock_explanation_result
        
        mock_verify_result = MagicMock()
        mock_verify_result.is_verified = True
        mock_verify_result.confidence = MagicMock(value="high")
        mock_verify_result.method = "symbolic"
        mock_verify_result.math_check_passed = True
        mock_verify.return_value = mock_verify_result
        
        mock_analyze_result = MagicMock()
        mock_analyze_result.confidence = "high"
        mock_analyze_result.source = "heuristic"
        mock_analyze_result.math_result = MagicMock(success=True, result="[2]")
        mock_analyze.return_value = mock_analyze_result
        
        yield {
            "limit": mock_limit,
            "cache_lookup": mock_cache_lookup,
            "cache_store": mock_cache_store,
            "redis_lock": mock_redis_lock,
            "fallback": mock_fallback
        }


@pytest.mark.asyncio
async def test_solve_happy_path(mock_pipeline):
    """Test standard valid mathematical input via non-streaming POST."""
    
    # We also need to patch the auth middleware so we don't need valid JWTs
    # The middleware gets user_id from token. We will mock the Request directly
    # OR bypass middleware for tests. Let's patch the auth route dependency.
    
    from gateway.auth_middleware import AuthMiddleware
    with patch.object(AuthMiddleware, 'dispatch', new=lambda self, req, call_next: call_next(req)) as mock_auth:
        
        # Manually inject state that auth middleware would
        @app.middleware("http")
        async def inject_state(request, call_next):
            request.state.user_id = "test-user-123"
            return await call_next(request)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/solve", json={
                "question": "solve x + 2 = 4",
                "input_type": "text",
                "stream": False
            })
            
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["final_answer"] == "x = 2"
        assert data["verified"] is True
        assert data["credits_remaining"] == 99
        
        # Ensure lock was released
        mock_pipeline["redis_lock"].assert_called_once()
        
        # Ensure it was stored in cache
        mock_pipeline["cache_store"].assert_called_once()


@pytest.mark.asyncio
async def test_solve_rate_limit_failure(mock_pipeline):
    """Test 429 Too Many Requests response."""
    
    mock_pipeline["limit"].return_value = {"allowed": False, "remaining": 0, "message": "No credits"}
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/solve", json={
            "question": "solve x + 2 = 4",
        })
        
    assert response.status_code == 429
    assert "No credits" in response.json()["detail"]
    
    # Ensure no pipeline steps were called
    mock_pipeline["fallback"].assert_not_called()


@pytest.mark.asyncio
async def test_solve_llm_outage(mock_pipeline):
    """Test fallback failure (all models dead) 503 response."""
    
    # Return None to simulate full fallback failure
    mock_pipeline["fallback"].return_value = None
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/solve", json={
            "question": "solve x + 3 = 7",
        })
        
    assert response.status_code == 503
    assert "All AI models unavailable" in response.json()["detail"]


@pytest.mark.asyncio
async def test_solve_cache_hit_short_circuits(mock_pipeline):
    """Test that finding a cache hits returns immediately."""
    
    mock_cache_hit = MagicMock()
    mock_cache_hit.found = True
    mock_cache_hit.cached_solution = {"solution": "Cached Answer: x=99"}
    mock_pipeline["cache_lookup"].return_value = mock_cache_hit
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/solve", json={
            "question": "solve cached problem",
        })
        
    assert response.status_code == 200
    assert response.json()["final_answer"] == "Cached Answer: x=99"
    assert response.json()["cached"] is True
    
    # Ensure expensive ML pipeline was NOT called
    mock_pipeline["fallback"].assert_not_called()
    mock_pipeline["cache_store"].assert_not_called()

