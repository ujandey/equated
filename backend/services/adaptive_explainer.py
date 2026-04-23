"""
Services - Adaptive Explainer

Generates explanations tailored to a student's inferred proficiency level.
"""

from __future__ import annotations

import json
import re
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


_SHARED_RULES = (
    "Use LaTeX for all math — $inline$ for inline expressions, $$display$$ for equations on their own line.\n"
    "Keep the section headers exactly as written (## header name).\n"
    "No filler phrases. No 'Great question!' or preamble. Start directly with ## Problem Interpretation."
)

_SECTION_TEMPLATE = (
    "Problem: {problem}\n\n"
    "Verified answer: {solution}\n\n"
    "Explain this solution using the exact structure below:\n\n"
    "## Problem Interpretation\n"
    "{interp_hint}\n\n"
    "## Concept Used\n"
    "{concept_hint}\n\n"
    "## Step-by-Step Solution\n"
    "{steps_hint}\n\n"
    "## Final Answer\n"
    "State the answer clearly with proper LaTeX notation.\n\n"
    "## Quick Summary\n"
    "{summary_hint}\n\n"
    "{rules}"
)

PROMPT_TEMPLATES: dict[ExplanationLevel, PromptTemplate] = {
    "beginner": PromptTemplate(
        system=(
            "You are Equated, an encouraging STEM tutor for beginners. "
            "A verified mathematical answer is provided — your job is to explain "
            "how we arrive at it so clearly that a student with no prior exposure can follow every step."
        ),
        user=_SECTION_TEMPLATE.format(
            problem="{problem}",
            solution="{solution}",
            interp_hint="What are we solving and what are we looking for? (1–2 plain-English sentences)",
            concept_hint="Name the mathematical concept or method being applied. (1 line)",
            steps_hint=(
                "Number each step. Format each as:\n"
                "**Step 1: [short title]**\n"
                "[explanation — include an analogy or everyday example if it helps]\n\n"
                "Show every arithmetic operation. Explain WHY each step works, not just what it is."
            ),
            summary_hint="1–2 sentences: what did we do and what does the answer mean?",
            rules=_SHARED_RULES,
        ),
    ),
    "intermediate": PromptTemplate(
        system=(
            "You are Equated, a precise STEM tutor. "
            "A verified mathematical answer is provided. Explain it clearly — "
            "show all working and emphasise WHY each step is valid."
        ),
        user=_SECTION_TEMPLATE.format(
            problem="{problem}",
            solution="{solution}",
            interp_hint="What is the problem asking? (1–2 sentences)",
            concept_hint="The key mathematical method or theorem. (1 line)",
            steps_hint=(
                "Number each step. Format each as:\n"
                "**Step 1: [short title]**\n"
                "[explanation]\n\n"
                "Show all arithmetic. For any non-obvious step, explain the reasoning."
            ),
            summary_hint="1–2 sentences: which method was used and what the result means.",
            rules=_SHARED_RULES,
        ),
    ),
    "advanced": PromptTemplate(
        system=(
            "You are Equated, a concise STEM tutor for advanced students. "
            "A verified answer is provided. Be mathematically precise and efficient — "
            "skip trivial arithmetic explanations and focus on the key derivation."
        ),
        user=_SECTION_TEMPLATE.format(
            problem="{problem}",
            solution="{solution}",
            interp_hint="One sentence stating what we are solving.",
            concept_hint="Key method or theorem. (1 line)",
            steps_hint=(
                "Numbered steps, concise. Use formal mathematical language. Format each as:\n"
                "**Step 1: [short title]**\n"
                "[explanation — skip trivial arithmetic, focus on non-obvious moves]"
            ),
            summary_hint="One sentence.",
            rules=_SHARED_RULES,
        ),
    ),
}

# ---------------------------------------------------------------------------
# Structured JSON solution prompt — used when SymPy has already verified the
# answer and we need a clean, parseable JSON response for the SolutionCard.
# ---------------------------------------------------------------------------

STRUCTURED_SOLUTION_SYSTEM_PROMPT = r"""\
You are a STEM tutor generating a structured solution. You must return ONLY a valid JSON object. No explanation outside the JSON. No markdown. No backticks. No preamble.
The SymPy engine has already computed the correct answer. It will be provided to you. Your job is to write the pedagogical explanation AROUND the verified answer — never recompute it yourself.
STRICT RULES:

final_answer must contain ONLY a clean LaTeX expression. Examples:

Correct: "x = 2, \\, x = 3"
Correct: "v = 12.4 \\, \\text{m/s}"
Correct: "\\frac{dy}{dx} = \\cos(x) - \\sin(x)"
WRONG: "The solutions are x=2 and x=3 which can be written as..."
WRONG: "x = {2, 3} or in LaTeX notation..."
WRONG: Any sentence. Any explanation. Any words at all.

IMPORTANT: You must escape all backslashes in LaTeX equations. For example, write \\frac instead of \frac, and \\sqrt instead of \sqrt.

answer_summary must be exactly ONE sentence of plain English. No LaTeX. No math symbols.
Each step explanation must be 2-3 sentences maximum. No rambling.
Each step equation must be a LaTeX string only — no prose mixed in.
Never mention formatting, LaTeX, notation systems, or your own output format.
Never say "as requested", "following the format", "properly displayed as", or any self-referential phrase.
subject_hint must be exactly one of: "algebra", "calculus", "trigonometry", "statistics", "physics", "chemistry", "linear_algebra", "differential_equations"
"""

STRUCTURED_SOLUTION_USER_TEMPLATE = """\
VERIFIED ANSWER FROM SYMPY (use this exactly, do not recompute):
{sympy_result}
PROBLEM:
{problem_text}
Return this exact JSON structure:
{{
"problem_interpretation": "<one sentence: what is the problem asking>",
"concept_used": "<name of the mathematical concept, 2-4 words max>",
"concept_explanation": "<one sentence explaining the concept>",
"subject_hint": "<one of the eight subjects listed above>",
"steps": [
{{
"number": 1,
"title": "<step title, 3-6 words>",
"explanation": "<2-3 sentence explanation, plain English only>",
"equation": "<LaTeX string for the key equation in this step, or null if no equation>"
}}
],
"final_answer": "<LaTeX expression only — NO WORDS>",
"answer_summary": "<exactly one plain English sentence>",
"verification_status": "verified",
"confidence": 0.95
}}"""

STRUCTURED_SOLUTION_RETRY_ADDENDUM = r"""\
CRITICAL CORRECTION: Your previous final_answer contained words/sentences. This is not allowed.
final_answer must be ONLY a LaTeX math expression. Nothing else. No words. No explanation.
Example of correct final_answer: "x = 2, \\, x = 3"
"""


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
        prompt_override: str | None = None,
    ) -> str:
        """
        Generate an explanation using the first available LLM provider.

        When *prompt_override* is provided it replaces the template-based user
        message entirely.  This is used by the ExplanationPathBuilder to pass a
        fully-scripted prompt to the LLM.
        """
        template = PROMPT_TEMPLATES[level]
        if prompt_override:
            messages = [{"role": "user", "content": prompt_override}]
        else:
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
                    max_tokens=1500,
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
        prompt_override: str | None = None,
    ) -> tuple[StructuredExplanation, ExplanationLevel, str]:
        """
        Generate and parse a level-adaptive explanation into the standard schema.

        Returns (structured, level, raw_text) where raw_text is the LLM's direct
        output — callers should use this as raw_text_override to avoid garbling
        from the regex-based section parser.

        When *prompt_override* is provided it is forwarded to generate_explanation,
        replacing the default template.
        """
        resolved_level = level or self.infer_level(student_model)
        if prefer_existing_text:
            structured = explanation_generator.generate(solution, problem)
            return structured, resolved_level, solution

        adaptive_text = await self.generate_explanation(
            problem,
            solution,
            resolved_level,
            preferred_provider=preferred_provider,
            teaching_directives=teaching_directives,
            prompt_override=prompt_override,
        )
        structured = explanation_generator.generate(adaptive_text, problem)
        return structured, resolved_level, adaptive_text

    async def generate_structured_json_solution(
        self,
        problem: str,
        sympy_result: str,
        preferred_provider: str | None = None,
        retry_on_prose: bool = True,
    ) -> dict:
        """
        Generate a strictly-structured JSON solution using the new prompt.

        Calls the LLM with STRUCTURED_SOLUTION_SYSTEM_PROMPT, validates the
        response with parse_solution_response, and retries once if final_answer
        contains prose.
        """
        from services.master_controller.response_assembler import parse_solution_response

        user_content = STRUCTURED_SOLUTION_USER_TEMPLATE.format(
            sympy_result=sympy_result,
            problem_text=problem,
        )
        messages = [
            {"role": "system", "content": STRUCTURED_SOLUTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        last_error: Exception | None = None
        for provider in self._provider_sequence(preferred_provider):
            try:
                model = get_model(provider)
                response = await model.generate(
                    messages=messages,
                    max_tokens=1500,
                    temperature=0.2,
                )
                raw_output = response.content.strip()

                try:
                    parsed = parse_solution_response(raw_output)
                    parsed["model_used"] = response.model
                    return parsed
                except ValueError as ve:
                    if retry_on_prose and "final_answer contains prose" in str(ve):
                        logger.warning(
                            "structured_solution_prose_retry",
                            provider=provider,
                            error=str(ve),
                        )
                        # Retry with correction addendum
                        retry_messages = messages + [
                            {"role": "assistant", "content": raw_output},
                            {"role": "user", "content": STRUCTURED_SOLUTION_RETRY_ADDENDUM},
                        ]
                        retry_response = await model.generate(
                            messages=retry_messages,
                            max_tokens=1500,
                            temperature=0.1,
                        )
                        retry_raw = retry_response.content.strip()
                        parsed = parse_solution_response(retry_raw)
                        parsed["model_used"] = retry_response.model
                        return parsed
                    raise

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "structured_json_solution_provider_failed",
                    provider=provider,
                    error=str(exc),
                )

        if last_error:
            raise last_error
        raise RuntimeError("No AI provider configured for structured JSON solution.")

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
