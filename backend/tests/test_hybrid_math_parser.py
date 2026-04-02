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

from services.hybrid_math_parser import HybridMathParser, StructuredMathParse


class _FakeModel:
    def __init__(self, content: str):
        self.content = content

    async def generate(self, *_args, **_kwargs):
        return SimpleNamespace(content=self.content)


def test_heuristic_fast_path_for_equation():
    parser = HybridMathParser()

    parsed = parser.heuristic_parse("solve x^2 - 5x + 6 = 0")

    assert parsed is not None
    assert parsed.operation == "solve"
    assert parsed.expression == "x**2 - 5x + 6 = 0"
    assert parsed.variable == "x"
    assert parsed.extra["heuristic_confidence"] == "high"


def test_validate_json_rejects_unsupported_operation():
    parser = HybridMathParser()

    assert parser.validate_json({"operation": "factor", "expression": "x^2 - 1"}) is False


def test_detect_incomplete_request_for_double_differentiation():
    parser = HybridMathParser()

    message = parser.detect_incomplete_request("solve a double differentiation")

    assert message is not None
    assert "differentiate" in message.lower()


def test_detect_incomplete_request_allows_explicit_derivative_expression():
    parser = HybridMathParser()

    message = parser.detect_incomplete_request("find the derivative of sin(x^2)")

    assert message is None


@pytest.mark.asyncio
async def test_hybrid_parse_falls_back_to_llm(monkeypatch):
    parser = HybridMathParser()
    llm_json = """
    {
      "operation": "differentiate",
      "expression": "sin(x^2)",
      "variable": "x",
      "bounds": null,
      "extra": {}
    }
    """

    monkeypatch.setattr(
        "services.hybrid_math_parser.get_model",
        lambda _provider, _model_name: _FakeModel(llm_json),
    )
    monkeypatch.setattr(
        parser,
        "_select_parser_model",
        lambda: ("groq", "llama-3.3-70b-versatile"),
    )

    result = await parser.hybrid_parse("What is the derivative of sin(x^2)?")

    assert result.source == "llm"
    assert result.confidence == "medium"
    assert result.parsed is not None
    assert result.parsed.operation == "differentiate"
    assert result.math_result is not None
    assert result.math_result.success is True
    assert "2*x*cos" in result.math_result.result


@pytest.mark.asyncio
async def test_hybrid_parse_uses_heuristic_fallback_when_llm_unavailable(monkeypatch):
    parser = HybridMathParser()

    async def _boom(_user_input):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(parser, "call_llm_parser", _boom)

    result = await parser.hybrid_parse("calculate x + 2")

    assert result.source == "heuristic_fallback"
    assert result.parsed is not None
    assert result.parsed.operation == "evaluate"
    assert result.math_result is not None
    assert "x + 2" in result.math_result.result
