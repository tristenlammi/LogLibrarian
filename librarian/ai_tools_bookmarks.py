"""
Bookmark Tools for Librarian AI

Tools for querying and monitoring bookmarked URLs/services:
- Get bookmark info and status
- List bookmarks with filters
- Get uptime and incident history
"""

from datetime import datetime, timedelta
from typing import Optional, List
from collections import Counter
import json

from ai_tools import (
    AITool, ToolParameter, ToolResult, ParameterType,
    register_tool, estimate_tokens, fuzzy_match,
    format_timestamp, format_duration, truncate_results
)


# ==================== BOOKMARK TOOLS ====================

async def get_bookmark_info_handler(
    db_manager,
    bookmark_name: str = None,
    bookmark_id: str = None,
    url: str = None
) -> ToolResult:
    """
    Get detailed information about a specific bookmark.
    
    Supports lookup by name (fuzzy), ID, or URL.
    """
    try:
        if not bookmark_name and not bookmark_id and not url:
            return ToolResult(
                success=False,
                error="Please provide bookmark_name, bookmark_id, or url"
            )
        
        # Get all bookmarks
        bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
        
        if not bookmarks:
            return ToolResult(
                success=False,
                error="No bookmarks found in system"
            )
        
        # Find the bookmark
        bookmark = None
        
        if bookmark_id:
            for bm in bookmarks:
                if str(bm.get('id')) == str(bookmark_id):
                    bookmark = bm
                    break
        elif url:
            for bm in bookmarks:
                if bm.get('url', '').lower() == url.lower():
                    bookmark = bm
                    break
        elif bookmark_name:
            # Fuzzy match on name
            names = [bm.get('name', '') for bm in bookmarks]
            matches = fuzzy_match(bookmark_name, names)
            if matches:
                for bm in bookmarks:
                    if bm.get('name') == matches[0][0]:
                        bookmark = bm
                        break
        
        if not bookmark:
            # Suggest similar if name search
            if bookmark_name:
                names = [bm.get('name', '') for bm in bookmarks]
                return ToolResult(
                    success=False,
                    error=f"Bookmark '{bookmark_name}' not found. Available: {', '.join(names[:5])}"
                )
            return ToolResult(
                success=False,
                error="Bookmark not found"
            )
        
        # Get recent status history
        status_history = []
        if hasattr(db_manager, 'get_bookmark_status_history'):
            status_history = db_manager.get_bookmark_status_history(
                bookmark['id'],
                hours=24
            )
        
        # Calculate uptime if we have history
        uptime_percent = None
        if status_history:
            up_count = sum(1 for s in status_history if s.get('status') in ['up', 'healthy', 200])
            uptime_percent = round(up_count / len(status_history) * 100, 2) if status_history else None
        
        result = {
            "id": bookmark.get('id'),
            "name": bookmark.get('name'),
            "url": bookmark.get('url'),
            "category": bookmark.get('category'),
            "tags": bookmark.get('tags', []),
            "enabled": bookmark.get('enabled', True),
            "check_interval_minutes": bookmark.get('check_interval', 5),
            "current_status": {
                "status": bookmark.get('status', 'unknown'),
                "response_time_ms": bookmark.get('response_time'),
                "last_checked": format_timestamp(bookmark.get('last_checked'))
            },
            "uptime_24h_percent": uptime_percent,
            "created": format_timestamp(bookmark.get('created_at')),
            "last_incident": format_timestamp(bookmark.get('last_incident'))
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def list_bookmarks_handler(
    db_manager,
    status: str = None,
    category: str = None,
    tag: str = None,
    enabled_only: bool = True
) -> ToolResult:
    """
    List all bookmarks with optional filters.
    """
    try:
        bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
        
        if not bookmarks:
            return ToolResult(
                success=True,
                data={"message": "No bookmarks configured", "bookmarks": []},
                token_estimate=20
            )
        
        # Apply filters
        filtered = bookmarks
        
        if enabled_only:
            filtered = [b for b in filtered if b.get('enabled', True)]
        
        if status:
            status_lower = status.lower()
            if status_lower == 'up':
                filtered = [b for b in filtered if b.get('status') in ['up', 'healthy', 200]]
            elif status_lower == 'down':
                filtered = [b for b in filtered if b.get('status') in ['down', 'unhealthy', 'error']]
            else:
                filtered = [b for b in filtered if str(b.get('status', '')).lower() == status_lower]
        
        if category:
            filtered = [b for b in filtered if b.get('category', '').lower() == category.lower()]
        
        if tag:
            tag_lower = tag.lower()
            filtered = [
                b for b in filtered 
                if any(t.lower() == tag_lower for t in (b.get('tags') or []))
            ]
        
        # Format for output
        formatted = []
        for bm in filtered:
            formatted.append({
                "id": bm.get('id'),
                "name": bm.get('name'),
                "url": bm.get('url'),
                "status": bm.get('status', 'unknown'),
                "response_time_ms": bm.get('response_time'),
                "category": bm.get('category'),
                "last_checked": format_timestamp(bm.get('last_checked'))
            })
        
        # Group by status for summary
        status_counts = Counter(b.get('status', 'unknown') for b in formatted)
        
        result = {
            "total_count": len(formatted),
            "filters_applied": {
                "status": status,
                "category": category,
                "tag": tag,
                "enabled_only": enabled_only
            },
            "status_summary": dict(status_counts),
            "bookmarks": formatted
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_bookmark_status_handler(
    db_manager,
    bookmark_name: str = None,
    bookmark_id: str = None,
    hours: int = 24
) -> ToolResult:
    """
    Get status history and response times for a bookmark.
    """
    try:
        if not bookmark_name and not bookmark_id:
            return ToolResult(
                success=False,
                error="Please provide bookmark_name or bookmark_id"
            )
        
        hours = min(hours, 168)  # Max 1 week
        
        # Find bookmark
        bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
        bookmark = None
        
        if bookmark_id:
            for bm in bookmarks:
                if str(bm.get('id')) == str(bookmark_id):
                    bookmark = bm
                    break
        elif bookmark_name:
            names = [bm.get('name', '') for bm in bookmarks]
            matches = fuzzy_match(bookmark_name, names)
            if matches:
                for bm in bookmarks:
                    if bm.get('name') == matches[0][0]:
                        bookmark = bm
                        break
        
        if not bookmark:
            return ToolResult(
                success=False,
                error=f"Bookmark not found: {bookmark_name or bookmark_id}"
            )
        
        # Get status history
        history = []
        if hasattr(db_manager, 'get_bookmark_status_history'):
            history = db_manager.get_bookmark_status_history(
                bookmark['id'],
                hours=hours
            )
        
        if not history:
            return ToolResult(
                success=True,
                data={
                    "bookmark": bookmark.get('name'),
                    "current_status": bookmark.get('status'),
                    "message": f"No status history available for last {hours} hours"
                },
                token_estimate=40
            )
        
        # Calculate statistics
        up_checks = sum(1 for h in history if h.get('status') in ['up', 'healthy', 200])
        down_checks = len(history) - up_checks
        
        response_times = [h.get('response_time') for h in history if h.get('response_time')]
        avg_response = sum(response_times) / len(response_times) if response_times else None
        max_response = max(response_times) if response_times else None
        min_response = min(response_times) if response_times else None
        
        # Find outages (transitions to down)
        outages = []
        prev_up = True
        current_outage = None
        
        for h in sorted(history, key=lambda x: x.get('timestamp', datetime.min)):
            is_up = h.get('status') in ['up', 'healthy', 200]
            if prev_up and not is_up:
                current_outage = {'start': h.get('timestamp')}
            elif not prev_up and is_up and current_outage:
                current_outage['end'] = h.get('timestamp')
                outages.append(current_outage)
                current_outage = None
            prev_up = is_up
        
        # Downsample history for output (max 50 points)
        if len(history) > 50:
            step = len(history) // 50
            history = history[::step][:50]
        
        result = {
            "bookmark": bookmark.get('name'),
            "url": bookmark.get('url'),
            "period_hours": hours,
            "statistics": {
                "uptime_percent": round(up_checks / len(history) * 100, 2) if history else None,
                "total_checks": up_checks + down_checks,
                "up_checks": up_checks,
                "down_checks": down_checks,
                "avg_response_ms": round(avg_response, 1) if avg_response else None,
                "min_response_ms": min_response,
                "max_response_ms": max_response
            },
            "outages_count": len(outages),
            "recent_history": [
                {
                    "timestamp": format_timestamp(h.get('timestamp')),
                    "status": h.get('status'),
                    "response_time_ms": h.get('response_time')
                }
                for h in history[-20:]  # Last 20 entries
            ]
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_bookmark_incidents_handler(
    db_manager,
    bookmark_name: str = None,
    bookmark_id: str = None,
    days: int = 7,
    limit: int = 20
) -> ToolResult:
    """
    Get incident/outage history for a bookmark.
    """
    try:
        days = min(days, 30)
        limit = min(limit, 50)
        
        # Find bookmark if specified
        bookmark = None
        if bookmark_name or bookmark_id:
            bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
            
            if bookmark_id:
                for bm in bookmarks:
                    if str(bm.get('id')) == str(bookmark_id):
                        bookmark = bm
                        break
            elif bookmark_name:
                names = [bm.get('name', '') for bm in bookmarks]
                matches = fuzzy_match(bookmark_name, names)
                if matches:
                    for bm in bookmarks:
                        if bm.get('name') == matches[0][0]:
                            bookmark = bm
                            break
        
        # Get incidents
        incidents = []
        if hasattr(db_manager, 'get_bookmark_incidents'):
            incidents = db_manager.get_bookmark_incidents(
                bookmark_id=bookmark['id'] if bookmark else None,
                days=days,
                limit=limit
            )
        elif hasattr(db_manager, 'get_incidents'):
            incidents = db_manager.get_incidents(
                bookmark_id=bookmark['id'] if bookmark else None,
                days=days
            )
        
        if not incidents:
            return ToolResult(
                success=True,
                data={
                    "message": f"No incidents in the last {days} days",
                    "bookmark": bookmark.get('name') if bookmark else "all",
                    "status": "healthy"
                },
                token_estimate=30
            )
        
        # Format incidents
        formatted = []
        for inc in incidents[:limit]:
            duration = None
            if inc.get('start_time') and inc.get('end_time'):
                duration = format_duration(
                    (inc['end_time'] - inc['start_time']).total_seconds()
                )
            
            formatted.append({
                "bookmark_name": inc.get('bookmark_name'),
                "start_time": format_timestamp(inc.get('start_time')),
                "end_time": format_timestamp(inc.get('end_time')),
                "duration": duration,
                "status_code": inc.get('status_code'),
                "error_message": inc.get('error_message', '')[:200],
                "resolved": inc.get('resolved', inc.get('end_time') is not None)
            })
        
        # Summary by bookmark
        by_bookmark = Counter(inc.get('bookmark_name') for inc in formatted)
        
        result = {
            "incident_count": len(formatted),
            "period_days": days,
            "by_bookmark": dict(by_bookmark),
            "incidents": formatted
        }
        
        result_json = json.dumps(result, default=str)
        return ToolResult(
            success=True,
            data=result,
            token_estimate=estimate_tokens(result_json)
        )
        
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def get_bookmark_uptime_handler(
    db_manager,
    bookmark_name: str = None,
    bookmark_id: str = None,
    days: int = 7
) -> ToolResult:
    """
    Calculate uptime percentage for bookmark(s) over a period.
    """
    try:
        days = min(days, 30)
        
        bookmarks = db_manager.get_bookmarks() if hasattr(db_manager, 'get_bookmarks') else []
        
        if not bookmarks:
            return ToolResult(
                success=True,
                data={"message": "No bookmarks configured"},
                token_estimate=15
            )
        
        # Filter to specific bookmark if requested
        if bookmark_name or bookmark_id:
            target = None
            if bookmark_id:
                for bm in bookmarks:
                    if str(bm.get('id')) == str(bookmark_id):
                        target = bm
                        break
            elif bookmark_name:
                names = [bm.get('name', '') for bm in bookmarks]
                matches = fuzzy_match(bookmark_name, names)
                if matches:
                    for bm in bookmarks:
                        if bm.get('name') == matches[0][0]:
                            target = bm
                            break
            
            if target:
                bookmarks = [target]
            else:
                return ToolResult(
                    success=False,
                    error=f"Bookmark not found: {bookmark_name or bookmark_id}"
                )
        
        # Calculate uptime for each bookmark
        uptime_data = []
        
        for bm in bookmarks:
            uptime_percent = None
            total_checks = 0
            
            if hasattr(db_manager, 'get_bookmark_uptime'):
                uptime_info = db_manager.get_bookmark_uptime(bm['id'], days=days)
                uptime_percent = uptime_info.get('uptime_percent')
                total_checks = uptime_info.get('total_checks', 0)
            elif hasattr(db_manager, 'get_bookmark_status_history'):
                history = db_manager.get_bookmark_status_history(bm['id'], hours=days*24)
                if history:
                    up_count = sum(1 for h in history if h.get('status') in ['up', 'healthy', 200])
                    total_checks = len(history)
                    uptime_percent = round(up_count / total_checks * 100, 2)
            
            uptime_data.append({
                "bookmark_id": bm.get('id'),
                "name": bm.get('name'),
                "url": bm.get('url'),
                "uptime_percent": uptime_percent,
                "total_checks": total_checks,
                "current_status": bm.get('status', 'unknown')
            })
        
        # Sort by uptime (worst first)
        uptime_data.sort(key=lambda x: x.get('uptime_percent') or 0)
        
        # Calculate average uptime
        valid_uptimes = [u['uptime_percent'] for u in uptime_data if u['uptime_percent'] is not None]
        avg_uptime = sum(valid_uptimes) / len(valid_uptimes) if valid_uptimes else None
        
        result = {
            "period_days": days,
            "total_bookmarks": len(uptime_data),
            "average_uptime_percent": round(avg_uptime, 2) if avg_uptime else None,
            "uptimes": uptime_data
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

def register_bookmark_tools():
    """Register all bookmark tools in the global registry"""
    
    register_tool(AITool(
        name="get_bookmark_info",
        description="Get detailed information about a specific monitored URL/service. Look up by name, ID, or URL.",
        parameters=[
            ToolParameter(
                name="bookmark_name",
                type=ParameterType.STRING,
                description="Name of the bookmark (supports fuzzy matching)",
                required=False
            ),
            ToolParameter(
                name="bookmark_id",
                type=ParameterType.STRING,
                description="Exact bookmark ID if known",
                required=False
            ),
            ToolParameter(
                name="url",
                type=ParameterType.STRING,
                description="URL of the bookmark to find",
                required=False
            )
        ],
        handler=get_bookmark_info_handler,
        category="bookmarks"
    ))
    
    register_tool(AITool(
        name="list_bookmarks",
        description="List all monitored URLs/services with their current status. Filter by status, category, or tag.",
        parameters=[
            ToolParameter(
                name="status",
                type=ParameterType.STRING,
                description="Filter by status (up, down)",
                required=False,
                enum=["up", "down"]
            ),
            ToolParameter(
                name="category",
                type=ParameterType.STRING,
                description="Filter by category",
                required=False
            ),
            ToolParameter(
                name="tag",
                type=ParameterType.STRING,
                description="Filter by tag",
                required=False
            ),
            ToolParameter(
                name="enabled_only",
                type=ParameterType.BOOLEAN,
                description="Only show enabled bookmarks (default true)",
                required=False,
                default=True
            )
        ],
        handler=list_bookmarks_handler,
        category="bookmarks"
    ))
    
    register_tool(AITool(
        name="get_bookmark_status",
        description="Get status history and response time statistics for a bookmark over time.",
        parameters=[
            ToolParameter(
                name="bookmark_name",
                type=ParameterType.STRING,
                description="Name of the bookmark",
                required=False
            ),
            ToolParameter(
                name="bookmark_id",
                type=ParameterType.STRING,
                description="Bookmark ID if known",
                required=False
            ),
            ToolParameter(
                name="hours",
                type=ParameterType.INTEGER,
                description="Hours of history (default 24, max 168)",
                required=False,
                default=24
            )
        ],
        handler=get_bookmark_status_handler,
        category="bookmarks"
    ))
    
    register_tool(AITool(
        name="get_bookmark_incidents",
        description="Get outage/incident history for monitored services. Shows when services went down and for how long.",
        parameters=[
            ToolParameter(
                name="bookmark_name",
                type=ParameterType.STRING,
                description="Filter to specific bookmark name",
                required=False
            ),
            ToolParameter(
                name="bookmark_id",
                type=ParameterType.STRING,
                description="Filter to specific bookmark ID",
                required=False
            ),
            ToolParameter(
                name="days",
                type=ParameterType.INTEGER,
                description="Days of history (default 7, max 30)",
                required=False,
                default=7
            ),
            ToolParameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum incidents to return (default 20)",
                required=False,
                default=20
            )
        ],
        handler=get_bookmark_incidents_handler,
        category="bookmarks"
    ))
    
    register_tool(AITool(
        name="get_bookmark_uptime",
        description="Calculate uptime percentage for monitored services over a period.",
        parameters=[
            ToolParameter(
                name="bookmark_name",
                type=ParameterType.STRING,
                description="Calculate for specific bookmark",
                required=False
            ),
            ToolParameter(
                name="bookmark_id",
                type=ParameterType.STRING,
                description="Bookmark ID if known",
                required=False
            ),
            ToolParameter(
                name="days",
                type=ParameterType.INTEGER,
                description="Period in days (default 7, max 30)",
                required=False,
                default=7
            )
        ],
        handler=get_bookmark_uptime_handler,
        category="bookmarks"
    ))


# Auto-register on import
register_bookmark_tools()
