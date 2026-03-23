"""
AI — Fallback Handler

Manages model retries and fallback escalation when a primary model fails.
Each provider has a pre-configured fallback chain.

Fallback Strategy:
  1. Retry same model once (transient errors)
  2. Try fallback model (different provider)
  3. Try emergency model (cheapest available)
  4. Return error to user

All failures are logged with latency and error details for monitoring.
"""

import time
import structlog
from typing import AsyncIterator

from ai.models import get_model, ModelResponse, MODEL_REGISTRY
from ai.router import RoutingDecision, ModelProvider, model_router
from services.model_usage_tracker import model_usage_tracker, UsageEntry

logger = structlog.get_logger("equated.ai.fallback")


class FallbackHandler:
    """
    Executes AI model calls with automatic retry and fallback.

    Tracks every attempt (success or failure) for cost monitoring.
    """

    MAX_RETRIES: int = 1           # Retries on same model
    EMERGENCY_PROVIDERS = [        # Last-resort order
        ModelProvider.GROQ,
        ModelProvider.GEMINI,
        ModelProvider.OPENAI,
        ModelProvider.DEEPSEEK,
        ModelProvider.MISTRAL,
    ]

    async def generate_with_fallback(
        self,
        messages: list[dict],
        decision: RoutingDecision,
        user_id: str = "",
    ) -> ModelResponse:
        """
        Call the AI model with retry → fallback → emergency.
        Logs all attempts to model_usage_tracker.
        """
        attempts = []

        # ── Attempt 1: Primary model ───────────────
        response = await self._try_model(
            decision.provider.value,
            decision.model_name,
            messages,
            decision.max_tokens,
            decision.temperature,
            user_id,
        )
        if response:
            return response
        attempts.append(decision.provider.value)

        # ── Attempt 2: Retry primary once ──────────
        response = await self._try_model(
            decision.provider.value,
            decision.model_name,
            messages,
            decision.max_tokens,
            decision.temperature,
            user_id,
        )
        if response:
            return response

        # ── Attempt 3: Configured fallback ─────────
        if decision.fallback_provider and decision.fallback_model:
            logger.warning(
                "using_fallback",
                from_provider=decision.provider.value,
                to_provider=decision.fallback_provider.value,
            )
            response = await self._try_model(
                decision.fallback_provider.value,
                decision.fallback_model,
                messages,
                decision.max_tokens,
                decision.temperature,
                user_id,
            )
            if response:
                return response
            attempts.append(decision.fallback_provider.value)

        # ── Attempt 4: Emergency fallback ──────────
        for provider in self.EMERGENCY_PROVIDERS:
            if provider.value in attempts:
                continue
            if provider.value not in MODEL_REGISTRY:
                continue

            logger.warning("emergency_fallback", provider=provider.value)
            _, default_model = MODEL_REGISTRY[provider.value]
            response = await self._try_model(
                provider.value,
                default_model,
                messages,
                decision.max_tokens,
                decision.temperature,
                user_id,
            )
            if response:
                return response
            attempts.append(provider.value)

        # All providers failed
        from core.exceptions import AIServiceError
        raise AIServiceError(
            f"All AI providers failed after {len(attempts)} attempts.",
            provider=", ".join(attempts),
        )

    async def stream_with_fallback(
        self,
        messages: list[dict],
        decision: RoutingDecision,
        user_id: str = "",
    ) -> AsyncIterator[str]:
        """
        Stream tokens with fallback.
        If primary stream fails, falls back to generate() and yields full response.
        """
        try:
            model = get_model(decision.provider.value, decision.model_name)
            async for token in model.stream(messages, decision.max_tokens, decision.temperature):
                yield token
            return
        except Exception as e:
            logger.warning(
                "stream_fallback_to_generate",
                provider=decision.provider.value,
                error=str(e)[:100],
            )

        # Fallback: use generate() and yield the full response
        response = await self.generate_with_fallback(messages, decision, user_id)
        yield response.content

    async def _try_model(
        self, provider: str, model_name: str,
        messages: list[dict], max_tokens: int,
        temperature: float, user_id: str,
    ) -> ModelResponse | None:
        """
        Attempt a single model call. Returns ModelResponse on success, None on failure.
        Logs usage regardless of outcome.
        """
        start = time.perf_counter()
        try:
            model = get_model(provider, model_name)
            response = await model.generate(messages, max_tokens, temperature)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)

            # Log successful call
            await model_usage_tracker.log_usage(UsageEntry(
                user_id=user_id,
                model=response.model,
                provider=provider,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.total_cost_usd,
                latency_ms=latency_ms,
                success=True,
            ))

            return response

        except Exception as e:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "model_call_failed",
                provider=provider,
                model=model_name,
                error=str(e)[:200],
                latency_ms=latency_ms,
            )

            # Log failed call
            await model_usage_tracker.log_usage(UsageEntry(
                user_id=user_id,
                model=model_name,
                provider=provider,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=latency_ms,
                success=False,
                error=str(e)[:200],
            ))

            return None


# Singleton
fallback_handler = FallbackHandler()
