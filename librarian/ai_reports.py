"""
AI Report Generators - Business Logic

Scheduled jobs that analyze metrics and generate AI-powered reports:
- Daily Briefing: Morning summary of all servers (8 AM)
- Consultant Tips: Weekly optimization suggestions
- Alert Analysis: On-demand incident analysis
- Post-Mortem: Deep dive after major events
"""

import asyncio
import random
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Use same path as main db.py
SQLITE_DB_PATH = "./loglibrarian.db"

# ==================== SYSTEM PROMPTS ====================

# Report style templates
REPORT_STYLES = {
    "concise": """You are a technical writer creating a concise daily infrastructure report.

STRICT RULES:
1. ONLY report the exact statistics provided - do NOT invent or estimate any values
2. If a value shows "N/A", say "data not available" - do NOT guess
3. Do NOT hallucinate hardware specs or any details not in the data
4. Use bullet points for quick scanning
5. Keep it under 150 words total
6. Use emoji: ✅ healthy, ⚠️ warning, 🔴 critical

FORMAT:
## 🌅 Daily Report - {date}
**Fleet:** X/Y online
**Issues:** (bullet list or "None")
**Action Items:** (bullet list or "None")""",

    "executive": """You are a technical writer creating an executive summary for leadership.

STRICT RULES:
1. ONLY report the exact statistics provided - do NOT invent any values
2. If a value shows "N/A", say "data not available"
3. Focus on business impact, not technical details
4. Keep it under 200 words
5. Professional tone, no jargon

FORMAT:
## Infrastructure Status Summary
**Overall Health:** (Good/Fair/Poor based on provided concerns)
**Key Findings:** (2-3 sentences summarizing fleet status)
**Attention Required:** (any concerns that need action, or "None")""",

    "technical": """You are a technical writer creating a detailed infrastructure report for engineers.

STRICT RULES:
1. ONLY report the exact statistics provided - do NOT invent any values
2. If a value shows "N/A", say "data not available" - do NOT guess
3. Include all metrics for each server
4. Use technical terminology
5. Keep it under 400 words
6. Use emoji: ✅ healthy, ⚠️ warning, 🔴 critical

FORMAT:
## 🌅 Daily Infrastructure Report - {date}
### Fleet Overview
- Total: X servers | Online: Y | Offline: Z
- Errors (24h): N | Warnings (24h): M

### Pre-Identified Concerns
(list all concerns with exact values)

### Per-Server Metrics
(for each server: CPU, RAM, Disk, Temp stats)

### Recommended Actions
(based on concerns, or "No immediate action required")"""
}

# Legacy prompt for backward compatibility
SYSTEM_PROMPTS = {
    "daily_briefing": REPORT_STYLES["concise"],

    "consultant_tip": """You are an experienced DevOps consultant reviewing server metrics.
Provide a single, actionable optimization tip based on the metric anomaly provided.
Be specific and practical. Include the expected benefit.
Keep your response to 2-3 sentences maximum.""",

    "alert_analysis": """You are a senior SRE analyzing a production incident.
Based on the error logs and metrics provided, explain:
1. What likely happened
2. The probable root cause
3. Recommended immediate actions
Be concise but thorough. Use technical language appropriate for engineers.""",

    "post_mortem": """You are writing a post-mortem report for an incident.
Structure your response with:
- **Summary**: One-line incident description
- **Impact**: What was affected and for how long
- **Timeline**: Key events in chronological order
- **Root Cause**: Technical explanation
- **Action Items**: Preventive measures
Keep it professional and blameless."""
}


# ==================== DAILY BRIEFING ====================

class DailyBriefingGenerator:
    """
    Generates a morning briefing summarizing the last 24 hours.
    Runs daily at 8:00 AM.
    """
    
    def __init__(self, db_manager, ai_service):
        self.db = db_manager
        self.ai = ai_service
    
    async def generate(self, skip_ready_check: bool = False) -> Optional[int]:
        """
        Generate the daily briefing report.
        
        Args:
            skip_ready_check: If True, skip the is_ready() check (useful when called from API that already validated)
        
        Returns:
            Report ID if successful, None otherwise
        """
        if not self.ai.is_feature_enabled("daily_briefing"):
            logger.info("Daily briefing feature is disabled")
            return None
        
        if not skip_ready_check and not self.ai.is_ready():
            logger.warning("AI service not ready, skipping daily briefing")
            return None
        
        try:
            # Get report style from settings
            settings = self.db.get_ai_settings()
            report_style = settings.get("report_style", "concise")
            system_prompt = REPORT_STYLES.get(report_style, REPORT_STYLES["concise"])
            
            # Adjust max tokens based on style
            max_tokens = {"concise": 300, "executive": 400, "technical": 700}.get(report_style, 500)
            
            # Gather metrics summary
            summary = await self._gather_24h_summary()
            
            if not summary["agents"]:
                logger.info("No agents to report on, skipping briefing")
                return None
            
            # Build prompt
            prompt = self._build_prompt(summary)
            
            # Generate with AI using selected style
            result = await self.ai.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            if not result.success:
                logger.error(f"AI generation failed: {result.error}")
                return None
            
            # Save report
            report_id = self.db.create_ai_report(
                report_type="briefing",
                title=f"☀️ Morning Briefing - {datetime.now().strftime('%B %d, %Y')}",
                content=result.content,
                metadata={
                    "generated_at": datetime.now().isoformat(),
                    "model": result.model,
                    "tokens_used": result.tokens_used,
                    "agent_count": len(summary["agents"]),
                    "time_range_hours": 24,
                    "report_style": report_style
                }
            )
            
            logger.info(f"Daily briefing generated, report ID: {report_id}")
            return report_id
            
        except Exception as e:
            logger.error(f"Failed to generate daily briefing: {e}")
            return None
    
    async def _gather_24h_summary(self) -> Dict[str, Any]:
        """
        Gather pre-calculated statistics from the last 24 hours.
        
        HARDENED: All statistics are calculated in Python, not by AI.
        The AI only summarizes the provided facts.
        """
        
        # Get all agents
        agents = self.db.get_all_agents()
        cutoff_24h = datetime.now() - timedelta(hours=24)
        
        summary = {
            "timestamp": datetime.now().isoformat(),
            "report_date": datetime.now().strftime('%B %d, %Y'),
            "period": "24 hours",
            "agents": [],
            "totals": {
                "total_agents": len(agents),
                "online_agents": 0,
                "offline_agents": 0,
                "total_errors_24h": 0,
                "total_warnings_24h": 0
            },
            "concerns": [],  # Pre-calculated warnings
            "healthy_count": 0
        }
        
        for agent in agents:
            agent_id = agent.get("id") or agent.get("agent_id")
            hostname = agent.get("hostname", "Unknown")
            status = agent.get("status", "offline")
            
            # Get metrics history for 24h analysis
            metrics_list = self.db.get_agent_metrics(agent_id, limit=288)  # ~24h at 5min intervals
            latest_metrics = metrics_list[0] if metrics_list else {}
            
            # HARDENED: Calculate statistics in Python
            cpu_values = [m.get("cpu_percent", 0) for m in metrics_list if m.get("cpu_percent") is not None]
            ram_values = [m.get("ram_percent", 0) for m in metrics_list if m.get("ram_percent") is not None]
            temp_values = [m.get("cpu_temp", 0) for m in metrics_list if m.get("cpu_temp") and m.get("cpu_temp") > 0]
            
            # Calculate max, avg, current values
            max_cpu_24h = round(max(cpu_values), 1) if cpu_values else "N/A"
            avg_cpu_24h = round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else "N/A"
            current_cpu = round(latest_metrics.get("cpu_percent", 0), 1) if latest_metrics else "N/A"
            
            max_ram_24h = round(max(ram_values), 1) if ram_values else "N/A"
            current_ram = round(latest_metrics.get("ram_percent", 0), 1) if latest_metrics else "N/A"
            
            max_temp_24h = round(max(temp_values), 1) if temp_values else "N/A"
            current_temp = round(latest_metrics.get("cpu_temp", 0), 1) if latest_metrics.get("cpu_temp") else "N/A"
            
            # Calculate disk usage from disks array
            disk_percent = "N/A"
            if latest_metrics.get("disks"):
                disk_percent = round(max((d.get("percent", 0) for d in latest_metrics["disks"]), default=0), 1)
            
            # Calculate uptime percentage (data points received / expected points)
            expected_points = 288  # 24h at 5min intervals
            actual_points = len(metrics_list)
            uptime_percent = round((actual_points / expected_points) * 100, 1) if expected_points > 0 else "N/A"
            
            # Count errors and warnings
            error_count = self._count_recent_errors(agent_id)
            warning_count = self._count_recent_warnings(agent_id)
            
            # Track online/offline
            if status == "online":
                summary["totals"]["online_agents"] += 1
            else:
                summary["totals"]["offline_agents"] += 1
            
            summary["totals"]["total_errors_24h"] += error_count
            summary["totals"]["total_warnings_24h"] += warning_count
            
            # Build agent summary with ONLY calculated facts
            agent_summary = {
                "hostname": hostname,
                "os": agent.get("os", "unknown"),
                "status": status,
                "current_cpu": current_cpu,
                "max_cpu_24h": max_cpu_24h,
                "avg_cpu_24h": avg_cpu_24h,
                "current_ram": current_ram,
                "max_ram_24h": max_ram_24h,
                "disk_percent": disk_percent,
                "current_temp": current_temp,
                "max_temp_24h": max_temp_24h,
                "uptime_percent": uptime_percent,
                "error_count_24h": error_count,
                "warning_count_24h": warning_count
            }
            
            # HARDENED: Pre-calculate concerns based on thresholds
            agent_concerns = []
            if status == "offline":
                agent_concerns.append("OFFLINE")
            if isinstance(max_cpu_24h, (int, float)) and max_cpu_24h > 90:
                agent_concerns.append(f"CPU peaked at {max_cpu_24h}%")
            if isinstance(max_ram_24h, (int, float)) and max_ram_24h > 90:
                agent_concerns.append(f"RAM peaked at {max_ram_24h}%")
            if isinstance(disk_percent, (int, float)) and disk_percent > 85:
                agent_concerns.append(f"Disk at {disk_percent}%")
            if isinstance(max_temp_24h, (int, float)) and max_temp_24h > 80:
                agent_concerns.append(f"Temp peaked at {max_temp_24h}°C")
            if error_count > 10:
                agent_concerns.append(f"{error_count} errors logged")
            
            if agent_concerns:
                summary["concerns"].append({
                    "hostname": hostname,
                    "issues": agent_concerns
                })
            else:
                summary["healthy_count"] += 1
            
            summary["agents"].append(agent_summary)
        
        return summary
    
    def _count_recent_warnings(self, agent_id: str) -> int:
        """Count warning logs in the last 24 hours"""
        try:
            logs = self.db.get_logs(
                agent_id=agent_id,
                level="warning",
                limit=1000
            )
            cutoff = datetime.now() - timedelta(hours=24)
            recent_warnings = [
                log for log in logs 
                if self._parse_timestamp(log.get("timestamp")) > cutoff
            ]
            return len(recent_warnings)
        except Exception:
            return 0
    
    def _count_recent_errors(self, agent_id: str) -> int:
        """Count error logs in the last 24 hours"""
        try:
            # Query logs with level=error from last 24h
            logs = self.db.get_logs(
                agent_id=agent_id,
                level="error",
                limit=1000  # Cap for performance
            )
            
            # Filter to last 24h
            cutoff = datetime.now() - timedelta(hours=24)
            recent_errors = [
                log for log in logs 
                if self._parse_timestamp(log.get("timestamp")) > cutoff
            ]
            
            return len(recent_errors)
        except Exception:
            return 0
    
    def _parse_timestamp(self, ts: str) -> datetime:
        """Parse timestamp string to datetime"""
        try:
            if ts:
                return datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
        except:
            pass
        return datetime.min
    
    def _build_prompt(self, summary: Dict) -> str:
        """
        Build the prompt from pre-calculated summary data.
        
        HARDENED: The prompt contains ONLY facts calculated in Python.
        The AI summarizes these facts without generating additional data.
        """
        
        # Build a structured, factual prompt
        prompt_lines = [
            f"# Infrastructure Report Data for {summary.get('report_date', 'Today')}",
            f"**Report Period:** Last {summary['period']}",
            "",
            "## Fleet Summary (PRE-CALCULATED - use these exact values)",
            f"- Total servers: {summary['totals']['total_agents']}",
            f"- Online: {summary['totals']['online_agents']}",
            f"- Offline: {summary['totals']['offline_agents']}",
            f"- Healthy (no concerns): {summary.get('healthy_count', 0)}",
            f"- Total errors (24h): {summary['totals']['total_errors_24h']}",
            f"- Total warnings (24h): {summary['totals']['total_warnings_24h']}",
            ""
        ]
        
        # Add pre-calculated concerns
        if summary.get("concerns"):
            prompt_lines.append("## Pre-Identified Concerns (REPORT THESE EXACTLY)")
            for concern in summary["concerns"]:
                issues_str = ", ".join(concern["issues"])
                prompt_lines.append(f"- **{concern['hostname']}**: {issues_str}")
            prompt_lines.append("")
        else:
            prompt_lines.append("## Concerns: NONE - All systems healthy")
            prompt_lines.append("")
        
        # Add per-server stats
        prompt_lines.append("## Server Details (EXACT VALUES - do not estimate)")
        for agent in summary["agents"]:
            prompt_lines.append(f"### {agent['hostname']} ({agent['os']}) - {agent['status'].upper()}")
            prompt_lines.append(f"- CPU: Current {agent['current_cpu']}%, Max 24h: {agent['max_cpu_24h']}%, Avg: {agent['avg_cpu_24h']}%")
            prompt_lines.append(f"- RAM: Current {agent['current_ram']}%, Max 24h: {agent['max_ram_24h']}%")
            prompt_lines.append(f"- Disk: {agent['disk_percent']}%")
            prompt_lines.append(f"- Temp: Current {agent['current_temp']}°C, Max 24h: {agent['max_temp_24h']}°C")
            prompt_lines.append(f"- Data Availability: {agent['uptime_percent']}%")
            prompt_lines.append(f"- Errors: {agent['error_count_24h']}, Warnings: {agent['warning_count_24h']}")
            prompt_lines.append("")
        
        prompt_lines.append("---")
        prompt_lines.append("INSTRUCTIONS: Summarize ONLY the data provided above. Do NOT invent hardware specs, model numbers, or any values not shown. If a value shows 'N/A', report it as 'data not available'.")
        
        return "\n".join(prompt_lines)


# ==================== CONSULTANT (WEEKLY TIPS) ====================

class ConsultantGenerator:
    """
    Generates optimization tips by analyzing server metrics.
    Runs weekly, picks random servers to analyze.
    """
    
    # Thresholds for detecting inefficiencies
    INEFFICIENCY_RULES = [
        {
            "name": "high_cpu_idle",
            "condition": lambda m: m.get("cpu_percent", 0) < 5,
            "message": "CPU usage is consistently below 5%",
            "suggestion": "This server may be oversized. Consider downsizing or consolidating workloads."
        },
        {
            "name": "high_ram_usage",
            "condition": lambda m: m.get("ram_percent", 0) > 90,
            "message": "RAM usage is above 90%",
            "suggestion": "Memory pressure detected. Consider adding RAM or identifying memory leaks."
        },
        {
            "name": "low_ram_usage",
            "condition": lambda m: m.get("ram_percent", 0) < 10,
            "message": "RAM usage is below 10%",
            "suggestion": "Significant unused memory. This server may be oversized."
        },
        {
            "name": "high_disk_usage",
            "condition": lambda m: max((d.get("percent", 0) for d in m.get("disks", [])), default=0) > 85,
            "message": "Disk usage is above 85%",
            "suggestion": "Running low on disk space. Plan for cleanup or expansion."
        },
        {
            "name": "high_gpu_temp",
            "condition": lambda m: m.get("gpu_temp", 0) > 80,
            "message": "GPU temperature exceeds 80°C",
            "suggestion": "GPU running hot. Check cooling and airflow."
        },
        {
            "name": "high_cpu_temp",
            "condition": lambda m: m.get("cpu_temp", 0) > 85,
            "message": "CPU temperature exceeds 85°C",
            "suggestion": "CPU thermal throttling may occur. Check cooler and thermal paste."
        }
    ]
    
    def __init__(self, db_manager, ai_service):
        self.db = db_manager
        self.ai = ai_service
    
    async def generate(self, agent_id: str = None, skip_ready_check: bool = False) -> Optional[int]:
        """
        Generate an optimization tip for a server.
        
        Args:
            agent_id: Specific agent to analyze, or None for random selection
            skip_ready_check: Skip the AI readiness check (use when already validated by API)
            
        Returns:
            Report ID if tip generated, None otherwise
        """
        if not self.ai.is_feature_enabled("tips"):
            logger.info("Tips feature is disabled")
            return None
        
        if not skip_ready_check and not self.ai.is_ready():
            logger.warning("AI service not ready, skipping consultant tip")
            return None
        
        try:
            # Select agent
            if agent_id:
                agents = [a for a in self.db.get_all_agents() if (a.get("id") or a.get("agent_id")) == agent_id]
            else:
                agents = self.db.get_all_agents()
            
            if not agents:
                logger.info("No agents available for analysis")
                return None
            
            # Pick random agent
            agent = random.choice(agents)
            agent_id = agent.get("id") or agent.get("agent_id")
            hostname = agent.get("hostname", "Unknown")
            
            # Get metrics (get_agent_metrics returns a list, take the first)
            metrics_list = self.db.get_agent_metrics(agent_id, limit=1)
            metrics = metrics_list[0] if metrics_list else None
            if not metrics:
                logger.info(f"No metrics for {hostname}, skipping")
                return None
            
            # Calculate disk usage from disks array
            disk_percent = 0
            if metrics.get("disks"):
                disk_percent = max((d.get("percent", 0) for d in metrics["disks"]), default=0)
            
            # Find inefficiencies
            inefficiency = self._find_inefficiency(metrics)
            if not inefficiency:
                logger.info(f"No inefficiencies found for {hostname}")
                return None
            
            # Generate AI tip
            prompt = f"""The server "{hostname}" has the following issue:
{inefficiency['message']}

Current metrics:
- CPU: {metrics.get('cpu_percent', 0):.1f}%
- RAM: {metrics.get('ram_percent', 0):.1f}%
- Disk: {disk_percent:.1f}%
- CPU Temp: {metrics.get('cpu_temp', 0):.0f}°C
- GPU Temp: {metrics.get('gpu_temp', 0):.0f}°C

Give me a 1-sentence actionable tip to address this."""
            
            result = await self.ai.generate(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPTS["consultant_tip"],
                max_tokens=150,
                temperature=0.7
            )
            
            if not result.success:
                logger.error(f"AI generation failed: {result.error}")
                return None
            
            # Save report
            report_id = self.db.create_ai_report(
                report_type="tip",
                title=f"💡 Optimization Tip: {hostname}",
                content=result.content,
                agent_id=agent_id,
                metadata={
                    "generated_at": datetime.now().isoformat(),
                    "model": result.model,
                    "tokens_used": result.tokens_used,
                    "hostname": hostname,
                    "inefficiency": inefficiency["name"],
                    "metric_value": inefficiency["message"]
                }
            )
            
            logger.info(f"Consultant tip generated for {hostname}, report ID: {report_id}")
            return report_id
            
        except Exception as e:
            logger.error(f"Failed to generate consultant tip: {e}")
            return None
    
    def _find_inefficiency(self, metrics: Dict) -> Optional[Dict]:
        """Check metrics against inefficiency rules"""
        for rule in self.INEFFICIENCY_RULES:
            try:
                if rule["condition"](metrics):
                    return rule
            except:
                continue
        return None


# ==================== ALERT ANALYSIS ====================

class AlertAnalyzer:
    """
    Analyzes error logs and alerts to provide incident insights.
    Triggered on-demand or when error threshold is exceeded.
    """
    
    def __init__(self, db_manager, ai_service):
        self.db = db_manager
        self.ai = ai_service
    
    async def analyze_errors(self, agent_id: str, hours: int = 1) -> Optional[int]:
        """
        Analyze recent errors for an agent.
        
        Args:
            agent_id: Agent to analyze
            hours: How many hours back to look
            
        Returns:
            Report ID if analysis generated, None otherwise
        """
        if not self.ai.is_feature_enabled("alert_analysis"):
            logger.info("Alert analysis feature is disabled")
            return None
        
        if not self.ai.is_ready():
            logger.warning("AI service not ready, skipping alert analysis")
            return None
        
        try:
            # Get agent info
            agents = self.db.get_all_agents()
            agent = next((a for a in agents if (a.get("id") or a.get("agent_id")) == agent_id), None)
            if not agent:
                logger.error(f"Agent {agent_id} not found")
                return None
            
            hostname = agent.get("hostname", "Unknown")
            
            # Get recent error logs
            logs = self.db.get_logs(agent_id=agent_id, level="error", limit=50)
            
            if not logs:
                logger.info(f"No error logs found for {hostname}")
                return None
            
            # Get current metrics for context (get_agent_metrics returns a list)
            metrics_list = self.db.get_agent_metrics(agent_id, limit=1)
            metrics = metrics_list[0] if metrics_list else {}
            
            # Calculate disk usage from disks array
            disk_percent = 0
            if metrics.get("disks"):
                disk_percent = max((d.get("percent", 0) for d in metrics["disks"]), default=0)
            
            # Build context
            log_summary = self._summarize_logs(logs[:20])  # Limit for tokens
            
            prompt = f"""Server: {hostname}
OS: {agent.get('os', 'unknown')}

Recent Error Logs (last {hours}h):
{log_summary}

Current Metrics:
- CPU: {metrics.get('cpu_percent', 0):.1f}%
- RAM: {metrics.get('ram_percent', 0):.1f}%
- Disk: {disk_percent:.1f}%

Analyze these errors and provide insights."""
            
            result = await self.ai.generate(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPTS["alert_analysis"],
                max_tokens=600,
                temperature=0.5
            )
            
            if not result.success:
                logger.error(f"AI generation failed: {result.error}")
                return None
            
            # Save report
            report_id = self.db.create_ai_report(
                report_type="alert",
                title=f"🚨 Error Analysis: {hostname}",
                content=result.content,
                agent_id=agent_id,
                metadata={
                    "generated_at": datetime.now().isoformat(),
                    "model": result.model,
                    "tokens_used": result.tokens_used,
                    "hostname": hostname,
                    "error_count": len(logs),
                    "time_range_hours": hours
                }
            )
            
            logger.info(f"Alert analysis generated for {hostname}, report ID: {report_id}")
            return report_id
            
        except Exception as e:
            logger.error(f"Failed to generate alert analysis: {e}")
            return None
    
    def _summarize_logs(self, logs: List[Dict]) -> str:
        """Summarize logs for the prompt (token efficient)"""
        lines = []
        for log in logs[:15]:  # Cap at 15 for tokens
            ts = log.get("timestamp", "")[:19]  # Trim timestamp
            msg = log.get("message", "")[:200]  # Trim long messages
            source = log.get("source", "")
            lines.append(f"[{ts}] {source}: {msg}")
        return "\n".join(lines)


# ==================== POST-MORTEM ====================

class PostMortemGenerator:
    """
    Generates detailed post-mortem reports after incidents.
    Triggered manually after an incident is resolved.
    """
    
    def __init__(self, db_manager, ai_service):
        self.db = db_manager
        self.ai = ai_service
    
    async def generate(
        self, 
        agent_id: str,
        incident_start: datetime,
        incident_end: datetime,
        incident_summary: str = ""
    ) -> Optional[int]:
        """
        Generate a post-mortem report.
        
        Args:
            agent_id: Affected agent
            incident_start: When the incident started
            incident_end: When it was resolved
            incident_summary: Optional human-provided summary
            
        Returns:
            Report ID if generated, None otherwise
        """
        if not self.ai.is_feature_enabled("post_mortem"):
            logger.info("Post-mortem feature is disabled")
            return None
        
        if not self.ai.is_ready():
            logger.warning("AI service not ready, skipping post-mortem")
            return None
        
        try:
            # Get agent info
            agents = self.db.get_all_agents()
            agent = next((a for a in agents if (a.get("id") or a.get("agent_id")) == agent_id), None)
            if not agent:
                logger.error(f"Agent {agent_id} not found")
                return None
            
            hostname = agent.get("hostname", "Unknown")
            duration = incident_end - incident_start
            
            # Get logs during incident window
            logs = self.db.get_logs(agent_id=agent_id, limit=100)
            incident_logs = [
                log for log in logs
                if incident_start <= self._parse_timestamp(log.get("timestamp", "")) <= incident_end
            ]
            
            # Build timeline
            log_timeline = self._build_timeline(incident_logs)
            
            prompt = f"""Incident Details:
- Server: {hostname}
- Duration: {duration}
- Start: {incident_start.isoformat()}
- End: {incident_end.isoformat()}
{f'- Summary: {incident_summary}' if incident_summary else ''}

Log Timeline During Incident:
{log_timeline}

Generate a post-mortem report for this incident."""
            
            result = await self.ai.generate(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPTS["post_mortem"],
                max_tokens=800,
                temperature=0.5
            )
            
            if not result.success:
                logger.error(f"AI generation failed: {result.error}")
                return None
            
            # Save report
            report_id = self.db.create_ai_report(
                report_type="postmortem",
                title=f"📋 Post-Mortem: {hostname} - {incident_start.strftime('%Y-%m-%d')}",
                content=result.content,
                agent_id=agent_id,
                metadata={
                    "generated_at": datetime.now().isoformat(),
                    "model": result.model,
                    "tokens_used": result.tokens_used,
                    "hostname": hostname,
                    "incident_start": incident_start.isoformat(),
                    "incident_end": incident_end.isoformat(),
                    "duration_minutes": duration.total_seconds() / 60,
                    "log_count": len(incident_logs)
                }
            )
            
            logger.info(f"Post-mortem generated for {hostname}, report ID: {report_id}")
            return report_id
            
        except Exception as e:
            logger.error(f"Failed to generate post-mortem: {e}")
            return None
    
    def _parse_timestamp(self, ts: str) -> datetime:
        """Parse timestamp string"""
        try:
            if ts:
                return datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
        except:
            pass
        return datetime.min
    
    def _build_timeline(self, logs: List[Dict]) -> str:
        """Build a timeline from logs"""
        # Sort by timestamp
        sorted_logs = sorted(logs, key=lambda x: x.get("timestamp", ""))
        
        lines = []
        for log in sorted_logs[:25]:  # Cap for tokens
            ts = log.get("timestamp", "")[:19]
            level = log.get("level", "info").upper()
            msg = log.get("message", "")[:150]
            lines.append(f"[{ts}] [{level}] {msg}")
        
        return "\n".join(lines) if lines else "No logs available for this time period."


# ==================== SCHEDULER ====================

class AIReportScheduler:
    """
    Manages scheduled AI report generation.
    Includes Daily Briefings and Profile-based Executive Summary scheduling.
    """
    
    def __init__(self, db_manager, ai_service):
        self.db = db_manager
        self.ai = ai_service
        self.briefing_generator = DailyBriefingGenerator(db_manager, ai_service)
        self.alert_analyzer = AlertAnalyzer(db_manager, ai_service)
        self.postmortem_generator = PostMortemGenerator(db_manager, ai_service)
        self._running = False
        self._task = None
        self._profile_task = None
        self._last_profile_run_date = None
    
    async def start(self):
        """Start the scheduler"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        self._profile_task = asyncio.create_task(self._profile_scheduler_loop())
        logger.info("AI Report Scheduler started (with profile scheduling)")
    
    async def stop(self):
        """Stop the scheduler"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._profile_task:
            self._profile_task.cancel()
            try:
                await self._profile_task
            except asyncio.CancelledError:
                pass
        logger.info("AI Report Scheduler stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler loop - runs Daily Briefing at configured time"""
        last_briefing_date = None
        
        while self._running:
            try:
                now = datetime.now()
                
                # Get configured briefing time from settings
                settings = self.db.get_ai_settings()
                briefing_time_str = settings.get("briefing_time", "08:00")
                
                try:
                    briefing_hour, briefing_minute = map(int, briefing_time_str.split(":"))
                except:
                    briefing_hour, briefing_minute = 8, 0
                
                # Daily Briefing at configured time
                if now.hour == briefing_hour and now.minute >= briefing_minute and now.date() != last_briefing_date:
                    logger.info(f"Running daily briefing job at {briefing_time_str}...")
                    await self.briefing_generator.generate()
                    last_briefing_date = now.date()
                
                # Sleep for 1 minute before checking again
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)
    
    async def _profile_scheduler_loop(self):
        """
        Profile-based Executive Summary scheduler.
        Runs every 5 minutes to check which profiles need reports generated.
        Each profile has its own schedule_hour (default 7am).
        - DAILY: Generate every day at schedule_hour
        - WEEKLY: Generate if today is Monday at schedule_hour  
        - MONTHLY: Generate if today is the 1st of the month at schedule_hour
        - MANUAL: Never auto-generate
        """
        while self._running:
            try:
                now = datetime.now()
                current_hour = now.hour
                current_date = now.date()
                
                # Check each profile to see if it needs a report generated
                await self._check_and_generate_profile_reports(current_hour, current_date)
                
                # Sleep for 5 minutes before checking again
                await asyncio.sleep(300)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Profile scheduler error: {e}")
                await asyncio.sleep(300)
    
    async def _check_and_generate_profile_reports(self, current_hour: int, current_date):
        """Check each profile and generate reports if it's their scheduled time"""
        try:
            from datetime import date
            
            today = current_date if isinstance(current_date, date) else date.today()
            is_monday = today.weekday() == 0  # Monday is 0
            is_first_of_month = today.day == 1
            is_first_of_quarter = today.day == 1 and today.month in [1, 4, 7, 10]  # Jan, Apr, Jul, Oct
            is_first_of_year = today.day == 1 and today.month == 1  # January 1st
            
            # Get all profiles for scheduling
            profiles = self.db.get_all_report_profiles_for_scheduling()
            
            for profile in profiles:
                frequency = profile.get("frequency", "MONTHLY").upper()
                schedule_hour = profile.get("schedule_hour", 7)  # Default 7am
                profile_id = profile.get("id")
                profile_name = profile.get("name", "Unknown")
                
                # Skip if not the right hour for this profile
                if current_hour != schedule_hour:
                    continue
                
                # Create a unique key for tracking when we last ran this profile
                run_key = f"{profile_id}_{today.isoformat()}"
                if not hasattr(self, '_profile_runs'):
                    self._profile_runs = set()
                
                # Skip if we already generated for this profile today
                if run_key in self._profile_runs:
                    continue
                
                should_generate = False
                
                if frequency == "DAILY":
                    should_generate = True
                elif frequency == "WEEKLY" and is_monday:
                    should_generate = True
                elif frequency == "MONTHLY" and is_first_of_month:
                    should_generate = True
                elif frequency == "QUARTERLY" and is_first_of_quarter:
                    should_generate = True
                elif frequency == "ANNUALLY" and is_first_of_year:
                    should_generate = True
                # MANUAL frequency never auto-generates
                
                if should_generate:
                    logger.info(f"Generating scheduled report for profile: {profile_name} ({frequency}) at hour {schedule_hour}")
                    try:
                        await self._generate_profile_report(profile)
                        self._profile_runs.add(run_key)
                    except Exception as e:
                        logger.error(f"Failed to generate report for profile {profile_name}: {e}")
            
        except Exception as e:
                logger.error(f"Profile scheduler check failed: {e}")
    
    async def _generate_profile_report(self, profile: dict):
        """Generate an Executive Summary report for a profile and save to storage"""
        import sqlite3
        from datetime import timedelta
        
        profile_id = profile.get("id")
        profile_name = profile.get("name", "Unknown")
        tenant_id = profile.get("tenant_id", "default")
        
        # Default to 30 days for scheduled reports
        days = 30
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get bookmarks scoped to this profile
        bookmarks = self.db.get_bookmarks(tenant_id)
        active_bookmarks = [b for b in bookmarks if b.get("active", True)]
        
        scope_ids = profile.get("monitor_scope_ids") or []
        scope_tags = profile.get("monitor_scope_tags") or []
        
        if scope_ids or scope_tags:
            filtered_bookmarks = []
            for b in active_bookmarks:
                if b.get("id") in scope_ids:
                    filtered_bookmarks.append(b)
                    continue
                bookmark_tags = b.get("tags") or []
                if isinstance(bookmark_tags, str):
                    bookmark_tags = [t.strip() for t in bookmark_tags.split(",") if t.strip()]
                if any(t in scope_tags for t in bookmark_tags):
                    filtered_bookmarks.append(b)
            active_bookmarks = filtered_bookmarks if filtered_bookmarks else active_bookmarks
        
        if not active_bookmarks:
            logger.warning(f"No active monitors for profile {profile_name}, skipping report")
            return
        
        # Calculate metrics
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        total_checks = 0
        total_up_checks = 0
        incident_count = 0
        
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='bookmark_checks'
        """)
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            for bookmark in active_bookmarks:
                bookmark_id = bookmark["id"]
                cursor.execute("""
                    SELECT status FROM bookmark_checks 
                    WHERE bookmark_id = ? AND created_at >= ?
                """, (bookmark_id, start_date.isoformat()))
                
                checks = cursor.fetchall()
                if checks:
                    total_checks += len(checks)
                    total_up_checks += sum(1 for c in checks if c["status"] == 1)
                    
                    prev_status = 1
                    for check in checks:
                        if check["status"] == 0 and prev_status == 1:
                            incident_count += 1
                        prev_status = check["status"]
        
        conn.close()
        
        global_uptime = (total_up_checks / total_checks * 100) if total_checks > 0 else 100.0
        sla_target = 99.9
        sla_passed = global_uptime >= sla_target
        
        # Build report data for storage
        report_data = {
            "profile_name": profile_name,
            "tenant_id": tenant_id,
            "period_days": days,
            "uptime": round(global_uptime, 2),
            "sla_target": sla_target,
            "sla_passed": sla_passed,
            "incident_count": incident_count,
            "monitors_count": len(active_bookmarks),
            "total_checks": total_checks,
            "frequency": profile.get("frequency", "MONTHLY"),
            "scheduled": True
        }
        
        # Save to file storage
        self.db.save_profile_report(profile_id, report_data)
        
        # Also save to ai_reports table for the dashboard
        report_title = f"{profile_name} - {days} Day Report"
        report_content = f"""# Executive Summary Report

**Profile:** {profile_name}
**Period:** {start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')} ({days} days)

## Key Metrics

- **Global Availability:** {global_uptime:.2f}%
- **SLA Status:** {'✓ PASSED' if sla_passed else '✕ FAILED'} (Target: {sla_target}%)
- **Service Interruptions:** {incident_count}
- **Total Checks Performed:** {total_checks:,}
- **Active Services Monitored:** {len(active_bookmarks)}

## Summary

{'All systems maintained excellent availability during this period.' if global_uptime >= 99.9 else 'Some services experienced availability issues during this period.'}

---
*Generated automatically by LogLibrarian Scheduler on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}*
"""
        
        metadata = {
            "period_days": days,
            "uptime": round(global_uptime, 2),
            "sla_passed": sla_passed,
            "incident_count": incident_count,
            "monitors_count": len(active_bookmarks),
            "total_checks": total_checks,
            "profile_id": profile_id,
            "profile_name": profile_name,
            "scheduled": True
        }
        
        self.db.create_ai_report(
            report_type="executive_summary",
            title=report_title,
            content=report_content,
            metadata=metadata
        )
        
        logger.info(f"Generated scheduled report for {profile_name}: {global_uptime:.2f}% uptime")
    
    # Manual trigger methods
    async def trigger_daily_briefing(self) -> Optional[int]:
        """Manually trigger a daily briefing"""
        return await self.briefing_generator.generate()
    
    async def trigger_alert_analysis(self, agent_id: str, hours: int = 1) -> Optional[int]:
        """Manually trigger alert analysis"""
        return await self.alert_analyzer.analyze_errors(agent_id, hours)
    
    async def trigger_post_mortem(
        self, 
        agent_id: str, 
        incident_start: datetime,
        incident_end: datetime,
        summary: str = ""
    ) -> Optional[int]:
        """Manually trigger post-mortem generation"""
        return await self.postmortem_generator.generate(
            agent_id, incident_start, incident_end, summary
        )
    
    async def trigger_profile_reports_now(self):
        """Manually trigger all scheduled profile reports (for testing)"""
        await self._generate_scheduled_profile_reports()


# ==================== SINGLETON ====================

_scheduler: Optional[AIReportScheduler] = None


def get_report_scheduler(db_manager=None, ai_service=None) -> Optional[AIReportScheduler]:
    """Get or create the report scheduler"""
    global _scheduler
    
    if _scheduler is None and db_manager is not None and ai_service is not None:
        _scheduler = AIReportScheduler(db_manager, ai_service)
    
    return _scheduler


async def init_report_scheduler(db_manager, ai_service) -> AIReportScheduler:
    """Initialize and start the report scheduler"""
    global _scheduler
    
    _scheduler = AIReportScheduler(db_manager, ai_service)
    await _scheduler.start()
    
    return _scheduler
