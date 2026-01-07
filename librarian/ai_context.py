"""
AI Context Builder - Read-only data access for AI chat

Provides the AI with real-time access to database information including:
- Agents/Scribes: status, system info, metrics history
- Logs: counts, recent entries, search
- Metrics: current and historical data
- Alerts: active alerts and history
- Archive: semantic search over historical logs (via Archivist)

ALL OPERATIONS ARE READ-ONLY - NO WRITES ALLOWED
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json
import re


# Common error/issue keywords for log searching
ERROR_KEYWORDS = [
    'error', 'fail', 'failed', 'failure', 'crash', 'crashed', 'exception',
    'critical', 'fatal', 'panic', 'timeout', 'refused', 'denied', 'unauthorized',
    'corrupt', 'invalid', 'missing', 'not found', 'unavailable', 'offline',
    'disconnected', 'killed', 'oom', 'out of memory', 'segfault', 'abort'
]

# Time reference patterns
TIME_PATTERNS = {
    'today': lambda: (datetime.now().replace(hour=0, minute=0, second=0), datetime.now()),
    'yesterday': lambda: (
        (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0),
        (datetime.now() - timedelta(days=1)).replace(hour=23, minute=59, second=59)
    ),
    'last hour': lambda: (datetime.now() - timedelta(hours=1), datetime.now()),
    'last 2 hours': lambda: (datetime.now() - timedelta(hours=2), datetime.now()),
    'last 6 hours': lambda: (datetime.now() - timedelta(hours=6), datetime.now()),
    'last 12 hours': lambda: (datetime.now() - timedelta(hours=12), datetime.now()),
    'last 24 hours': lambda: (datetime.now() - timedelta(hours=24), datetime.now()),
    'last week': lambda: (datetime.now() - timedelta(days=7), datetime.now()),
    'last month': lambda: (datetime.now() - timedelta(days=30), datetime.now()),
    'this week': lambda: (datetime.now() - timedelta(days=datetime.now().weekday()), datetime.now()),
    'this month': lambda: (datetime.now().replace(day=1, hour=0, minute=0, second=0), datetime.now()),
}

# Day name patterns
DAY_NAMES = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6
}


class AIContextBuilder:
    """
    Builds context strings for AI based on database queries.
    All methods are read-only.
    """
    
    def __init__(self, db_manager, archivist=None):
        self.db = db_manager
        self._archivist = archivist
    
    def get_system_overview(self) -> str:
        """Get a high-level overview of the entire system"""
        try:
            agents = self.db.get_all_agents()
            
            online_count = sum(1 for a in agents if a.get('status') == 'online')
            offline_count = len(agents) - online_count
            
            # Get total log count
            total_logs = self._get_total_log_count()
            
            # Get total metrics count
            total_metrics = self._get_total_metrics_count()
            
            # Get active alerts
            alerts = self._get_active_alerts()
            
            overview = f"""## System Overview (as of {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

**Agents/Scribes:**
- Total agents: {len(agents)}
- Online: {online_count}
- Offline: {offline_count}

**Data stored:**
- Total log entries: {total_logs:,}
- Total metric records: {total_metrics:,}

**Active Alerts:** {len(alerts)}
"""
            if alerts:
                overview += "\nAlert Summary:\n"
                for alert in alerts[:5]:  # Show first 5
                    overview += f"- {alert.get('agent_id', 'Unknown')}: {alert.get('message', 'No message')}\n"
            
            return overview
            
        except Exception as e:
            return f"Error getting system overview: {e}"
    
    def get_agents_summary(self) -> str:
        """Get summary of all agents"""
        try:
            agents = self.db.get_all_agents()
            
            if not agents:
                return "No agents registered in the system."
            
            summary = f"## Agents Summary ({len(agents)} total)\n\n"
            
            for agent in agents:
                status = agent.get('status', 'unknown')
                status_emoji = '🟢' if status == 'online' else '🔴'
                
                summary += f"### {status_emoji} {agent.get('hostname', agent.get('agent_id', 'Unknown'))}\n"
                summary += f"- **Agent ID:** {agent.get('agent_id', 'N/A')}\n"
                summary += f"- **Status:** {status}\n"
                summary += f"- **OS:** {agent.get('os', 'Unknown')} {agent.get('os_version', '')}\n"
                summary += f"- **IP:** {agent.get('ip_address', 'Unknown')}\n"
                
                if agent.get('last_seen'):
                    summary += f"- **Last seen:** {agent.get('last_seen')}\n"
                
                summary += "\n"
            
            return summary
            
        except Exception as e:
            return f"Error getting agents summary: {e}"
    
    def get_agent_details(self, agent_identifier: str) -> str:
        """Get detailed info about a specific agent by ID or hostname"""
        try:
            # Try to find agent by ID or hostname
            agents = self.db.get_all_agents()
            agent = None
            
            for a in agents:
                if (a.get('agent_id', '').lower() == agent_identifier.lower() or
                    a.get('hostname', '').lower() == agent_identifier.lower() or
                    agent_identifier.lower() in a.get('agent_id', '').lower() or
                    agent_identifier.lower() in a.get('hostname', '').lower()):
                    agent = a
                    break
            
            if not agent:
                return f"Agent '{agent_identifier}' not found. Use 'list agents' to see available agents."
            
            agent_id = agent.get('agent_id')
            
            # Get recent metrics
            metrics = self.db.get_agent_metrics(agent_id, limit=1)
            latest_metrics = metrics[0] if metrics else {}
            
            # Get system info
            system_info = agent.get('system_info', {})
            if isinstance(system_info, str):
                try:
                    system_info = json.loads(system_info)
                except:
                    system_info = {}
            
            details = f"""## Agent Details: {agent.get('hostname', agent_id)}

**Basic Info:**
- Agent ID: {agent_id}
- Hostname: {agent.get('hostname', 'Unknown')}
- Status: {agent.get('status', 'unknown')}
- IP Address: {agent.get('ip_address', 'Unknown')}
- Last Seen: {agent.get('last_seen', 'Never')}
- First Seen: {agent.get('created_at', 'Unknown')}

**System Info:**
- OS: {agent.get('os', 'Unknown')} {agent.get('os_version', '')}
- Architecture: {system_info.get('arch', 'Unknown')}
- CPU Cores: {system_info.get('cpu_count', 'Unknown')}
- Total RAM: {self._format_bytes(system_info.get('total_memory', 0))}
- Total Disk: {self._format_bytes(system_info.get('total_disk', 0))}
"""
            
            if latest_metrics:
                # Get disk usage info from parsed disks data
                disk_info = ""
                cpu_temp_info = ""
                gpu_info = ""
                
                # Disk usage - db.get_agent_metrics parses disk_json into 'disks' key
                disks = latest_metrics.get('disks', [])
                if disks:
                    root_disk = next((d for d in disks if d.get('mountpoint') == '/'), disks[0])
                    disk_info = f"\n- Disk Usage: {root_disk.get('usage_percent', 0):.1f}%"
                
                # GPU temp is also extracted by db.get_agent_metrics
                gpu_temp = latest_metrics.get('gpu_temp')
                if gpu_temp and gpu_temp > 0:
                    gpu_name = latest_metrics.get('gpu_name', 'Unknown GPU')
                    gpu_info = f"\n- GPU Temp: {gpu_temp:.1f}°C ({gpu_name})"
                
                cpu_temp = latest_metrics.get('cpu_temp', 0)
                if cpu_temp and cpu_temp > 0:
                    cpu_temp_info = f"\n- CPU Temp: {cpu_temp:.1f}°C"
                
                details += f"""
**Current Metrics:**
- CPU Usage: {latest_metrics.get('cpu_percent', 0):.1f}%
- RAM Usage: {latest_metrics.get('ram_percent', 0):.1f}%{disk_info}
- Network In: {self._format_bytes(latest_metrics.get('net_recv_bps', 0))}/s
- Network Out: {self._format_bytes(latest_metrics.get('net_sent_bps', 0))}/s
- Load Avg: {latest_metrics.get('load_avg', 0):.2f}{cpu_temp_info}{gpu_info}
- Recorded at: {latest_metrics.get('timestamp', 'Unknown')}
"""
            
            # Get log count for this agent
            log_count = self._get_agent_log_count(agent_id)
            details += f"\n**Logs:** {log_count:,} entries stored\n"
            
            return details
            
        except Exception as e:
            return f"Error getting agent details: {e}"
    
    def get_agent_metrics_history(self, agent_identifier: str, hours: int = 24) -> str:
        """Get metrics history for an agent"""
        try:
            # Find agent
            agents = self.db.get_all_agents()
            agent_id = None
            
            for a in agents:
                if (a.get('agent_id', '').lower() == agent_identifier.lower() or
                    a.get('hostname', '').lower() == agent_identifier.lower() or
                    agent_identifier.lower() in a.get('agent_id', '').lower() or
                    agent_identifier.lower() in a.get('hostname', '').lower()):
                    agent_id = a.get('agent_id')
                    break
            
            if not agent_id:
                return f"Agent '{agent_identifier}' not found."
            
            # Get metrics (limit to reasonable amount)
            limit = min(hours * 12, 288)  # ~5 min intervals, max 24 hours
            metrics = self.db.get_agent_metrics(agent_id, limit=limit)
            
            if not metrics:
                return f"No metrics found for agent '{agent_identifier}'."
            
            # Calculate stats
            cpu_values = [m.get('cpu_percent', 0) for m in metrics]
            ram_values = [m.get('ram_percent', 0) for m in metrics]
            disk_values = [m.get('disk_percent', 0) for m in metrics]
            
            summary = f"""## Metrics History for {agent_identifier}
**Period:** Last {len(metrics)} records

**CPU Usage:**
- Current: {cpu_values[0]:.1f}%
- Average: {sum(cpu_values)/len(cpu_values):.1f}%
- Min: {min(cpu_values):.1f}%
- Max: {max(cpu_values):.1f}%

**RAM Usage:**
- Current: {ram_values[0]:.1f}%
- Average: {sum(ram_values)/len(ram_values):.1f}%
- Min: {min(ram_values):.1f}%
- Max: {max(ram_values):.1f}%

**Disk Usage:**
- Current: {disk_values[0]:.1f}%
- Average: {sum(disk_values)/len(disk_values):.1f}%
- Min: {min(disk_values):.1f}%
- Max: {max(disk_values):.1f}%
"""
            return summary
            
        except Exception as e:
            return f"Error getting metrics history: {e}"
    
    def get_recent_logs(self, agent_identifier: str = None, limit: int = 20) -> str:
        """Get recent logs, optionally filtered by agent"""
        try:
            # Build query
            if agent_identifier:
                # Find agent ID
                agents = self.db.get_all_agents()
                agent_id = None
                for a in agents:
                    if (a.get('agent_id', '').lower() == agent_identifier.lower() or
                        a.get('hostname', '').lower() == agent_identifier.lower() or
                        agent_identifier.lower() in a.get('agent_id', '').lower() or
                        agent_identifier.lower() in a.get('hostname', '').lower()):
                        agent_id = a.get('agent_id')
                        break
                
                if not agent_id:
                    return f"Agent '{agent_identifier}' not found."
                
                logs = self.db.get_logs(agent_id=agent_id, limit=min(limit, 50))
                header = f"## Recent Logs for {agent_identifier}"
            else:
                logs = self.db.get_logs(limit=min(limit, 50))
                header = "## Recent Logs (All Agents)"
            
            if not logs:
                return f"{header}\n\nNo logs found."
            
            result = f"{header}\n\nShowing {len(logs)} most recent entries:\n\n"
            
            for log in logs[:limit]:
                level = log.get('level', 'INFO')
                level_emoji = {'ERROR': '🔴', 'WARN': '🟡', 'WARNING': '🟡', 'INFO': '🔵', 'DEBUG': '⚪'}.get(level.upper(), '⚪')
                
                result += f"{level_emoji} **[{log.get('timestamp', 'Unknown')}]** "
                result += f"[{log.get('agent_id', 'Unknown')[:15]}] "
                result += f"{log.get('message', 'No message')[:200]}\n"
            
            return result
            
        except Exception as e:
            return f"Error getting logs: {e}"
    
    def search_logs(self, query: str, agent_identifier: str = None, limit: int = 20) -> str:
        """Search logs by message content"""
        try:
            agent_id = None
            if agent_identifier:
                agents = self.db.get_all_agents()
                for a in agents:
                    if (agent_identifier.lower() in a.get('agent_id', '').lower() or
                        agent_identifier.lower() in a.get('hostname', '').lower()):
                        agent_id = a.get('agent_id')
                        break
            
            # Search logs
            logs = self.db.search_logs(query=query, agent_id=agent_id, limit=min(limit, 50))
            
            if not logs:
                return f"No logs found matching '{query}'."
            
            result = f"## Log Search Results for '{query}'\n\nFound {len(logs)} matches:\n\n"
            
            for log in logs:
                level = log.get('level', 'INFO')
                level_emoji = {'ERROR': '🔴', 'WARN': '🟡', 'WARNING': '🟡', 'INFO': '🔵', 'DEBUG': '⚪'}.get(level.upper(), '⚪')
                
                result += f"{level_emoji} **[{log.get('timestamp', 'Unknown')}]** "
                result += f"[{log.get('agent_id', 'Unknown')[:15]}] "
                result += f"{log.get('message', 'No message')[:200]}\n"
            
            return result
            
        except Exception as e:
            return f"Error searching logs: {e}"
    
    def get_log_statistics(self) -> str:
        """Get log statistics by level and agent"""
        try:
            stats = self._get_log_stats()
            
            result = """## Log Statistics

**By Level:**
"""
            for level, count in stats.get('by_level', {}).items():
                emoji = {'ERROR': '🔴', 'WARN': '🟡', 'WARNING': '🟡', 'INFO': '🔵', 'DEBUG': '⚪'}.get(level.upper(), '⚪')
                result += f"- {emoji} {level}: {count:,}\n"
            
            result += "\n**By Agent:**\n"
            for agent, count in stats.get('by_agent', {}).items():
                result += f"- {agent}: {count:,}\n"
            
            result += f"\n**Total Logs:** {stats.get('total', 0):,}\n"
            
            return result
            
        except Exception as e:
            return f"Error getting log statistics: {e}"
    
    def get_alerts_summary(self) -> str:
        """Get current alerts and recent alert history"""
        try:
            alerts = self._get_active_alerts()
            
            if not alerts:
                return "## Alerts\n\n✅ No active alerts. All systems normal."
            
            result = f"## Active Alerts ({len(alerts)} total)\n\n"
            
            for alert in alerts:
                result += f"⚠️ **{alert.get('agent_id', 'Unknown')}**\n"
                result += f"   - Type: {alert.get('alert_type', 'Unknown')}\n"
                result += f"   - Message: {alert.get('message', 'No details')}\n"
                result += f"   - Since: {alert.get('created_at', 'Unknown')}\n\n"
            
            return result
            
        except Exception as e:
            return f"Error getting alerts: {e}"
    
    def build_context_for_query(self, user_query: str) -> str:
        """
        Build relevant context based on the user's query.
        Analyzes the query and fetches appropriate data.
        """
        query_lower = user_query.lower()
        context_parts = []
        
        # Always include system overview for context
        context_parts.append(self.get_system_overview())
        
        # Check for specific data requests
        if any(word in query_lower for word in ['agent', 'scribe', 'server', 'machine', 'host']):
            # Check if asking about specific agent
            agents = self.db.get_all_agents()
            mentioned_agent = None
            
            for agent in agents:
                hostname = agent.get('hostname', '').lower()
                agent_id = agent.get('agent_id', '').lower()
                if hostname in query_lower or agent_id in query_lower:
                    mentioned_agent = agent.get('agent_id')
                    break
            
            if mentioned_agent:
                context_parts.append(self.get_agent_details(mentioned_agent))
                context_parts.append(self.get_agent_metrics_history(mentioned_agent, hours=6))
            else:
                context_parts.append(self.get_agents_summary())
        
        if any(word in query_lower for word in ['log', 'error', 'warning', 'message']):
            # Check for search terms
            if 'search' in query_lower or 'find' in query_lower:
                # Try to extract search term (simplified)
                context_parts.append(self.get_recent_logs(limit=30))
            else:
                context_parts.append(self.get_recent_logs(limit=20))
            context_parts.append(self.get_log_statistics())
        
        if any(word in query_lower for word in ['metric', 'cpu', 'ram', 'memory', 'disk', 'usage', 'performance']):
            agents = self.db.get_all_agents()
            for agent in agents[:3]:  # Limit to first 3 agents
                context_parts.append(self.get_agent_metrics_history(agent.get('agent_id'), hours=6))
        
        if any(word in query_lower for word in ['alert', 'warning', 'problem', 'issue']):
            context_parts.append(self.get_alerts_summary())
        
        # Use Archivist for semantic search if available and query seems to need historical context
        if self._archivist and any(word in query_lower for word in [
            'history', 'past', 'before', 'previous', 'last week', 'yesterday',
            'similar', 'like', 'related', 'find', 'search', 'when', 'ever'
        ]):
            archive_results = self.search_archives(user_query, limit=5)
            if archive_results and "No archived logs found" not in archive_results:
                context_parts.append(archive_results)
        
        # Combine all context
        full_context = "\n\n---\n\n".join(context_parts)
        
        return full_context
    
    def search_archives(self, query: str, limit: int = 10, server_name: str = None, 
                       log_level: str = None, time_range_hours: int = None) -> str:
        """
        Search the log archives using semantic similarity via the Archivist.
        
        Returns formatted results for AI context.
        """
        if not self._archivist:
            return "Archive search not available - Archivist not initialized."
        
        try:
            return self._archivist.search_archives_formatted(
                query=query,
                limit=limit,
                server_name=server_name,
                log_level=log_level,
                time_range_hours=time_range_hours
            )
        except Exception as e:
            return f"Archive search error: {e}"
    
    # Helper methods
    
    def _get_total_log_count(self) -> int:
        """Get total number of logs"""
        try:
            result = self.db.execute_query("SELECT COUNT(*) as count FROM raw_logs")
            return result[0]['count'] if result else 0
        except:
            return 0
    
    def _get_total_metrics_count(self) -> int:
        """Get total number of metric records"""
        try:
            result = self.db.execute_query("SELECT COUNT(*) as count FROM metrics")
            return result[0]['count'] if result else 0
        except:
            return 0
    
    def _get_agent_log_count(self, agent_id: str) -> int:
        """Get log count for specific agent"""
        try:
            result = self.db.execute_query(
                "SELECT COUNT(*) as count FROM raw_logs WHERE agent_id = ?",
                (agent_id,)
            )
            return result[0]['count'] if result else 0
        except:
            return 0
    
    def _get_active_alerts(self) -> List[Dict]:
        """Get active alerts"""
        try:
            return self.db.get_active_alerts() or []
        except:
            return []
    
    def get_agent_health_packet(self, agent_id: str) -> str:
        """
        Generate a dense 'Health Packet' for a specific agent.
        Returns a compact text block with hardware, metrics summary, and recent issues.
        
        Used for manual context selection in AI chat.
        """
        try:
            # Get agent info
            agents = self.db.get_all_agents()
            agent = None
            for a in agents:
                if a.get('agent_id') == agent_id or a.get('hostname', '').lower() == agent_id.lower():
                    agent = a
                    break
            
            if not agent:
                return f"[AGENT: {agent_id}] - NOT FOUND"
            
            agent_id = agent.get('agent_id')
            hostname = agent.get('hostname', agent_id)
            status = agent.get('status', 'unknown')
            
            # Parse system_info
            system_info = agent.get('system_info', {})
            if isinstance(system_info, str):
                try:
                    system_info = json.loads(system_info)
                except:
                    system_info = {}
            
            # Hardware info
            cpu_model = system_info.get('cpu_model', 'Unknown CPU')
            cpu_cores = system_info.get('cpu_cores', '?')
            ram_total = system_info.get('ram_total_gb', 0)
            gpu_model = system_info.get('gpu_model', 'No GPU detected')
            os_info = f"{agent.get('os', 'Unknown')} {agent.get('os_version', '')}"
            
            # Get 24h metrics summary
            from datetime import datetime, timedelta
            start_time = (datetime.now() - timedelta(hours=24)).isoformat()
            metrics = self.db.get_agent_metrics(agent_id, limit=1000, start_time=start_time)
            
            # Calculate stats
            avg_cpu = max_cpu = avg_ram = max_ram = 0
            avg_cpu_temp = max_cpu_temp = avg_gpu_temp = max_gpu_temp = 0
            
            if metrics:
                try:
                    cpu_values = [float(m.get('cpu_percent', 0) or 0) for m in metrics]
                    ram_values = [float(m.get('ram_percent', 0) or 0) for m in metrics]
                    cpu_temp_values = [float(m.get('cpu_temp', 0) or 0) for m in metrics if m.get('cpu_temp') and float(m.get('cpu_temp', 0)) > 0]
                    gpu_temp_values = [float(m.get('gpu_temp', 0) or 0) for m in metrics if m.get('gpu_temp') and float(m.get('gpu_temp', 0)) > 0]
                    
                    avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0
                    max_cpu = max(cpu_values) if cpu_values else 0
                    avg_ram = sum(ram_values) / len(ram_values) if ram_values else 0
                    max_ram = max(ram_values) if ram_values else 0
                    avg_cpu_temp = sum(cpu_temp_values) / len(cpu_temp_values) if cpu_temp_values else 0
                    max_cpu_temp = max(cpu_temp_values) if cpu_temp_values else 0
                    avg_gpu_temp = sum(gpu_temp_values) / len(gpu_temp_values) if gpu_temp_values else 0
                    max_gpu_temp = max(gpu_temp_values) if gpu_temp_values else 0
                except Exception as e:
                    print(f"Error calculating metrics stats: {e}")
            
            # Get recent error logs
            error_logs = []
            try:
                result = self.db.get_raw_logs(agent_id=agent_id, severity='error', limit=5)
                if result and result.get('logs'):
                    error_logs = result['logs']
                # Also check critical
                critical_result = self.db.get_raw_logs(agent_id=agent_id, severity='critical', limit=3)
                if critical_result and critical_result.get('logs'):
                    error_logs = critical_result['logs'] + error_logs
                error_logs = error_logs[:5]  # Keep max 5
            except Exception as e:
                print(f"Error getting logs: {e}")
            
            # Build the compact packet
            status_emoji = '🟢' if status == 'online' else '🔴'
            
            packet = f"""[AGENT: {hostname}] {status_emoji} {status.upper()}
- Hardware: {cpu_model} ({cpu_cores} cores), {ram_total:.1f}GB RAM
- GPU: {gpu_model}
- OS: {os_info}
- 24h Metrics: Avg CPU {avg_cpu:.0f}%, Max CPU {max_cpu:.0f}%, Avg RAM {avg_ram:.0f}%, Max RAM {max_ram:.0f}%"""
            
            if max_cpu_temp > 0:
                packet += f"\n- CPU Temps: Avg {avg_cpu_temp:.0f}°C, Max {max_cpu_temp:.0f}°C"
            if max_gpu_temp > 0:
                packet += f"\n- GPU Temps: Avg {avg_gpu_temp:.0f}°C, Max {max_gpu_temp:.0f}°C"
            
            if error_logs:
                packet += "\n- Recent Errors:"
                for log in error_logs[:3]:
                    msg = log.get('message', 'No message')[:60]
                    ts = log.get('timestamp', 'Unknown time')
                    if isinstance(ts, str) and len(ts) > 16:
                        ts = ts[11:16]  # Extract HH:MM
                    packet += f"\n  • '{msg}' at {ts}"
            else:
                packet += "\n- Recent Errors: None"
            
            return packet
            
        except Exception as e:
            return f"[AGENT: {agent_id}] - Error generating packet: {str(e)}"
    
    def get_multi_agent_context(self, agent_ids: list) -> str:
        """
        Generate combined health packets for multiple agents.
        Used when user selects specific agents for AI chat context.
        """
        if not agent_ids:
            return ""
        
        packets = []
        for agent_id in agent_ids:
            packet = self.get_agent_health_packet(agent_id)
            packets.append(packet)
        
        return "\n\n".join(packets)
    
    def parse_time_reference(self, user_message: str) -> tuple:
        """
        Parse time references from user's message.
        Returns (start_time, end_time) as datetime objects, or (None, None) if no time reference.
        """
        message_lower = user_message.lower()
        
        # Check explicit time patterns first
        for pattern, time_func in TIME_PATTERNS.items():
            if pattern in message_lower:
                return time_func()
        
        # Check for "X days ago", "X hours ago", "X weeks ago" patterns
        days_match = re.search(r'(\d+)\s*days?\s*ago', message_lower)
        if days_match:
            days = int(days_match.group(1))
            target_date = datetime.now() - timedelta(days=days)
            return (
                target_date.replace(hour=0, minute=0, second=0),
                target_date.replace(hour=23, minute=59, second=59)
            )
        
        hours_match = re.search(r'(\d+)\s*hours?\s*ago', message_lower)
        if hours_match:
            hours = int(hours_match.group(1))
            end_time = datetime.now() - timedelta(hours=hours)
            start_time = end_time - timedelta(hours=1)  # 1 hour window
            return (start_time, end_time + timedelta(hours=1))
        
        weeks_match = re.search(r'(\d+)\s*weeks?\s*ago', message_lower)
        if weeks_match:
            weeks = int(weeks_match.group(1))
            target_date = datetime.now() - timedelta(weeks=weeks)
            return (
                target_date - timedelta(days=3),  # ±3 day window
                target_date + timedelta(days=3)
            )
        
        # Check for day names (e.g., "last Tuesday")
        for day_name, day_num in DAY_NAMES.items():
            if day_name in message_lower:
                # Find the most recent occurrence of that day
                today = datetime.now()
                days_since = (today.weekday() - day_num) % 7
                if days_since == 0:
                    days_since = 7  # If today is that day, go back a week
                if 'last' in message_lower:
                    days_since += 7  # "last Tuesday" means go back further
                
                target_date = today - timedelta(days=days_since)
                return (
                    target_date.replace(hour=0, minute=0, second=0),
                    target_date.replace(hour=23, minute=59, second=59)
                )
        
        # Check for specific date patterns (MM/DD, YYYY-MM-DD)
        date_match = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', message_lower)
        if date_match:
            month = int(date_match.group(1))
            day = int(date_match.group(2))
            year = int(date_match.group(3)) if date_match.group(3) else datetime.now().year
            if year < 100:
                year += 2000
            try:
                target_date = datetime(year, month, day)
                return (
                    target_date.replace(hour=0, minute=0, second=0),
                    target_date.replace(hour=23, minute=59, second=59)
                )
            except ValueError:
                pass
        
        # No time reference found - default to last 24 hours for context
        return (None, None)
    
    def extract_keywords(self, user_message: str) -> List[str]:
        """
        Extract relevant search keywords from user's message.
        Returns list of keywords to search for in logs.
        """
        message_lower = user_message.lower()
        keywords = []
        
        # Check for error-related keywords in the message
        for kw in ERROR_KEYWORDS:
            if kw in message_lower:
                keywords.append(kw)
        
        # Extract quoted strings (user explicitly searching for something)
        quoted = re.findall(r'"([^"]+)"', user_message)
        keywords.extend(quoted)
        quoted_single = re.findall(r"'([^']+)'", user_message)
        keywords.extend(quoted_single)
        
        # Common question patterns that indicate what to look for
        question_patterns = [
            (r'why.*(?:crash|fail|stop|offline|down)', ['crash', 'error', 'fail', 'stopped', 'offline']),
            (r'what.*error', ['error', 'exception', 'fail']),
            (r'disk.*(?:full|space|issue)', ['disk', 'storage', 'space', 'full', 'no space']),
            (r'memory.*(?:issue|problem|high|leak)', ['memory', 'oom', 'out of memory', 'killed']),
            (r'cpu.*(?:high|spike|issue)', ['cpu', 'load', 'high cpu']),
            (r'network.*(?:issue|problem|slow|timeout)', ['network', 'connection', 'timeout', 'refused']),
            (r'restart|reboot', ['restart', 'reboot', 'shutdown', 'startup', 'boot']),
            (r'slow|performance', ['slow', 'performance', 'timeout', 'latency', 'lag']),
            (r'login|auth|permission', ['login', 'auth', 'permission', 'denied', 'unauthorized']),
            (r'update|upgrade|install', ['update', 'upgrade', 'install', 'package', 'apt', 'yum']),
        ]
        
        for pattern, kws in question_patterns:
            if re.search(pattern, message_lower):
                keywords.extend(kws)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique_keywords.append(kw)
        
        return unique_keywords
    
    def fetch_relevant_logs(self, agent_id: str, user_message: str, limit: int = 25) -> str:
        """
        Intelligently fetch logs relevant to the user's question.
        
        Analyzes the user's message to:
        1. Determine time range (e.g., "yesterday", "last Tuesday", "3 days ago")
        2. Extract keywords (e.g., "crash", "error", "disk full")
        3. Query database for matching logs
        
        Returns formatted log entries or empty string if none found.
        """
        try:
            # Parse time reference
            start_time, end_time = self.parse_time_reference(user_message)
            
            # Extract keywords
            keywords = self.extract_keywords(user_message)
            
            # Build search query
            all_logs = []
            
            # If we have a specific time range, use it
            if start_time and end_time:
                start_str = start_time.isoformat()
                end_str = end_time.isoformat()
                
                # Search with time range
                if keywords:
                    # Search for each keyword within time range
                    for keyword in keywords[:5]:  # Limit to 5 keywords
                        try:
                            result = self.db.get_raw_logs(
                                agent_id=agent_id,
                                search=keyword,
                                start_time=start_str,
                                end_time=end_str,
                                limit=limit
                            )
                            if result and result.get('logs'):
                                all_logs.extend(result['logs'])
                        except Exception as e:
                            print(f"Error searching for keyword '{keyword}': {e}")
                else:
                    # No keywords, just get logs from time range
                    result = self.db.get_raw_logs(
                        agent_id=agent_id,
                        start_time=start_str,
                        end_time=end_str,
                        limit=limit
                    )
                    if result and result.get('logs'):
                        all_logs.extend(result['logs'])
            else:
                # No time reference - search by keywords in recent logs (24h)
                recent_start = (datetime.now() - timedelta(hours=24)).isoformat()
                
                if keywords:
                    for keyword in keywords[:5]:
                        try:
                            result = self.db.get_raw_logs(
                                agent_id=agent_id,
                                search=keyword,
                                start_time=recent_start,
                                limit=limit
                            )
                            if result and result.get('logs'):
                                all_logs.extend(result['logs'])
                        except Exception as e:
                            print(f"Error searching for keyword '{keyword}': {e}")
                
                # Also get any error/critical logs
                try:
                    for severity in ['error', 'critical']:
                        result = self.db.get_raw_logs(
                            agent_id=agent_id,
                            severity=severity,
                            start_time=recent_start,
                            limit=10
                        )
                        if result and result.get('logs'):
                            all_logs.extend(result['logs'])
                except Exception as e:
                    print(f"Error getting error logs: {e}")
            
            # Deduplicate by log ID and sort by timestamp
            seen_ids = set()
            unique_logs = []
            for log in all_logs:
                log_id = log.get('id') or f"{log.get('timestamp')}_{log.get('message', '')[:50]}"
                if log_id not in seen_ids:
                    seen_ids.add(log_id)
                    unique_logs.append(log)
            
            # Sort by timestamp (newest first for recent, oldest first for historical)
            unique_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            # Limit to top N
            unique_logs = unique_logs[:limit]
            
            if not unique_logs:
                return ""
            
            # Format logs for AI context
            formatted = []
            for log in unique_logs:
                ts = log.get('timestamp', 'Unknown')
                if isinstance(ts, str) and len(ts) > 19:
                    ts = ts[:19]  # Trim to YYYY-MM-DD HH:MM:SS
                
                severity = log.get('severity', 'info').upper()
                source = log.get('source', 'system')
                message = log.get('message', 'No message')
                
                # Truncate long messages
                if len(message) > 200:
                    message = message[:200] + '...'
                
                formatted.append(f"[{ts}] [{severity}] {source}: {message}")
            
            return "\n".join(formatted)
            
        except Exception as e:
            print(f"Error fetching relevant logs: {e}")
            return ""
    
    def get_scoped_context(self, agent_ids: List[str], user_message: str) -> str:
        """
        Build a complete scoped context for AI chat with selected agents.
        
        Combines:
        1. Health Packets (hardware, metrics, status) for each agent
        2. Relevant logs based on user's question
        
        This is the "Intelligent Filter" that gives AI focused context.
        """
        if not agent_ids:
            return ""
        
        sections = []
        
        for agent_id in agent_ids:
            # Get the static health packet
            health_packet = self.get_agent_health_packet(agent_id)
            
            # Get relevant logs for this agent based on user's question
            relevant_logs = self.fetch_relevant_logs(agent_id, user_message, limit=25)
            
            # Get hostname for section header
            agents = self.db.get_all_agents()
            hostname = agent_id
            for a in agents:
                if a.get('agent_id') == agent_id:
                    hostname = a.get('hostname', agent_id)
                    break
            
            # Build agent section
            section = health_packet
            
            if relevant_logs:
                section += f"\n\n[RELEVANT LOGS FOR {hostname}]:\n{relevant_logs}"
            else:
                section += f"\n\n[RELEVANT LOGS FOR {hostname}]: No matching logs found for your query."
            
            sections.append(section)
        
        # Add search metadata
        keywords = self.extract_keywords(user_message)
        start_time, end_time = self.parse_time_reference(user_message)
        
        metadata = "\n---\n[SEARCH METADATA]"
        if keywords:
            metadata += f"\n- Keywords detected: {', '.join(keywords[:5])}"
        if start_time and end_time:
            metadata += f"\n- Time range: {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}"
        else:
            metadata += "\n- Time range: Last 24 hours (default)"
        
        return "\n\n".join(sections) + metadata
    
    def _get_log_stats(self) -> Dict:
        """Get log statistics"""
        try:
            # By severity level
            level_result = self.db.execute_query(
                "SELECT severity, COUNT(*) as count FROM raw_logs GROUP BY severity ORDER BY count DESC"
            )
            by_level = {r['severity']: r['count'] for r in (level_result or [])}
            
            # By agent
            agent_result = self.db.execute_query(
                "SELECT agent_id, COUNT(*) as count FROM raw_logs GROUP BY agent_id ORDER BY count DESC LIMIT 10"
            )
            by_agent = {r['agent_id']: r['count'] for r in (agent_result or [])}
            
            # Total
            total_result = self.db.execute_query("SELECT COUNT(*) as count FROM raw_logs")
            total = total_result[0]['count'] if total_result else 0
            
            return {'by_level': by_level, 'by_agent': by_agent, 'total': total}
        except:
            return {'by_level': {}, 'by_agent': {}, 'total': 0}
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes to human readable"""
        if not bytes_val:
            return "0 B"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if abs(bytes_val) < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
