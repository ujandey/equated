import asyncio

from services.adaptive_explainer import AdaptiveExplainerService, PROMPT_TEMPLATES
from ai.models import ModelResponse


def test_infer_level_returns_beginner_for_low_assumed_level():
    service = AdaptiveExplainerService()

    level = service.infer_level({"assumed_level": 0.2})

    assert level == "beginner"


def test_infer_level_returns_advanced_for_high_assumed_level():
    service = AdaptiveExplainerService()

    level = service.infer_level({"assumed_level": 0.9})

    assert level == "advanced"


def test_infer_level_uses_topic_average_when_root_level_missing():
    service = AdaptiveExplainerService()

    level = service.infer_level(
        {
            "topics": [
                {"topic": "algebra", "assumed_level": 0.8},
                {"topic": "geometry", "assumed_level": 0.7},
            ]
        }
    )

    assert level == "advanced"


def test_infer_level_falls_back_to_struggle_signals():
    service = AdaptiveExplainerService()

    level = service.infer_level(
        {
            "weak_areas": [{"topic": "fractions"}],
            "interaction_signals": {"hints_used": 1, "failures": 1},
        }
    )

    assert level == "beginner"


def test_prompt_templates_capture_level_rules():
    beginner_prompt = PROMPT_TEMPLATES["beginner"].user.lower()
    advanced_prompt = PROMPT_TEMPLATES["advanced"].user.lower()

    assert "analogy" in beginner_prompt
    assert "step" in beginner_prompt
    assert "concise" in advanced_prompt
    assert "formal" in advanced_prompt


def test_generate_structured_explanation_uses_llm_and_parses_output(monkeypatch):
    service = AdaptiveExplainerService()

    class DummyModel:
        async def generate(self, messages, max_tokens, temperature):
            assert messages[0]["role"] == "system"
            assert "beginner" in messages[1]["content"].lower()
            return ModelResponse(
                content=(
                    "**Problem Interpretation**\nSolve a simple sum.\n\n"
                    "**Concept Used**\nAddition\n\n"
                    "**Step-by-Step Solution**\nStep 1: Add the numbers.\n\n"
                    "**Final Answer**\n5\n\n"
                    "**Quick Summary**\nAdd both values."
                ),
                model="dummy-model",
                provider="dummy",
                input_tokens=10,
                output_tokens=20,
                total_cost_usd=0.0,
                finish_reason="stop",
            )

    monkeypatch.setattr("services.adaptive_explainer.get_model", lambda _provider: DummyModel())
    monkeypatch.setattr(service, "_select_provider", lambda: "openai")

    explanation, level, _ = asyncio.run(
        service.generate_structured_explanation(
            problem="2 + 3",
            solution="5",
            level="beginner",
        )
    )

    assert level == "beginner"
    assert explanation.concept_used == "Addition"
    assert explanation.final_answer == "5"
