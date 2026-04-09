import structlog
from collections import namedtuple
from ai.fallback import fallback_handler as ai_fallback
from ai.circuit_breaker import CircuitBreaker
from core.exceptions import AIServiceError

logger = structlog.get_logger("equated.services.controller.fallback")

# Simple structure to mimic fallback_handler response
FallbackResult = namedtuple("FallbackResult", ["content", "model"])

class ControllerFallbackHandler:
    """
    Wraps AI fallback logic with a controller-specific circuit breaker.
    Maintains separation of concerns by delegating core iteration to ai.fallback
    while managing Controller-level resilience and graceful degradation here.
    """

    def __init__(self):
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5, 
            recovery_timeout=60,
        )

    async def generate_with_fallback(self, messages: list[dict], decision, user_id: str):
        try:
            # Execute through circuit breaker
            result = await self.circuit_breaker.call(
                ai_fallback.generate_with_fallback,
                messages,
                decision,
                user_id
            )
            if not result:
                raise AIServiceError("All AI models unavailable")
            return result
        except Exception as e:
            logger.warning("circuit_breaker_active_or_fallback_failed", error=str(e))
            # Controller-specific Graceful Degradation:
            # Instead of crashing the entire solve pipeline, return a graceful explanation.
            return FallbackResult(
                content=(
                    "I am currently experiencing extremely high demand or my backend services are temporarily unavailable. "
                    "I've activated my safety circuit breaker. Please try again in about a minute!"
                ),
                model="circuit_breaker_safety"
            )

controller_fallback_handler = ControllerFallbackHandler()
