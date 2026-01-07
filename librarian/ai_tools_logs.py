"""
Log Tools for Librarian AI

Tools for querying and analyzing logs:
- Query logs with filters
- Count/aggregate logs
- Full-text search
- Pattern detection
"""

from datetime import datetime, timedelta
from typing import Optional, List
from collections import Counter
import json
import re

from ai_tools import (
    AITool, ToolParameter, ToolResult, ParameterType,
    register_tool, estimate_tokens, fuzzy_match,
    format_timestamp, truncate_results, sanitize_log_content
)


# ==================== LOG TOOLS ====================

async def query_logs_handler(
    db_manager,
    agent_name: str = None,
    agent_id: str = None,
    severity: str = None,
    source: str = None,
    hours: int = 24,
    limit: int = 50,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Query logs with various filters.
    
    By default, focuses on warning/error/critical logs to surface issues.
    """
    try:
        # Time range
        hours = min(hours, 168)  # Max 1 week
        start_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Agent filter - resolve name to ID if needed
        target_agent_id = agent_id
        if not target_agent_id and agent_name:
            agents = db_manager.get_all_agents()
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(agent_name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent_id = agent.get('agent_id')
                        break
        
        # Build severity filter
        severity_filter = None
        if severity:
            severity_filter = severity.upper()
        else:
            # Default: show warning and above
            severity_filter = 'WARNING,ERROR,CRITICAL'
        
        # Limit
        limit = min(limit, 100)
        
        # Execute query using query_raw_logs
        logs = []
        if hasattr(db_manager, 'query_raw_logs'):
            logs = db_manager.query_raw_logs(
                agent_id=target_agent_id,
                severity=severity_filter,
                source=source,
                start_time=start_time,
                limit=limit
            ) or []
        
        if not logs:
            return ToolResult(
                success=True,
                data={
                    "message": f"No logs found matching criteria in the last {hours} hours",
                    "filters_applied": {
                        "agent": agent_name or agent_id,
                        "severity": severity or "WARNING+",
                        "source": source,
                        "hours": hours
                    }
                },
                token_estimate=50
            )
        
        # Format and sanitize logs
        formatted = []
        for log in logs[:limit]:
            entry = {
                "timestamp": format_timestamp(log['timestamp']) if log.get('timestamp') else None,
                "severity": log.get('severity', log.get('level', 'INFO')),
                "source": log.get('source', 'unknown'),
                "message": sanitize_log_content(log.get('message', '')[:500]),  # Truncate long messages
                "hostname": log.get('hostname', log.get('agent_hostname'))
            }
            formatted.append(entry)
        
        # Group by severity for summary
        severity_counts = Counter(log['severity'] for log in formatted)
        
        result = {
            "log_count": len(formatted),
            "period_hours": hours,
            "severity_summary": dict(severity_counts),
            "logs": formatted
        }
        
        if len(logs) > limit:
            result["truncated"] = True
            result["total_available"] = len(logs)
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json),
            truncated=len(logs) > limit,
            total_count=len(logs) if len(logs) > limit else None
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def count_logs_handler(
    db_manager,
    agent_name: str = None,
    agent_id: str = None,
    group_by: str = "severity",
    hours: int = 24,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Count and aggregate logs.
    
    Returns counts grouped by severity, source, or agent.
    """
    try:
        hours = min(hours, 168)
        start_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Get agent ID if name provided
        target_agent_id = agent_id
        if not target_agent_id and agent_name:
            agents = db_manager.get_all_agents()
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(agent_name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent_id = agent.get('agent_id')
                        break
        
        # Try to use aggregation method if available
        counts = {}
        if hasattr(db_manager, 'count_logs_grouped'):
            counts = db_manager.count_logs_grouped(
                agent_id=target_agent_id,
                group_by=group_by,
                start_time=start_time
            )
        elif hasattr(db_manager, 'query_raw_logs'):
            # Fallback: fetch logs and count in Python
            logs = db_manager.query_raw_logs(
                agent_id=target_agent_id,
                start_time=start_time,
                limit=5000  # Higher limit for counting
            ) or []
            
            # Get agent lookup for hostname resolution
            agents = db_manager.get_all_agents()
            agent_lookup = {a.get('agent_id'): a.get('hostname') for a in agents}
            
            if group_by == 'severity':
                counts = Counter(log.get('severity', 'INFO') for log in logs)
            elif group_by == 'source':
                counts = Counter(log.get('source', 'unknown') for log in logs)
            elif group_by == 'agent' or group_by == 'hostname':
                counts = Counter(agent_lookup.get(log.get('agent_id'), 'unknown') for log in logs)
            elif group_by == 'hour':
                def parse_ts(ts):
                    if isinstance(ts, str):
                        try:
                            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        except:
                            return None
                    return ts
                counts = Counter(
                    parse_ts(log['timestamp']).strftime('%Y-%m-%d %H:00') 
                    for log in logs if parse_ts(log.get('timestamp'))
                )
            else:
                counts = {'total': len(logs)}
        
        result = {
            "period_hours": hours,
            "group_by": group_by,
            "agent": agent_name or agent_id,
            "counts": dict(counts) if isinstance(counts, Counter) else counts,
            "total": sum(counts.values()) if isinstance(counts, (Counter, dict)) else 0
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def search_logs_handler(
    db_manager,
    query: str,
    agent_name: str = None,
    agent_id: str = None,
    severity: str = None,
    hours: int = 24,
    limit: int = 50,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Full-text search in log messages.
    
    Searches for the query string in log message content.
    """
    try:
        if not query or len(query) < 2:
            return ToolResult(
                success=False,
                error="Search query must be at least 2 characters"
            )
        
        hours = min(hours, 168)
        limit = min(limit, 100)
        start_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Get agent ID if name provided
        target_agent_id = agent_id
        if not target_agent_id and agent_name:
            agents = db_manager.get_all_agents()
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(agent_name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent_id = agent.get('agent_id')
                        break
        
        # Use query_raw_logs with search parameter
        logs = []
        if hasattr(db_manager, 'query_raw_logs'):
            logs = db_manager.query_raw_logs(
                agent_id=target_agent_id,
                search=query,
                severity=severity.upper() if severity else None,
                start_time=start_time,
                limit=limit
            ) or []
        
        if not logs:
            return ToolResult(
                success=True,
                data={
                    "message": f"No logs found containing '{query}'",
                    "query": query,
                    "period_hours": hours
                },
                token_estimate=30
            )
        
        # Get agent lookup for hostname resolution
        agents = db_manager.get_all_agents()
        agent_lookup = {a.get('agent_id'): a.get('hostname') for a in agents}
        
        # Format results with highlighted matches
        formatted = []
        for log in logs[:limit]:
            message = log.get('message', '')
            # Highlight match in message (simple version)
            sanitized = sanitize_log_content(message[:500])
            hostname = log.get('hostname') or agent_lookup.get(log.get('agent_id'), 'unknown')
            
            # Parse timestamp if string
            ts = log.get('timestamp')
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    ts = None
            
            formatted.append({
                "timestamp": format_timestamp(ts) if ts else None,
                "severity": log.get('severity', 'INFO'),
                "source": log.get('source', 'unknown'),
                "message": sanitized,
                "hostname": hostname
            })
        
        result = {
            "query": query,
            "match_count": len(formatted),
            "period_hours": hours,
            "logs": formatted
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json),
            truncated=len(logs) >= limit,
            total_count=None  # Unknown total for search
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_log_patterns_handler(
    db_manager,
    agent_name: str = None,
    agent_id: str = None,
    severity: str = "ERROR",
    hours: int = 24,
    top_n: int = 10,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Identify common log patterns/messages.
    
    Groups similar log messages to identify recurring issues.
    """
    try:
        hours = min(hours, 168)
        top_n = min(top_n, 20)
        start_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Get agent ID if name provided
        target_agent_id = agent_id
        if not target_agent_id and agent_name:
            agents = db_manager.get_all_agents()
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(agent_name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent_id = agent.get('agent_id')
                        break
        
        # Get logs for pattern analysis using query_raw_logs
        logs = []
        if hasattr(db_manager, 'query_raw_logs'):
            logs = db_manager.query_raw_logs(
                agent_id=target_agent_id,
                severity=severity.upper() if severity else None,
                start_time=start_time,
                limit=5000
            ) or []
        
        if not logs:
            return ToolResult(
                success=True,
                data={
                    "message": f"No {severity or 'all'} logs found in the last {hours} hours",
                    "period_hours": hours
                },
                token_estimate=30
            )
        
        # Extract patterns by normalizing messages
        def normalize_message(msg: str) -> str:
            """Normalize message for pattern matching"""
            if not msg:
                return ""
            # Remove timestamps, numbers, GUIDs, etc.
            msg = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', '[TIMESTAMP]', msg)
            msg = re.sub(r'\b\d+\b', '[NUM]', msg)
            msg = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '[UUID]', msg, flags=re.I)
            msg = re.sub(r'\b[0-9a-f]{32,}\b', '[HASH]', msg, flags=re.I)
            msg = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', msg)
            msg = re.sub(r'\\+', '/', msg)  # Normalize paths
            msg = re.sub(r'\s+', ' ', msg).strip()
            # Truncate for comparison
            return msg[:200]
        
        # Group by normalized pattern
        pattern_counts = Counter()
        pattern_examples = {}
        
        for log in logs:
            msg = log.get('message', '')
            pattern = normalize_message(msg)
            if pattern:
                pattern_counts[pattern] += 1
                if pattern not in pattern_examples:
                    pattern_examples[pattern] = sanitize_log_content(msg[:300])
        
        # Get top patterns
        top_patterns = pattern_counts.most_common(top_n)
        
        formatted = []
        for pattern, count in top_patterns:
            formatted.append({
                "pattern": pattern,
                "count": count,
                "example": pattern_examples.get(pattern, pattern),
                "percentage": round(count / len(logs) * 100, 1)
            })
        
        result = {
            "total_logs_analyzed": len(logs),
            "unique_patterns": len(pattern_counts),
            "severity": severity or "all",
            "period_hours": hours,
            "top_patterns": formatted
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_recent_errors_handler(
    db_manager,
    agent_name: str = None,
    agent_id: str = None,
    minutes: int = 60,
    limit: int = 20,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Get the most recent error and critical logs.
    
    Quick view of recent issues across the system.
    """
    try:
        minutes = min(minutes, 1440)  # Max 24 hours
        limit = min(limit, 50)
        
        # Get agent ID if name provided
        target_agent_id = agent_id
        if not target_agent_id and agent_name:
            agents = db_manager.get_all_agents()
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(agent_name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent_id = agent.get('agent_id')
                        break
        
        # Query for error/critical only using query_raw_logs
        start_time = datetime.utcnow() - timedelta(minutes=minutes)
        logs = []
        if hasattr(db_manager, 'query_raw_logs'):
            logs = db_manager.query_raw_logs(
                agent_id=target_agent_id,
                severity='ERROR,CRITICAL',
                start_time=start_time,
                limit=limit * 2  # Get more to ensure we have enough after sorting
            ) or []
            # Sort by timestamp descending
            logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            logs = logs[:limit]
        
        if not logs:
            return ToolResult(
                success=True,
                data={
                    "message": f"No errors or critical logs in the last {minutes} minutes",
                    "status": "healthy"
                },
                token_estimate=30
            )
        
        # Format - need to get hostname from agent lookup
        agents = db_manager.get_all_agents()
        agent_lookup = {a.get('agent_id'): a.get('hostname') for a in agents}
        
        formatted = []
        for log in logs:
            hostname = log.get('hostname') or agent_lookup.get(log.get('agent_id'), 'unknown')
            # Parse timestamp if it's a string
            ts = log.get('timestamp')
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    ts = None
            formatted.append({
                "timestamp": format_timestamp(ts) if ts else None,
                "severity": log.get('severity', 'ERROR'),
                "source": log.get('source', 'unknown'),
                "message": sanitize_log_content(log.get('message', '')[:300]),
                "hostname": hostname
            })
        
        # Count by agent
        by_agent = Counter(log['hostname'] for log in formatted if log.get('hostname'))
        
        result = {
            "error_count": len(formatted),
            "period_minutes": minutes,
            "by_agent": dict(by_agent),
            "errors": formatted
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


# ==================== REGISTER TOOLS ====================

def register_log_tools():
    """Register all log tools in the global registry"""
    
    register_tool(AITool(
        name="query_logs",
        description="Query logs with filters for agent, severity, source, and time range. Use this to investigate issues or see what's happening on a system. By default shows WARNING and above.",
        parameters=[
            ToolParameter(
                name="agent_name",
                type=ParameterType.STRING,
                description="Hostname of the scribe to filter logs (supports fuzzy matching)",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="severity",
                type=ParameterType.STRING,
                description="Filter by severity level",
                required=False,
                enum=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            ),
            ToolParameter(
                name="source",
                type=ParameterType.STRING,
                description="Filter by log source/application",
                required=False
            ),
            ToolParameter(
                name="hours",
                type=ParameterType.INTEGER,
                description="Hours of history to query (default 24, max 168)",
                required=False,
                default=24
            ),
            ToolParameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum logs to return (default 50, max 100)",
                required=False,
                default=50
            )
        ],
        handler=query_logs_handler,
        category="logs"
    ))
    
    register_tool(AITool(
        name="count_logs",
        description="Count and aggregate logs by severity, source, agent, or time. Use for getting an overview of log volume and distribution.",
        parameters=[
            ToolParameter(
                name="agent_name",
                type=ParameterType.STRING,
                description="Hostname to filter (supports fuzzy matching)",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="group_by",
                type=ParameterType.STRING,
                description="How to group counts (default: severity)",
                required=False,
                default="severity",
                enum=["severity", "source", "agent", "hostname", "hour"]
            ),
            ToolParameter(
                name="hours",
                type=ParameterType.INTEGER,
                description="Hours of history (default 24)",
                required=False,
                default=24
            )
        ],
        handler=count_logs_handler,
        category="logs"
    ))
    
    register_tool(AITool(
        name="search_logs",
        description="Full-text search in log messages. Use when looking for specific text, error codes, or keywords in logs.",
        parameters=[
            ToolParameter(
                name="query",
                type=ParameterType.STRING,
                description="Text to search for in log messages",
                required=True
            ),
            ToolParameter(
                name="agent_name",
                type=ParameterType.STRING,
                description="Hostname to filter (supports fuzzy matching)",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="severity",
                type=ParameterType.STRING,
                description="Filter by severity",
                required=False,
                enum=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            ),
            ToolParameter(
                name="hours",
                type=ParameterType.INTEGER,
                description="Hours of history (default 24)",
                required=False,
                default=24
            ),
            ToolParameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum results (default 50, max 100)",
                required=False,
                default=50
            )
        ],
        handler=search_logs_handler,
        category="logs"
    ))
    
    register_tool(AITool(
        name="get_log_patterns",
        description="Identify recurring log patterns and their frequency. Use to find the most common errors or issues.",
        parameters=[
            ToolParameter(
                name="agent_name",
                type=ParameterType.STRING,
                description="Hostname to filter",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="severity",
                type=ParameterType.STRING,
                description="Severity to analyze (default: ERROR)",
                required=False,
                default="ERROR",
                enum=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            ),
            ToolParameter(
                name="hours",
                type=ParameterType.INTEGER,
                description="Hours of history (default 24)",
                required=False,
                default=24
            ),
            ToolParameter(
                name="top_n",
                type=ParameterType.INTEGER,
                description="Number of top patterns to return (default 10)",
                required=False,
                default=10
            )
        ],
        handler=get_log_patterns_handler,
        category="logs"
    ))
    
    register_tool(AITool(
        name="get_recent_errors",
        description="Get the most recent error and critical logs. Quick way to see current issues.",
        parameters=[
            ToolParameter(
                name="agent_name",
                type=ParameterType.STRING,
                description="Hostname to filter",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="minutes",
                type=ParameterType.INTEGER,
                description="How many minutes back to look (default 60)",
                required=False,
                default=60
            ),
            ToolParameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum errors to return (default 20)",
                required=False,
                default=20
            )
        ],
        handler=get_recent_errors_handler,
        category="logs"
    ))


# Auto-register on import
register_log_tools()
