"""
Database Factory Module

This module provides a unified interface for database operations,
automatically selecting between SQLite (default) and PostgreSQL/TimescaleDB
based on environment configuration.

Environment Variables:
    USE_POSTGRES: Set to "true" to use PostgreSQL instead of SQLite
    DATABASE_URL: PostgreSQL connection string (required if USE_POSTGRES=true)
    USE_TIMESCALE: Enable TimescaleDB features (default: true when using PostgreSQL)
"""

import os
import asyncio
import concurrent.futures
from typing import Optional, Union
from functools import wraps

# Configuration
USE_POSTGRES = os.getenv("USE_POSTGRES", "false").lower() == "true"

# Import appropriate database manager
if USE_POSTGRES:
    from db_postgres import PostgresDatabaseManager, get_postgres_db
    print("✓ Using PostgreSQL/TimescaleDB database backend")
else:
    from db import DatabaseManager
    print("✓ Using SQLite database backend")


class DatabaseFactory:
    """
    Factory class that provides a unified sync interface to either
    SQLite or PostgreSQL database backends.
    
    For SQLite: Uses synchronous methods directly
    For PostgreSQL: Wraps async methods to run in event loop
    """
    
    _instance: Optional['DatabaseFactory'] = None
    _db: Union['DatabaseManager', 'PostgresDatabaseManager', None] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._db is not None:
            return
            
        if USE_POSTGRES:
            self._db = PostgresDatabaseManager()
            # Create event loop for async operations
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            # Create a reusable thread pool executor (4 workers)
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db_factory")
        else:
            self._db = DatabaseManager()
    
    def _run_async(self, coro):
        """Run an async coroutine synchronously using reusable thread pool"""
        if self._loop.is_running():
            # If we're already in an async context, use the shared executor
            future = self._executor.submit(asyncio.run, coro)
            return future.result()
        else:
            return self._loop.run_until_complete(coro)
    
    def shutdown(self):
        """Cleanup resources (call on application shutdown)"""
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
    
    async def initialize_async(self):
        """Initialize database (async version for PostgreSQL)"""
        if USE_POSTGRES:
            await self._db.initialize()
    
    def initialize(self):
        """Initialize database (sync version)"""
        if USE_POSTGRES:
            self._run_async(self._db.initialize())
    
    # ==================== Agent Methods ====================
    
    def upsert_agent(self, agent_id: str, hostname: str, status: str, 
                    last_seen, public_ip: str = "") -> None:
        if USE_POSTGRES:
            self._run_async(self._db.upsert_agent(agent_id, hostname, status, last_seen, public_ip))
        else:
            self._db.upsert_agent(agent_id, hostname, status, last_seen, public_ip)
    
    def get_all_agents(self):
        if USE_POSTGRES:
            return self._run_async(self._db.get_all_agents())
        else:
            return self._db.get_all_agents()
    
    def delete_agent(self, agent_id: str) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.delete_agent(agent_id))
        else:
            self._db.delete_agent(agent_id)
    
    def disable_agent(self, agent_id: str) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.disable_agent(agent_id))
        else:
            self._db.disable_agent(agent_id)
    
    def enable_agent(self, agent_id: str) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.enable_agent(agent_id))
        else:
            self._db.enable_agent(agent_id)
    
    def update_agent_display_name(self, agent_id: str, display_name: str) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.update_agent_display_name(agent_id, display_name))
        else:
            self._db.update_agent_display_name(agent_id, display_name)
    
    # ==================== Metrics Methods ====================
    
    def bulk_insert_metrics(self, agent_id: str, metrics: list, load_avg: float = 0.0) -> int:
        if USE_POSTGRES:
            return self._run_async(self._db.bulk_insert_metrics(agent_id, metrics, load_avg))
        else:
            return self._db.bulk_insert_metrics(agent_id, metrics, load_avg)
    
    def get_agent_metrics(self, agent_id: str, limit: int = 100, start_time: str = None,
                         end_time: str = None, downsample: str = None):
        if USE_POSTGRES:
            return self._run_async(self._db.get_agent_metrics(
                agent_id, limit, start_time, end_time, downsample
            ))
        else:
            return self._db.get_agent_metrics(agent_id, limit, start_time, end_time, downsample)
    
    # ==================== Process Snapshots ====================
    
    def insert_process_snapshot(self, agent_id: str, timestamp, processes: list) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.insert_process_snapshot(agent_id, timestamp, processes))
        else:
            self._db.insert_process_snapshot(agent_id, timestamp, processes)
    
    def get_latest_process_snapshot(self, agent_id: str):
        if USE_POSTGRES:
            return self._run_async(self._db.get_latest_process_snapshot(agent_id))
        else:
            return self._db.get_latest_process_snapshot(agent_id)
    
    def get_process_snapshots_range(self, agent_id: str, start_time, end_time):
        if USE_POSTGRES:
            return self._run_async(self._db.get_process_snapshots_range(agent_id, start_time, end_time))
        else:
            return self._db.get_process_snapshots_range(agent_id, start_time, end_time)
    
    # ==================== Alert Methods ====================
    
    def get_alert_rules(self, agent_id: str):
        if USE_POSTGRES:
            return self._run_async(self._db.get_alert_rules(agent_id))
        else:
            return self._db.get_alert_rules(agent_id)
    
    def upsert_alert_rules(self, agent_id: str, rules: dict) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.upsert_alert_rules(agent_id, rules))
        else:
            self._db.upsert_alert_rules(agent_id, rules)
    
    def get_active_alerts(self, agent_id: str = None):
        if USE_POSTGRES:
            return self._run_async(self._db.get_active_alerts(agent_id))
        else:
            return self._db.get_active_alerts(agent_id)
    
    def create_alert(self, agent_id: str, alert_type: str, threshold_value: float,
                    current_value: float, message: str, severity: str = 'warning'):
        if USE_POSTGRES:
            return self._run_async(self._db.create_alert(
                agent_id, alert_type, threshold_value, current_value, message, severity
            ))
        else:
            return self._db.create_alert(
                agent_id, alert_type, threshold_value, current_value, message, severity
            )
    
    def resolve_alert(self, alert_id: int) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.resolve_alert(alert_id))
        else:
            self._db.resolve_alert(alert_id)
    
    # ==================== Log Settings ====================
    
    def get_agent_log_settings(self, agent_id: str):
        if USE_POSTGRES:
            return self._run_async(self._db.get_agent_log_settings(agent_id))
        else:
            return self._db.get_agent_log_settings(agent_id)
    
    def upsert_agent_log_settings(self, agent_id: str, settings: dict) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.upsert_agent_log_settings(agent_id, settings))
        else:
            self._db.upsert_agent_log_settings(agent_id, settings)
    
    # ==================== Raw Logs ====================
    
    def insert_raw_logs(self, logs: list) -> int:
        if USE_POSTGRES:
            return self._run_async(self._db.insert_raw_logs(logs))
        else:
            return self._db.insert_raw_logs(logs)
    
    def query_raw_logs(self, agent_id: str, limit: int = 100, offset: int = 0,
                      severity: str = None, source: str = None, search: str = None,
                      start_time=None, end_time=None):
        if USE_POSTGRES:
            return self._run_async(self._db.query_raw_logs(
                agent_id, limit, offset, severity, source, search, start_time, end_time
            ))
        else:
            return self._db.query_raw_logs(
                agent_id, limit, offset, severity, source, search, start_time, end_time
            )
    
    def get_raw_log_stats(self, agent_id: str, hours: int = 24):
        if USE_POSTGRES:
            return self._run_async(self._db.get_raw_log_stats(agent_id, hours))
        else:
            return self._db.get_raw_log_stats(agent_id, hours)
    
    # ==================== System Settings ====================
    
    def get_setting(self, key: str):
        if USE_POSTGRES:
            return self._run_async(self._db.get_setting(key))
        else:
            return self._db.get_setting(key)
    
    def set_setting(self, key: str, value: str, description: str = None) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.set_setting(key, value, description))
        else:
            self._db.set_setting(key, value, description)
    
    def get_all_settings(self):
        if USE_POSTGRES:
            return self._run_async(self._db.get_all_settings())
        else:
            return self._db.get_all_settings()
    
    # ==================== Uptime Monitoring ====================
    
    def get_agents_to_check_uptime(self):
        if USE_POSTGRES:
            return self._run_async(self._db.get_agents_to_check_uptime())
        else:
            return self._db.get_agents_to_check_uptime()
    
    def update_agent_status(self, agent_id: str, status: str) -> None:
        if USE_POSTGRES:
            self._run_async(self._db.update_agent_status(agent_id, status))
        else:
            self._db.update_agent_status(agent_id, status)
    
    # ==================== Alert Rules V2 ====================
    
    def get_effective_rules_for_target(self, target_type: str, target_id: str, 
                                       tenant_id: str = "default") -> list:
        """Get all effective alert rules for a target (agent or bookmark)"""
        if USE_POSTGRES:
            return self._db.get_effective_rules_for_target(target_type, target_id, tenant_id)
        else:
            return self._db.get_effective_rules_for_target(target_type, target_id, tenant_id)
    
    def get_alert_rules_v2(self, tenant_id: str = "default", scope: str = None,
                           target_id: str = None) -> list:
        """Get alert rules with optional filtering"""
        if USE_POSTGRES:
            return self._db.get_alert_rules_v2(tenant_id, scope, target_id)
        else:
            return self._db.get_alert_rules_v2(tenant_id, scope, target_id)
    
    # ==================== Notification Channels ====================
    
    def get_notification_channels(self, tenant_id: str = "default") -> list:
        """Get all notification channels for a tenant"""
        if USE_POSTGRES:
            return self._db.get_notification_channels(tenant_id)
        else:
            return self._db.get_notification_channels(tenant_id)
    
    def get_notification_channel_by_id(self, channel_id: int, tenant_id: str = "default"):
        """Get a specific notification channel by ID"""
        channels = self.get_notification_channels(tenant_id)
        return next((c for c in channels if c['id'] == channel_id), None)
    
    def add_notification_history(self, channel_id: int, event_type: str, title: str,
                                 body: str, status: str, error: str = None) -> None:
        """Record a notification in history"""
        if USE_POSTGRES:
            self._db.add_notification_history(channel_id, event_type, title, body, status, error)
        else:
            self._db.add_notification_history(channel_id, event_type, title, body, status, error)
    
    def get_notification_history(self, tenant_id: str = "default", limit: int = 100) -> list:
        """Get notification history"""
        if USE_POSTGRES:
            return self._db.get_notification_history(tenant_id, limit)
        else:
            return self._db.get_notification_history(tenant_id, limit)
    
    # ==================== Direct DB Access (for methods not in factory) ====================
    
    @property
    def raw_db(self):
        """Get direct access to underlying database manager"""
        return self._db


# Singleton instance
_db_factory: Optional[DatabaseFactory] = None


def get_database() -> DatabaseFactory:
    """Get or create the database factory singleton"""
    global _db_factory
    if _db_factory is None:
        _db_factory = DatabaseFactory()
        if USE_POSTGRES:
            _db_factory.initialize()
    return _db_factory


# For backwards compatibility - expose DatabaseManager-like interface
def get_db_manager():
    """Get database manager (backwards compatible)"""
    return get_database()
