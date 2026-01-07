"""
Scribe (Agent) Tools for Librarian AI

Tools for querying information about scribes/agents:
- Agent info and status
- Metrics (CPU, RAM, disk, etc.)
- Running processes
- Uptime and availability
"""

from datetime import datetime, timedelta
from typing import Optional, List
import json

from ai_tools import (
    AITool, ToolParameter, ToolResult, ParameterType,
    register_tool, estimate_tokens, fuzzy_match, 
    format_timestamp, format_duration, truncate_results
)


# ==================== SCRIBE TOOLS ====================

async def get_scribe_info_handler(db_manager, name: str = None, agent_id: str = None, **kwargs) -> ToolResult:
    """
    Get detailed information about a specific scribe/agent.
    
    Supports fuzzy name matching if exact match not found.
    """
    try:
        agents = db_manager.get_all_agents()
        
        if not agents:
            return ToolResult(
                success=True,
                data={"message": "No scribes registered in the system"},
                token_estimate=20
            )
        
        target_agent = None
        
        # Find by ID first (exact match)
        if agent_id:
            for agent in agents:
                if agent.get('agent_id') == agent_id:
                    target_agent = agent
                    break
        
        # Find by name (with fuzzy matching)
        if not target_agent and name:
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(name, agent_names)
            
            if matches:
                best_match = matches[0][0]
                for agent in agents:
                    if agent.get('hostname') == best_match:
                        target_agent = agent
                        break
        
        if not target_agent:
            # Return suggestions
            suggestions = [a.get('hostname', a.get('agent_id', 'unknown')) for a in agents[:5]]
            return ToolResult(
                success=True,
                data={
                    "message": f"No scribe found matching '{name or agent_id}'",
                    "suggestions": suggestions
                },
                token_estimate=50
            )
        
        # Build detailed info
        info = {
            "agent_id": target_agent.get('agent_id'),
            "hostname": target_agent.get('hostname'),
            "os": target_agent.get('os', 'Unknown'),
            "os_version": target_agent.get('os_version', ''),
            "ip_address": target_agent.get('ip_address', 'Unknown'),
            "status": "online" if target_agent.get('is_connected') else "offline",
            "last_seen": format_timestamp(target_agent['last_heartbeat']) if target_agent.get('last_heartbeat') else "Never",
            "first_seen": format_timestamp(target_agent['first_seen']) if target_agent.get('first_seen') else "Unknown",
            "scribe_version": target_agent.get('scribe_version', 'Unknown'),
            "enabled": target_agent.get('enabled', True),
            "tags": target_agent.get('tags', [])
        }
        
        # Get latest metrics if available
        try:
            metrics = db_manager.get_agent_metrics(target_agent['agent_id'], hours=1)
            if metrics:
                latest = metrics[-1] if isinstance(metrics, list) else metrics
                info["latest_metrics"] = {
                    "cpu_percent": latest.get('cpu_percent'),
                    "memory_percent": latest.get('memory_percent'),
                    "disk_percent": latest.get('disk_percent'),
                    "timestamp": format_timestamp(latest['timestamp']) if latest.get('timestamp') else None
                }
        except Exception:
            pass
        
        result_json = json.dumps(info, default=str)
        return ToolResult(
            success=True,
            data=info,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def list_scribes_handler(
    db_manager,
    status: str = None,
    os: str = None,
    tag: str = None,
    limit: int = 50,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """List all scribes with optional filtering."""
    try:
        agents = db_manager.get_all_agents()
        
        if not agents:
            return ToolResult(
                success=True,
                data={"message": "No scribes registered", "scribes": []},
                token_estimate=20
            )
        
        # Apply filters
        filtered = []
        for agent in agents:
            # Status filter
            if status:
                is_online = agent.get('is_connected', False)
                if status.lower() == 'online' and not is_online:
                    continue
                if status.lower() == 'offline' and is_online:
                    continue
            
            # OS filter
            if os and os.lower() not in agent.get('os', '').lower():
                continue
            
            # Tag filter
            if tag:
                agent_tags = agent.get('tags', [])
                if not any(tag.lower() in t.lower() for t in agent_tags):
                    continue
            
            filtered.append(agent)
        
        # Truncate and format
        filtered, truncated, total = truncate_results(filtered, limit)
        
        scribes = []
        for agent in filtered:
            scribes.append({
                "hostname": agent.get('hostname'),
                "agent_id": agent.get('agent_id'),
                "os": agent.get('os', 'Unknown'),
                "status": "online" if agent.get('is_connected') else "offline",
                "last_seen": format_timestamp(agent['last_heartbeat']) if agent.get('last_heartbeat') else "Never",
                "tags": agent.get('tags', [])
            })
        
        result = {"scribes": scribes, "count": len(scribes)}
        if truncated:
            result["total"] = total
            result["truncated"] = True
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json),
            truncated=truncated,
            total_count=total if truncated else None
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_scribe_metrics_handler(
    db_manager,
    name: str = None,
    agent_id: str = None,
    hours: int = 24,
    metric_type: str = None,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Get time-series metrics for a scribe.
    
    Returns CPU, memory, disk, and network metrics.
    """
    try:
        # First find the agent
        agents = db_manager.get_all_agents()
        target_agent = None
        
        if agent_id:
            for agent in agents:
                if agent.get('agent_id') == agent_id:
                    target_agent = agent
                    break
        
        if not target_agent and name:
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent = agent
                        break
        
        if not target_agent:
            return ToolResult(
                success=True,
                data={"message": f"No scribe found matching '{name or agent_id}'"},
                token_estimate=20
            )
        
        # Get metrics
        hours = min(hours, 168)  # Cap at 1 week
        metrics = db_manager.get_agent_metrics(target_agent['agent_id'], hours=hours)
        
        if not metrics:
            return ToolResult(
                success=True,
                data={
                    "hostname": target_agent.get('hostname'),
                    "message": f"No metrics available for the last {hours} hours"
                },
                token_estimate=30
            )
        
        # Aggregate metrics (downsample if too many points)
        max_points = 100
        if len(metrics) > max_points:
            # Sample evenly
            step = len(metrics) // max_points
            metrics = metrics[::step]
        
        # Format based on metric type requested
        if metric_type:
            metric_type = metric_type.lower()
            if metric_type in ('cpu', 'memory', 'disk', 'network'):
                # Filter to specific metric
                formatted = []
                for m in metrics:
                    point = {"timestamp": format_timestamp(m['timestamp'])}
                    if metric_type == 'cpu':
                        point['cpu_percent'] = m.get('cpu_percent')
                    elif metric_type == 'memory':
                        point['memory_percent'] = m.get('memory_percent')
                        point['memory_used_gb'] = round(m.get('memory_used', 0) / (1024**3), 2)
                    elif metric_type == 'disk':
                        point['disk_percent'] = m.get('disk_percent')
                        point['disk_used_gb'] = round(m.get('disk_used', 0) / (1024**3), 2)
                    elif metric_type == 'network':
                        point['bytes_sent'] = m.get('bytes_sent')
                        point['bytes_recv'] = m.get('bytes_recv')
                    formatted.append(point)
                metrics = formatted
        else:
            # Return summary with key metrics
            formatted = []
            for m in metrics:
                formatted.append({
                    "timestamp": format_timestamp(m['timestamp']),
                    "cpu_percent": m.get('cpu_percent'),
                    "memory_percent": m.get('memory_percent'),
                    "disk_percent": m.get('disk_percent')
                })
            metrics = formatted
        
        # Calculate summary stats
        cpu_values = [m.get('cpu_percent') for m in metrics if m.get('cpu_percent') is not None]
        mem_values = [m.get('memory_percent') for m in metrics if m.get('memory_percent') is not None]
        
        result = {
            "hostname": target_agent.get('hostname'),
            "period_hours": hours,
            "data_points": len(metrics),
            "summary": {
                "cpu_avg": round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None,
                "cpu_max": max(cpu_values) if cpu_values else None,
                "memory_avg": round(sum(mem_values) / len(mem_values), 1) if mem_values else None,
                "memory_max": max(mem_values) if mem_values else None
            },
            "metrics": metrics[:50]  # Limit data points returned
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json),
            truncated=len(metrics) > 50,
            total_count=len(metrics) if len(metrics) > 50 else None
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_scribe_processes_handler(
    db_manager,
    name: str = None,
    agent_id: str = None,
    sort_by: str = "cpu",
    limit: int = 20,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Get running processes for a scribe.
    
    Returns process list sorted by CPU or memory usage.
    """
    try:
        # Find the agent
        agents = db_manager.get_all_agents()
        target_agent = None
        
        if agent_id:
            for agent in agents:
                if agent.get('agent_id') == agent_id:
                    target_agent = agent
                    break
        
        if not target_agent and name:
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent = agent
                        break
        
        if not target_agent:
            return ToolResult(
                success=True,
                data={"message": f"No scribe found matching '{name or agent_id}'"},
                token_estimate=20
            )
        
        # Get latest process snapshot
        processes = db_manager.get_agent_processes(target_agent['agent_id'])
        
        if not processes:
            return ToolResult(
                success=True,
                data={
                    "hostname": target_agent.get('hostname'),
                    "message": "No process data available"
                },
                token_estimate=30
            )
        
        # Sort processes
        sort_key = 'cpu_percent' if sort_by.lower() == 'cpu' else 'memory_percent'
        processes = sorted(processes, key=lambda p: p.get(sort_key, 0) or 0, reverse=True)
        
        # Limit and format
        limit = min(limit, 50)
        processes, truncated, total = truncate_results(processes, limit)
        
        formatted = []
        for proc in processes:
            formatted.append({
                "name": proc.get('name'),
                "pid": proc.get('pid'),
                "cpu_percent": proc.get('cpu_percent'),
                "memory_percent": proc.get('memory_percent'),
                "memory_mb": round(proc.get('memory_rss', 0) / (1024**2), 1) if proc.get('memory_rss') else None,
                "status": proc.get('status'),
                "username": proc.get('username')
            })
        
        result = {
            "hostname": target_agent.get('hostname'),
            "process_count": len(formatted),
            "sorted_by": sort_by,
            "processes": formatted
        }
        if truncated:
            result["total_processes"] = total
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json),
            truncated=truncated,
            total_count=total if truncated else None
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_scribe_uptime_handler(
    db_manager,
    name: str = None,
    agent_id: str = None,
    days: int = 7,
    **kwargs  # Ignore extra parameters AI might send
) -> ToolResult:
    """
    Calculate uptime/availability for a scribe.
    
    Returns uptime percentage and incident timeline.
    """
    try:
        # Find the agent
        agents = db_manager.get_all_agents()
        target_agent = None
        
        if agent_id:
            for agent in agents:
                if agent.get('agent_id') == agent_id:
                    target_agent = agent
                    break
        
        if not target_agent and name:
            agent_names = [a.get('hostname', '') for a in agents]
            matches = fuzzy_match(name, agent_names)
            if matches:
                for agent in agents:
                    if agent.get('hostname') == matches[0][0]:
                        target_agent = agent
                        break
        
        if not target_agent:
            return ToolResult(
                success=True,
                data={"message": f"No scribe found matching '{name or agent_id}'"},
                token_estimate=20
            )
        
        # Calculate uptime from heartbeat data
        days = min(days, 30)  # Cap at 30 days
        
        # Get uptime stats if method exists
        uptime_data = None
        if hasattr(db_manager, 'get_agent_uptime_stats'):
            uptime_data = db_manager.get_agent_uptime_stats(target_agent['agent_id'], days=days)
        
        if uptime_data:
            result = {
                "hostname": target_agent.get('hostname'),
                "period_days": days,
                "uptime_percent": uptime_data.get('uptime_percent'),
                "total_downtime": format_duration(uptime_data.get('total_downtime_seconds', 0)),
                "incidents": uptime_data.get('incidents', [])[:10],  # Limit incidents
                "current_status": "online" if target_agent.get('is_connected') else "offline"
            }
        else:
            # Fallback: simple calculation
            is_online = target_agent.get('is_connected', False)
            last_seen = target_agent.get('last_heartbeat')
            
            result = {
                "hostname": target_agent.get('hostname'),
                "period_days": days,
                "current_status": "online" if is_online else "offline",
                "last_seen": format_timestamp(last_seen) if last_seen else "Never",
                "message": "Detailed uptime tracking requires heartbeat history"
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

def register_scribe_tools():
    """Register all scribe tools in the global registry"""
    
    register_tool(AITool(
        name="get_scribe_info",
        description="Get detailed information about a specific scribe/agent including OS, IP, status, version, and latest metrics. Use this when asked about a specific machine or server.",
        parameters=[
            ToolParameter(
                name="name",
                type=ParameterType.STRING,
                description="Hostname or name of the scribe (supports fuzzy matching)",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            )
        ],
        handler=get_scribe_info_handler,
        category="scribes"
    ))
    
    register_tool(AITool(
        name="list_scribes",
        description="List all registered scribes/agents with optional filtering by status, OS, or tags. Use this to see all monitored machines.",
        parameters=[
            ToolParameter(
                name="status",
                type=ParameterType.STRING,
                description="Filter by status: 'online' or 'offline'",
                required=False,
                enum=["online", "offline"]
            ),
            ToolParameter(
                name="os",
                type=ParameterType.STRING,
                description="Filter by operating system (e.g., 'windows', 'linux')",
                required=False
            ),
            ToolParameter(
                name="tag",
                type=ParameterType.STRING,
                description="Filter by tag",
                required=False
            ),
            ToolParameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum number of results (default 50)",
                required=False,
                default=50
            )
        ],
        handler=list_scribes_handler,
        category="scribes"
    ))
    
    register_tool(AITool(
        name="get_scribe_metrics",
        description="Get CPU, memory, disk, and network metrics for a scribe over time. Use this when asked about resource usage or performance.",
        parameters=[
            ToolParameter(
                name="name",
                type=ParameterType.STRING,
                description="Hostname or name of the scribe",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="hours",
                type=ParameterType.INTEGER,
                description="How many hours of history to retrieve (default 24, max 168)",
                required=False,
                default=24
            ),
            ToolParameter(
                name="metric_type",
                type=ParameterType.STRING,
                description="Specific metric type to focus on",
                required=False,
                enum=["cpu", "memory", "disk", "network"]
            )
        ],
        handler=get_scribe_metrics_handler,
        category="scribes"
    ))
    
    register_tool(AITool(
        name="get_scribe_processes",
        description="Get list of running processes on a scribe, sorted by resource usage. Use when asked about what's running or consuming resources.",
        parameters=[
            ToolParameter(
                name="name",
                type=ParameterType.STRING,
                description="Hostname or name of the scribe",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="sort_by",
                type=ParameterType.STRING,
                description="Sort by 'cpu' or 'memory' (default: cpu)",
                required=False,
                default="cpu",
                enum=["cpu", "memory"]
            ),
            ToolParameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum processes to return (default 20, max 50)",
                required=False,
                default=20
            )
        ],
        handler=get_scribe_processes_handler,
        category="scribes"
    ))
    
    register_tool(AITool(
        name="get_scribe_uptime",
        description="Get uptime/availability statistics for a scribe including downtime incidents. Use when asked about reliability or outages.",
        parameters=[
            ToolParameter(
                name="name",
                type=ParameterType.STRING,
                description="Hostname or name of the scribe",
                required=False
            ),
            ToolParameter(
                name="agent_id",
                type=ParameterType.STRING,
                description="Exact agent ID if known",
                required=False
            ),
            ToolParameter(
                name="days",
                type=ParameterType.INTEGER,
                description="Number of days to calculate uptime for (default 7, max 30)",
                required=False,
                default=7
            )
        ],
        handler=get_scribe_uptime_handler,
        category="scribes"
    ))


# Auto-register on import
register_scribe_tools()
