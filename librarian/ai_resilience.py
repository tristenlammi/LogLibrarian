"""
AI Resilience Module

Provides production-ready error handling and resilience:
- Retry logic with exponential backoff
- Circuit breaker pattern for failing services
- Graceful fallbacks when AI is unavailable
- User-friendly error messages
- Request timeout management
"""

import asyncio
import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, TypeVar, Generic
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ==================== ERROR CLASSES ====================

class AIError(Exception):
    """Base class for AI-related errors"""
    def __init__(self, message: str, user_message: str = None, retryable: bool = False):
        super().__init__(message)
        self.user_message = user_message or "An error occurred. Please try again."
        self.retryable = retryable


class AIServiceUnavailableError(AIError):
    """AI service is not available"""
    def __init__(self, message: str = "AI service unavailable"):
        super().__init__(
            message,
            user_message="The AI assistant is currently unavailable. Please try again in a few moments.",
            retryable=True
        )


class AIModelNotLoadedError(AIError):
    """AI model is not loaded"""
    def __init__(self, message: str = "Model not loaded"):
        super().__init__(
            message,
            user_message="The AI model is still loading. Please wait a moment and try again.",
            retryable=True
        )


class AITimeoutError(AIError):
    """AI request timed out"""
    def __init__(self, message: str = "Request timed out"):
        super().__init__(
            message,
            user_message="The request took too long. Try asking a simpler question or being more specific.",
            retryable=True
        )


class AIRateLimitError(AIError):
    """Rate limit exceeded"""
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(
            message,
            user_message=f"Too many requests. Please wait {retry_after} seconds before trying again.",
            retryable=True
        )
        self.retry_after = retry_after


class AIContentFilterError(AIError):
    """Content was filtered"""
    def __init__(self, message: str = "Content filtered"):
        super().__init__(
            message,
            user_message="I can't help with that request. Please try rephrasing your question.",
            retryable=False
        )


class AIToolExecutionError(AIError):
    """Tool execution failed"""
    def __init__(self, tool_name: str, message: str):
        super().__init__(
            f"Tool {tool_name} failed: {message}",
            user_message=f"I encountered an issue while gathering data. Some information may be incomplete.",
            retryable=True
        )
        self.tool_name = tool_name


# ==================== RETRY DECORATOR ====================

@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (AIServiceUnavailableError, AITimeoutError, AIToolExecutionError)


def with_retry(config: RetryConfig = None):
    """
    Decorator that adds retry logic with exponential backoff.
    
    Usage:
        @with_retry(RetryConfig(max_attempts=3))
        async def my_function():
            ...
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts - 1:
                        # Calculate delay with exponential backoff
                        delay = min(
                            config.initial_delay * (config.exponential_base ** attempt),
                            config.max_delay
                        )
                        
                        # Add jitter to prevent thundering herd
                        if config.jitter:
                            import random
                            delay = delay * (0.5 + random.random())
                        
                        logger.warning(
                            f"Retry {attempt + 1}/{config.max_attempts} for {func.__name__} "
                            f"after {delay:.1f}s due to: {e}"
                        )
                        
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_attempts} retries exhausted for {func.__name__}: {e}"
                        )
                except Exception as e:
                    # Non-retryable exception
                    logger.error(f"Non-retryable error in {func.__name__}: {e}")
                    raise
            
            # All retries exhausted
            raise last_exception
        
        return wrapper
    return decorator


# ==================== CIRCUIT BREAKER ====================

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5        # Failures before opening
    success_threshold: int = 2        # Successes to close from half-open
    timeout: float = 60.0             # Seconds before trying half-open
    excluded_exceptions: tuple = ()   # Exceptions that don't count as failures


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    Prevents cascading failures by temporarily blocking requests
    to a failing service.
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout"""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = (datetime.now() - self._last_failure_time).total_seconds()
                if elapsed >= self.config.timeout:
                    logger.info(f"Circuit {self.name} transitioning to HALF_OPEN")
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
        return self._state
    
    def record_success(self):
        """Record a successful call"""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                logger.info(f"Circuit {self.name} transitioning to CLOSED")
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            self._failure_count = 0
    
    def record_failure(self, exception: Exception):
        """Record a failed call"""
        if isinstance(exception, self.config.excluded_exceptions):
            return
        
        self._failure_count += 1
        self._last_failure_time = datetime.now()
        
        if self._state == CircuitState.HALF_OPEN:
            logger.warning(f"Circuit {self.name} transitioning to OPEN (half-open failure)")
            self._state = CircuitState.OPEN
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                logger.warning(f"Circuit {self.name} transitioning to OPEN ({self._failure_count} failures)")
                self._state = CircuitState.OPEN
    
    def is_available(self) -> bool:
        """Check if requests should be allowed"""
        state = self.state  # This checks for timeout transition
        return state != CircuitState.OPEN
    
    def get_status(self) -> Dict[str, Any]:
        """Get circuit breaker status"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": self._last_failure_time.isoformat() if self._last_failure_time else None
        }


def with_circuit_breaker(circuit: CircuitBreaker):
    """
    Decorator that adds circuit breaker protection.
    
    Usage:
        circuit = CircuitBreaker("ai_service")
        
        @with_circuit_breaker(circuit)
        async def call_ai():
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if not circuit.is_available():
                raise AIServiceUnavailableError(
                    f"Circuit breaker {circuit.name} is open"
                )
            
            try:
                result = await func(*args, **kwargs)
                circuit.record_success()
                return result
            except Exception as e:
                circuit.record_failure(e)
                raise
        
        return wrapper
    return decorator


# ==================== GRACEFUL FALLBACKS ====================

@dataclass
class FallbackResponse:
    """A fallback response when AI is unavailable"""
    content: str
    is_fallback: bool = True
    reason: str = ""


class FallbackHandler:
    """
    Provides graceful fallbacks when AI service is unavailable.
    """
    
    # Fallback responses for common queries
    FALLBACK_RESPONSES = {
        "status": FallbackResponse(
            content="I'm currently unable to check system status. You can view the dashboard for real-time information.",
            reason="AI unavailable"
        ),
        "help": FallbackResponse(
            content="""Here are some things you can ask me when I'm fully operational:
            
• "What scribes are offline?" - Check agent status
• "Show recent errors" - View error logs
• "How is CPU usage on [server]?" - Check metrics
• "What happened yesterday?" - Review activity
• "Are there any active alerts?" - Check alerts

For now, please use the dashboard for real-time data.""",
            reason="AI unavailable"
        ),
        "default": FallbackResponse(
            content="I'm temporarily unable to process your request. Please try again in a moment, or use the dashboard to view system information directly.",
            reason="AI unavailable"
        )
    }
    
    @classmethod
    def get_fallback(cls, query: str) -> FallbackResponse:
        """Get an appropriate fallback response for a query"""
        query_lower = query.lower()
        
        if any(word in query_lower for word in ['help', 'what can you', 'how do i']):
            return cls.FALLBACK_RESPONSES["help"]
        
        if any(word in query_lower for word in ['status', 'health', 'online', 'offline']):
            return cls.FALLBACK_RESPONSES["status"]
        
        return cls.FALLBACK_RESPONSES["default"]
    
    @classmethod
    def format_error_response(cls, error: AIError) -> str:
        """Format an error into a user-friendly response"""
        return f"⚠️ {error.user_message}"


# ==================== ERROR MESSAGE FORMATTER ====================

class ErrorFormatter:
    """
    Formats errors into user-friendly messages.
    """
    
    ERROR_TEMPLATES = {
        "timeout": "⏱️ The request took too long. {suggestion}",
        "unavailable": "🔌 The AI assistant is temporarily unavailable. {suggestion}",
        "rate_limit": "⏳ You've made too many requests. Please wait {wait_time} before trying again.",
        "tool_error": "⚠️ I encountered an issue while gathering data: {details}",
        "generic": "❌ Something went wrong. {suggestion}",
    }
    
    SUGGESTIONS = {
        "timeout": "Try asking a simpler question or being more specific about what you need.",
        "unavailable": "Please try again in a few moments.",
        "tool_error": "Some information may be incomplete. You can try asking again.",
        "generic": "Please try again. If the problem persists, check the system logs.",
    }
    
    @classmethod
    def format(cls, error: Exception) -> str:
        """Format an exception into a user-friendly message"""
        if isinstance(error, AITimeoutError):
            return cls.ERROR_TEMPLATES["timeout"].format(
                suggestion=cls.SUGGESTIONS["timeout"]
            )
        
        if isinstance(error, AIServiceUnavailableError):
            return cls.ERROR_TEMPLATES["unavailable"].format(
                suggestion=cls.SUGGESTIONS["unavailable"]
            )
        
        if isinstance(error, AIRateLimitError):
            return cls.ERROR_TEMPLATES["rate_limit"].format(
                wait_time=f"{error.retry_after} seconds"
            )
        
        if isinstance(error, AIToolExecutionError):
            return cls.ERROR_TEMPLATES["tool_error"].format(
                details=error.tool_name
            )
        
        if isinstance(error, AIError):
            return error.user_message
        
        # Unknown error
        logger.error(f"Unexpected error: {error}")
        return cls.ERROR_TEMPLATES["generic"].format(
            suggestion=cls.SUGGESTIONS["generic"]
        )


# ==================== REQUEST CONTEXT ====================

@dataclass
class RequestContext:
    """Context for an AI request, used for logging and tracking"""
    request_id: str
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    start_time: datetime = field(default_factory=datetime.now)
    query: str = ""
    
    def elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds"""
        return int((datetime.now() - self.start_time).total_seconds() * 1000)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "elapsed_ms": self.elapsed_ms(),
            "query_length": len(self.query)
        }


# ==================== RESILIENCE SERVICE ====================

class ResilienceService:
    """
    Main service for resilience features.
    
    Coordinates circuit breakers, retries, and fallbacks.
    """
    
    def __init__(self):
        self.ai_circuit = CircuitBreaker("ai_service", CircuitBreakerConfig(
            failure_threshold=5,
            timeout=30.0
        ))
        self.tool_circuit = CircuitBreaker("tool_executor", CircuitBreakerConfig(
            failure_threshold=10,
            timeout=15.0
        ))
        self.fallback_handler = FallbackHandler()
        self.error_formatter = ErrorFormatter()
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all circuit breakers"""
        return {
            "ai_service": self.ai_circuit.get_status(),
            "tool_executor": self.tool_circuit.get_status()
        }
    
    def is_ai_available(self) -> bool:
        """Check if AI service is available"""
        return self.ai_circuit.is_available()
    
    def record_ai_success(self):
        """Record successful AI call"""
        self.ai_circuit.record_success()
    
    def record_ai_failure(self, error: Exception):
        """Record failed AI call"""
        self.ai_circuit.record_failure(error)
    
    def get_fallback_response(self, query: str) -> str:
        """Get a fallback response for a query"""
        fallback = self.fallback_handler.get_fallback(query)
        return fallback.content
    
    def format_error(self, error: Exception) -> str:
        """Format an error for display to user"""
        return self.error_formatter.format(error)


# ==================== MODULE SINGLETON ====================

_resilience: ResilienceService = None


def get_resilience_service() -> ResilienceService:
    """Get the global resilience service instance"""
    global _resilience
    if _resilience is None:
        _resilience = ResilienceService()
    return _resilience
