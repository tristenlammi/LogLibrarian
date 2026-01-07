import json
import logging
import datetime
from typing import List, Dict, Optional

from notification_manager import NotificationManager, APPRISE_AVAILABLE

# Import database factory for cross-database compatibility
from db_factory import get_database, USE_POSTGRES

logger = logging.getLogger("librarian.alerts")


class AlertEngine:
    """
    Evaluates incoming metrics/events against defined alert rules (V2).
    Supports global rules, agent-specific rules, and bookmark rules.
    Handles rule overrides and cooldowns.
    
    Uses db_factory for database abstraction (works with both SQLite and TimescaleDB).
    """
    
    def __init__(self, db_manager=None, notification_manager: NotificationManager = None):
        self.db = db_manager or get_database()
        self.notification_manager = notification_manager or NotificationManager()
        # Cache for cooldowns: {rule_id_target_id: last_triggered_timestamp}
        self.cooldowns: Dict[str, float] = {}
        # Default cooldown period (overridden by rule-specific settings)
        self.DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes

    # ==========================================
    # Agent Metrics Evaluation
    # ==========================================
    
    async def check_agent_metrics(self, agent_id: str, metrics: Dict, tenant_id: str = "default"):
        """
        Evaluate agent metrics against all applicable rules (global + agent specific).
        Called on each heartbeat.
        """
        try:
            rules = self._get_effective_rules("agent", agent_id, tenant_id)
            
            for rule in rules:
                triggered = self._evaluate_metric_rule(rule, metrics)
                if triggered:
                    await self._trigger_alert(
                        rule=rule,
                        target_type="agent",
                        target_id=agent_id,
                        context=metrics,
                        tenant_id=tenant_id
                    )
                    
        except Exception as e:
            logger.error(f"Error checking alerts for agent {agent_id}: {e}")

    # Legacy method for backwards compatibility
    async def check_heartbeat(self, agent_id: str, metrics: Dict, tenant_id: str = "default"):
        """Legacy wrapper for check_agent_metrics."""
        await self.check_agent_metrics(agent_id, metrics, tenant_id)

    async def check_agent_offline(self, agent_id: str, hostname: str, 
                                   offline_seconds: int, tenant_id: str = "default"):
        """
        Check if agent offline should trigger an alert.
        Called by the watchdog when an agent goes offline.
        """
        try:
            rules = self._get_effective_rules("agent", agent_id, tenant_id)
            
            for rule in rules:
                if rule['metric'] == 'status':
                    # Status rule - check if offline duration exceeds threshold
                    threshold = float(rule['threshold'])  # threshold is offline seconds
                    if offline_seconds >= threshold:
                        await self._trigger_alert(
                            rule=rule,
                            target_type="agent",
                            target_id=agent_id,
                            context={
                                "hostname": hostname,
                                "offline_seconds": offline_seconds,
                                "status": "offline"
                            },
                            tenant_id=tenant_id
                        )
        except Exception as e:
            logger.error(f"Error checking offline alert for agent {agent_id}: {e}")

    # ==========================================
    # Bookmark Status Evaluation
    # ==========================================
    
    async def check_bookmark_status(self, bookmark_id: str, bookmark_name: str, 
                                    check_result: Dict, tenant_id: str = "default"):
        """
        Evaluate bookmark check result against applicable rules.
        Called after each bookmark check.
        
        check_result: {
            "status": 0 or 1 (0=down, 1=up),
            "latency_ms": int,
            "message": str,
            "consecutive_failures": int  # How many failures in a row
        }
        """
        try:
            rules = self._get_effective_rules("bookmark", bookmark_id, tenant_id)
            
            for rule in rules:
                triggered = self._evaluate_bookmark_rule(rule, check_result)
                if triggered:
                    await self._trigger_alert(
                        rule=rule,
                        target_type="bookmark",
                        target_id=bookmark_id,
                        context={
                            "bookmark_name": bookmark_name,
                            **check_result
                        },
                        tenant_id=tenant_id
                    )
        except Exception as e:
            logger.error(f"Error checking alerts for bookmark {bookmark_id}: {e}")

    # ==========================================
    # Rule Fetching (with overrides applied)
    # ==========================================
    
    def _get_effective_rules(self, target_type: str, target_id: str, 
                             tenant_id: str) -> List[Dict]:
        """
        Get all effective rules for a target, including global rules with overrides applied.
        Uses db_factory for database abstraction.
        """
        try:
            return self.db.get_effective_rules_for_target(target_type, target_id, tenant_id)
        except Exception as e:
            logger.error(f"Error getting effective rules for {target_type}/{target_id}: {e}")
            return []

    # ==========================================
    # Rule Evaluation
    # ==========================================
    
    def _evaluate_metric_rule(self, rule: Dict, metrics: Dict) -> bool:
        """Evaluate a metric-based rule against current metrics."""
        metric_key = rule['metric']
        threshold = rule['threshold']
        operator = rule['operator']
        
        value = None
        
        # Map metric names to metric values
        if metric_key == 'cpu':
            value = metrics.get('cpu_percent')
        elif metric_key == 'ram':
            value = metrics.get('ram_percent')
        elif metric_key == 'disk':
            # Get max disk usage percentage
            disks = metrics.get('disk_usage', metrics.get('disks', []))
            if disks:
                max_usage = max(d.get('percent', d.get('used_percent', 0)) for d in disks if isinstance(d, dict))
                value = max_usage
        elif metric_key == 'disk_free':
            # Get min free disk percentage
            disks = metrics.get('disk_usage', metrics.get('disks', []))
            if disks:
                for d in disks:
                    if isinstance(d, dict):
                        total = d.get('total', 1)
                        free = d.get('free', 0)
                        free_pct = (free / total * 100) if total > 0 else 100
                        if value is None or free_pct < value:
                            value = free_pct
        elif metric_key == 'cpu_temp':
            value = metrics.get('cpu_temp')
        elif metric_key == 'net_bandwidth':
            # Max of up/down in Mbps
            net_up = metrics.get('net_up', 0) / 1_000_000
            net_down = metrics.get('net_down', 0) / 1_000_000
            value = max(net_up, net_down)
        
        if value is None:
            return False
        
        return self._compare_values(value, operator, threshold)
    
    def _evaluate_bookmark_rule(self, rule: Dict, check_result: Dict) -> bool:
        """Evaluate a bookmark rule against check result."""
        metric_key = rule['metric']
        threshold = rule['threshold']
        operator = rule['operator']
        
        value = None
        
        if metric_key == 'status':
            # Status: 0 = down, 1 = up
            # For "status down" rules, threshold is number of consecutive failures
            if check_result.get('status') == 0:
                value = check_result.get('consecutive_failures', 1)
            else:
                return False  # Up, don't trigger down alert
        elif metric_key == 'response_time':
            value = check_result.get('latency_ms')
        elif metric_key == 'ssl_expiry':
            value = check_result.get('ssl_days_remaining')
        
        if value is None:
            return False
        
        return self._compare_values(value, operator, threshold)
    
    def _compare_values(self, value: float, operator: str, threshold: str) -> bool:
        """Compare a value against a threshold using the given operator."""
        try:
            val_float = float(value)
            thresh_float = float(threshold)
            
            if operator == 'gt':
                return val_float > thresh_float
            elif operator == 'lt':
                return val_float < thresh_float
            elif operator == 'eq':
                return val_float == thresh_float
            elif operator == 'ne':
                return val_float != thresh_float
            elif operator == 'gte':
                return val_float >= thresh_float
            elif operator == 'lte':
                return val_float <= thresh_float
        except (ValueError, TypeError):
            pass
        
        return False

    # ==========================================
    # Alert Triggering & Notifications
    # ==========================================
    
    async def _trigger_alert(self, rule: Dict, target_type: str, target_id: str,
                            context: Dict, tenant_id: str):
        """Trigger an alert and send notifications."""
        rule_id = rule['id']
        cooldown_key = f"{rule_id}_{target_type}_{target_id}"
        
        # Check cooldown
        now = datetime.datetime.utcnow().timestamp()
        last_triggered = self.cooldowns.get(cooldown_key, 0)
        cooldown_seconds = (rule.get('cooldown_minutes', 5) or 5) * 60
        
        if now - last_triggered < cooldown_seconds:
            logger.debug(f"Alert {rule['name']} suppressed (cooldown) for {target_id}")
            return
        
        # Update cooldown
        self.cooldowns[cooldown_key] = now
        
        # Build notification message
        title, body = self._format_alert_message(rule, target_type, target_id, context)
        
        logger.info(f"[ALERT] Triggering: {title}")
        
        # Send to configured channels
        channel_ids = rule.get('channels', [])
        if channel_ids:
            await self._send_to_channels(channel_ids, title, body, tenant_id, rule['name'])
        else:
            logger.warning(f"Alert rule '{rule['name']}' has no notification channels configured")
    
    def _format_alert_message(self, rule: Dict, target_type: str, target_id: str,
                              context: Dict) -> tuple:
        """Format the alert title and body."""
        rule_name = rule['name']
        metric = rule['metric']
        operator = rule['operator']
        threshold = rule['threshold']
        
        # Operator symbols
        op_symbols = {
            'gt': '>', 'lt': '<', 'eq': '=', 'ne': '≠', 'gte': '≥', 'lte': '≤'
        }
        op_symbol = op_symbols.get(operator, operator)
        
        if target_type == "agent":
            hostname = context.get('hostname', target_id)
            title = f"Alert: {rule_name}"
            
            if metric == 'status':
                body = f"Agent '{hostname}' is offline.\n"
                body += f"Offline for: {context.get('offline_seconds', 0)} seconds"
            else:
                current_value = context.get(f'{metric}_percent', context.get(metric, 'N/A'))
                body = f"Agent '{hostname}' triggered alert '{rule_name}'.\n"
                body += f"Metric: {metric}\n"
                body += f"Condition: {op_symbol} {threshold}\n"
                body += f"Current Value: {current_value}"
                
        elif target_type == "bookmark":
            bookmark_name = context.get('bookmark_name', target_id)
            title = f"Alert: {rule_name}"
            
            if metric == 'status':
                body = f"Bookmark '{bookmark_name}' is DOWN.\n"
                body += f"Message: {context.get('message', 'No response')}\n"
                body += f"Consecutive failures: {context.get('consecutive_failures', 1)}"
            elif metric == 'response_time':
                body = f"Bookmark '{bookmark_name}' response time alert.\n"
                body += f"Latency: {context.get('latency_ms', 'N/A')} ms\n"
                body += f"Threshold: {op_symbol} {threshold} ms"
            elif metric == 'ssl_expiry':
                body = f"Bookmark '{bookmark_name}' SSL certificate expiring soon.\n"
                body += f"Days remaining: {context.get('ssl_days_remaining', 'N/A')}\n"
                body += f"Threshold: {op_symbol} {threshold} days"
            else:
                body = f"Bookmark '{bookmark_name}' triggered alert.\n"
                body += f"Metric: {metric}, Threshold: {op_symbol} {threshold}"
        else:
            title = f"Alert: {rule_name}"
            body = f"Target: {target_id}\nMetric: {metric}\nThreshold: {op_symbol} {threshold}"
        
        return title, body
    
    async def _send_to_channels(self, channel_ids: List[int], title: str, body: str,
                                tenant_id: str, rule_name: str):
        """Send notification to specified channels using db_factory."""
        if not channel_ids:
            return
        
        if not APPRISE_AVAILABLE:
            logger.warning("Apprise not available, cannot send notifications")
            return
        
        import apprise
        
        # Get channels from db_factory
        all_channels = self.db.get_notification_channels(tenant_id)
        channels = [c for c in all_channels if c['id'] in channel_ids]
        
        for channel in channels:
            try:
                ap = apprise.Apprise()
                ap.add(channel['url'])
                success = await ap.async_notify(title=title, body=body)
                
                # Record in history using db_factory
                self.db.add_notification_history(
                    channel_id=channel['id'],
                    event_type=f"alert:{rule_name}",
                    title=title,
                    body=body,
                    status='sent' if success else 'failed',
                    error=None if success else 'Send failed'
                )
                
                logger.info(f"Notification {'sent' if success else 'FAILED'} to channel '{channel['name']}'")
                
            except Exception as ex:
                logger.error(f"Failed to send to channel {channel['id']}: {ex}")
                self.db.add_notification_history(
                    channel_id=channel['id'],
                    event_type=f"alert:{rule_name}",
                    title=title,
                    body=body,
                    status='failed',
                    error=str(ex)
                )


# Singleton instance for use across the application
_alert_engine: Optional[AlertEngine] = None

def get_alert_engine(db_manager=None) -> AlertEngine:
    """Get or create the singleton AlertEngine instance."""
    global _alert_engine
    if _alert_engine is None:
        _alert_engine = AlertEngine(db_manager)
    return _alert_engine
