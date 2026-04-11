"""
Services - Adaptive Explainer

Generates explanations tailored to a student's inferred proficiency level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import structlog

from ai.models import get_model
from config.settings import settings
from services.explanation import StructuredExplanation, explanation_generator

logger = structlog.get_logger("equated.services.adaptive_explainer")

ExplanationLevel = Literal["beginner", "intermediate", "advanced"]


@dataclass(frozen=True)
class PromptTemplate:
    """Container for level-specific prompting rules."""

    system: str
    user: str


PROMPT_TEMPLATES: dict[ExplanationLevel, PromptTemplate] = {
    "beginner": PromptTemplate(
        system=(
            "You are Equated, an adaptive tutor for beginners.\n"
            "Explain in simple language.\n"
            "Use one helpful analogy.\n"
            "Teach step by step.\n"
            "Avoid jargon unless you immediately explain it.\n"
            "Keep the tone encouraging and clear."
        ),
        user=(
            "Student level: beginner\n"
            "Problem:\n{problem}\n\n"
            "Verified solution:\n{solution}\n\n"
            "Write an explanation that:\n"
            "- uses simple language\n"
            "- includes an everyday analogy\n"
            "- breaks the work into clear numbered steps\n"
            "- ends with a short recap"
        ),
    ),
    "intermediate": PromptTemplate(
        system=(
            "You are Equated, an adaptive tutor for intermediate students.\n"
            "Balance clarity with mathematical precision.\n"
            "Explain why each step works.\n"
            "Use direct, readable language."
        ),
        user=(
            "Student level: intermediate\n"
            "Problem:\n{problem}\n\n"
            "Verified solution:\n{solution}\n\n"
            "Write an explanation that:\n"
            "- is clear and structured\n"
            "- shows the main steps and reasoning\n"
            "- uses correct technical terms when useful\n"
            "- ends with a concise summary"
        ),
    ),
    "advanced": PromptTemplate(
        system=(
            "You are Equated, an adaptive tutor for advanced students.\n"
            "Be concise, formal, and mathematically precise.\n"
            "Do not over-explain basic algebra or arithmetic.\n"
            "Prioritize the core derivation and final result."
        ),
        user=(
            "Student level: advanced\n"
            "Problem:\n{problem}\n\n"
            "Verified solution:\n{solution}\n\n"
            "Write an explanation that:\n"
            "- is concise\n"
            "- uses formal mathematical language\n"
            "- focuses on the essential derivation\n"
            "- ends with a brief conclusion"
        ),
    ),
}


class AdaptiveExplainerService:
    """Infers student level and generates level-aware explanations with an LLM."""

    DEFAULT_PROVIDER_ORDER = ("deepseek", "openai", "gemini", "groq", "mistral")

    def infer_level(self, student_model: dict[str, Any] | None) -> ExplanationLevel:
        """
        Infer the student's explanation level from the stored student model.

        Uses `assumed_level` when available and falls back to struggle signals.
        """
        if not student_model:
            return "intermediate"

        assumed_level = self._extract_assumed_level(student_model)
        if assumed_level is not None:
            if assumed_level < 0.4:
                return "beginner"
            if assumed_level >= 0.75:
                return "advanced"
            return "intermediate"

        weak_areas = student_model.get("weak_areas") or []
        interaction = student_model.get("interaction_signals") or {}
        struggle_score = (
            len(weak_areas)
            + int(interaction.get("hints_used", 0) or 0)
            + int(interaction.get("failures", 0) or 0)
        )
        if struggle_score >= 3:
            return "beginner"

        learning_velocity = student_model.get("learning_velocity") or {}
        if float(learning_velocity.get("overall", 0.0) or 0.0) > 0.18:
            return "advanced"

        return "intermediate"

    async def generate_explanation(
        self,
        problem: str,
        solution: str,
        level: ExplanationLevel,
        preferred_provider: str | None = None,
        teaching_directives: list[str] | None = None,
    ) -> str:
        """Generate an explanation using the first available LLM provider."""
        template = PROMPT_TEMPLATES[level]
        messages = [
            {"role": "system", "content": template.system},
            {
                "role": "user",
                "content": self._build_user_prompt(
                    template=template,
                    problem=problem,
                    solution=solution,
                    teaching_directives=teaching_directives,
                ),
            },
        ]

        last_error: Exception | None = None
        for provider in self._provider_sequence(preferred_provider):
            try:
                model = get_model(provider)
                response = await model.generate(
                    messages=messages,
                    max_tokens=900,
                    temperature=self._temperature_for_level(level),
                )

                logger.info(
                    "adaptive_explanation_generated",
                    level=level,
                    provider=provider,
                    model=response.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
                return response.content.strip()
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "adaptive_explanation_provider_failed",
                    level=level,
                    provider=provider,
                    error=str(exc),
                )

        if last_error:
            raise last_error
        raise RuntimeError("No AI provider configured for adaptive explanations.")

    async def generate_structured_explanation(
        self,
        problem: str,
        solution: str,
        student_model: dict[str, Any] | None = None,
        level: ExplanationLevel | None = None,
        preferred_provider: str | None = None,
        prefer_existing_text: bool = False,
        teaching_directives: list[str] | None = None,
    ) -> tuple[StructuredExplanation, ExplanationLevel]:
        """
        Generate and parse a level-adaptive explanation into the standard schema.
        """
        resolved_level = level or self.infer_level(student_model)
        if prefer_existing_text:
            structured = explanation_generator.generate(solution, problem)
            return structured, resolved_level

        adaptive_text = await self.generate_explanation(
            problem,
            solution,
            resolved_level,
            preferred_provider=preferred_provider,
            teaching_directives=teaching_directives,
        )
        structured = explanation_generator.generate(adaptive_text, problem)
        return structured, resolved_level

    @staticmethod
    def _build_user_prompt(
        *,
        template: PromptTemplate,
        problem: str,
        solution: str,
        teaching_directives: list[str] | None,
    ) -> str:
        prompt = template.user.format(problem=problem.strip(), solution=solution.strip())
        directives = [directive.strip() for directive in (teaching_directives or []) if directive and directive.strip()]
        if not directives:
            return prompt
        extra = "\n".join(f"- {directive}" for directive in directives)
        return f"{prompt}\n- follow these additional teaching instructions:\n{extra}"

    def _extract_assumed_level(self, student_model: dict[str, Any]) -> float | None:
        direct_value = student_model.get("assumed_level")
        if direct_value is not None:
            return self._clamp_level(direct_value)

        topics = student_model.get("topics") or []
        if not topics:
            return None

        topic_levels = [
            self._clamp_level(topic.get("assumed_level"))
            for topic in topics
            if topic.get("assumed_level") is not None
        ]
        topic_levels = [value for value in topic_levels if value is not None]
        if not topic_levels:
            return None

        return sum(topic_levels) / len(topic_levels)

    def _clamp_level(self, value: Any) -> float | None:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return None

    def _provider_sequence(self, preferred_provider: str | None = None) -> list[str]:
        provider_keys = {
            "openai": settings.OPENAI_API_KEY,
            "deepseek": settings.DEEPSEEK_API_KEY,
            "gemini": settings.GEMINI_API_KEY,
            "groq": settings.GROQ_API_KEY,
            "mistral": settings.MISTRAL_API_KEY,
        }
        ordered = list(self.DEFAULT_PROVIDER_ORDER)
        if preferred_provider in provider_keys:
            ordered = [preferred_provider] + [provider for provider in ordered if provider != preferred_provider]

        return [
            provider
            for provider in ordered
            if settings._is_set(provider_keys[provider])
        ]

    def _select_provider(self) -> str:
        providers = self._provider_sequence()
        if providers:
            return providers[0]
        raise RuntimeError("No AI provider configured for adaptive explanations.")

    def _temperature_for_level(self, level: ExplanationLevel) -> float:
        return {
            "beginner": 0.55,
            "intermediate": 0.35,
            "advanced": 0.15,
        }[level]


adaptive_explainer = AdaptiveExplainerService()
