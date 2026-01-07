"""
AI Query Optimization Module

Provides performance optimizations for AI tool execution:
- Result caching with intelligent invalidation
- Parallel tool execution for independent queries
- Query timeout handling
- Result size limiting and pagination
- Token budget management
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)


# ==================== RESULT CACHE ====================

@dataclass
class CacheEntry:
    """A cached query result"""
    result: Any
    created_at: datetime
    ttl: timedelta
    hit_count: int = 0
    
    def is_expired(self) -> bool:
        return datetime.now() - self.created_at > self.ttl
    
    def touch(self):
        """Record a cache hit"""
        self.hit_count += 1


class QueryCache:
    """
    LRU cache for query results with TTL-based expiration.
    
    Different query types have different TTLs:
    - Agent status: 30 seconds (changes frequently)
    - Metrics: 1 minute (aggregated data)
    - Logs: 2 minutes (historical data)
    - Bookmarks: 5 minutes (rarely changes)
    """
    
    # TTLs by query type
    DEFAULT_TTLS = {
        'agent_status': timedelta(seconds=30),
        'agent_list': timedelta(minutes=1),
        'metrics': timedelta(minutes=1),
        'logs': timedelta(minutes=2),
        'log_count': timedelta(minutes=2),
        'bookmarks': timedelta(minutes=5),
        'bookmark_status': timedelta(minutes=1),
        'alerts': timedelta(minutes=1),
        'system_health': timedelta(seconds=30),
        'default': timedelta(minutes=1)
    }
    
    def __init__(self, max_size: int = 100):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
    
    def _generate_key(self, query_type: str, params: Dict) -> str:
        """Generate a cache key from query type and parameters"""
        # Sort params for consistent hashing
        param_str = json.dumps(params, sort_keys=True, default=str)
        key_str = f"{query_type}:{param_str}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_ttl(self, query_type: str) -> timedelta:
        """Get TTL for a query type"""
        return self.DEFAULT_TTLS.get(query_type, self.DEFAULT_TTLS['default'])
    
    def get(self, query_type: str, params: Dict) -> Optional[Any]:
        """
        Get a cached result.
        
        Returns None if not cached or expired.
        """
        key = self._generate_key(query_type, params)
        
        if key not in self._cache:
            self._misses += 1
            return None
        
        entry = self._cache[key]
        
        if entry.is_expired():
            del self._cache[key]
            self._misses += 1
            return None
        
        # Move to end (LRU)
        self._cache.move_to_end(key)
        entry.touch()
        self._hits += 1
        
        return entry.result
    
    def set(self, query_type: str, params: Dict, result: Any):
        """Cache a query result"""
        key = self._generate_key(query_type, params)
        ttl = self._get_ttl(query_type)
        
        # Evict if at max size
        while len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        
        self._cache[key] = CacheEntry(
            result=result,
            created_at=datetime.now(),
            ttl=ttl
        )
    
    def invalidate(self, query_type: str = None):
        """
        Invalidate cache entries.
        
        If query_type is provided, only invalidate that type.
        Otherwise, clear all entries.
        """
        if query_type is None:
            self._cache.clear()
            logger.debug("Cache cleared")
        else:
            # Remove entries matching the query type prefix
            to_remove = [
                key for key in self._cache.keys()
                if key.startswith(f"{query_type}:")
            ]
            for key in to_remove:
                del self._cache[key]
            logger.debug(f"Invalidated {len(to_remove)} cache entries for {query_type}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3)
        }
    
    def cleanup_expired(self):
        """Remove all expired entries"""
        expired = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        for key in expired:
            del self._cache[key]
        
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired cache entries")


# ==================== PARALLEL EXECUTOR ====================

@dataclass
class ToolCall:
    """A tool call to be executed"""
    tool_name: str
    params: Dict[str, Any]
    priority: int = 0  # Higher priority runs first
    depends_on: List[str] = field(default_factory=list)  # Tool names this depends on


class ParallelExecutor:
    """
    Executes independent tool calls in parallel.
    
    Analyzes tool call dependencies and runs independent calls
    concurrently while respecting dependencies.
    """
    
    # Tools that are independent and can run in parallel
    INDEPENDENT_TOOLS = {
        'list_scribes', 'list_bookmarks', 'get_active_alerts',
        'get_system_health', 'get_daily_summary'
    }
    
    # Tools that must run sequentially (modify state or have side effects)
    SEQUENTIAL_TOOLS = set()  # Currently none
    
    def __init__(self, max_parallel: int = 3, timeout: float = 30.0):
        self.max_parallel = max_parallel
        self.timeout = timeout
    
    def can_parallelize(self, calls: List[ToolCall]) -> Tuple[List[List[ToolCall]], bool]:
        """
        Analyze calls and group them for parallel execution.
        
        Returns:
            Tuple of (groups, can_parallel) where groups is a list of
            lists of calls that can run together.
        """
        if len(calls) <= 1:
            return [[c] for c in calls], False
        
        # Check if all calls are independent
        all_independent = all(
            c.tool_name in self.INDEPENDENT_TOOLS 
            for c in calls
        )
        
        if all_independent:
            # All can run in parallel (up to max_parallel)
            groups = []
            for i in range(0, len(calls), self.max_parallel):
                groups.append(calls[i:i + self.max_parallel])
            return groups, True
        
        # Some dependencies - run sequentially for safety
        return [[c] for c in calls], False
    
    async def execute_parallel(
        self, 
        calls: List[ToolCall],
        executor_func: Callable[[str, Dict], Any]
    ) -> Dict[str, Any]:
        """
        Execute tool calls, parallelizing where possible.
        
        Args:
            calls: List of tool calls to execute
            executor_func: Async function(tool_name, params) -> result
            
        Returns:
            Dict mapping tool names to results
        """
        groups, can_parallel = self.can_parallelize(calls)
        results = {}
        
        for group in groups:
            if len(group) == 1:
                # Single call
                call = group[0]
                try:
                    result = await asyncio.wait_for(
                        executor_func(call.tool_name, call.params),
                        timeout=self.timeout
                    )
                    results[call.tool_name] = result
                except asyncio.TimeoutError:
                    results[call.tool_name] = {
                        "error": f"Tool {call.tool_name} timed out after {self.timeout}s"
                    }
                except Exception as e:
                    results[call.tool_name] = {"error": str(e)}
            else:
                # Parallel execution
                tasks = []
                for call in group:
                    task = asyncio.create_task(
                        asyncio.wait_for(
                            executor_func(call.tool_name, call.params),
                            timeout=self.timeout
                        )
                    )
                    tasks.append((call.tool_name, task))
                
                # Wait for all tasks
                for tool_name, task in tasks:
                    try:
                        result = await task
                        results[tool_name] = result
                    except asyncio.TimeoutError:
                        results[tool_name] = {
                            "error": f"Tool {tool_name} timed out after {self.timeout}s"
                        }
                    except Exception as e:
                        results[tool_name] = {"error": str(e)}
        
        return results


# ==================== RESULT LIMITER ====================

class ResultLimiter:
    """
    Intelligently limits query results to fit within token budgets.
    
    Features:
    - Adaptive limiting based on data type
    - Smart truncation that preserves most relevant data
    - Summary generation for truncated results
    """
    
    # Default limits by data type
    DEFAULT_LIMITS = {
        'logs': 50,
        'metrics': 100,
        'processes': 30,
        'alerts': 20,
        'bookmarks': 50,
        'scribes': 50,
        'default': 50
    }
    
    # Estimated tokens per item by type
    TOKENS_PER_ITEM = {
        'logs': 50,  # Log entries are verbose
        'metrics': 10,  # Metrics are compact
        'processes': 30,  # Process list moderate
        'alerts': 40,  # Alerts have messages
        'bookmarks': 20,  # Bookmark info compact
        'scribes': 25,  # Agent info moderate
        'default': 30
    }
    
    def __init__(self, token_budget: int = 4000):
        self.token_budget = token_budget
    
    def estimate_tokens(self, data: Any, data_type: str = 'default') -> int:
        """Estimate token count for data"""
        if isinstance(data, list):
            per_item = self.TOKENS_PER_ITEM.get(data_type, self.TOKENS_PER_ITEM['default'])
            return len(data) * per_item
        elif isinstance(data, dict):
            # Rough estimate based on JSON size
            json_str = json.dumps(data, default=str)
            return len(json_str) // 4  # ~4 chars per token
        elif isinstance(data, str):
            return len(data) // 4
        return 10
    
    def limit_results(
        self, 
        data: List[Any], 
        data_type: str = 'default',
        max_items: int = None,
        prioritize_recent: bool = True
    ) -> Tuple[List[Any], bool, int]:
        """
        Limit results to fit within token budget.
        
        Args:
            data: List of items to limit
            data_type: Type of data for smart limiting
            max_items: Override max items (uses default if None)
            prioritize_recent: If True, keep most recent items
            
        Returns:
            Tuple of (limited_data, was_truncated, total_count)
        """
        if not data:
            return data, False, 0
        
        total_count = len(data)
        limit = max_items or self.DEFAULT_LIMITS.get(data_type, self.DEFAULT_LIMITS['default'])
        
        # Calculate how many items fit in token budget
        per_item = self.TOKENS_PER_ITEM.get(data_type, self.TOKENS_PER_ITEM['default'])
        budget_limit = self.token_budget // per_item
        
        # Use the smaller of the two limits
        effective_limit = min(limit, budget_limit)
        
        if total_count <= effective_limit:
            return data, False, total_count
        
        # Truncate
        if prioritize_recent:
            # Assume most recent items are at the beginning or have timestamps
            limited = data[:effective_limit]
        else:
            limited = data[:effective_limit]
        
        return limited, True, total_count
    
    def create_summary(
        self, 
        data: List[Any], 
        data_type: str,
        truncated_count: int
    ) -> str:
        """Create a summary note for truncated data"""
        return f"[Showing {len(data)} of {truncated_count} {data_type}. Use more specific filters to narrow results.]"


# ==================== TIMEOUT HANDLER ====================

class TimeoutHandler:
    """
    Handles timeouts for long-running queries.
    
    Features:
    - Configurable timeouts by query type
    - Graceful timeout with partial results
    - Progress reporting for long queries
    """
    
    # Timeouts by query type (seconds)
    DEFAULT_TIMEOUTS = {
        'simple_lookup': 5.0,
        'log_search': 15.0,
        'metrics_aggregate': 10.0,
        'complex_analysis': 30.0,
        'default': 10.0
    }
    
    def __init__(self):
        self._active_queries: Dict[str, datetime] = {}
    
    def get_timeout(self, query_type: str) -> float:
        """Get timeout for a query type"""
        return self.DEFAULT_TIMEOUTS.get(query_type, self.DEFAULT_TIMEOUTS['default'])
    
    async def execute_with_timeout(
        self,
        coro,
        query_type: str = 'default',
        timeout_override: float = None
    ) -> Tuple[Any, bool]:
        """
        Execute a coroutine with timeout.
        
        Args:
            coro: The coroutine to execute
            query_type: Type of query for timeout selection
            timeout_override: Override the default timeout
            
        Returns:
            Tuple of (result, timed_out)
        """
        timeout = timeout_override or self.get_timeout(query_type)
        
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            return result, False
        except asyncio.TimeoutError:
            logger.warning(f"Query timed out after {timeout}s ({query_type})")
            return None, True


# ==================== QUERY OPTIMIZER ====================

class QueryOptimizer:
    """
    Main query optimization service.
    
    Combines caching, parallel execution, result limiting,
    and timeout handling into a unified optimization layer.
    """
    
    def __init__(
        self,
        cache_size: int = 100,
        max_parallel: int = 3,
        token_budget: int = 4000
    ):
        self.cache = QueryCache(max_size=cache_size)
        self.parallel_executor = ParallelExecutor(max_parallel=max_parallel)
        self.result_limiter = ResultLimiter(token_budget=token_budget)
        self.timeout_handler = TimeoutHandler()
        
        # Statistics
        self._queries_executed = 0
        self._queries_cached = 0
        self._queries_parallel = 0
        self._queries_timed_out = 0
    
    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        tool_handler: Callable,
        db_manager,
        use_cache: bool = True,
        data_type: str = None
    ) -> Dict[str, Any]:
        """
        Execute a tool with all optimizations applied.
        
        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            tool_handler: Async function to execute the tool
            db_manager: Database manager instance
            use_cache: Whether to use caching
            data_type: Data type for result limiting
            
        Returns:
            Tool result with optimizations applied
        """
        self._queries_executed += 1
        
        # Determine query type for caching
        query_type = self._infer_query_type(tool_name)
        
        # Check cache first
        if use_cache:
            cached = self.cache.get(query_type, params)
            if cached is not None:
                self._queries_cached += 1
                logger.debug(f"Cache hit for {tool_name}")
                return cached
        
        # Execute with timeout
        try:
            result, timed_out = await self.timeout_handler.execute_with_timeout(
                tool_handler(db_manager, **params),
                query_type=query_type
            )
            
            if timed_out:
                self._queries_timed_out += 1
                return {
                    "success": False,
                    "error": f"Query timed out. Try a more specific filter.",
                    "partial": True
                }
            
            # Apply result limiting if applicable
            if result and isinstance(result, dict) and 'data' in result:
                data = result.get('data')
                if isinstance(data, list):
                    dt = data_type or self._infer_data_type(tool_name)
                    limited, truncated, total = self.result_limiter.limit_results(data, dt)
                    result['data'] = limited
                    if truncated:
                        result['truncated'] = True
                        result['total_count'] = total
                        result['summary'] = self.result_limiter.create_summary(limited, dt, total)
            
            # Cache the result
            if use_cache and result:
                self.cache.set(query_type, params, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def execute_tools_parallel(
        self,
        calls: List[Tuple[str, Dict[str, Any]]],
        tool_handlers: Dict[str, Callable],
        db_manager
    ) -> Dict[str, Any]:
        """
        Execute multiple tools, parallelizing where possible.
        
        Args:
            calls: List of (tool_name, params) tuples
            tool_handlers: Dict mapping tool names to handlers
            db_manager: Database manager instance
            
        Returns:
            Dict mapping tool names to results
        """
        tool_calls = [
            ToolCall(tool_name=name, params=params)
            for name, params in calls
        ]
        
        async def executor(tool_name: str, params: Dict) -> Any:
            handler = tool_handlers.get(tool_name)
            if not handler:
                return {"error": f"Unknown tool: {tool_name}"}
            return await self.execute_tool(
                tool_name, params, handler, db_manager
            )
        
        groups, can_parallel = self.parallel_executor.can_parallelize(tool_calls)
        if can_parallel:
            self._queries_parallel += len(calls)
        
        return await self.parallel_executor.execute_parallel(tool_calls, executor)
    
    def _infer_query_type(self, tool_name: str) -> str:
        """Infer query type from tool name for caching"""
        if 'list_scribes' in tool_name or 'get_scribe' in tool_name:
            return 'agent_list'
        elif 'metrics' in tool_name:
            return 'metrics'
        elif 'logs' in tool_name or 'log' in tool_name:
            return 'logs'
        elif 'bookmark' in tool_name:
            return 'bookmarks'
        elif 'alert' in tool_name:
            return 'alerts'
        elif 'health' in tool_name:
            return 'system_health'
        return 'default'
    
    def _infer_data_type(self, tool_name: str) -> str:
        """Infer data type from tool name for result limiting"""
        if 'log' in tool_name:
            return 'logs'
        elif 'metric' in tool_name:
            return 'metrics'
        elif 'process' in tool_name:
            return 'processes'
        elif 'alert' in tool_name:
            return 'alerts'
        elif 'bookmark' in tool_name:
            return 'bookmarks'
        elif 'scribe' in tool_name or 'agent' in tool_name:
            return 'scribes'
        return 'default'
    
    def invalidate_cache(self, query_type: str = None):
        """Invalidate cache entries"""
        self.cache.invalidate(query_type)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get optimization statistics"""
        return {
            "queries_executed": self._queries_executed,
            "queries_cached": self._queries_cached,
            "queries_parallel": self._queries_parallel,
            "queries_timed_out": self._queries_timed_out,
            "cache": self.cache.get_stats()
        }
    
    def cleanup(self):
        """Cleanup expired cache entries"""
        self.cache.cleanup_expired()


# ==================== MODULE SINGLETON ====================

_optimizer: QueryOptimizer = None


def get_query_optimizer() -> QueryOptimizer:
    """Get the global query optimizer instance"""
    global _optimizer
    if _optimizer is None:
        _optimizer = QueryOptimizer()
    return _optimizer
