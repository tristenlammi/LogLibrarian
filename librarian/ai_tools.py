"""
AI Tools Module for Librarian AI

Provides the tool framework and implementations that allow the AI to query
LogLibrarian's database intelligently. Each tool has defined parameters,
result limits, and token budget tracking.

Tools follow llama.cpp's function calling format for local models.
"""

import json
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime, timedelta
from enum import Enum
import re
import logging

logger = logging.getLogger(__name__)


# ==================== DATA CLASSES ====================

class ParameterType(Enum):
    """Supported parameter types for tools"""
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class ToolParameter:
    """Definition of a tool parameter"""
    name: str
    type: ParameterType
    description: str
    required: bool = False
    default: Any = None
    enum: Optional[List[str]] = None  # For constrained string values
    items_type: Optional[ParameterType] = None  # For array types
    
    def to_schema(self) -> dict:
        """Convert to JSON Schema format for function calling"""
        schema = {
            "type": self.type.value,
            "description": self.description
        }
        if self.enum:
            schema["enum"] = self.enum
        if self.type == ParameterType.ARRAY and self.items_type:
            schema["items"] = {"type": self.items_type.value}
        return schema


@dataclass
class ToolResult:
    """Result from executing a tool"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    token_estimate: int = 0  # Estimated tokens in result
    truncated: bool = False  # Whether results were truncated
    total_count: Optional[int] = None  # Total available if truncated
    
    def to_dict(self) -> dict:
        result = {"success": self.success}
        if self.success:
            result["data"] = self.data
            if self.truncated:
                result["truncated"] = True
                if self.total_count:
                    result["total_count"] = self.total_count
        else:
            result["error"] = self.error
        return result


@dataclass
class AITool:
    """Definition of an AI-callable tool"""
    name: str
    description: str
    parameters: List[ToolParameter]
    handler: Callable  # async function(db_manager, **kwargs) -> ToolResult
    max_results: int = 100  # Default result limit
    category: str = "general"  # For grouping tools
    
    def to_function_schema(self) -> dict:
        """Convert to function calling schema format"""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_schema()
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }


# ==================== TOOL REGISTRY ====================

class ToolRegistry:
    """
    Registry of all available AI tools.
    
    Manages tool registration, lookup, and schema generation.
    """
    
    def __init__(self):
        self._tools: Dict[str, AITool] = {}
    
    def register(self, tool: AITool):
        """Register a tool"""
        self._tools[tool.name] = tool
        logger.info(f"Registered AI tool: {tool.name}")
    
    def get(self, name: str) -> Optional[AITool]:
        """Get a tool by name"""
        return self._tools.get(name)
    
    def list_tools(self, category: Optional[str] = None) -> List[AITool]:
        """List all tools, optionally filtered by category"""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())
    
    def get_all_schemas(self) -> List[dict]:
        """Get function schemas for all tools (for AI prompt)"""
        return [tool.to_function_schema() for tool in self._tools.values()]
    
    def get_tools_prompt(self) -> str:
        """Generate a text description of all tools for the AI"""
        lines = ["Available tools:\n"]
        
        # Group by category
        categories: Dict[str, List[AITool]] = {}
        for tool in self._tools.values():
            if tool.category not in categories:
                categories[tool.category] = []
            categories[tool.category].append(tool)
        
        for category, tools in sorted(categories.items()):
            lines.append(f"\n## {category.title()} Tools\n")
            for tool in tools:
                lines.append(f"### {tool.name}")
                lines.append(f"{tool.description}")
                if tool.parameters:
                    lines.append("Parameters:")
                    for param in tool.parameters:
                        req = "(required)" if param.required else "(optional)"
                        lines.append(f"  - {param.name} ({param.type.value}) {req}: {param.description}")
                lines.append("")
        
        return "\n".join(lines)


# Global registry
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry"""
    return _registry


def register_tool(tool: AITool):
    """Register a tool in the global registry"""
    _registry.register(tool)


# ==================== TOOL EXECUTOR ====================

class ToolExecutor:
    """
    Executes AI tool calls with safety limits.
    
    Enforces:
    - Max tool calls per turn (default 5)
    - Max same tool calls per turn (default 2)
    - Token budget tracking
    - Execution timeouts
    """
    
    MAX_CALLS_PER_TURN = 5
    MAX_SAME_TOOL_PER_TURN = 2
    EXECUTION_TIMEOUT = 30  # seconds
    MAX_TOKEN_BUDGET = 4000  # Max tokens for tool results
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.registry = get_tool_registry()
        self._call_counts: Dict[str, int] = {}
        self._total_calls = 0
        self._token_budget_used = 0
    
    def reset_turn(self):
        """Reset counters for a new turn"""
        self._call_counts = {}
        self._total_calls = 0
        self._token_budget_used = 0
    
    async def execute(self, tool_name: str, arguments: dict) -> ToolResult:
        """
        Execute a tool call.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool
            
        Returns:
            ToolResult with data or error
        """
        # Check limits
        if self._total_calls >= self.MAX_CALLS_PER_TURN:
            return ToolResult(
                success=False,
                error=f"Maximum tool calls ({self.MAX_CALLS_PER_TURN}) reached for this turn"
            )
        
        current_count = self._call_counts.get(tool_name, 0)
        if current_count >= self.MAX_SAME_TOOL_PER_TURN:
            return ToolResult(
                success=False,
                error=f"Maximum calls to {tool_name} ({self.MAX_SAME_TOOL_PER_TURN}) reached"
            )
        
        # Get tool
        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}"
            )
        
        # Validate required parameters
        for param in tool.parameters:
            if param.required and param.name not in arguments:
                return ToolResult(
                    success=False,
                    error=f"Missing required parameter: {param.name}"
                )
        
        # Apply defaults
        for param in tool.parameters:
            if param.name not in arguments and param.default is not None:
                arguments[param.name] = param.default
        
        # Execute with timeout
        try:
            result = await asyncio.wait_for(
                tool.handler(self.db_manager, **arguments),
                timeout=self.EXECUTION_TIMEOUT
            )
            
            # Update counters
            self._total_calls += 1
            self._call_counts[tool_name] = current_count + 1
            self._token_budget_used += result.token_estimate
            
            # Check token budget
            if self._token_budget_used > self.MAX_TOKEN_BUDGET:
                logger.warning(f"Token budget exceeded: {self._token_budget_used}/{self.MAX_TOKEN_BUDGET}")
            
            return result
            
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Tool execution timed out after {self.EXECUTION_TIMEOUT}s"
            )
        except Exception as e:
            logger.error(f"Tool execution error: {tool_name}: {e}")
            return ToolResult(
                success=False,
                error=f"Tool execution failed: {str(e)}"
            )
    
    async def execute_parallel(self, calls: List[tuple]) -> List[ToolResult]:
        """
        Execute multiple independent tool calls in parallel.
        
        Args:
            calls: List of (tool_name, arguments) tuples
            
        Returns:
            List of ToolResults in same order as calls
        """
        tasks = [self.execute(name, args) for name, args in calls]
        return await asyncio.gather(*tasks)
    
    def get_budget_status(self) -> dict:
        """Get current budget usage"""
        return {
            "calls_used": self._total_calls,
            "calls_max": self.MAX_CALLS_PER_TURN,
            "tokens_used": self._token_budget_used,
            "tokens_max": self.MAX_TOKEN_BUDGET,
            "by_tool": dict(self._call_counts)
        }


# ==================== UTILITY FUNCTIONS ====================

def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough approximation)"""
    # Average ~4 chars per token for English text
    return len(text) // 4


def fuzzy_match(query: str, candidates: List[str], threshold: float = 0.6) -> List[tuple]:
    """
    Simple fuzzy matching for entity names.
    
    Args:
        query: Search query
        candidates: List of candidate strings
        threshold: Minimum similarity score (0-1)
        
    Returns:
        List of (candidate, score) tuples, sorted by score descending
    """
    query_lower = query.lower()
    results = []
    
    for candidate in candidates:
        candidate_lower = candidate.lower()
        
        # Exact match
        if query_lower == candidate_lower:
            results.append((candidate, 1.0))
            continue
        
        # Contains match
        if query_lower in candidate_lower:
            score = len(query_lower) / len(candidate_lower)
            results.append((candidate, max(score, 0.8)))
            continue
        
        # Word match
        query_words = set(query_lower.split())
        candidate_words = set(candidate_lower.split())
        common_words = query_words & candidate_words
        if common_words:
            score = len(common_words) / max(len(query_words), len(candidate_words))
            if score >= threshold:
                results.append((candidate, score))
                continue
        
        # Simple character overlap (Jaccard-ish)
        query_chars = set(query_lower)
        candidate_chars = set(candidate_lower)
        intersection = len(query_chars & candidate_chars)
        union = len(query_chars | candidate_chars)
        score = intersection / union if union > 0 else 0
        
        if score >= threshold:
            results.append((candidate, score))
    
    return sorted(results, key=lambda x: x[1], reverse=True)


def sanitize_log_content(content: str) -> str:
    """
    Remove potentially sensitive data from log content.
    
    Sanitizes:
    - API keys and tokens
    - Passwords
    - Email addresses
    - IP addresses (partial)
    - Credit card numbers
    """
    # API keys / tokens (common patterns)
    content = re.sub(
        r'(api[_-]?key|token|secret|password|pwd|auth)["\s:=]+["\']?[\w\-\.]{20,}["\']?',
        r'\1=[REDACTED]',
        content,
        flags=re.IGNORECASE
    )
    
    # Bearer tokens
    content = re.sub(
        r'Bearer\s+[\w\-\.]+',
        'Bearer [REDACTED]',
        content
    )
    
    # Basic auth
    content = re.sub(
        r'Basic\s+[\w\+/=]+',
        'Basic [REDACTED]',
        content
    )
    
    # Email addresses (partial redaction)
    content = re.sub(
        r'([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        r'\1[...]@\2',
        content
    )
    
    # Credit card numbers
    content = re.sub(
        r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b',
        '[CARD REDACTED]',
        content
    )
    
    return content


def format_timestamp(dt: datetime, include_date: bool = True) -> str:
    """Format datetime for user display"""
    if include_date:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%H:%M:%S")


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    elif seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f}h"
    else:
        days = seconds / 86400
        return f"{days:.1f}d"


def truncate_results(results: List[Any], max_count: int) -> tuple:
    """
    Truncate results list and return metadata.
    
    Returns:
        (truncated_list, was_truncated, total_count)
    """
    total = len(results)
    if total <= max_count:
        return results, False, total
    return results[:max_count], True, total


# ==================== TOOL CALL PARSER ====================

class ToolCallParser:
    """
    Parses tool calls from AI model output.
    
    Supports multiple formats:
    - JSON function calls
    - <tool_call> XML-style tags
    - Markdown code blocks with json
    """
    
    @staticmethod
    def parse(text: str) -> List[dict]:
        """
        Parse tool calls from AI output.
        
        Returns:
            List of {name: str, arguments: dict} dicts
        """
        calls = []
        
        # Try JSON array format first
        try:
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    if ("name" in item or "tool" in item) and "arguments" in item:
                        calls.append({
                            "name": item.get("name") or item.get("tool"),
                            "arguments": item.get("arguments", {})
                        })
                return calls
            elif isinstance(data, dict) and ("name" in data or "tool" in data):
                return [{
                    "name": data.get("name") or data.get("tool"),
                    "arguments": data.get("arguments", {})
                }]
        except json.JSONDecodeError:
            pass
        
        # Try <tool_call> format
        tool_call_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        matches = re.findall(tool_call_pattern, text, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                if "name" in data:
                    calls.append({
                        "name": data["name"],
                        "arguments": data.get("arguments", data.get("parameters", {}))
                    })
            except json.JSONDecodeError:
                continue
        
        if calls:
            return calls
        
        # Try markdown code block format
        code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        matches = re.findall(code_block_pattern, text, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                if "name" in data or "tool" in data or "function" in data:
                    name = data.get("name") or data.get("tool") or data.get("function", {}).get("name")
                    args = data.get("arguments") or data.get("parameters") or data.get("function", {}).get("arguments", {})
                    if name:
                        calls.append({"name": name, "arguments": args})
            except json.JSONDecodeError:
                continue
        
        return calls
    
    @staticmethod
    def format_results_for_ai(results: List[ToolResult]) -> str:
        """Format tool results for feeding back to AI"""
        lines = ["Tool Results:\n"]
        
        for i, result in enumerate(results, 1):
            lines.append(f"[Result {i}]")
            if result.success:
                # Format data nicely
                if isinstance(result.data, (dict, list)):
                    lines.append(json.dumps(result.data, indent=2, default=str))
                else:
                    lines.append(str(result.data))
                
                if result.truncated:
                    lines.append(f"(Showing {len(result.data) if isinstance(result.data, list) else 'partial'} of {result.total_count} total results)")
            else:
                lines.append(f"Error: {result.error}")
            lines.append("")
        
        return "\n".join(lines)


# ==================== INITIALIZE REGISTRY ====================

def initialize_tools():
    """
    Initialize all tools in the registry.
    
    Called at module import time to register all available tools.
    """
    # Tools are registered by importing the tool modules
    # Each module registers its tools when imported
    pass


# Import and register tool implementations
# These will be added in subsequent files
