"""
Alert and System Tools for Librarian AI

Tools for alerts, system health, and summaries:
- Active alerts
- Alert history
- System health overview
- Daily summaries
"""

from datetime import datetime, timedelta
from typing import Optional, List
from collections import Counter
import json

from ai_tools import (
    AITool, ToolParameter, ToolResult, ParameterType,
    register_tool, estimate_tokens, format_timestamp, format_duration
)


# ==================== ALERT TOOLS ====================

async def get_active_alerts_handler(
    db_manager,
    severity: str = None,
    category: str = None
) -> ToolResult:
    """
    Get currently active (unacknowledged) alerts.
    """
    try:
        alerts = []
        
        if hasattr(db_manager, 'get_active_alerts'):
            alerts = db_manager.get_active_alerts()
        elif hasattr(db_manager, 'get_alerts'):
            alerts = db_manager.get_alerts(active_only=True)
        
        if not alerts:
            return ToolResult(
                success=True,
                data={
                    "message": "No active alerts",
                    "alert_count": 0,
                    "status": "healthy"
                },
                token_estimate=25
            )
        
        # Apply filters
        filtered = alerts
        
        if severity:
            severity_upper = severity.upper()
            filtered = [a for a in filtered if a.get('severity', '').upper() == severity_upper]
        
        if category:
            category_lower = category.lower()
            filtered = [a for a in filtered if a.get('category', '').lower() == category_lower]
        
        # Format alerts
        formatted = []
        for alert in filtered:
            duration = None
            if alert.get('triggered_at'):
                triggered = alert['triggered_at']
                if isinstance(triggered, str):
                    triggered = datetime.fromisoformat(triggered.replace('Z', '+00:00'))
                duration = format_duration((datetime.utcnow() - triggered.replace(tzinfo=None)).total_seconds())
            
            formatted.append({
                "id": alert.get('id'),
                "name": alert.get('name', alert.get('rule_name')),
                "severity": alert.get('severity', 'WARNING'),
                "category": alert.get('category'),
                "message": alert.get('message', '')[:300],
                "triggered_at": format_timestamp(alert.get('triggered_at')),
                "duration_active": duration,
                "target": alert.get('target', alert.get('agent_name', alert.get('bookmark_name'))),
                "value": alert.get('current_value'),
                "threshold": alert.get('threshold')
            })
        
        # Summary by severity
        by_severity = Counter(a.get('severity', 'UNKNOWN') for a in formatted)
        
        result = {
            "alert_count": len(formatted),
            "by_severity": dict(by_severity),
            "alerts": formatted
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_alert_history_handler(
    db_manager,
    hours: int = 24,
    severity: str = None,
    limit: int = 50
) -> ToolResult:
    """
    Get alert history over a time period.
    """
    try:
        hours = min(hours, 168)
        limit = min(limit, 100)
        
        alerts = []
        if hasattr(db_manager, 'get_alert_history'):
            alerts = db_manager.get_alert_history(hours=hours, limit=limit)
        elif hasattr(db_manager, 'get_alerts'):
            alerts = db_manager.get_alerts(hours=hours, limit=limit)
        
        if not alerts:
            return ToolResult(
                success=True,
                data={
                    "message": f"No alerts in the last {hours} hours",
                    "period_hours": hours
                },
                token_estimate=25
            )
        
        # Apply severity filter
        if severity:
            severity_upper = severity.upper()
            alerts = [a for a in alerts if a.get('severity', '').upper() == severity_upper]
        
        # Format
        formatted = []
        for alert in alerts[:limit]:
            formatted.append({
                "id": alert.get('id'),
                "name": alert.get('name', alert.get('rule_name')),
                "severity": alert.get('severity'),
                "message": alert.get('message', '')[:200],
                "triggered_at": format_timestamp(alert.get('triggered_at')),
                "resolved_at": format_timestamp(alert.get('resolved_at')),
                "acknowledged": alert.get('acknowledged', False),
                "target": alert.get('target')
            })
        
        # Statistics
        by_severity = Counter(a.get('severity') for a in formatted)
        resolved_count = sum(1 for a in formatted if a.get('resolved_at'))
        
        result = {
            "total_alerts": len(formatted),
            "period_hours": hours,
            "resolved_count": resolved_count,
            "active_count": len(formatted) - resolved_count,
            "by_severity": dict(by_severity),
            "alerts": formatted
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


# ==================== SYSTEM TOOLS ====================

async def get_system_health_handler(
    db_manager,
    include_details: bool = True
) -> ToolResult:
    """
    Get overall system health summary.
    
    Combines agent status, bookmark health, and active alerts.
    """
    try:
        health = {
            "timestamp": format_timestamp(datetime.utcnow()),
            "overall_status": "healthy",  # Will be downgraded if issues found
            "issues": []
        }
        
        # Agent health
        agents = db_manager.get_all_agents() if hasattr(db_manager, 'get_all_agents') else []
        if agents:
            online = sum(1 for a in agents if a.get('status') == 'online')
            offline = len(agents) - online
            
            health["agents"] = {
                "total": len(agents),
                "online": online,
                "offline": offline,
                "health_percent": round(online / len(agents) * 100, 1) if agents else 100
            }
            
            if offline > 0:
                health["overall_status"] = "degraded"
                offline_names = [a.get('hostname') for a in agents if a.get('status') != 'online'][:5]
                health["issues"].append(f"{offline} agent(s) offline: {', '.join(offline_names)}")
                
                if include_details:
                    health["agents"]["offline_agents"] = offline_names
        
        # Bookmark health
        bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
        if bookmarks:
            enabled = [b for b in bookmarks if b.get('enabled', True)]
            up = sum(1 for b in enabled if b.get('status') in ['up', 'healthy', 200])
            down = len(enabled) - up
            
            health["bookmarks"] = {
                "total": len(enabled),
                "up": up,
                "down": down,
                "health_percent": round(up / len(enabled) * 100, 1) if enabled else 100
            }
            
            if down > 0:
                health["overall_status"] = "degraded"
                down_names = [b.get('name') for b in enabled if b.get('status') not in ['up', 'healthy', 200]][:5]
                health["issues"].append(f"{down} service(s) down: {', '.join(down_names)}")
                
                if include_details:
                    health["bookmarks"]["down_services"] = down_names
        
        # Active alerts
        active_alerts = []
        if hasattr(db_manager, 'get_active_alerts'):
            active_alerts = db_manager.get_active_alerts()
        elif hasattr(db_manager, 'get_alerts'):
            active_alerts = db_manager.get_alerts(active_only=True)
        
        if active_alerts:
            critical = sum(1 for a in active_alerts if a.get('severity', '').upper() == 'CRITICAL')
            warning = sum(1 for a in active_alerts if a.get('severity', '').upper() == 'WARNING')
            
            health["alerts"] = {
                "total_active": len(active_alerts),
                "critical": critical,
                "warning": warning
            }
            
            if critical > 0:
                health["overall_status"] = "critical"
                health["issues"].append(f"{critical} critical alert(s) active")
            elif warning > 0 and health["overall_status"] != "critical":
                health["overall_status"] = "warning"
        
        # Recent errors (last hour)
        if hasattr(db_manager, 'get_logs'):
            recent_errors = db_manager.get_logs(severity='ERROR', hours=1, limit=100)
            recent_critical = db_manager.get_logs(severity='CRITICAL', hours=1, limit=100)
            
            error_count = len(recent_errors or [])
            critical_count = len(recent_critical or [])
            
            if error_count > 0 or critical_count > 0:
                health["recent_logs"] = {
                    "errors_last_hour": error_count,
                    "critical_last_hour": critical_count
                }
                
                if critical_count > 0:
                    health["issues"].append(f"{critical_count} critical log(s) in last hour")
        
        # Set healthy status message if no issues
        if not health["issues"]:
            health["status_message"] = "All systems operating normally"
        else:
            health["status_message"] = f"{len(health['issues'])} issue(s) detected"
        
        result_json = json.dumps(health, default=str)
        return ToolResult(
            success=True,
            data=health,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_daily_summary_handler(
    db_manager,
    date: str = None
) -> ToolResult:
    """
    Get a daily summary of system activity.
    
    Default is today. Pass date as YYYY-MM-DD for historical.
    """
    try:
        # Parse date
        if date:
            try:
                target_date = datetime.strptime(date, '%Y-%m-%d').date()
            except ValueError:
                return ToolResult(
                    success=False,
                    error="Invalid date format. Use YYYY-MM-DD"
                )
        else:
            target_date = datetime.utcnow().date()
        
        start_time = datetime.combine(target_date, datetime.min.time())
        end_time = datetime.combine(target_date, datetime.max.time())
        
        summary = {
            "date": str(target_date),
            "generated_at": format_timestamp(datetime.utcnow())
        }
        
        # Log summary
        if hasattr(db_manager, 'get_logs'):
            # This is simplified - ideally would use a dedicated aggregation
            all_logs = db_manager.get_logs(hours=24, limit=10000) or []
            
            # Filter to target date (rough)
            by_severity = Counter()
            by_source = Counter()
            
            for log in all_logs:
                log_time = log.get('timestamp')
                if log_time and start_time <= log_time <= end_time:
                    by_severity[log.get('severity', 'INFO')] += 1
                    by_source[log.get('source', 'unknown')] += 1
            
            total_logs = sum(by_severity.values())
            
            summary["logs"] = {
                "total": total_logs,
                "by_severity": dict(by_severity),
                "top_sources": dict(by_source.most_common(5))
            }
        
        # Agent activity
        agents = db_manager.get_all_agents() if hasattr(db_manager, 'get_all_agents') else []
        if agents:
            summary["agents"] = {
                "total": len(agents),
                "currently_online": sum(1 for a in agents if a.get('status') == 'online'),
                "currently_offline": sum(1 for a in agents if a.get('status') != 'online')
            }
        
        # Bookmark summary
        bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
        if bookmarks:
            enabled = [b for b in bookmarks if b.get('enabled', True)]
            summary["bookmarks"] = {
                "monitored": len(enabled),
                "currently_up": sum(1 for b in enabled if b.get('status') in ['up', 'healthy', 200]),
                "currently_down": sum(1 for b in enabled if b.get('status') not in ['up', 'healthy', 200])
            }
        
        # Alert summary
        alerts = []
        if hasattr(db_manager, 'get_alert_history'):
            alerts = db_manager.get_alert_history(hours=24)
        elif hasattr(db_manager, 'get_alerts'):
            alerts = db_manager.get_alerts(hours=24)
        
        if alerts:
            summary["alerts"] = {
                "total_triggered": len(alerts),
                "by_severity": dict(Counter(a.get('severity') for a in alerts)),
                "resolved": sum(1 for a in alerts if a.get('resolved_at')),
                "still_active": sum(1 for a in alerts if not a.get('resolved_at'))
            }
        
        result_json = json.dumps(summary, default=str)
        return ToolResult(
            success=True,
            data=summary,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_tenant_info_handler(
    db_manager,
    tenant_id: str = None
) -> ToolResult:
    """
    Get information about current tenant context.
    """
    try:
        # Get current tenant from context
        current_tenant = getattr(db_manager, 'tenant_id', None) or tenant_id
        
        if not current_tenant:
            return ToolResult(
                success=True,
                data={
                    "message": "No tenant context - operating in single-tenant mode"
                },
                token_estimate=20
            )
        
        # Get tenant info if available
        tenant_info = {}
        if hasattr(db_manager, 'get_tenant_info'):
            tenant_info = db_manager.get_tenant_info(current_tenant)
        
        # Count resources for this tenant
        agents = db_manager.get_all_agents() if hasattr(db_manager, 'get_all_agents') else []
        bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
        
        result = {
            "tenant_id": current_tenant,
            "name": tenant_info.get('name', 'Unknown'),
            "resources": {
                "agents": len(agents),
                "bookmarks": len(bookmarks)
            },
            "created": format_timestamp(tenant_info.get('created_at')),
            "settings": tenant_info.get('settings', {})
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

def register_alert_system_tools():
    """Register all alert and system tools in the global registry"""
    
    register_tool(AITool(
        name="get_active_alerts",
        description="Get currently active (unacknowledged) alerts in the system. Shows what needs attention right now.",
        parameters=[
            ToolParameter(
                name="severity",
                type=ParameterType.STRING,
                description="Filter by severity level",
                required=False,
                enum=["WARNING", "ERROR", "CRITICAL"]
            ),
            ToolParameter(
                name="category",
                type=ParameterType.STRING,
                description="Filter by alert category",
                required=False
            )
        ],
        handler=get_active_alerts_handler,
        category="alerts"
    ))
    
    register_tool(AITool(
        name="get_alert_history",
        description="Get historical alerts over a time period. Shows past alerts and their resolution status.",
        parameters=[
            ToolParameter(
                name="hours",
                type=ParameterType.INTEGER,
                description="Hours of history (default 24, max 168)",
                required=False,
                default=24
            ),
            ToolParameter(
                name="severity",
                type=ParameterType.STRING,
                description="Filter by severity",
                required=False,
                enum=["WARNING", "ERROR", "CRITICAL"]
            ),
            ToolParameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum alerts to return (default 50)",
                required=False,
                default=50
            )
        ],
        handler=get_alert_history_handler,
        category="alerts"
    ))
    
    register_tool(AITool(
        name="get_system_health",
        description="Get an overall system health summary combining agent status, service health, and active alerts. Use this for a quick overview of the entire system.",
        parameters=[
            ToolParameter(
                name="include_details",
                type=ParameterType.BOOLEAN,
                description="Include lists of offline agents/down services (default true)",
                required=False,
                default=True
            )
        ],
        handler=get_system_health_handler,
        category="system"
    ))
    
    register_tool(AITool(
        name="get_daily_summary",
        description="Get a summary of system activity for a specific day. Includes log counts, agent status, alerts triggered.",
        parameters=[
            ToolParameter(
                name="date",
                type=ParameterType.STRING,
                description="Date to summarize in YYYY-MM-DD format (default: today)",
                required=False
            )
        ],
        handler=get_daily_summary_handler,
        category="system"
    ))
    
    register_tool(AITool(
        name="get_tenant_info",
        description="Get information about the current tenant context in multi-tenant mode.",
        parameters=[
            ToolParameter(
                name="tenant_id",
                type=ParameterType.STRING,
                description="Tenant ID (defaults to current context)",
                required=False
            )
        ],
        handler=get_tenant_info_handler,
        category="system"
    ))


# Auto-register on import
register_alert_system_tools()
