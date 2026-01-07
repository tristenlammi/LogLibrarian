"""
AI Response Quality Module

Enhances AI response quality through:
- Intelligent summarization of large result sets
- Highlighting important/anomalous information
- Generating recommendations based on data patterns
- Formatting data appropriately (tables, lists, markdown)
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import json
import logging

logger = logging.getLogger(__name__)


# ==================== DATA CLASSES ====================

@dataclass
class ResultSummary:
    """Summary of a large result set"""
    total_count: int
    shown_count: int
    key_findings: List[str]
    time_range: Optional[str] = None
    data_type: str = "items"
    
    def to_markdown(self) -> str:
        """Convert to markdown summary"""
        lines = [f"**Summary**: Showing {self.shown_count} of {self.total_count} {self.data_type}"]
        if self.time_range:
            lines.append(f"**Time Range**: {self.time_range}")
        if self.key_findings:
            lines.append("\n**Key Findings:**")
            for finding in self.key_findings:
                lines.append(f"- {finding}")
        return "\n".join(lines)


@dataclass
class Recommendation:
    """A recommendation based on data analysis"""
    title: str
    description: str
    priority: str  # 'critical', 'high', 'medium', 'low'
    action: Optional[str] = None
    related_entity: Optional[str] = None
    
    def to_markdown(self) -> str:
        priority_emoji = {
            'critical': '🔴',
            'high': '🟠',
            'medium': '🟡',
            'low': '🟢'
        }
        emoji = priority_emoji.get(self.priority, '🔵')
        lines = [f"{emoji} **{self.title}**", self.description]
        if self.action:
            lines.append(f"→ *Suggested action*: {self.action}")
        return "\n".join(lines)


@dataclass  
class Highlight:
    """A highlighted piece of important information"""
    category: str  # 'warning', 'error', 'success', 'info'
    message: str
    context: Optional[str] = None
    
    def to_markdown(self) -> str:
        icons = {
            'warning': '⚠️',
            'error': '❌',
            'success': '✅',
            'info': 'ℹ️'
        }
        icon = icons.get(self.category, '•')
        result = f"{icon} {self.message}"
        if self.context:
            result += f" ({self.context})"
        return result


# ==================== RESULT SUMMARIZER ====================

class ResultSummarizer:
    """
    Summarizes large result sets into concise, actionable insights.
    """
    
    def summarize_logs(self, logs: List[Dict], total_count: int) -> ResultSummary:
        """Summarize a log query result"""
        findings = []
        
        if not logs:
            return ResultSummary(
                total_count=total_count,
                shown_count=0,
                key_findings=["No logs found matching the criteria"],
                data_type="logs"
            )
        
        # Count by severity
        severity_counts = {}
        for log in logs:
            sev = log.get('severity', 'info').lower()
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        if 'error' in severity_counts or 'critical' in severity_counts:
            error_count = severity_counts.get('error', 0) + severity_counts.get('critical', 0)
            findings.append(f"{error_count} error/critical level entries found")
        
        # Count by source/hostname
        source_counts = {}
        for log in logs:
            source = log.get('hostname', log.get('source', 'unknown'))
            source_counts[source] = source_counts.get(source, 0) + 1
        
        if len(source_counts) > 1:
            top_source = max(source_counts.items(), key=lambda x: x[1])
            findings.append(f"Most logs from {top_source[0]} ({top_source[1]} entries)")
        
        # Time range
        timestamps = [log.get('timestamp') for log in logs if log.get('timestamp')]
        time_range = None
        if timestamps:
            try:
                times = [datetime.fromisoformat(t.replace('Z', '+00:00')) if isinstance(t, str) else t 
                        for t in timestamps]
                earliest = min(times)
                latest = max(times)
                time_range = f"{earliest.strftime('%H:%M')} - {latest.strftime('%H:%M')}"
            except:
                pass
        
        # Common patterns
        messages = [log.get('message', '') for log in logs[:20]]
        common_words = self._find_common_terms(messages)
        if common_words:
            findings.append(f"Common terms: {', '.join(common_words[:5])}")
        
        return ResultSummary(
            total_count=total_count,
            shown_count=len(logs),
            key_findings=findings,
            time_range=time_range,
            data_type="logs"
        )
    
    def summarize_metrics(self, metrics: List[Dict], total_count: int) -> ResultSummary:
        """Summarize metrics data"""
        findings = []
        
        if not metrics:
            return ResultSummary(
                total_count=total_count,
                shown_count=0,
                key_findings=["No metrics data available"],
                data_type="metrics"
            )
        
        # Calculate averages for common metrics
        cpu_values = [m.get('cpu_percent') for m in metrics if m.get('cpu_percent') is not None]
        mem_values = [m.get('memory_percent') for m in metrics if m.get('memory_percent') is not None]
        
        if cpu_values:
            avg_cpu = sum(cpu_values) / len(cpu_values)
            max_cpu = max(cpu_values)
            findings.append(f"CPU: avg {avg_cpu:.1f}%, peak {max_cpu:.1f}%")
            
            if max_cpu > 90:
                findings.append("⚠️ High CPU peaks detected (>90%)")
        
        if mem_values:
            avg_mem = sum(mem_values) / len(mem_values)
            max_mem = max(mem_values)
            findings.append(f"Memory: avg {avg_mem:.1f}%, peak {max_mem:.1f}%")
            
            if max_mem > 85:
                findings.append("⚠️ High memory usage detected (>85%)")
        
        return ResultSummary(
            total_count=total_count,
            shown_count=len(metrics),
            key_findings=findings,
            data_type="metric samples"
        )
    
    def summarize_alerts(self, alerts: List[Dict], total_count: int) -> ResultSummary:
        """Summarize alerts"""
        findings = []
        
        if not alerts:
            return ResultSummary(
                total_count=total_count,
                shown_count=0,
                key_findings=["No alerts found"],
                data_type="alerts"
            )
        
        # Count by status
        active = sum(1 for a in alerts if a.get('resolved_at') is None)
        resolved = len(alerts) - active
        
        if active > 0:
            findings.append(f"🔴 {active} active alert{'s' if active > 1 else ''}")
        if resolved > 0:
            findings.append(f"✅ {resolved} resolved alert{'s' if resolved > 1 else ''}")
        
        # Count by type
        type_counts = {}
        for alert in alerts:
            alert_type = alert.get('type', 'unknown')
            type_counts[alert_type] = type_counts.get(alert_type, 0) + 1
        
        if type_counts:
            top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            type_str = ", ".join(f"{t[0]} ({t[1]})" for t in top_types)
            findings.append(f"Types: {type_str}")
        
        return ResultSummary(
            total_count=total_count,
            shown_count=len(alerts),
            key_findings=findings,
            data_type="alerts"
        )
    
    def _find_common_terms(self, messages: List[str], min_freq: int = 3) -> List[str]:
        """Find commonly occurring terms in messages"""
        word_counts = {}
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'to', 'from', 'for', 'in', 'on', 'at'}
        
        for msg in messages:
            words = re.findall(r'\b[a-zA-Z]{3,}\b', msg.lower())
            for word in words:
                if word not in stop_words:
                    word_counts[word] = word_counts.get(word, 0) + 1
        
        common = [(w, c) for w, c in word_counts.items() if c >= min_freq]
        common.sort(key=lambda x: x[1], reverse=True)
        return [w[0] for w in common]


# ==================== RECOMMENDATION ENGINE ====================

class RecommendationEngine:
    """
    Generates recommendations based on data patterns.
    """
    
    def analyze_scribe_health(self, scribe: Dict) -> List[Recommendation]:
        """Generate recommendations for a scribe's health"""
        recommendations = []
        
        # Check if offline
        if not scribe.get('is_online'):
            recommendations.append(Recommendation(
                title="Agent Offline",
                description=f"{scribe.get('hostname', 'Unknown')} is currently offline.",
                priority="high",
                action="Check network connectivity and agent service status",
                related_entity=scribe.get('hostname')
            ))
            return recommendations
        
        # Check CPU
        cpu = scribe.get('cpu_percent', 0)
        if cpu > 90:
            recommendations.append(Recommendation(
                title="Critical CPU Usage",
                description=f"CPU at {cpu:.1f}% on {scribe.get('hostname')}",
                priority="critical",
                action="Identify resource-intensive processes and consider load balancing",
                related_entity=scribe.get('hostname')
            ))
        elif cpu > 75:
            recommendations.append(Recommendation(
                title="Elevated CPU Usage",
                description=f"CPU at {cpu:.1f}% on {scribe.get('hostname')}",
                priority="medium",
                action="Monitor for sustained high usage",
                related_entity=scribe.get('hostname')
            ))
        
        # Check Memory
        mem = scribe.get('memory_percent', 0)
        if mem > 90:
            recommendations.append(Recommendation(
                title="Critical Memory Usage",
                description=f"Memory at {mem:.1f}% on {scribe.get('hostname')}",
                priority="critical",
                action="Identify memory-hungry processes or consider adding RAM",
                related_entity=scribe.get('hostname')
            ))
        elif mem > 80:
            recommendations.append(Recommendation(
                title="High Memory Usage",
                description=f"Memory at {mem:.1f}% on {scribe.get('hostname')}",
                priority="high",
                action="Review running applications and services",
                related_entity=scribe.get('hostname')
            ))
        
        # Check Disk
        disk = scribe.get('disk_percent', 0)
        if disk > 90:
            recommendations.append(Recommendation(
                title="Critical Disk Space",
                description=f"Disk at {disk:.1f}% on {scribe.get('hostname')}",
                priority="critical",
                action="Free up disk space immediately or expand storage",
                related_entity=scribe.get('hostname')
            ))
        elif disk > 80:
            recommendations.append(Recommendation(
                title="Low Disk Space",
                description=f"Disk at {disk:.1f}% on {scribe.get('hostname')}",
                priority="high",
                action="Plan for disk cleanup or expansion",
                related_entity=scribe.get('hostname')
            ))
        
        return recommendations
    
    def analyze_error_patterns(self, logs: List[Dict]) -> List[Recommendation]:
        """Analyze error patterns and generate recommendations"""
        recommendations = []
        
        if not logs:
            return recommendations
        
        # Find repeating errors
        error_messages = {}
        for log in logs:
            if log.get('severity', '').lower() in ('error', 'critical'):
                msg = log.get('message', '')[:100]  # Truncate for grouping
                error_messages[msg] = error_messages.get(msg, 0) + 1
        
        # Recommend investigation for frequent errors
        for msg, count in error_messages.items():
            if count >= 5:
                recommendations.append(Recommendation(
                    title="Recurring Error Pattern",
                    description=f"Error seen {count} times: '{msg[:50]}...'",
                    priority="high" if count >= 10 else "medium",
                    action="Investigate root cause to prevent recurrence"
                ))
        
        return recommendations[:5]  # Limit to top 5
    
    def analyze_bookmark_health(self, bookmark: Dict, checks: List[Dict]) -> List[Recommendation]:
        """Analyze bookmark monitoring health"""
        recommendations = []
        
        if not checks:
            return recommendations
        
        # Calculate recent uptime
        total = len(checks)
        up_count = sum(1 for c in checks if c.get('is_up'))
        uptime = (up_count / total * 100) if total > 0 else 100
        
        name = bookmark.get('name', 'Unknown')
        
        if uptime < 99:
            recommendations.append(Recommendation(
                title="Service Instability",
                description=f"{name} has {uptime:.1f}% uptime recently ({total - up_count} downtimes)",
                priority="high" if uptime < 95 else "medium",
                action="Investigate cause of downtimes and consider redundancy",
                related_entity=name
            ))
        
        # Check response times if available
        response_times = [c.get('response_time_ms') for c in checks if c.get('response_time_ms')]
        if response_times:
            avg_response = sum(response_times) / len(response_times)
            max_response = max(response_times)
            
            if avg_response > 2000:
                recommendations.append(Recommendation(
                    title="Slow Response Times",
                    description=f"{name} averaging {avg_response:.0f}ms response time",
                    priority="medium",
                    action="Check server performance and network latency",
                    related_entity=name
                ))
        
        return recommendations


# ==================== DATA FORMATTER ====================

class DataFormatter:
    """
    Formats data appropriately for AI responses.
    """
    
    def format_as_table(self, data: List[Dict], columns: List[str] = None) -> str:
        """Format data as a markdown table"""
        if not data:
            return "*No data available*"
        
        # Auto-detect columns if not provided
        if not columns:
            columns = list(data[0].keys())[:6]  # Limit columns
        
        # Build header
        header = "| " + " | ".join(columns) + " |"
        separator = "| " + " | ".join(["---"] * len(columns)) + " |"
        
        # Build rows
        rows = []
        for item in data[:20]:  # Limit rows
            row_values = []
            for col in columns:
                val = item.get(col, "")
                # Truncate long values
                val_str = str(val)[:30]
                row_values.append(val_str)
            rows.append("| " + " | ".join(row_values) + " |")
        
        return "\n".join([header, separator] + rows)
    
    def format_as_list(self, items: List[Any], bullet: str = "-") -> str:
        """Format items as a bulleted list"""
        if not items:
            return "*No items*"
        
        return "\n".join(f"{bullet} {item}" for item in items[:20])
    
    def format_metric_inline(self, label: str, value: Any, unit: str = "") -> str:
        """Format a metric for inline display"""
        return f"**{label}**: {value}{unit}"
    
    def format_status_badge(self, status: str) -> str:
        """Format a status as an emoji badge"""
        badges = {
            'online': '🟢 Online',
            'offline': '🔴 Offline',
            'up': '✅ Up',
            'down': '❌ Down',
            'healthy': '💚 Healthy',
            'warning': '⚠️ Warning',
            'critical': '🔴 Critical',
            'ok': '✅ OK',
            'error': '❌ Error'
        }
        return badges.get(status.lower(), status)
    
    def format_scribe_summary(self, scribe: Dict) -> str:
        """Format a scribe summary"""
        hostname = scribe.get('hostname', 'Unknown')
        status = self.format_status_badge('online' if scribe.get('is_online') else 'offline')
        
        lines = [f"### {hostname}", status]
        
        if scribe.get('is_online'):
            lines.append(f"- CPU: {scribe.get('cpu_percent', 0):.1f}%")
            lines.append(f"- Memory: {scribe.get('memory_percent', 0):.1f}%")
            lines.append(f"- Disk: {scribe.get('disk_percent', 0):.1f}%")
            
            if scribe.get('os'):
                lines.append(f"- OS: {scribe.get('os')}")
        
        return "\n".join(lines)
    
    def format_time_ago(self, dt: datetime) -> str:
        """Format a datetime as 'X ago'"""
        if not dt:
            return "unknown"
        
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = now - dt
        
        if delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds >= 60:
            mins = delta.seconds // 60
            return f"{mins} minute{'s' if mins > 1 else ''} ago"
        else:
            return "just now"


# ==================== HIGHLIGHT EXTRACTOR ====================

class HighlightExtractor:
    """
    Extracts important/anomalous information to highlight.
    """
    
    def extract_from_metrics(self, metrics: List[Dict]) -> List[Highlight]:
        """Extract highlights from metrics data"""
        highlights = []
        
        if not metrics:
            return highlights
        
        # Find anomalies
        cpu_values = [m.get('cpu_percent', 0) for m in metrics]
        mem_values = [m.get('memory_percent', 0) for m in metrics]
        
        if cpu_values:
            max_cpu = max(cpu_values)
            if max_cpu > 95:
                highlights.append(Highlight(
                    category='error',
                    message=f"CPU peaked at {max_cpu:.1f}%",
                    context="may indicate resource exhaustion"
                ))
            elif max_cpu > 80:
                highlights.append(Highlight(
                    category='warning',
                    message=f"CPU reached {max_cpu:.1f}%",
                    context="monitor for sustained high usage"
                ))
        
        if mem_values:
            max_mem = max(mem_values)
            if max_mem > 90:
                highlights.append(Highlight(
                    category='error',
                    message=f"Memory peaked at {max_mem:.1f}%",
                    context="risk of OOM"
                ))
        
        return highlights
    
    def extract_from_logs(self, logs: List[Dict]) -> List[Highlight]:
        """Extract highlights from log data"""
        highlights = []
        
        error_count = sum(1 for l in logs if l.get('severity', '').lower() in ('error', 'critical'))
        
        if error_count > 0:
            highlights.append(Highlight(
                category='error' if error_count > 5 else 'warning',
                message=f"{error_count} error{'s' if error_count > 1 else ''} found",
                context=f"in {len(logs)} log entries"
            ))
        
        return highlights
    
    def extract_from_alerts(self, alerts: List[Dict]) -> List[Highlight]:
        """Extract highlights from alerts"""
        highlights = []
        
        active = [a for a in alerts if not a.get('resolved_at')]
        
        if active:
            highlights.append(Highlight(
                category='error' if len(active) > 3 else 'warning',
                message=f"{len(active)} active alert{'s' if len(active) > 1 else ''}",
                context="requiring attention"
            ))
        
        return highlights


# ==================== RESPONSE ENHANCER ====================

class ResponseEnhancer:
    """
    Main service for enhancing AI response quality.
    """
    
    def __init__(self):
        self.summarizer = ResultSummarizer()
        self.recommender = RecommendationEngine()
        self.formatter = DataFormatter()
        self.highlighter = HighlightExtractor()
    
    def enhance_tool_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Enhance a tool result with summaries, highlights, and recommendations.
        
        Args:
            tool_name: Name of the tool that produced the result
            result: The raw tool result
            context: Additional context (e.g., query parameters)
            
        Returns:
            Enhanced result with additional analysis
        """
        enhanced = result.copy()
        
        if not result.get('success') or not result.get('data'):
            return enhanced
        
        data = result['data']
        total_count = result.get('total_count', len(data) if isinstance(data, list) else 1)
        
        # Add type-specific enhancements
        if 'log' in tool_name.lower():
            if isinstance(data, list):
                summary = self.summarizer.summarize_logs(data, total_count)
                enhanced['summary'] = summary.to_markdown()
                
                highlights = self.highlighter.extract_from_logs(data)
                if highlights:
                    enhanced['highlights'] = [h.to_markdown() for h in highlights]
                
                recommendations = self.recommender.analyze_error_patterns(data)
                if recommendations:
                    enhanced['recommendations'] = [r.to_markdown() for r in recommendations]
        
        elif 'metric' in tool_name.lower():
            if isinstance(data, list):
                summary = self.summarizer.summarize_metrics(data, total_count)
                enhanced['summary'] = summary.to_markdown()
                
                highlights = self.highlighter.extract_from_metrics(data)
                if highlights:
                    enhanced['highlights'] = [h.to_markdown() for h in highlights]
        
        elif 'alert' in tool_name.lower():
            if isinstance(data, list):
                summary = self.summarizer.summarize_alerts(data, total_count)
                enhanced['summary'] = summary.to_markdown()
                
                highlights = self.highlighter.extract_from_alerts(data)
                if highlights:
                    enhanced['highlights'] = [h.to_markdown() for h in highlights]
        
        elif 'scribe' in tool_name.lower() and isinstance(data, dict):
            # Single scribe info
            recommendations = self.recommender.analyze_scribe_health(data)
            if recommendations:
                enhanced['recommendations'] = [r.to_markdown() for r in recommendations]
        
        return enhanced
    
    def format_for_display(
        self,
        data: Any,
        data_type: str,
        display_format: str = 'auto'
    ) -> str:
        """
        Format data for display in AI response.
        
        Args:
            data: The data to format
            data_type: Type of data
            display_format: 'table', 'list', 'inline', or 'auto'
            
        Returns:
            Formatted string
        """
        if display_format == 'auto':
            # Auto-detect best format
            if isinstance(data, list) and len(data) > 3:
                if isinstance(data[0], dict):
                    return self.formatter.format_as_table(data)
                return self.formatter.format_as_list(data)
            elif isinstance(data, dict):
                if data_type == 'scribe':
                    return self.formatter.format_scribe_summary(data)
                return json.dumps(data, indent=2, default=str)
            return str(data)
        
        elif display_format == 'table':
            return self.formatter.format_as_table(data)
        elif display_format == 'list':
            return self.formatter.format_as_list(data)
        else:
            return str(data)


# ==================== MODULE SINGLETON ====================

_enhancer: ResponseEnhancer = None


def get_response_enhancer() -> ResponseEnhancer:
    """Get the global response enhancer instance"""
    global _enhancer
    if _enhancer is None:
        _enhancer = ResponseEnhancer()
    return _enhancer
