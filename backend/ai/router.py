"""
AI — Model Router

Selects the optimal AI model for each query based on:
  1. Subject category (from classifier)
  2. Complexity level
  3. Cost constraints
  4. Provider availability

Routing Rules:
  ┌────────────────┬─────────────────┬──────────────────┐
  │ Query Type      │ Primary         │ Fallback         │
  ├────────────────┼─────────────────┼──────────────────┤
  │ Math / STEM     │ DeepSeek R1     │ OpenAI GPT-4o    │
  │ Coding          │ Mistral Codestral│ DeepSeek V3     │
  │ Reasoning       │ OpenAI GPT-4o   │ DeepSeek R1      │
  │ Physics/Chem    │ DeepSeek R1     │ OpenAI GPT-4o    │
  │ General (cheap) │ Gemini Flash    │ Groq Llama       │
  │ Image           │ OpenAI GPT-4o   │ Gemini Pro       │
  │ LOW complexity  │ Groq (free)     │ Gemini Flash     │
  └────────────────┴─────────────────┴──────────────────┘
"""

from enum import Enum
from dataclasses import dataclass
import structlog

from ai.classifier import Classification, SubjectCategory, ComplexityLevel
from config.settings import settings
from config.feature_flags import flags

logger = structlog.get_logger("equated.ai.router")


class ModelProvider(str, Enum):
    DEEPSEEK = "deepseek"
    MISTRAL = "mistral"
    OPENAI = "openai"
    GEMINI = "gemini"
    GROQ = "groq"
    LOCAL = "local"


@dataclass
class RoutingDecision:
    """The router's decision on which model to use."""
    provider: ModelProvider
    model_name: str
    max_tokens: int
    temperature: float
    reason: str                       # Why this model was selected
    estimated_cost_usd: float = 0.0   # Estimated cost for this call
    fallback_provider: ModelProvider | None = None
    fallback_model: str | None = None


# ── Provider-Model Mappings ─────────────────────────

MODEL_CONFIGS = {
    ModelProvider.DEEPSEEK: {
        "default": "deepseek-reasoner",
        "fast": "deepseek-chat",
        "enabled": lambda: bool(settings.DEEPSEEK_API_KEY),
    },
    ModelProvider.MISTRAL: {
        "default": "codestral-latest",
        "large": "mistral-large-latest",
        "small": "mistral-small-latest",
        "enabled": lambda: bool(settings.MISTRAL_API_KEY),
    },
    ModelProvider.OPENAI: {
        "default": "gpt-4o-mini",
        "premium": "gpt-4o",
        "enabled": lambda: bool(settings.OPENAI_API_KEY),
    },
    ModelProvider.GEMINI: {
        "default": "gemini-2.0-flash",
        "premium": "gemini-2.0-pro",
        "enabled": lambda: bool(settings.GEMINI_API_KEY),
    },
    ModelProvider.GROQ: {
        "default": "llama-3.3-70b-versatile",
        "enabled": lambda: bool(settings.GROQ_API_KEY),
    },
}


class ModelRouter:
    """
    Routes classified problems to the optimal model provider.

    Decision layers:
      1. Fast path:  LOW complexity → Groq (free, fast)
      2. Subject:    Route by category to specialist model
      3. Complexity: Upgrade model tier for HIGH complexity
      4. Cost:       Stay within budget constraints
      5. Fallback:   Pre-computed fallback chain per route
    """

    def route(self, classification: Classification, budget_usd: float | None = None) -> RoutingDecision:
        """
        Route a classified problem to the best available model.

        Args:
            classification: Problem classification result
            budget_usd: Optional budget constraint per call
        """
        subject = classification.subject
        complexity = classification.complexity

        if settings.APP_ENV == "development" and settings.DEV_PRIMARY_PROVIDER == "groq":
            if self._is_enabled(ModelProvider.GROQ):
                return RoutingDecision(
                    provider=ModelProvider.GROQ,
                    model_name="llama-3.3-70b-versatile",
                    max_tokens=min(classification.tokens_est, 4096),
                    temperature=0.2 if subject == SubjectCategory.MATH else 0.3,
                    reason=f"development_primary_{subject.value}",
                    estimated_cost_usd=0.0,
                    fallback_provider=ModelProvider.GEMINI if self._is_enabled(ModelProvider.GEMINI) else None,
                    fallback_model="gemini-2.0-flash" if self._is_enabled(ModelProvider.GEMINI) else None,
                )

        # ── Layer 1: Low complexity fast path ───────
        if complexity == ComplexityLevel.LOW and flags.enable_fast_model:
            if self._is_enabled(ModelProvider.GROQ):
                return RoutingDecision(
                    provider=ModelProvider.GROQ,
                    model_name="llama-3.3-70b-versatile",
                    max_tokens=min(classification.tokens_est, 2048),
                    temperature=0.2,
                    reason="low_complexity_fast_path",
                    estimated_cost_usd=0.0,
                    fallback_provider=ModelProvider.GEMINI,
                    fallback_model="gemini-2.0-flash",
                )

        # ── Layer 2: Subject-based routing ──────────
        decision = self._route_by_subject(subject, complexity, classification.tokens_est)

        # ── Layer 3: Budget constraint ──────────────
        if budget_usd is not None and decision.estimated_cost_usd > budget_usd:
            decision = self._downgrade_for_budget(decision, budget_usd, classification.tokens_est)

        # ── Layer 4: Availability check ─────────────
        if not self._is_enabled(decision.provider):
            decision = self._find_available_fallback(decision, classification)

        logger.info(
            "routed",
            subject=subject.value,
            complexity=complexity.value,
            provider=decision.provider.value,
            model=decision.model_name,
            reason=decision.reason,
        )

        return decision

    def _route_by_subject(self, subject: SubjectCategory, complexity: ComplexityLevel,
                          tokens_est: int) -> RoutingDecision:
        """Select provider based on subject category."""

        if subject in (SubjectCategory.MATH, SubjectCategory.PHYSICS, SubjectCategory.CHEMISTRY):
            # DeepSeek R1 excels at STEM reasoning
            model = "deepseek-reasoner" if complexity == ComplexityLevel.HIGH else "deepseek-chat"
            return RoutingDecision(
                provider=ModelProvider.DEEPSEEK,
                model_name=model,
                max_tokens=min(tokens_est, 8192),
                temperature=0.1 if subject == SubjectCategory.MATH else 0.3,
                reason=f"stem_specialist_{subject.value}",
                estimated_cost_usd=self._estimate_cost("deepseek", tokens_est),
                fallback_provider=ModelProvider.OPENAI,
                fallback_model="gpt-4o",
            )

        elif subject == SubjectCategory.CODING:
            # Mistral Codestral is specialized for code
            model = "codestral-latest"
            if complexity == ComplexityLevel.HIGH:
                model = "mistral-large-latest"
            return RoutingDecision(
                provider=ModelProvider.MISTRAL,
                model_name=model,
                max_tokens=min(tokens_est, 8192),
                temperature=0.2,
                reason="code_specialist",
                estimated_cost_usd=self._estimate_cost("mistral", tokens_est),
                fallback_provider=ModelProvider.DEEPSEEK,
                fallback_model="deepseek-chat",
            )

        elif subject == SubjectCategory.REASONING:
            # OpenAI GPT-4o for complex reasoning
            model = "gpt-4o" if complexity == ComplexityLevel.HIGH else "gpt-4o-mini"
            return RoutingDecision(
                provider=ModelProvider.OPENAI,
                model_name=model,
                max_tokens=min(tokens_est, 4096),
                temperature=0.4,
                reason="reasoning_specialist",
                estimated_cost_usd=self._estimate_cost("openai", tokens_est),
                fallback_provider=ModelProvider.DEEPSEEK,
                fallback_model="deepseek-reasoner",
            )

        elif subject == SubjectCategory.IMAGE:
            # OpenAI GPT-4o has best vision capabilities
            return RoutingDecision(
                provider=ModelProvider.OPENAI,
                model_name="gpt-4o",
                max_tokens=2048,
                temperature=0.3,
                reason="image_understanding",
                estimated_cost_usd=self._estimate_cost("openai", tokens_est),
                fallback_provider=ModelProvider.GEMINI,
                fallback_model="gemini-2.0-pro",
            )

        else:
            # General queries → cheapest model (Gemini Flash)
            return RoutingDecision(
                provider=ModelProvider.GEMINI,
                model_name="gemini-2.0-flash",
                max_tokens=min(tokens_est, 2048),
                temperature=0.5,
                reason="general_cheapest",
                estimated_cost_usd=self._estimate_cost("gemini", tokens_est),
                fallback_provider=ModelProvider.GROQ,
                fallback_model="llama-3.3-70b-versatile",
            )

    def _downgrade_for_budget(self, decision: RoutingDecision, budget_usd: float,
                              tokens_est: int) -> RoutingDecision:
        """If estimated cost exceeds budget, try a cheaper alternative."""
        # Priority: Groq (free) → Gemini Flash (cheap) → original
        cheap_options = [
            (ModelProvider.GROQ, "llama-3.3-70b-versatile", 0.0),
            (ModelProvider.GEMINI, "gemini-2.0-flash", self._estimate_cost("gemini", tokens_est)),
            (ModelProvider.MISTRAL, "mistral-small-latest", self._estimate_cost("mistral", tokens_est) * 0.3),
        ]

        for provider, model, cost in cheap_options:
            if cost <= budget_usd and self._is_enabled(provider):
                return RoutingDecision(
                    provider=provider,
                    model_name=model,
                    max_tokens=decision.max_tokens,
                    temperature=decision.temperature,
                    reason=f"budget_downgrade_from_{decision.provider.value}",
                    estimated_cost_usd=cost,
                    fallback_provider=decision.provider,
                    fallback_model=decision.model_name,
                )

        return decision  # No cheaper option available

    def _find_available_fallback(self, decision: RoutingDecision,
                                 classification: Classification) -> RoutingDecision:
        """If the primary provider is unavailable, use fallback chain."""
        fallback_chain = [
            ModelProvider.GROQ,
            ModelProvider.GEMINI,
            ModelProvider.DEEPSEEK,
            ModelProvider.OPENAI,
            ModelProvider.MISTRAL,
        ]

        for provider in fallback_chain:
            if provider != decision.provider and self._is_enabled(provider):
                config = MODEL_CONFIGS[provider]
                return RoutingDecision(
                    provider=provider,
                    model_name=config["default"],
                    max_tokens=decision.max_tokens,
                    temperature=decision.temperature,
                    reason=f"fallback_from_{decision.provider.value}",
                    estimated_cost_usd=self._estimate_cost(provider.value, classification.tokens_est),
                )

        raise RuntimeError("No AI providers available. Check API keys.")

    def _is_enabled(self, provider: ModelProvider) -> bool:
        """Check if a provider has a valid API key configured."""
        config = MODEL_CONFIGS.get(provider)
        if not config:
            return False
        return config["enabled"]()

    def _estimate_cost(self, provider: str, output_tokens: int) -> float:
        """Rough cost estimate based on expected token usage."""
        # Input is ~20% of output for typical STEM problems
        input_tokens = int(output_tokens * 0.2)

        cost_table = {
            "deepseek": {"input": 0.00055, "output": 0.00219},
            "mistral":  {"input": 0.0003,  "output": 0.0009},
            "openai":   {"input": 0.00015, "output": 0.0006},   # gpt-4o-mini
            "gemini":   {"input": 0.0001,  "output": 0.0004},
            "groq":     {"input": 0.0,     "output": 0.0},
        }

        costs = cost_table.get(provider, {"input": 0.001, "output": 0.003})
        return round(
            (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1000,
            6,
        )

    def get_fallback(self, provider: ModelProvider) -> RoutingDecision | None:
        """Get the next model in the fallback chain for a given provider."""
        fallback_map = {
            ModelProvider.DEEPSEEK: (ModelProvider.OPENAI, "gpt-4o"),
            ModelProvider.MISTRAL:  (ModelProvider.DEEPSEEK, "deepseek-chat"),
            ModelProvider.OPENAI:   (ModelProvider.DEEPSEEK, "deepseek-reasoner"),
            ModelProvider.GEMINI:   (ModelProvider.GROQ, "llama-3.3-70b-versatile"),
            ModelProvider.GROQ:     (ModelProvider.GEMINI, "gemini-2.0-flash"),
        }

        if provider not in fallback_map:
            return None

        fb_provider, fb_model = fallback_map[provider]
        if not self._is_enabled(fb_provider):
            return None

        return RoutingDecision(
            provider=fb_provider,
            model_name=fb_model,
            max_tokens=4096,
            temperature=0.3,
            reason=f"fallback_from_{provider.value}",
        )


# Singleton
model_router = ModelRouter()
