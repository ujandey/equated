import logging
from datetime import datetime, timedelta
from typing import Dict, Callable, Any
import asyncio

logger = logging.getLogger("equated.ai.circuit_breaker")

class CircuitBreaker:
    """Prevent cascading failures when AI services are down."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        
        # If circuit is OPEN, reject immediately
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """Reset failure count on success."""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        """Increment failure count and open circuit if threshold reached."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                "circuit_breaker_opened",
                failures=self.failure_count
            )
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        return (
            self.last_failure_time and
            datetime.now() - self.last_failure_time > 
            timedelta(seconds=self.recovery_timeout)
        )

# Usage example:
# ai_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
# await ai_circuit_breaker.call(func, *args, **kwargs)
