import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(TESTS_DIR)

from services.math_engine import MathResult
from services.hybrid_math_parser import HybridParseResult, StructuredMathParse
from services.parser import ParsedProblem, InputType
from services.explanation import StructuredExplanation
from services.verification import VerificationResult
from routers import solver as solver_router
from routers import chat as chat_router


class _DummyRedis:
    async def set_nx(self, *_args, **_kwargs):
        return True

    async def exists(self, *_args, **_kwargs):
        return False

    async def delete(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_solve_endpoint_runs_math_verification(monkeypatch):
    from cache import redis_cache

    request = SimpleNamespace(state=SimpleNamespace(user_id="user-1"))
    req = SimpleNamespace(
        question="Solve 2*x + 3 = 7",
        image_base64=None,
        input_type="text",
        stream=False,
        session_id=None,
    )

    parsed = ParsedProblem(
        original_input=req.question,
        normalized_text="2*x + 3 = 7",
        input_type=InputType.TEXT,
        subject_tag="math",
        latex_expressions=[],
        confidence=0.95,
    )

    monkeypatch.setattr(redis_cache, "redis_client", _DummyRedis())
    monkeypatch.setattr(solver_router.user_rate_limiter, "check_and_deduct", _async_return({
        "allowed": True,
        "remaining": 4,
        "message": "",
    }))
    monkeypatch.setattr(solver_router.problem_parser, "parse", lambda **_kwargs: parsed)
    monkeypatch.setattr(solver_router.query_cache, "lookup", _async_return(SimpleNamespace(found=False)))
    monkeypatch.setattr(solver_router.classifier, "classify", lambda _text: SimpleNamespace())
    monkeypatch.setattr(
        solver_router.model_router,
        "route",
        lambda _classification: SimpleNamespace(
            provider=SimpleNamespace(value="deepseek"),
            max_tokens=512,
            temperature=0.2,
            model_name="deepseek-chat",
        ),
    )
    monkeypatch.setattr(solver_router.prompt_optimizer, "optimize", lambda messages: messages)
    monkeypatch.setattr(
        solver_router.fallback_handler,
        "generate_with_fallback",
        _async_return(SimpleNamespace(
            content="Step 1: subtract 3\nFinal answer: 2",
            model="deepseek-chat",
            input_tokens=10,
            output_tokens=15,
            total_cost_usd=0.001,
        )),
    )
    monkeypatch.setattr(
        solver_router.explanation_generator,
        "generate",
        lambda _raw, problem: StructuredExplanation(
            problem_interpretation=problem,
            concept_used="Linear equations",
            steps=[{"step": 1, "rule": "", "explanation": "Subtract 3 from both sides."}],
            final_answer="2",
            quick_summary="x = 2",
        ),
    )
    monkeypatch.setattr(solver_router.cost_optimizer, "record_call", lambda **_kwargs: None)
    monkeypatch.setattr(solver_router.query_cache, "store", _async_return(None))

    analysis_calls = []
    verify_calls = []

    monkeypatch.setattr(
        solver_router.verification_engine,
        "analyze_problem",
        _async_record_return(
            analysis_calls,
            "2*x + 3 = 7",
            HybridParseResult(
                parsed=StructuredMathParse(
                    operation="solve",
                    expression="2*x + 3 = 7",
                    variable="x",
                ),
                confidence="high",
                source="heuristic",
                parse_ok=True,
                execution_ok=True,
                math_result=MathResult(
                    expression="2*x + 3 = 7",
                    result="[2]",
                    latex_result="2",
                    steps=[],
                    success=True,
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        solver_router.verification_engine,
        "verify",
        lambda problem, answer, math_result: verify_calls.append((problem, answer, math_result.result)) or VerificationResult(
            is_verified=True,
            confidence=0.98,
            math_check_passed=True,
            discrepancies=[],
        ),
    )

    response = await solver_router.solve_problem(req, request)

    assert analysis_calls == ["2*x + 3 = 7"]
    assert verify_calls == [("2*x + 3 = 7", "2", "[2]")]
    assert response.parser_source == "heuristic"
    assert response.parser_confidence == "high"
    assert response.verified is True
    assert response.math_check_passed is True
    assert response.math_engine_result == "[2]"


@pytest.mark.asyncio
async def test_chat_stream_runs_math_verification(monkeypatch):
    req = chat_router.SendMessageRequest(content="Solve 2*x + 3 = 7", session_id="session-1")

    monkeypatch.setattr(chat_router.input_validator, "validate_query", lambda content: content)
    monkeypatch.setattr(chat_router.session_manager, "add_message", _async_return(None))
    monkeypatch.setattr(chat_router.session_manager, "get_context_messages", _async_return([]))
    monkeypatch.setattr(chat_router.context_compressor, "compress", lambda messages: messages)

    from cache import query_cache as query_cache_module
    from cache import cache_metrics as cache_metrics_module
    from workers import tasks as worker_tasks

    monkeypatch.setattr(query_cache_module.query_cache, "lookup", _async_return(SimpleNamespace(found=False)))
    monkeypatch.setattr(cache_metrics_module.cache_metrics, "record_redis_miss", lambda: None)
    monkeypatch.setattr(cache_metrics_module.cache_metrics, "record_vector_miss", lambda: None)

    from ai import classifier as classifier_module
    from ai import router as router_module
    from ai import models as models_module

    monkeypatch.setattr(classifier_module.classifier, "classify", lambda _text: SimpleNamespace())
    monkeypatch.setattr(
        router_module.model_router,
        "route",
        lambda _classification: SimpleNamespace(
            provider=SimpleNamespace(value="deepseek"),
            model_name="deepseek-chat",
            max_tokens=128,
            temperature=0.1,
        ),
    )

    class _Model:
        async def stream(self, *_args, **_kwargs):
            yield "Step 1: subtract 3\n"
            yield "Final answer: 2"

    monkeypatch.setattr(models_module, "get_model", lambda _provider: _Model())

    saved_messages = []
    cached_entries = []
    monkeypatch.setattr(worker_tasks.index_cache_entry, "delay", lambda query, content: cached_entries.append((query, content)))
    monkeypatch.setattr(
        worker_tasks.save_chat_message,
        "delay",
        lambda session_id, role, content, metadata: saved_messages.append((session_id, role, content, metadata)),
    )

    monkeypatch.setattr(
        chat_router.explanation_generator,
        "generate",
        lambda _raw, problem: StructuredExplanation(
            problem_interpretation=problem,
            concept_used="Linear equations",
            steps=[],
            final_answer="2",
            quick_summary="x = 2",
        ),
    )

    analysis_calls = []
    verify_calls = []
    monkeypatch.setattr(
        chat_router.verification_engine,
        "analyze_problem",
        _async_record_return(
            analysis_calls,
            "Solve 2*x + 3 = 7",
            HybridParseResult(
                parsed=StructuredMathParse(
                    operation="solve",
                    expression="2*x + 3 = 7",
                    variable="x",
                ),
                confidence="medium",
                source="llm",
                parse_ok=True,
                execution_ok=True,
                math_result=MathResult(
                    expression="2*x + 3 = 7",
                    result="[2]",
                    latex_result="2",
                    steps=[],
                    success=True,
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        chat_router.verification_engine,
        "verify",
        lambda problem, answer, math_result: verify_calls.append((problem, answer, math_result.result)) or VerificationResult(
            is_verified=True,
            confidence=0.97,
            math_check_passed=True,
            discrepancies=[],
        ),
    )

    response = await chat_router.stream_chat(req, user_id="user-1")
    body = []
    async for chunk in response.body_iterator:
        body.append(chunk)

    assert body
    assert analysis_calls == ["Solve 2*x + 3 = 7"]
    assert verify_calls == [("Solve 2*x + 3 = 7", "2", "[2]")]
    assert cached_entries == [("Solve 2*x + 3 = 7", "Step 1: subtract 3\nFinal answer: 2")]
    assert saved_messages
    assert saved_messages[0][3]["verified"] is True
    assert saved_messages[0][3]["math_engine_result"] == "[2]"
    assert saved_messages[0][3]["parser_source"] == "llm"
    assert saved_messages[0][3]["parser_confidence"] == "medium"


def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


def _async_record_return(calls, expected_value, result):
    async def _inner(value):
        calls.append(value)
        assert value == expected_value
        return result

    return _inner
