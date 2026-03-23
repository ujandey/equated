"""
AI — Model Wrappers

Unified interface for all AI model providers.
Each wrapper exposes the same generate() and stream() methods
so the router can call any model interchangeably.

Supported Providers:
  - DeepSeek  (R1 / V3 — best for math + STEM reasoning)
  - Mistral   (Codestral / Large — best for coding)
  - OpenAI    (GPT-4o / GPT-4o-mini — best for reasoning)
  - Gemini    (2.0 Flash / Pro — fast + cheap general)
  - Groq      (Llama 3.3 70B — free tier, low-latency)
  - Local     (future — Ollama / vLLM)
"""

import json
import time
import structlog
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

from config.settings import settings

logger = structlog.get_logger("equated.ai.models")


# ── Standardized Response ───────────────────────────
@dataclass
class ModelResponse:
    """Standardized response from any model."""
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    finish_reason: str
    latency_ms: float = 0.0


# ── Abstract Base ───────────────────────────────────
class BaseModel(ABC):
    """Abstract base class for all model wrappers."""

    provider: str = ""

    @abstractmethod
    async def generate(self, messages: list[dict], max_tokens: int, temperature: float) -> ModelResponse:
        ...

    @abstractmethod
    async def stream(self, messages: list[dict], max_tokens: int, temperature: float) -> AsyncIterator[str]:
        ...


# ── OpenAI-Compatible Helper ───────────────────────
class OpenAICompatibleModel(BaseModel):
    """
    Base class for any model using the OpenAI-compatible chat completions API.
    DeepSeek, Groq, Mistral, and others all use this format.
    """

    def __init__(self, base_url: str, api_key: str, model_name: str,
                 provider: str, cost_input: float, cost_output: float,
                 timeout: float = 60.0):
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.provider = provider
        self.cost_per_1k_input = cost_input
        self.cost_per_1k_output = cost_output
        self.timeout = timeout

    async def generate(self, messages: list[dict], max_tokens: int = 4096,
                       temperature: float = 0.3) -> ModelResponse:
        start = time.perf_counter()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = (input_tokens * self.cost_per_1k_input + output_tokens * self.cost_per_1k_output) / 1000

        logger.info(
            "model_call",
            provider=self.provider,
            model=self.model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            latency_ms=latency_ms,
        )

        return ModelResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", self.model_name),
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost_usd=cost,
            finish_reason=data["choices"][0].get("finish_reason", "stop"),
            latency_ms=latency_ms,
        )

    async def stream(self, messages: list[dict], max_tokens: int = 4096,
                     temperature: float = 0.3) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=self.timeout * 2) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line.removeprefix("data: "))
                            delta = chunk["choices"][0].get("delta", {})
                            if content := delta.get("content"):
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue


# ══════════════════════════════════════════════════════
#  PROVIDER IMPLEMENTATIONS
# ══════════════════════════════════════════════════════


class DeepSeekModel(OpenAICompatibleModel):
    """
    DeepSeek R1 / V3 — Best for math and STEM reasoning.

    Pricing (per 1K tokens):
      Input:  $0.00055
      Output: $0.00219
    """

    def __init__(self, model_name: str = "deepseek-reasoner"):
        super().__init__(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY,
            model_name=model_name,
            provider="deepseek",
            cost_input=0.00055,
            cost_output=0.00219,
            timeout=90.0,  # Reasoning models can be slow
        )


class MistralModel(OpenAICompatibleModel):
    """
    Mistral Codestral / Large — Best for code generation and analysis.

    Pricing (per 1K tokens):
      Codestral:  Input $0.0003, Output $0.0009
      Large:      Input $0.002,  Output $0.006
    """

    # Mistral uses OpenAI-compatible API
    MODELS = {
        "codestral-latest":  {"input": 0.0003, "output": 0.0009},
        "mistral-large-latest": {"input": 0.002,  "output": 0.006},
        "mistral-small-latest": {"input": 0.0002, "output": 0.0006},
    }

    def __init__(self, model_name: str = "codestral-latest"):
        costs = self.MODELS.get(model_name, self.MODELS["codestral-latest"])
        super().__init__(
            base_url=settings.MISTRAL_BASE_URL,
            api_key=settings.MISTRAL_API_KEY,
            model_name=model_name,
            provider="mistral",
            cost_input=costs["input"],
            cost_output=costs["output"],
            timeout=60.0,
        )


class OpenAIModel(OpenAICompatibleModel):
    """
    OpenAI GPT-4o / GPT-4o-mini — Best for complex reasoning and general tasks.

    Pricing (per 1K tokens):
      GPT-4o-mini: Input $0.00015, Output $0.0006
      GPT-4o:      Input $0.0025,  Output $0.01
    """

    MODELS = {
        "gpt-4o-mini":  {"input": 0.00015, "output": 0.0006},
        "gpt-4o":       {"input": 0.0025,  "output": 0.01},
    }

    def __init__(self, model_name: str = "gpt-4o-mini"):
        costs = self.MODELS.get(model_name, self.MODELS["gpt-4o-mini"])
        super().__init__(
            base_url=settings.OPENAI_BASE_URL,
            api_key=settings.OPENAI_API_KEY,
            model_name=model_name,
            provider="openai",
            cost_input=costs["input"],
            cost_output=costs["output"],
            timeout=60.0,
        )


class GeminiModel(BaseModel):
    """
    Google Gemini 2.0 Flash / Pro — Fast, cheap, great for general queries.

    Pricing (per 1K tokens):
      Flash: Input $0.0001, Output $0.0004 (practically free)
      Pro:   Input $0.00125, Output $0.005
    """

    MODELS = {
        "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
        "gemini-2.0-pro":   {"input": 0.00125, "output": 0.005},
    }

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        self.provider = "gemini"
        self.api_key = settings.GEMINI_API_KEY
        costs = self.MODELS.get(model_name, self.MODELS["gemini-2.0-flash"])
        self.cost_per_1k_input = costs["input"]
        self.cost_per_1k_output = costs["output"]

    async def generate(self, messages: list[dict], max_tokens: int = 4096,
                       temperature: float = 0.3) -> ModelResponse:
        """Call Gemini via the Google AI API (REST)."""
        start = time.perf_counter()

        # Convert OpenAI message format to Gemini format
        contents = self._convert_messages(messages)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent",
                params={"key": self.api_key},
                json={
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        # Extract response content
        content = ""
        if "candidates" in data and data["candidates"]:
            parts = data["candidates"][0].get("content", {}).get("parts", [])
            content = "".join(p.get("text", "") for p in parts)

        # Extract usage
        usage = data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)
        cost = (input_tokens * self.cost_per_1k_input + output_tokens * self.cost_per_1k_output) / 1000

        logger.info(
            "model_call",
            provider="gemini",
            model=self.model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            latency_ms=latency_ms,
        )

        return ModelResponse(
            content=content,
            model=self.model_name,
            provider="gemini",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost_usd=cost,
            finish_reason=data.get("candidates", [{}])[0].get("finishReason", "STOP"),
            latency_ms=latency_ms,
        )

    async def stream(self, messages: list[dict], max_tokens: int = 4096,
                     temperature: float = 0.3) -> AsyncIterator[str]:
        """Stream from Gemini via the REST streaming endpoint."""
        contents = self._convert_messages(messages)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:streamGenerateContent",
                params={"key": self.api_key, "alt": "sse"},
                json={
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "temperature": temperature,
                    },
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line.removeprefix("data: "))
                            candidates = chunk.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    if text := part.get("text"):
                                        yield text
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        """Convert OpenAI message format → Gemini contents format."""
        contents = []
        system_text = ""

        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "system":
                system_text += content + "\n"
            elif role == "user":
                text = (system_text + content) if system_text else content
                system_text = ""
                contents.append({
                    "role": "user",
                    "parts": [{"text": text}],
                })
            elif role == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [{"text": content}],
                })

        # If only system message, add as user
        if system_text and not contents:
            contents.append({
                "role": "user",
                "parts": [{"text": system_text}],
            })

        return contents


class GroqModel(OpenAICompatibleModel):
    """
    Groq (Llama 3.3 70B) — Free tier, sub-200ms responses.

    Pricing: FREE (rate-limited)
    """

    def __init__(self, model_name: str = "llama-3.3-70b-versatile"):
        super().__init__(
            base_url=settings.GROQ_BASE_URL,
            api_key=settings.GROQ_API_KEY,
            model_name=model_name,
            provider="groq",
            cost_input=0.0,
            cost_output=0.0,
            timeout=30.0,
        )


# ══════════════════════════════════════════════════════
#  FACTORY
# ══════════════════════════════════════════════════════

# Registry: provider → (class, default_model)
MODEL_REGISTRY: dict[str, tuple[type, str]] = {
    "deepseek":  (DeepSeekModel,  "deepseek-reasoner"),
    "mistral":   (MistralModel,   "codestral-latest"),
    "openai":    (OpenAIModel,    "gpt-4o-mini"),
    "gemini":    (GeminiModel,    "gemini-2.0-flash"),
    "groq":      (GroqModel,      "llama-3.3-70b-versatile"),
}


def get_model(provider: str, model_name: str | None = None) -> BaseModel:
    """
    Get a model wrapper by provider name.

    Args:
        provider: One of "deepseek", "mistral", "openai", "gemini", "groq"
        model_name: Optional specific model name (uses default if None)
    """
    if provider not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model provider: {provider}. Available: {list(MODEL_REGISTRY.keys())}")

    model_class, default_name = MODEL_REGISTRY[provider]
    name = model_name or default_name
    return model_class(name)


def list_providers() -> list[dict]:
    """List all available providers with their default models and costs."""
    providers = []
    for provider_name, (model_class, default_model) in MODEL_REGISTRY.items():
        instance = model_class(default_model)
        cost_input = getattr(instance, "cost_per_1k_input", 0)
        cost_output = getattr(instance, "cost_per_1k_output", 0)
        providers.append({
            "provider": provider_name,
            "default_model": default_model,
            "cost_per_1k_input": cost_input,
            "cost_per_1k_output": cost_output,
        })
    return providers
