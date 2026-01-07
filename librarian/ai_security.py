"""
AI Security Module

Production-ready security hardening:
- Input sanitization and validation
- Rate limiting to prevent abuse
- Audit logging for compliance
- Content filtering
"""

import asyncio
import hashlib
import logging
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict
from functools import wraps

logger = logging.getLogger(__name__)


# ==================== INPUT SANITIZATION ====================

@dataclass
class SanitizationResult:
    """Result of input sanitization"""
    original: str
    sanitized: str
    was_modified: bool
    flags: List[str] = field(default_factory=list)


class InputSanitizer:
    """
    Sanitizes user input to prevent injection attacks
    and remove potentially harmful content.
    """
    
    # Patterns that might indicate injection attempts
    INJECTION_PATTERNS = [
        # SQL injection attempts
        (r"('|\")\s*(or|and)\s*('|\")?1\s*=\s*1", "sql_injection"),
        (r";\s*(drop|delete|truncate|update|insert)\s+", "sql_injection"),
        (r"union\s+(all\s+)?select", "sql_injection"),
        
        # Command injection attempts
        (r"[;&|]\s*(cat|ls|rm|wget|curl|bash|sh|python)\s", "command_injection"),
        (r"\$\([^)]+\)", "command_substitution"),
        (r"`[^`]+`", "backtick_execution"),
        
        # Path traversal
        (r"\.\./", "path_traversal"),
        (r"\.\.\\", "path_traversal"),
        
        # Prompt injection attempts
        (r"ignore\s+(previous|all)\s+(instructions?|prompts?)", "prompt_injection"),
        (r"forget\s+(everything|your|all)", "prompt_injection"),
        (r"you\s+are\s+(now|a|an)\s+", "role_override"),
        (r"pretend\s+(you|to\s+be)", "role_override"),
        (r"act\s+as\s+", "role_override"),
        (r"system\s*:\s*", "system_prompt"),
    ]
    
    # Characters that should be escaped or removed
    DANGEROUS_CHARS = {
        '\x00': '',      # Null byte
        '\x1b': '',      # Escape
        '\r': '\n',      # Normalize newlines
    }
    
    # Maximum input length
    MAX_INPUT_LENGTH = 10000
    
    # Maximum line count
    MAX_LINE_COUNT = 100
    
    def __init__(self):
        # Compile patterns for efficiency
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), flag)
            for pattern, flag in self.INJECTION_PATTERNS
        ]
    
    def sanitize(self, text: str) -> SanitizationResult:
        """
        Sanitize user input text.
        
        Returns:
            SanitizationResult with the sanitized text and any flags
        """
        if not text:
            return SanitizationResult(
                original=text,
                sanitized="",
                was_modified=False
            )
        
        original = text
        flags = []
        
        # 1. Length check
        if len(text) > self.MAX_INPUT_LENGTH:
            text = text[:self.MAX_INPUT_LENGTH]
            flags.append("truncated")
            logger.warning(f"Input truncated from {len(original)} to {self.MAX_INPUT_LENGTH} chars")
        
        # 2. Line count check
        lines = text.split('\n')
        if len(lines) > self.MAX_LINE_COUNT:
            text = '\n'.join(lines[:self.MAX_LINE_COUNT])
            flags.append("lines_truncated")
            logger.warning(f"Input truncated from {len(lines)} to {self.MAX_LINE_COUNT} lines")
        
        # 3. Remove dangerous characters
        for char, replacement in self.DANGEROUS_CHARS.items():
            if char in text:
                text = text.replace(char, replacement)
                flags.append("dangerous_chars_removed")
        
        # 4. Check for injection patterns
        for pattern, flag in self._compiled_patterns:
            if pattern.search(text):
                flags.append(flag)
                logger.warning(f"Potential {flag} detected in input")
        
        # 5. Normalize whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        return SanitizationResult(
            original=original,
            sanitized=text,
            was_modified=(text != original),
            flags=flags
        )
    
    def is_safe(self, text: str) -> bool:
        """Quick check if input appears safe"""
        result = self.sanitize(text)
        # Consider unsafe if any injection flags were found
        dangerous_flags = {'sql_injection', 'command_injection', 'prompt_injection', 
                          'role_override', 'system_prompt', 'command_substitution',
                          'backtick_execution', 'path_traversal'}
        return not bool(set(result.flags) & dangerous_flags)


# ==================== RATE LIMITING ====================

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    requests_per_minute: int = 30
    requests_per_hour: int = 500
    burst_limit: int = 5  # Max requests in 10 seconds
    cooldown_seconds: int = 60


@dataclass
class RateLimitResult:
    """Result of rate limit check"""
    allowed: bool
    remaining: int
    reset_at: datetime
    limit_type: str = ""  # Which limit was hit


class RateLimiter:
    """
    Token bucket rate limiter with multiple time windows.
    
    Prevents abuse by limiting request frequency per user/IP.
    """
    
    def __init__(self, config: RateLimitConfig = None):
        self.config = config or RateLimitConfig()
        
        # Track requests per identifier
        self._minute_requests: Dict[str, List[datetime]] = defaultdict(list)
        self._hour_requests: Dict[str, List[datetime]] = defaultdict(list)
        self._burst_requests: Dict[str, List[datetime]] = defaultdict(list)
        
        # Cooldown tracking
        self._cooldowns: Dict[str, datetime] = {}
    
    def _cleanup_old_requests(self, identifier: str, now: datetime):
        """Remove expired request records"""
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        ten_seconds_ago = now - timedelta(seconds=10)
        
        self._minute_requests[identifier] = [
            t for t in self._minute_requests[identifier] if t > minute_ago
        ]
        self._hour_requests[identifier] = [
            t for t in self._hour_requests[identifier] if t > hour_ago
        ]
        self._burst_requests[identifier] = [
            t for t in self._burst_requests[identifier] if t > ten_seconds_ago
        ]
    
    def check(self, identifier: str) -> RateLimitResult:
        """
        Check if a request is allowed for the given identifier.
        
        Args:
            identifier: User ID, IP address, or other unique identifier
            
        Returns:
            RateLimitResult indicating if the request is allowed
        """
        now = datetime.now()
        
        # Check if in cooldown
        if identifier in self._cooldowns:
            if now < self._cooldowns[identifier]:
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=self._cooldowns[identifier],
                    limit_type="cooldown"
                )
            else:
                del self._cooldowns[identifier]
        
        # Clean up old requests
        self._cleanup_old_requests(identifier, now)
        
        # Check burst limit (10 second window)
        burst_count = len(self._burst_requests[identifier])
        if burst_count >= self.config.burst_limit:
            reset_at = self._burst_requests[identifier][0] + timedelta(seconds=10)
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=reset_at,
                limit_type="burst"
            )
        
        # Check minute limit
        minute_count = len(self._minute_requests[identifier])
        if minute_count >= self.config.requests_per_minute:
            reset_at = self._minute_requests[identifier][0] + timedelta(minutes=1)
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=reset_at,
                limit_type="minute"
            )
        
        # Check hour limit
        hour_count = len(self._hour_requests[identifier])
        if hour_count >= self.config.requests_per_hour:
            # Apply cooldown
            self._cooldowns[identifier] = now + timedelta(seconds=self.config.cooldown_seconds)
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=self._cooldowns[identifier],
                limit_type="hour"
            )
        
        # Record this request
        self._minute_requests[identifier].append(now)
        self._hour_requests[identifier].append(now)
        self._burst_requests[identifier].append(now)
        
        return RateLimitResult(
            allowed=True,
            remaining=min(
                self.config.requests_per_minute - minute_count - 1,
                self.config.requests_per_hour - hour_count - 1
            ),
            reset_at=now + timedelta(minutes=1)
        )
    
    def get_usage(self, identifier: str) -> Dict[str, Any]:
        """Get current usage for an identifier"""
        now = datetime.now()
        self._cleanup_old_requests(identifier, now)
        
        return {
            "burst_count": len(self._burst_requests[identifier]),
            "burst_limit": self.config.burst_limit,
            "minute_count": len(self._minute_requests[identifier]),
            "minute_limit": self.config.requests_per_minute,
            "hour_count": len(self._hour_requests[identifier]),
            "hour_limit": self.config.requests_per_hour,
            "in_cooldown": identifier in self._cooldowns
        }


# ==================== AUDIT LOGGING ====================

@dataclass
class AuditEntry:
    """An audit log entry"""
    timestamp: datetime
    event_type: str
    user_id: Optional[str]
    tenant_id: Optional[str]
    action: str
    details: Dict[str, Any]
    request_id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "action": self.action,
            "details": self.details,
            "request_id": self.request_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent
        }


class AuditLogger:
    """
    Audit logging for AI interactions.
    
    Records all AI chat requests for compliance and debugging.
    """
    
    def __init__(self, max_entries: int = 10000):
        self._entries: List[AuditEntry] = []
        self._max_entries = max_entries
        self._logger = logging.getLogger("ai_audit")
        
        # Set up file handler for audit log
        try:
            handler = logging.FileHandler("ai_audit.log")
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(message)s'
            ))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
        except Exception as e:
            logger.warning(f"Could not set up audit file handler: {e}")
    
    def log(
        self,
        event_type: str,
        action: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        details: Dict[str, Any] = None,
        request_id: str = None,
        ip_address: str = None,
        user_agent: str = None
    ):
        """Log an audit event"""
        entry = AuditEntry(
            timestamp=datetime.now(),
            event_type=event_type,
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            details=details or {},
            request_id=request_id or str(uuid.uuid4()),
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # Add to in-memory buffer
        self._entries.append(entry)
        
        # Trim old entries
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        
        # Log to file
        self._logger.info(f"{event_type}|{action}|user={user_id}|tenant={tenant_id}|{details}")
    
    def log_chat_request(
        self,
        user_id: str,
        tenant_id: str,
        query: str,
        request_id: str,
        ip_address: str = None
    ):
        """Log a chat request"""
        # Hash the query for privacy but store length
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        
        self.log(
            event_type="ai_chat",
            action="request",
            user_id=user_id,
            tenant_id=tenant_id,
            details={
                "query_hash": query_hash,
                "query_length": len(query)
            },
            request_id=request_id,
            ip_address=ip_address
        )
    
    def log_chat_response(
        self,
        request_id: str,
        success: bool,
        duration_ms: int,
        tool_count: int = 0,
        error: str = None
    ):
        """Log a chat response"""
        self.log(
            event_type="ai_chat",
            action="response",
            details={
                "success": success,
                "duration_ms": duration_ms,
                "tool_count": tool_count,
                "error": error
            },
            request_id=request_id
        )
    
    def log_security_event(
        self,
        event: str,
        user_id: Optional[str],
        details: Dict[str, Any],
        severity: str = "warning"
    ):
        """Log a security-related event"""
        self.log(
            event_type="security",
            action=event,
            user_id=user_id,
            details={**details, "severity": severity}
        )
        
        # Also log to main logger for immediate visibility
        log_func = getattr(logger, severity, logger.warning)
        log_func(f"Security event: {event} - {details}")
    
    def get_recent_entries(
        self,
        count: int = 100,
        event_type: str = None,
        user_id: str = None
    ) -> List[Dict[str, Any]]:
        """Get recent audit entries"""
        entries = self._entries
        
        if event_type:
            entries = [e for e in entries if e.event_type == event_type]
        
        if user_id:
            entries = [e for e in entries if e.user_id == user_id]
        
        return [e.to_dict() for e in entries[-count:]]
    
    def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """Get audit statistics"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [e for e in self._entries if e.timestamp > cutoff]
        
        by_type = defaultdict(int)
        by_user = defaultdict(int)
        by_action = defaultdict(int)
        
        for entry in recent:
            by_type[entry.event_type] += 1
            if entry.user_id:
                by_user[entry.user_id] += 1
            by_action[entry.action] += 1
        
        return {
            "period_hours": hours,
            "total_events": len(recent),
            "by_type": dict(by_type),
            "by_action": dict(by_action),
            "unique_users": len(by_user),
            "top_users": sorted(by_user.items(), key=lambda x: x[1], reverse=True)[:10]
        }


# ==================== CONTENT FILTER ====================

class ContentFilter:
    """
    Filters potentially sensitive content from AI responses.
    """
    
    # Patterns to redact
    SENSITIVE_PATTERNS = [
        # API keys and tokens
        (r'[a-zA-Z0-9]{32,}', '[REDACTED_KEY]'),
        (r'api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9-_]+', '[REDACTED_API_KEY]'),
        (r'bearer\s+[a-zA-Z0-9._-]+', '[REDACTED_TOKEN]'),
        
        # Passwords
        (r'password["\']?\s*[:=]\s*["\'][^"\']+["\']', 'password=[REDACTED]'),
        
        # Connection strings
        (r'(mysql|postgres|mongodb)://[^\s]+', '[REDACTED_CONNECTION_STRING]'),
        
        # Email addresses (optional, can be disabled)
        # (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]'),
    ]
    
    def __init__(self, redact_emails: bool = False):
        self._patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, replacement in self.SENSITIVE_PATTERNS
        ]
        
        if redact_emails:
            self._patterns.append((
                re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
                '[EMAIL]'
            ))
    
    def filter(self, text: str) -> str:
        """Filter sensitive content from text"""
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text


# ==================== SECURITY SERVICE ====================

class SecurityService:
    """
    Main security service coordinating all security features.
    """
    
    def __init__(self, rate_limit_config: RateLimitConfig = None):
        self.sanitizer = InputSanitizer()
        self.rate_limiter = RateLimiter(rate_limit_config)
        self.audit_logger = AuditLogger()
        self.content_filter = ContentFilter()
    
    def validate_request(
        self,
        query: str,
        user_id: str,
        tenant_id: str,
        ip_address: str = None
    ) -> tuple[bool, str, str]:
        """
        Validate an incoming chat request.
        
        Returns:
            (allowed, sanitized_query, error_message)
        """
        request_id = str(uuid.uuid4())
        
        # 1. Rate limit check
        rate_result = self.rate_limiter.check(f"{tenant_id}:{user_id}")
        if not rate_result.allowed:
            self.audit_logger.log_security_event(
                event="rate_limit_exceeded",
                user_id=user_id,
                details={
                    "tenant_id": tenant_id,
                    "limit_type": rate_result.limit_type,
                    "ip_address": ip_address
                }
            )
            wait_seconds = int((rate_result.reset_at - datetime.now()).total_seconds())
            return False, query, f"Rate limit exceeded. Please wait {max(wait_seconds, 1)} seconds."
        
        # 2. Input sanitization
        sanitize_result = self.sanitizer.sanitize(query)
        
        if not self.sanitizer.is_safe(query):
            self.audit_logger.log_security_event(
                event="suspicious_input",
                user_id=user_id,
                details={
                    "tenant_id": tenant_id,
                    "flags": sanitize_result.flags,
                    "ip_address": ip_address
                },
                severity="warning"
            )
            # Still allow but log - don't block legitimate users
        
        # 3. Log the request
        self.audit_logger.log_chat_request(
            user_id=user_id,
            tenant_id=tenant_id,
            query=sanitize_result.sanitized,
            request_id=request_id,
            ip_address=ip_address
        )
        
        return True, sanitize_result.sanitized, ""
    
    def filter_response(self, response: str) -> str:
        """Filter sensitive content from AI response"""
        return self.content_filter.filter(response)
    
    def get_status(self) -> Dict[str, Any]:
        """Get security service status"""
        return {
            "audit_stats": self.audit_logger.get_statistics(hours=1),
            "sanitizer": {
                "max_input_length": self.sanitizer.MAX_INPUT_LENGTH,
                "max_line_count": self.sanitizer.MAX_LINE_COUNT
            },
            "rate_limits": {
                "per_minute": self.rate_limiter.config.requests_per_minute,
                "per_hour": self.rate_limiter.config.requests_per_hour,
                "burst": self.rate_limiter.config.burst_limit
            }
        }


# ==================== MODULE SINGLETON ====================

_security: SecurityService = None


def get_security_service() -> SecurityService:
    """Get the global security service instance"""
    global _security
    if _security is None:
        _security = SecurityService()
    return _security
