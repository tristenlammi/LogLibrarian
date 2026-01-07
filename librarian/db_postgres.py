"""
PostgreSQL + TimescaleDB Database Manager

This module provides a SYNCHRONOUS PostgreSQL database layer with TimescaleDB
support for efficient time-series data storage and querying.

Phase 1 Migration: Fully synchronous using psycopg2 connection pooling.
No async/await - compatible with all FastAPI/threading contexts.

Environment Variables:
    DATABASE_URL: PostgreSQL connection string (required for PostgreSQL mode)
    USE_TIMESCALE: Enable TimescaleDB hypertables (default: true)
"""

import os
import json
import secrets
import hashlib
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values

from db_connection_pool import get_pool, ConnectionPool


# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/loglibrarian")
USE_TIMESCALE = os.getenv("USE_TIMESCALE", "true").lower() == "true"


class PostgresDatabaseManager:
    """
    Synchronous PostgreSQL database manager with TimescaleDB support.
    
    Provides the same interface as the SQLite DatabaseManager but uses
    PostgreSQL for better scalability and TimescaleDB for optimized
    time-series queries.
    
    Uses thread-safe connection pooling via psycopg2.pool.ThreadedConnectionPool.
    All methods are synchronous - no async/await needed.
    """
    
    def __init__(self):
        self._pool: Optional[ConnectionPool] = None
        self._initialized = False
        
    def initialize(self):
        """Initialize the database connection pool and schema"""
        if self._initialized:
            return
            
        print(f"Connecting to PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
        
        # Get or create the connection pool
        self._pool = get_pool()
        self._pool.initialize()
        
        # Initialize schema
        self._init_schema()
        self._initialized = True
        print(f"PostgreSQL initialized with connection pool")
        
    def close(self):
        """Close the connection pool"""
        if self._pool:
            self._pool.close()
            self._initialized = False
            print("PostgreSQL connection pool closed")
    
    @property
    def pool(self) -> ConnectionPool:
        """Get the connection pool, initializing if needed"""
        if self._pool is None:
            self._pool = get_pool()
            self._pool.initialize()
        return self._pool
    
    def _init_schema(self):
        """Initialize database schema with TimescaleDB hypertables"""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                # Enable TimescaleDB extension if available
                if USE_TIMESCALE:
                    try:
                        cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
                        conn.commit()
                        print("✓ TimescaleDB extension enabled")
                    except Exception as e:
                        conn.rollback()
                        print(f"⚠ TimescaleDB extension not available: {e}")
                
                # Create agents table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agents (
                        agent_id TEXT PRIMARY KEY,
                        hostname TEXT NOT NULL,
                        status TEXT NOT NULL,
                        public_ip TEXT DEFAULT '',
                        display_name TEXT DEFAULT '',
                        first_seen TIMESTAMPTZ NOT NULL,
                        last_seen TIMESTAMPTZ NOT NULL,
                        enabled BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        connection_address TEXT DEFAULT '',
                        os TEXT DEFAULT '',
                        system_info JSONB,
                        uptime_seconds INTEGER DEFAULT 0,
                        auth_token_hash TEXT,
                        tags TEXT DEFAULT '',
                        uptime_window TEXT DEFAULT '24h'
                    )
                """)
                
                # Add missing columns to existing agents table
                for col_sql in [
                    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS connection_address TEXT DEFAULT ''",
                    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS os TEXT DEFAULT ''",
                    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS system_info JSONB",
                    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS uptime_seconds INTEGER DEFAULT 0",
                    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS auth_token_hash TEXT",
                    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT ''",
                    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS uptime_window TEXT DEFAULT '24h'"
                ]:
                    try:
                        cur.execute(col_sql)
                    except Exception:
                        pass  # Column already exists
                
                conn.commit()
                
                # Create metrics table (will be converted to hypertable)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS metrics (
                        id BIGSERIAL,
                        agent_id TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        cpu_percent REAL NOT NULL,
                        ram_percent REAL NOT NULL,
                        net_up REAL DEFAULT 0.0,
                        net_down REAL DEFAULT 0.0,
                        disk_read REAL DEFAULT 0.0,
                        disk_write REAL DEFAULT 0.0,
                        ping REAL DEFAULT 0.0,
                        cpu_temp REAL DEFAULT 0.0,
                        load_avg REAL DEFAULT 0.0,
                        disk_json JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (id, timestamp)
                    )
                """)
                conn.commit()
            
                # Convert metrics to hypertable if TimescaleDB is enabled
                if USE_TIMESCALE:
                    try:
                        # Check if already a hypertable
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT 1 FROM timescaledb_information.hypertables 
                                WHERE hypertable_name = 'metrics'
                            )
                        """)
                        is_hypertable = cur.fetchone()[0]
                        
                        if not is_hypertable:
                            cur.execute("""
                                SELECT create_hypertable('metrics', 'timestamp',
                                    chunk_time_interval => INTERVAL '1 day',
                                    if_not_exists => TRUE,
                                    migrate_data => TRUE
                                )
                            """)
                            print("✓ Metrics table converted to TimescaleDB hypertable")
                        else:
                            print("✓ Metrics hypertable already exists")
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        print(f"⚠ Could not create hypertable: {e}")
                
                # Create optimized indexes for time-range queries
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_metrics_agent_time 
                    ON metrics (agent_id, timestamp DESC)
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_metrics_time 
                    ON metrics (timestamp DESC)
                """)
                
                # Create process_snapshots table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS process_snapshots (
                        id BIGSERIAL PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        json_data JSONB NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_process_agent_time 
                    ON process_snapshots (agent_id, timestamp DESC)
                """)
                
                # Create alert_rules table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS alert_rules (
                        agent_id TEXT PRIMARY KEY,
                        monitor_uptime BOOLEAN DEFAULT TRUE,
                        cpu_percent_threshold REAL DEFAULT NULL,
                        ram_percent_threshold REAL DEFAULT NULL,
                        disk_free_percent_threshold REAL DEFAULT NULL,
                        cpu_temp_threshold REAL DEFAULT NULL,
                        network_bandwidth_mbps_threshold REAL DEFAULT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                # Create active_alerts table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS active_alerts (
                        id BIGSERIAL PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        alert_type TEXT NOT NULL,
                        threshold_value REAL,
                        current_value REAL,
                        message TEXT NOT NULL,
                        severity TEXT DEFAULT 'warning',
                        triggered_at TIMESTAMPTZ NOT NULL,
                        resolved_at TIMESTAMPTZ DEFAULT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_alert_agent_active 
                    ON active_alerts (agent_id, is_active)
                """)
                
                # Create agent_log_settings table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agent_log_settings (
                        agent_id TEXT PRIMARY KEY,
                        logging_enabled BOOLEAN DEFAULT TRUE,
                        log_level_threshold TEXT DEFAULT 'ERROR',
                        log_retention_days INTEGER DEFAULT 7,
                        watch_docker_containers BOOLEAN DEFAULT FALSE,
                        watch_system_logs BOOLEAN DEFAULT TRUE,
                        watch_security_logs BOOLEAN DEFAULT TRUE,
                        troubleshooting_mode BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                # Create raw_logs table (also a hypertable candidate)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS raw_logs (
                        id BIGSERIAL,
                        agent_id TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        severity TEXT NOT NULL,
                        source TEXT NOT NULL,
                        message TEXT NOT NULL,
                        metadata JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (id, timestamp)
                    )
                """)
                conn.commit()
                
                # Convert raw_logs to hypertable
                if USE_TIMESCALE:
                    try:
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT 1 FROM timescaledb_information.hypertables 
                                WHERE hypertable_name = 'raw_logs'
                            )
                        """)
                        is_hypertable = cur.fetchone()[0]
                        
                        if not is_hypertable:
                            cur.execute("""
                                SELECT create_hypertable('raw_logs', 'timestamp',
                                    chunk_time_interval => INTERVAL '1 day',
                                    if_not_exists => TRUE,
                                    migrate_data => TRUE
                                )
                            """)
                            print("✓ Raw_logs table converted to TimescaleDB hypertable")
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        print(f"⚠ Could not create raw_logs hypertable: {e}")
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_raw_logs_agent_time 
                    ON raw_logs (agent_id, timestamp DESC)
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_raw_logs_severity 
                    ON raw_logs (agent_id, severity)
                """)
                
                # Create system_settings table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS system_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        description TEXT,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                # Initialize default settings
                cur.execute("""
                    INSERT INTO system_settings (key, value, description)
                    VALUES ('public_app_url', '', 'Public URL for agent connections')
                    ON CONFLICT (key) DO NOTHING
                """)
                
                # Initialize AI settings (disabled by default)
                cur.execute("""
                    INSERT INTO system_settings (key, value, description)
                    VALUES 
                        ('ai_enabled', 'false', 'Whether Librarian AI is enabled'),
                        ('ai_backend', '', 'AI acceleration backend: cuda, rocm, sycl, or cpu'),
                        ('ai_dependencies_installed', 'false', 'Whether AI dependencies are installed'),
                        ('ai_current_model', '', 'Currently selected AI model ID'),
                        ('ai_model_loaded', 'false', 'Whether the AI model is loaded in memory')
                    ON CONFLICT (key) DO NOTHING
                """)
                
                # Create templates tables for log deduplication
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS templates_metadata (
                        template_id TEXT PRIMARY KEY,
                        template_text TEXT NOT NULL,
                        first_seen TIMESTAMPTZ NOT NULL,
                        last_seen TIMESTAMPTZ NOT NULL,
                        occurrence_count INTEGER DEFAULT 1
                    )
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS log_occurrences (
                        id BIGSERIAL,
                        template_id TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        variables JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (id, timestamp)
                    )
                """)
                conn.commit()
                
                if USE_TIMESCALE:
                    try:
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT 1 FROM timescaledb_information.hypertables 
                                WHERE hypertable_name = 'log_occurrences'
                            )
                        """)
                        is_hypertable = cur.fetchone()[0]
                        
                        if not is_hypertable:
                            cur.execute("""
                                SELECT create_hypertable('log_occurrences', 'timestamp',
                                    chunk_time_interval => INTERVAL '1 day',
                                    if_not_exists => TRUE,
                                    migrate_data => TRUE
                                )
                            """)
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        print(f"⚠ Could not create log_occurrences hypertable: {e}")
                
                # Create agent_heartbeats table for historical uptime tracking
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agent_heartbeats (
                        id BIGSERIAL PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        status TEXT NOT NULL DEFAULT 'online',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_heartbeats_agent_timestamp 
                    ON agent_heartbeats(agent_id, timestamp DESC)
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp 
                    ON agent_heartbeats(timestamp)
                """)
                
                # ==================== Phase 2: Notification Channels ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS notification_channels (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        name TEXT NOT NULL,
                        channel_type TEXT NOT NULL,
                        url TEXT NOT NULL,
                        events JSONB DEFAULT '["all"]',
                        enabled BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notification_channels_tenant 
                    ON notification_channels(tenant_id)
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS notification_history (
                        id SERIAL PRIMARY KEY,
                        channel_id INTEGER REFERENCES notification_channels(id) ON DELETE CASCADE,
                        event_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        body TEXT,
                        status TEXT NOT NULL,
                        error TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notification_history_channel 
                    ON notification_history(channel_id, created_at DESC)
                """)
                
                # ==================== Phase 2: Alert Rules V2 ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS alert_rules_v2 (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        name TEXT NOT NULL,
                        description TEXT,
                        scope TEXT NOT NULL,
                        target_id TEXT,
                        metric TEXT NOT NULL,
                        operator TEXT NOT NULL,
                        threshold TEXT NOT NULL,
                        channels JSONB DEFAULT '[]',
                        cooldown_minutes INTEGER DEFAULT 5,
                        enabled BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        profile_id TEXT,
                        profile_agents JSONB DEFAULT '[]',
                        profile_bookmarks JSONB DEFAULT '[]'
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_alert_rules_v2_tenant_scope 
                    ON alert_rules_v2(tenant_id, scope)
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS alert_rule_overrides (
                        id SERIAL PRIMARY KEY,
                        rule_id INTEGER REFERENCES alert_rules_v2(id) ON DELETE CASCADE,
                        target_type TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        override_type TEXT NOT NULL,
                        modified_threshold TEXT,
                        modified_channels JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(rule_id, target_type, target_id)
                    )
                """)
                
                # ==================== Phase 2: Monitor Groups & Bookmarks ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS monitor_groups (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        name TEXT NOT NULL,
                        weight INTEGER DEFAULT 0,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_monitor_groups_tenant 
                    ON monitor_groups(tenant_id)
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bookmarks (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        group_id TEXT REFERENCES monitor_groups(id) ON DELETE SET NULL,
                        name TEXT NOT NULL,
                        type TEXT NOT NULL,
                        target TEXT NOT NULL,
                        port INTEGER,
                        interval_seconds INTEGER DEFAULT 60,
                        timeout_seconds INTEGER DEFAULT 10,
                        max_retries INTEGER DEFAULT 1,
                        retry_interval INTEGER DEFAULT 30,
                        resend_notification INTEGER DEFAULT 0,
                        upside_down BOOLEAN DEFAULT FALSE,
                        active BOOLEAN DEFAULT TRUE,
                        tags TEXT,
                        description TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_bookmarks_tenant 
                    ON bookmarks(tenant_id)
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_bookmarks_group 
                    ON bookmarks(group_id)
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bookmark_checks (
                        id BIGSERIAL,
                        bookmark_id TEXT NOT NULL,
                        status SMALLINT NOT NULL,
                        latency_ms INTEGER,
                        message TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (id, created_at)
                    )
                """)
                conn.commit()
                
                # Convert bookmark_checks to hypertable
                if USE_TIMESCALE:
                    try:
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT 1 FROM timescaledb_information.hypertables 
                                WHERE hypertable_name = 'bookmark_checks'
                            )
                        """)
                        is_hypertable = cur.fetchone()[0]
                        
                        if not is_hypertable:
                            cur.execute("""
                                SELECT create_hypertable('bookmark_checks', 'created_at',
                                    chunk_time_interval => INTERVAL '1 day',
                                    if_not_exists => TRUE,
                                    migrate_data => TRUE
                                )
                            """)
                            print("✓ Bookmark_checks table converted to TimescaleDB hypertable")
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        print(f"⚠ Could not create bookmark_checks hypertable: {e}")
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_bookmark_checks_bookmark 
                    ON bookmark_checks(bookmark_id, created_at DESC)
                """)
                
                # ==================== Phase 2: AI Reports ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_reports (
                        id SERIAL PRIMARY KEY,
                        type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        agent_id TEXT,
                        metadata JSONB DEFAULT '{}',
                        is_read BOOLEAN DEFAULT FALSE,
                        feedback TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ai_reports_type 
                    ON ai_reports(type, created_at DESC)
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ai_reports_agent 
                    ON ai_reports(agent_id)
                """)
                
                # ==================== Phase 2: AI Model Cache ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_model_cache (
                        model_id TEXT PRIMARY KEY,
                        file_path TEXT NOT NULL,
                        file_hash TEXT DEFAULT '',
                        file_size_mb REAL DEFAULT 0,
                        is_downloaded BOOLEAN DEFAULT FALSE,
                        download_progress REAL DEFAULT 0,
                        downloaded_at TIMESTAMPTZ,
                        last_used_at TIMESTAMPTZ
                    )
                """)
                
                # ==================== Phase 2: AI Conversations ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL DEFAULT 'New Chat',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_messages (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ai_messages_conversation 
                    ON ai_messages(conversation_id, created_at ASC)
                """)
                
                # ==================== Phase 2: Report Profiles ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS report_profiles (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT 'default',
                        name TEXT NOT NULL,
                        description TEXT,
                        frequency TEXT DEFAULT 'MONTHLY',
                        sla_target REAL DEFAULT 99.9,
                        schedule_hour INTEGER DEFAULT 7,
                        recipient_emails JSONB DEFAULT '[]',
                        monitor_scope_tags JSONB DEFAULT '[]',
                        monitor_scope_ids JSONB DEFAULT '[]',
                        scribe_scope_tags JSONB DEFAULT '[]',
                        scribe_scope_ids JSONB DEFAULT '[]',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_report_profiles_tenant 
                    ON report_profiles(tenant_id)
                """)
                
                # ==================== Sessions Table (Database-backed auth) ====================
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        username TEXT NOT NULL,
                        is_admin BOOLEAN DEFAULT FALSE,
                        role TEXT DEFAULT 'user',
                        assigned_profile_id TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        expires_at TIMESTAMPTZ NOT NULL
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_expires 
                    ON sessions(expires_at)
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_user 
                    ON sessions(user_id)
                """)
                
                conn.commit()
                
                # ==================== Phase 3: TimescaleDB Optimizations ====================
                if USE_TIMESCALE:
                    self._setup_continuous_aggregates(cur, conn)
                    self._setup_retention_policies(cur, conn)
                    self._setup_compression_policies(cur, conn)
                
                print("✓ PostgreSQL schema initialized")
    
    def _setup_continuous_aggregates(self, cur, conn):
        """Create continuous aggregates for efficient time-range queries"""
        try:
            # Check if continuous aggregates already exist
            cur.execute("""
                SELECT matviewname FROM pg_matviews 
                WHERE matviewname IN ('metrics_1min', 'metrics_15min', 'metrics_1hour')
            """)
            existing = {row[0] for row in cur.fetchall()}
            
            # 1-minute aggregates (for 1-24 hour views)
            if 'metrics_1min' not in existing:
                print("  Creating metrics_1min continuous aggregate...")
                cur.execute("""
                    CREATE MATERIALIZED VIEW metrics_1min
                    WITH (timescaledb.continuous) AS
                    SELECT
                        time_bucket('1 minute', timestamp) AS bucket,
                        agent_id,
                        AVG(cpu_percent) AS cpu_percent,
                        AVG(ram_percent) AS ram_percent,
                        AVG(net_up) AS net_up,
                        AVG(net_down) AS net_down,
                        AVG(disk_read) AS disk_read,
                        AVG(disk_write) AS disk_write,
                        AVG(ping) AS ping,
                        AVG(cpu_temp) AS cpu_temp,
                        AVG(load_avg) AS load_avg,
                        MAX(cpu_percent) AS cpu_max,
                        MAX(ram_percent) AS ram_max,
                        MIN(cpu_percent) AS cpu_min,
                        MIN(ram_percent) AS ram_min,
                        COUNT(*) AS sample_count
                    FROM metrics
                    GROUP BY bucket, agent_id
                    WITH NO DATA
                """)
                conn.commit()
                
                # Add refresh policy for 1-minute aggregates
                cur.execute("""
                    SELECT add_continuous_aggregate_policy('metrics_1min',
                        start_offset => INTERVAL '1 hour',
                        end_offset => INTERVAL '1 minute',
                        schedule_interval => INTERVAL '1 minute',
                        if_not_exists => TRUE
                    )
                """)
                conn.commit()
                print("  ✓ metrics_1min created with refresh policy")
            
            # 15-minute aggregates (for 1-7 day views)
            if 'metrics_15min' not in existing:
                print("  Creating metrics_15min continuous aggregate...")
                cur.execute("""
                    CREATE MATERIALIZED VIEW metrics_15min
                    WITH (timescaledb.continuous) AS
                    SELECT
                        time_bucket('15 minutes', timestamp) AS bucket,
                        agent_id,
                        AVG(cpu_percent) AS cpu_percent,
                        AVG(ram_percent) AS ram_percent,
                        AVG(net_up) AS net_up,
                        AVG(net_down) AS net_down,
                        AVG(disk_read) AS disk_read,
                        AVG(disk_write) AS disk_write,
                        AVG(ping) AS ping,
                        AVG(cpu_temp) AS cpu_temp,
                        AVG(load_avg) AS load_avg,
                        MAX(cpu_percent) AS cpu_max,
                        MAX(ram_percent) AS ram_max,
                        COUNT(*) AS sample_count
                    FROM metrics
                    GROUP BY bucket, agent_id
                    WITH NO DATA
                """)
                conn.commit()
                
                cur.execute("""
                    SELECT add_continuous_aggregate_policy('metrics_15min',
                        start_offset => INTERVAL '2 hours',
                        end_offset => INTERVAL '15 minutes',
                        schedule_interval => INTERVAL '15 minutes',
                        if_not_exists => TRUE
                    )
                """)
                conn.commit()
                print("  ✓ metrics_15min created with refresh policy")
            
            # 1-hour aggregates (for 7+ day views)
            if 'metrics_1hour' not in existing:
                print("  Creating metrics_1hour continuous aggregate...")
                cur.execute("""
                    CREATE MATERIALIZED VIEW metrics_1hour
                    WITH (timescaledb.continuous) AS
                    SELECT
                        time_bucket('1 hour', timestamp) AS bucket,
                        agent_id,
                        AVG(cpu_percent) AS cpu_percent,
                        AVG(ram_percent) AS ram_percent,
                        AVG(net_up) AS net_up,
                        AVG(net_down) AS net_down,
                        AVG(disk_read) AS disk_read,
                        AVG(disk_write) AS disk_write,
                        AVG(ping) AS ping,
                        AVG(cpu_temp) AS cpu_temp,
                        AVG(load_avg) AS load_avg,
                        MAX(cpu_percent) AS cpu_max,
                        MAX(ram_percent) AS ram_max,
                        COUNT(*) AS sample_count
                    FROM metrics
                    GROUP BY bucket, agent_id
                    WITH NO DATA
                """)
                conn.commit()
                
                cur.execute("""
                    SELECT add_continuous_aggregate_policy('metrics_1hour',
                        start_offset => INTERVAL '4 hours',
                        end_offset => INTERVAL '1 hour',
                        schedule_interval => INTERVAL '1 hour',
                        if_not_exists => TRUE
                    )
                """)
                conn.commit()
                print("  ✓ metrics_1hour created with refresh policy")
            
            print("✓ Continuous aggregates configured")
        except Exception as e:
            conn.rollback()
            print(f"⚠ Could not create continuous aggregates: {e}")
    
    def _setup_retention_policies(self, cur, conn):
        """Configure automatic data retention via TimescaleDB policies"""
        try:
            # Raw metrics: 48 hours (high resolution)
            cur.execute("""
                SELECT add_retention_policy('metrics', INTERVAL '48 hours', if_not_exists => TRUE)
            """)
            
            # Raw logs: 7 days
            cur.execute("""
                SELECT add_retention_policy('raw_logs', INTERVAL '7 days', if_not_exists => TRUE)
            """)
            
            # Log occurrences: 30 days
            try:
                cur.execute("""
                    SELECT add_retention_policy('log_occurrences', INTERVAL '30 days', if_not_exists => TRUE)
                """)
            except Exception:
                pass  # Table might not be a hypertable
            
            # Bookmark checks: 30 days
            try:
                cur.execute("""
                    SELECT add_retention_policy('bookmark_checks', INTERVAL '30 days', if_not_exists => TRUE)
                """)
            except Exception:
                pass  # Table might not be a hypertable
            
            conn.commit()
            print("✓ Retention policies configured (48hr metrics, 7d logs, 30d checks)")
        except Exception as e:
            conn.rollback()
            print(f"⚠ Could not configure retention policies: {e}")
    
    def _setup_compression_policies(self, cur, conn):
        """Configure automatic compression for older data"""
        try:
            # Enable compression on metrics table
            cur.execute("""
                ALTER TABLE metrics SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'agent_id',
                    timescaledb.compress_orderby = 'timestamp DESC'
                )
            """)
            conn.commit()
            
            # Add compression policy (compress after 7 days)
            cur.execute("""
                SELECT add_compression_policy('metrics', INTERVAL '7 days', if_not_exists => TRUE)
            """)
            conn.commit()
            
            # Enable compression on raw_logs table
            cur.execute("""
                ALTER TABLE raw_logs SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'agent_id',
                    timescaledb.compress_orderby = 'timestamp DESC'
                )
            """)
            conn.commit()
            
            cur.execute("""
                SELECT add_compression_policy('raw_logs', INTERVAL '3 days', if_not_exists => TRUE)
            """)
            conn.commit()
            
            print("✓ Compression policies configured (7d metrics, 3d logs)")
        except Exception as e:
            conn.rollback()
            print(f"⚠ Could not configure compression policies: {e}")
    
    # ==================== Agent Methods ====================
    
    def upsert_agent(self, agent_id: str, hostname: str, status: str, 
                     last_seen: datetime = None, public_ip: str = "", 
                     connection_address: str = None, os: str = "") -> None:
        """Upsert agent information using connection pool"""
        if last_seen is None:
            last_seen = datetime.now()
        if connection_address is None:
            connection_address = ""
        
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    # Check if this is an offline -> online transition
                    cur.execute("SELECT status FROM agents WHERE agent_id = %s", (agent_id,))
                    row = cur.fetchone()
                    was_offline = row and row[0] == 'offline'
                    is_new = row is None
                    
                    if status == 'online' and (was_offline or is_new):
                        # Reset uptime tracking when agent comes online
                        cur.execute("""
                            INSERT INTO agents (agent_id, hostname, status, public_ip, os, first_seen, last_seen, connection_address, created_at, uptime_seconds)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), 0)
                            ON CONFLICT (agent_id) DO UPDATE SET
                                hostname = EXCLUDED.hostname,
                                status = EXCLUDED.status,
                                public_ip = EXCLUDED.public_ip,
                                os = EXCLUDED.os,
                                last_seen = EXCLUDED.last_seen,
                                connection_address = EXCLUDED.connection_address,
                                uptime_seconds = 0
                        """, (agent_id, hostname, status, public_ip, os, last_seen, last_seen, connection_address))
                    else:
                        cur.execute("""
                            INSERT INTO agents (agent_id, hostname, status, public_ip, os, first_seen, last_seen, connection_address)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (agent_id) DO UPDATE SET
                                hostname = EXCLUDED.hostname,
                                status = EXCLUDED.status,
                                public_ip = EXCLUDED.public_ip,
                                os = EXCLUDED.os,
                                last_seen = EXCLUDED.last_seen,
                                connection_address = EXCLUDED.connection_address
                        """, (agent_id, hostname, status, public_ip, os, last_seen, last_seen, connection_address))
        except Exception as e:
            print(f"Error upserting agent: {e}")
    
    def get_all_agents(self) -> List[dict]:
        """Get all registered agents with calculated uptime percentage"""
        try:
            rows = self.pool.fetchall("""
                SELECT agent_id, hostname, status, public_ip, first_seen, 
                       last_seen, enabled, display_name, system_info,
                       connection_address, os, uptime_seconds, tags, uptime_window
                FROM agents
                ORDER BY last_seen DESC
            """)
            
            result = []
            now = datetime.utcnow()
            
            # Map uptime_window values to timedelta
            window_to_timedelta = {
                'daily': timedelta(hours=24),
                'weekly': timedelta(days=7),
                'monthly': timedelta(days=30),
                'quarterly': timedelta(days=90),
                'yearly': timedelta(days=365)
            }
            
            for row in rows:
                system_info = None
                if row['system_info']:
                    system_info = json.loads(row['system_info']) if isinstance(row['system_info'], str) else row['system_info']
                
                # Get uptime window setting (default to monthly)
                uptime_window = row.get('uptime_window') or 'monthly'
                window_delta = window_to_timedelta.get(uptime_window, timedelta(days=30))
                
                # Calculate uptime percentage based on the configured window
                start_date = now - window_delta
                uptime_data = self.calculate_agent_uptime(
                    agent_id=row['agent_id'],
                    start_date=start_date,
                    end_date=now,
                    heartbeat_ttl_seconds=120
                )
                uptime_percentage = uptime_data.get('uptime_percentage')
                
                result.append({
                    "agent_id": row['agent_id'],
                    "hostname": row['hostname'],
                    "status": row['status'],
                    "public_ip": row['public_ip'] or '',
                    "first_seen": row['first_seen'].isoformat() if row['first_seen'] else None,
                    "last_seen": row['last_seen'].isoformat() if row['last_seen'] else None,
                    "enabled": row['enabled'],
                    "display_name": row['display_name'] or '',
                    "system_info": system_info,
                    "connection_address": row['connection_address'] or '',
                    "os": row['os'] or '',
                    "uptime_seconds": row['uptime_seconds'] or 0,
                    "tags": row.get('tags', '') or '',
                    "uptime_window": uptime_window,
                    "uptime_percentage": round(uptime_percentage, 1) if uptime_percentage is not None else None
                })
            return result
        except Exception as e:
            print(f"Error getting all agents: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_agents(self, tenant_id: str = None) -> List[dict]:
        """Alias for get_all_agents, accepts tenant_id for compatibility"""
        return self.get_all_agents()
    
    def delete_agent(self, agent_id: str) -> None:
        """Delete an agent and all its associated data"""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM process_snapshots WHERE agent_id = %s", (agent_id,))
                cur.execute("DELETE FROM metrics WHERE agent_id = %s", (agent_id,))
                cur.execute("DELETE FROM raw_logs WHERE agent_id = %s", (agent_id,))
                cur.execute("DELETE FROM active_alerts WHERE agent_id = %s", (agent_id,))
                cur.execute("DELETE FROM alert_rules WHERE agent_id = %s", (agent_id,))
                cur.execute("DELETE FROM agent_log_settings WHERE agent_id = %s", (agent_id,))
                cur.execute("DELETE FROM agent_heartbeats WHERE agent_id = %s", (agent_id,))
                cur.execute("DELETE FROM agents WHERE agent_id = %s", (agent_id,))
                print(f"Deleted agent {agent_id} and all associated data")
    
    def disable_agent(self, agent_id: str) -> None:
        """Disable an agent"""
        self.pool.execute("""
            UPDATE agents SET enabled = FALSE, status = 'disabled' 
            WHERE agent_id = %s
        """, (agent_id,))
        print(f"Disabled agent {agent_id}")
    
    def enable_agent(self, agent_id: str) -> None:
        """Enable an agent"""
        self.pool.execute("""
            UPDATE agents SET enabled = TRUE, status = 'offline' 
            WHERE agent_id = %s
        """, (agent_id,))
        print(f"Enabled agent {agent_id}")
    
    def update_agent_display_name(self, agent_id: str, display_name: str) -> None:
        """Update the display name of an agent"""
        self.pool.execute("""
            UPDATE agents SET display_name = %s WHERE agent_id = %s
        """, (display_name, agent_id))
        print(f"Updated display name for agent {agent_id}")
    
    def update_agent_system_info(self, agent_id: str, system_info: dict) -> None:
        """Update system info for an agent, including extracting OS to dedicated column"""
        # Extract OS from system_info for the dedicated column
        os_value = system_info.get('os', '') if system_info else ''
        print(f"[DEBUG] update_agent_system_info: agent_id={agent_id}, os_value={os_value}")
        self.pool.execute("""
            UPDATE agents SET system_info = %s, os = %s WHERE agent_id = %s
        """, (json.dumps(system_info), os_value, agent_id))
        print(f"[DEBUG] Updated agent {agent_id} with OS: {os_value}")
    
    def get_agent_system_info(self, agent_id: str) -> Optional[dict]:
        """Get system info for an agent"""
        row = self.pool.fetchone("""
            SELECT system_info FROM agents WHERE agent_id = %s
        """, (agent_id,))
        if row and row['system_info']:
            return json.loads(row['system_info']) if isinstance(row['system_info'], str) else row['system_info']
        return None
    
    def update_agent_tags(self, agent_id: str, tags: str) -> None:
        """Update tags for an agent"""
        self.pool.execute("""
            UPDATE agents SET tags = %s WHERE agent_id = %s
        """, (tags, agent_id))
    
    # ==================== Agent Token Methods ====================
    
    def generate_agent_token(self, agent_id: str) -> str:
        """
        Generate a new authentication token for an agent.
        
        Returns the plaintext token (to be sent to the agent).
        Stores only the hashed token in the database.
        """
        # Generate a secure random token (32 bytes = 64 hex chars)
        token = secrets.token_hex(32)
        
        # Hash the token for storage (we never store plaintext tokens)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        self.pool.execute(
            "UPDATE agents SET auth_token_hash = %s WHERE agent_id = %s",
            (token_hash, agent_id)
        )
        print(f"🔐 Generated auth token for agent {agent_id}")
        return token
    
    def validate_agent_token(self, agent_id: str, token: str) -> Tuple[bool, str]:
        """
        Validate an agent's authentication token.
        
        Returns:
            Tuple of (is_valid, reason)
            - (True, "valid") if token is valid
            - (True, "new_agent") if agent doesn't exist yet (first registration)
            - (True, "no_token") if agent exists but has no token (legacy agent)
            - (False, "invalid_token") if token doesn't match
        """
        row = self.pool.fetchone(
            "SELECT auth_token_hash FROM agents WHERE agent_id = %s",
            (agent_id,)
        )
        
        # Agent doesn't exist yet - this is first registration
        if row is None:
            return (True, "new_agent")
        
        stored_hash = row['auth_token_hash']
        
        # Agent exists but no token set yet (legacy or first registration)
        if not stored_hash:
            return (True, "no_token")
        
        # Agent has a token - validate it
        if not token:
            return (False, "missing_token")
        
        provided_hash = hashlib.sha256(token.encode()).hexdigest()
        
        if provided_hash == stored_hash:
            return (True, "valid")
        else:
            return (False, "invalid_token")
    
    def get_agent_has_token(self, agent_id: str) -> bool:
        """Check if an agent has an auth token set."""
        row = self.pool.fetchone(
            "SELECT auth_token_hash FROM agents WHERE agent_id = %s",
            (agent_id,)
        )
        return row is not None and row['auth_token_hash'] is not None and row['auth_token_hash'] != ''
    
    # ==================== Agent Heartbeat Methods ====================
    
    def record_agent_heartbeat(self, agent_id: str, status: str = 'online') -> None:
        """Record a heartbeat for an agent for historical uptime tracking"""
        self.pool.execute("""
            INSERT INTO agent_heartbeats (agent_id, timestamp, status)
            VALUES (%s, NOW(), %s)
        """, (agent_id, status))
    
    def record_bulk_heartbeats(self, agent_ids: list, status: str = 'online') -> int:
        """Record heartbeats for multiple agents at once (more efficient)"""
        if not agent_ids:
            return 0
        
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO agent_heartbeats (agent_id, timestamp, status)
                    VALUES %s
                """, [(agent_id, datetime.now(), status) for agent_id in agent_ids])
        return len(agent_ids)
    
    def calculate_agent_uptime(self, agent_id: str, start_date: datetime, 
                               end_date: datetime = None, heartbeat_ttl_seconds: int = 120) -> dict:
        """
        Calculate historical uptime for an agent based on heartbeat records.
        
        Implements "Smart Start" logic:
        - Adjusted_Start = MAX(Report_Start_Date, Agent_Created_At)
        - Total_Possible_Seconds = (Report_End_Date - Adjusted_Start).total_seconds()
        - Percentage = (Uptime_Seconds / Total_Possible_Seconds) * 100, capped at 100%
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        # Normalize all datetimes to naive (remove timezone info for consistent comparison)
        if hasattr(start_date, 'tzinfo') and start_date.tzinfo:
            start_date = start_date.replace(tzinfo=None)
        if hasattr(end_date, 'tzinfo') and end_date.tzinfo:
            end_date = end_date.replace(tzinfo=None)
        
        # Step 1: Get the agent's creation timestamp (first_seen)
        row = self.pool.fetchone("""
            SELECT first_seen FROM agents WHERE agent_id = %s
        """, (agent_id,))
        
        if not row or not row['first_seen']:
            return {
                "uptime_percentage": None,
                "total_seconds": 0,
                "uptime_seconds": 0,
                "downtime_seconds": 0,
                "heartbeat_count": 0,
                "status": "unknown_agent"
            }
        
        # Parse first_seen timestamp
        agent_created = row['first_seen']
        if isinstance(agent_created, str):
            agent_created = datetime.fromisoformat(agent_created.replace('Z', '').split('+')[0])
        if hasattr(agent_created, 'tzinfo') and agent_created.tzinfo:
            agent_created = agent_created.replace(tzinfo=None)
        
        # Step 2: Agent created AFTER report end date = N/A
        if agent_created >= end_date:
            return {
                "uptime_percentage": None,
                "total_seconds": 0,
                "uptime_seconds": 0,
                "downtime_seconds": 0,
                "heartbeat_count": 0,
                "status": "not_yet_created",
                "agent_created": agent_created.isoformat()
            }
        
        # Step 3: SMART START - Adjusted_Start = MAX(Report_Start_Date, Agent_Created_At)
        adjusted_start = max(start_date, agent_created)
        total_possible_seconds = (end_date - adjusted_start).total_seconds()
        
        # If period is too short (less than 1 minute), return N/A
        if total_possible_seconds < 60:
            return {
                "uptime_percentage": None,
                "total_seconds": total_possible_seconds,
                "uptime_seconds": 0,
                "downtime_seconds": 0,
                "heartbeat_count": 0,
                "status": "period_too_short",
                "adjusted_start": adjusted_start.isoformat()
            }
        
        # Step 4: Get first heartbeat ever for this agent
        first_hb_row = self.pool.fetchone("""
            SELECT MIN(timestamp) as min_ts FROM agent_heartbeats WHERE agent_id = %s
        """, (agent_id,))
        
        if not first_hb_row or not first_hb_row['min_ts']:
            return {
                "uptime_percentage": 0.0,
                "total_seconds": total_possible_seconds,
                "uptime_seconds": 0,
                "downtime_seconds": total_possible_seconds,
                "heartbeat_count": 0,
                "status": "no_heartbeats_ever",
                "adjusted_start": adjusted_start.isoformat()
            }
        
        first_heartbeat_time = first_hb_row['min_ts']
        if isinstance(first_heartbeat_time, str):
            first_heartbeat_time = datetime.fromisoformat(first_heartbeat_time.replace('Z', '').split('+')[0])
        if hasattr(first_heartbeat_time, 'tzinfo') and first_heartbeat_time.tzinfo:
            first_heartbeat_time = first_heartbeat_time.replace(tzinfo=None)
        
        # Measurement can only start when we have heartbeat data
        measurement_start = max(adjusted_start, first_heartbeat_time)
        total_possible_seconds = (end_date - measurement_start).total_seconds()
        
        if total_possible_seconds < 60:
            return {
                "uptime_percentage": 100.0,
                "total_seconds": 0,
                "uptime_seconds": 0,
                "downtime_seconds": 0,
                "heartbeat_count": 0,
                "status": "insufficient_measurement_period",
                "measurement_start": measurement_start.isoformat()
            }
        
        # Step 5: Get heartbeats within the measurement window
        heartbeats = self.pool.fetchall("""
            SELECT timestamp, status FROM agent_heartbeats
            WHERE agent_id = %s
            AND timestamp >= %s
            AND timestamp <= %s
            ORDER BY timestamp ASC
        """, (agent_id, measurement_start, end_date))
        
        if not heartbeats:
            return {
                "uptime_percentage": 0.0,
                "total_seconds": total_possible_seconds,
                "uptime_seconds": 0,
                "downtime_seconds": total_possible_seconds,
                "heartbeat_count": 0,
                "status": "offline_during_period",
                "measurement_start": measurement_start.isoformat()
            }
        
        # Step 6: Calculate uptime based on heartbeat coverage
        uptime_seconds = 0
        prev_time = measurement_start
        
        for hb in heartbeats:
            hb_time = hb['timestamp']
            if isinstance(hb_time, str):
                hb_time = datetime.fromisoformat(hb_time.replace('Z', '').split('+')[0])
            if hasattr(hb_time, 'tzinfo') and hb_time.tzinfo:
                hb_time = hb_time.replace(tzinfo=None)
            
            gap = (hb_time - prev_time).total_seconds()
            
            if gap <= heartbeat_ttl_seconds:
                uptime_seconds += gap
            else:
                uptime_seconds += heartbeat_ttl_seconds
            
            prev_time = hb_time
        
        # Step 7: Handle time from last heartbeat to end_date
        last_hb_time = heartbeats[-1]['timestamp']
        if isinstance(last_hb_time, str):
            last_hb_time = datetime.fromisoformat(last_hb_time.replace('Z', '').split('+')[0])
        if hasattr(last_hb_time, 'tzinfo') and last_hb_time.tzinfo:
            last_hb_time = last_hb_time.replace(tzinfo=None)
        
        remaining = (end_date - last_hb_time).total_seconds()
        if remaining <= heartbeat_ttl_seconds:
            uptime_seconds += remaining
        else:
            uptime_seconds += heartbeat_ttl_seconds
        
        # Step 8: Calculate percentage with cap at 100%
        uptime_seconds = min(uptime_seconds, total_possible_seconds)
        downtime_seconds = total_possible_seconds - uptime_seconds
        uptime_percentage = (uptime_seconds / total_possible_seconds) * 100
        uptime_percentage = min(uptime_percentage, 100.0)
        
        return {
            "uptime_percentage": round(uptime_percentage, 2),
            "total_seconds": round(total_possible_seconds, 0),
            "uptime_seconds": round(uptime_seconds, 0),
            "downtime_seconds": round(downtime_seconds, 0),
            "heartbeat_count": len(heartbeats),
            "status": "calculated",
            "adjusted_start": adjusted_start.isoformat(),
            "measurement_start": measurement_start.isoformat(),
            "agent_created": agent_created.isoformat()
        }
    
    def cleanup_old_heartbeats(self, days_to_keep: int = 30) -> int:
        """Remove heartbeats older than the specified number of days"""
        cutoff = datetime.now() - timedelta(days=days_to_keep)
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM agent_heartbeats
                    WHERE timestamp < %s
                """, (cutoff,))
                deleted = cur.rowcount
        return deleted
    
    def get_agent_uptime_stats(self, agent_id: str) -> dict:
        """Get uptime statistics for an agent (last 24h, 7d, 30d)"""
        now = datetime.utcnow()
        return {
            "last_24h": self.calculate_agent_uptime(agent_id, now - timedelta(hours=24), now),
            "last_7d": self.calculate_agent_uptime(agent_id, now - timedelta(days=7), now),
            "last_30d": self.calculate_agent_uptime(agent_id, now - timedelta(days=30), now)
        }
    
    # ==================== Metrics Methods ====================
    
    def bulk_insert_metrics(self, agent_id: str, metrics: List[dict], 
                            load_avg: float = 0.0) -> int:
        """
        Bulk insert metrics for an agent.
        
        Args:
            agent_id: Agent identifier
            metrics: List of metric dicts
            load_avg: 15-minute load average
        
        Returns:
            Number of rows inserted
        """
        if not metrics:
            return 0
        
        try:
            # Prepare data for bulk insert
            records = []
            for metric in metrics:
                extra_data = {
                    'disks': metric.get('disks', []),
                    'cpu_name': metric.get('cpu_name', ''),
                    'gpu_percent': metric.get('gpu_percent', 0.0),
                    'gpu_temp': metric.get('gpu_temp', 0.0),
                    'gpu_name': metric.get('gpu_name', ''),
                    'is_vm': metric.get('is_vm', False)
                }
                
                # Parse timestamp
                ts = metric['timestamp']
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                
                records.append((
                    agent_id,
                    ts,
                    metric['cpu_percent'],
                    metric['ram_percent'],
                    metric.get('net_sent_bps', 0.0),
                    metric.get('net_recv_bps', 0.0),
                    metric.get('disk_read_bps', 0.0),
                    metric.get('disk_write_bps', 0.0),
                    metric.get('ping_latency_ms', 0.0),
                    metric.get('cpu_temp', 0.0),
                    load_avg,
                    json.dumps(extra_data)
                ))
            
            # Bulk insert using execute_values
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    execute_values(cur, """
                        INSERT INTO metrics (agent_id, timestamp, cpu_percent, ram_percent,
                            net_up, net_down, disk_read, disk_write, ping, cpu_temp, load_avg, disk_json)
                        VALUES %s
                    """, records)
            
            return len(records)
        except Exception as e:
            print(f"Error bulk inserting metrics: {e}")
            return 0
    
    def bulk_insert_metrics_copy(self, agent_id: str, metrics: List[dict], 
                                  load_avg: float = 0.0) -> int:
        """
        High-performance COPY-based bulk insert for metrics.
        
        Uses PostgreSQL COPY command which is 2-5x faster than execute_values
        for large batches. Best for batches > 1000 rows.
        
        Args:
            agent_id: Agent identifier
            metrics: List of metric dicts
            load_avg: 15-minute load average
        
        Returns:
            Number of rows inserted
        """
        if not metrics:
            return 0
        
        try:
            import io
            
            # Build CSV-like string buffer
            buffer = io.StringIO()
            
            for metric in metrics:
                extra_data = json.dumps({
                    'disks': metric.get('disks', []),
                    'cpu_name': metric.get('cpu_name', ''),
                    'gpu_percent': metric.get('gpu_percent', 0.0),
                    'gpu_temp': metric.get('gpu_temp', 0.0),
                    'gpu_name': metric.get('gpu_name', ''),
                    'is_vm': metric.get('is_vm', False)
                }).replace('\t', ' ')  # Escape tabs
                
                # Parse timestamp
                ts = metric['timestamp']
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                ts_str = ts.isoformat()
                
                # Write tab-separated values
                buffer.write(f"{agent_id}\t{ts_str}\t")
                buffer.write(f"{metric['cpu_percent']}\t{metric['ram_percent']}\t")
                buffer.write(f"{metric.get('net_sent_bps', 0.0)}\t{metric.get('net_recv_bps', 0.0)}\t")
                buffer.write(f"{metric.get('disk_read_bps', 0.0)}\t{metric.get('disk_write_bps', 0.0)}\t")
                buffer.write(f"{metric.get('ping_latency_ms', 0.0)}\t{metric.get('cpu_temp', 0.0)}\t")
                buffer.write(f"{load_avg}\t{extra_data}\n")
            
            buffer.seek(0)
            
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.copy_from(
                        buffer,
                        'metrics',
                        columns=('agent_id', 'timestamp', 'cpu_percent', 'ram_percent',
                                'net_up', 'net_down', 'disk_read', 'disk_write', 
                                'ping', 'cpu_temp', 'load_avg', 'disk_json'),
                        sep='\t'
                    )
            
            return len(metrics)
        except Exception as e:
            print(f"Error COPY inserting metrics: {e}")
            # Fall back to regular bulk insert
            return self.bulk_insert_metrics(agent_id, metrics, load_avg)
    
    def _select_resolution_table(self, start_time: datetime, end_time: datetime) -> tuple:
        """
        Auto-select the appropriate table/aggregate based on time range.
        
        Resolution selection:
        - <= 2 hours: raw metrics (full resolution)
        - 2-24 hours: metrics_1min (1-minute aggregates)
        - 1-7 days: metrics_15min (15-minute aggregates)
        - > 7 days: metrics_1hour (1-hour aggregates)
        
        Returns:
            tuple: (table_name, time_column, has_minmax)
        """
        time_range = end_time - start_time
        hours = time_range.total_seconds() / 3600
        
        if hours <= 2:
            return ("metrics", "timestamp", False)
        elif hours <= 24:
            return ("metrics_1min", "bucket", True)
        elif hours <= 168:  # 7 days
            return ("metrics_15min", "bucket", True)
        else:
            return ("metrics_1hour", "bucket", True)
    
    def get_agent_metrics_smart(
        self,
        agent_id: str,
        start_time: str = None,
        end_time: str = None,
        max_points: int = 500
    ) -> dict:
        """
        Get metrics with automatic resolution selection based on time range.
        
        This method automatically selects the appropriate aggregate table
        to ensure efficient queries while maintaining good data resolution.
        
        Args:
            agent_id: Agent identifier
            start_time: ISO format start time
            end_time: ISO format end time
            max_points: Maximum data points to return
        
        Returns:
            dict with metrics, resolution info, and min/max values
        """
        # Parse time range
        now = datetime.now()
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            if end_dt.tzinfo:
                end_dt = end_dt.replace(tzinfo=None)
        else:
            end_dt = now
        
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            if start_dt.tzinfo:
                start_dt = start_dt.replace(tzinfo=None)
        else:
            start_dt = end_dt - timedelta(hours=1)  # Default: last hour
        
        # Select appropriate resolution
        table_name, time_column, has_minmax = self._select_resolution_table(start_dt, end_dt)
        
        with self.pool.dict_connection() as conn:
            with conn.cursor() as cur:
                if table_name == "metrics":
                    # Raw metrics query
                    cur.execute("""
                        SELECT 
                            timestamp, cpu_percent, ram_percent,
                            net_up, net_down, disk_read, disk_write,
                            ping, cpu_temp, load_avg, disk_json
                        FROM metrics
                        WHERE agent_id = %s
                        AND timestamp >= %s
                        AND timestamp <= %s
                        ORDER BY timestamp ASC
                        LIMIT %s
                    """, (agent_id, start_dt, end_dt, max_points))
                else:
                    # Continuous aggregate query (includes min/max)
                    cur.execute(f"""
                        SELECT 
                            {time_column} as timestamp,
                            cpu_percent, ram_percent,
                            net_up, net_down, disk_read, disk_write,
                            ping, cpu_temp, load_avg,
                            cpu_max, ram_max, cpu_min, ram_min
                        FROM {table_name}
                        WHERE agent_id = %s
                        AND {time_column} >= %s
                        AND {time_column} <= %s
                        ORDER BY {time_column} ASC
                        LIMIT %s
                    """, (agent_id, start_dt, end_dt, max_points))
                
                rows = cur.fetchall()
            
            # Format results
            results = []
            for row in rows:
                metric = {
                    "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                    "cpu_percent": float(row['cpu_percent']) if row['cpu_percent'] else 0.0,
                    "ram_percent": float(row['ram_percent']) if row['ram_percent'] else 0.0,
                    "net_sent_bps": float(row['net_up']) if row['net_up'] else 0.0,
                    "net_recv_bps": float(row['net_down']) if row['net_down'] else 0.0,
                    "disk_read_bps": float(row['disk_read']) if row['disk_read'] else 0.0,
                    "disk_write_bps": float(row['disk_write']) if row['disk_write'] else 0.0,
                    "ping_latency_ms": float(row['ping']) if row['ping'] else 0.0,
                    "cpu_temp": float(row['cpu_temp']) if row['cpu_temp'] else 0.0,
                    "load_avg": float(row['load_avg']) if row['load_avg'] else 0.0,
                }
                
                # Add min/max if available
                if has_minmax:
                    metric["cpu_max"] = float(row.get('cpu_max')) if row.get('cpu_max') else None
                    metric["cpu_min"] = float(row.get('cpu_min')) if row.get('cpu_min') else None
                    metric["ram_max"] = float(row.get('ram_max')) if row.get('ram_max') else None
                    metric["ram_min"] = float(row.get('ram_min')) if row.get('ram_min') else None
                
                # Parse disk_json for raw metrics
                if table_name == "metrics" and row.get('disk_json'):
                    extra_data = row['disk_json'] if isinstance(row['disk_json'], dict) else json.loads(row['disk_json'])
                    metric["disks"] = extra_data.get('disks', [])
                    metric["cpu_name"] = extra_data.get('cpu_name', '')
                    metric["gpu_percent"] = extra_data.get('gpu_percent', 0.0)
                    metric["gpu_temp"] = extra_data.get('gpu_temp', 0.0)
                    metric["gpu_name"] = extra_data.get('gpu_name', '')
                
                results.append(metric)
        
        # Calculate time range statistics
        time_range_hours = (end_dt - start_dt).total_seconds() / 3600
        
        return {
            "metrics": results,
            "count": len(results),
            "resolution": {
                "table": table_name,
                "time_column": time_column,
                "has_minmax": has_minmax,
                "description": self._get_resolution_description(table_name)
            },
            "time_range": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "hours": round(time_range_hours, 2)
            }
        }
    
    def _get_resolution_description(self, table_name: str) -> str:
        """Get human-readable description of resolution"""
        descriptions = {
            "metrics": "Raw data (1-2 second resolution)",
            "metrics_1min": "1-minute averages",
            "metrics_15min": "15-minute averages",
            "metrics_1hour": "Hourly averages"
        }
        return descriptions.get(table_name, "Unknown resolution")
    
    def get_agent_metrics(
        self, 
        agent_id: str, 
        limit: int = 100,
        start_time: str = None,
        end_time: str = None,
        downsample: str = None,
        auto_resolution: bool = True
    ) -> List[dict]:
        """
        Get metrics for an agent with automatic resolution selection.
        
        When auto_resolution=True (default) and a time range is provided,
        automatically selects the best data source:
        - <= 1 hour: raw metrics
        - 1-24 hours: 1-minute aggregates (metrics_1min)
        - 1-7 days: 15-minute aggregates (metrics_15min)
        - > 7 days: hourly aggregates (metrics_1hour)
        
        Performance logging: warns if query takes > 500ms
        """
        import time as time_module
        query_start = time_module.time()
        
        # Parse time range
        now = datetime.now()
        start_dt = None
        end_dt = None
        
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            if start_dt.tzinfo:
                start_dt = start_dt.replace(tzinfo=None)
        
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            if end_dt.tzinfo:
                end_dt = end_dt.replace(tzinfo=None)
        else:
            end_dt = now
        
        # Determine resolution
        resolution_info = {
            "table": "metrics",
            "description": "Raw data",
            "auto_selected": False
        }
        
        # Auto-select resolution based on time range (if not explicitly downsampling)
        if auto_resolution and start_dt and end_dt and not downsample:
            time_range_hours = (end_dt - start_dt).total_seconds() / 3600
            
            if time_range_hours <= 1:
                # <= 1 hour: use raw data
                table_name = "metrics"
                time_column = "timestamp"
            elif time_range_hours <= 24:
                # 1-24 hours: use 1-minute aggregates
                table_name = "metrics_1min"
                time_column = "bucket"
            elif time_range_hours <= 168:  # 7 days
                # 1-7 days: use 15-minute aggregates
                table_name = "metrics_15min"
                time_column = "bucket"
            else:
                # > 7 days: use hourly aggregates
                table_name = "metrics_1hour"
                time_column = "bucket"
            
            resolution_info = {
                "table": table_name,
                "description": self._get_resolution_description(table_name),
                "auto_selected": True,
                "time_range_hours": round(time_range_hours, 2)
            }
        else:
            table_name = "metrics"
            time_column = "timestamp"
        
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            
            # Build query based on table/downsample
            if downsample == '10min':
                query = """
                    SELECT 
                        time_bucket('10 minutes', timestamp) as timestamp,
                        AVG(cpu_percent) as cpu_percent,
                        AVG(ram_percent) as ram_percent,
                        AVG(net_up) as net_up,
                        AVG(net_down) as net_down,
                        AVG(disk_read) as disk_read,
                        AVG(disk_write) as disk_write,
                        AVG(ping) as ping,
                        AVG(cpu_temp) as cpu_temp,
                        AVG(load_avg) as load_avg,
                        NULL as disk_json,
                        NULL as cpu_max, NULL as cpu_min,
                        NULL as ram_max, NULL as ram_min
                    FROM metrics
                    WHERE agent_id = %s
                """
                group_by = "GROUP BY time_bucket('10 minutes', timestamp)"
                resolution_info = {"table": "metrics", "description": "10-minute aggregates (manual)", "auto_selected": False}
            elif downsample == 'hour':
                query = """
                    SELECT 
                        time_bucket('1 hour', timestamp) as timestamp,
                        AVG(cpu_percent) as cpu_percent,
                        AVG(ram_percent) as ram_percent,
                        AVG(net_up) as net_up,
                        AVG(net_down) as net_down,
                        AVG(disk_read) as disk_read,
                        AVG(disk_write) as disk_write,
                        AVG(ping) as ping,
                        AVG(cpu_temp) as cpu_temp,
                        AVG(load_avg) as load_avg,
                        NULL as disk_json,
                        NULL as cpu_max, NULL as cpu_min,
                        NULL as ram_max, NULL as ram_min
                    FROM metrics
                    WHERE agent_id = %s
                """
                group_by = "GROUP BY time_bucket('1 hour', timestamp)"
                resolution_info = {"table": "metrics", "description": "Hourly aggregates (manual)", "auto_selected": False}
            elif downsample == 'day':
                query = """
                    SELECT 
                        time_bucket('1 day', timestamp) as timestamp,
                        AVG(cpu_percent) as cpu_percent,
                        AVG(ram_percent) as ram_percent,
                        AVG(net_up) as net_up,
                        AVG(net_down) as net_down,
                        AVG(disk_read) as disk_read,
                        AVG(disk_write) as disk_write,
                        AVG(ping) as ping,
                        AVG(cpu_temp) as cpu_temp,
                        AVG(load_avg) as load_avg,
                        NULL as disk_json,
                        NULL as cpu_max, NULL as cpu_min,
                        NULL as ram_max, NULL as ram_min
                    FROM metrics
                    WHERE agent_id = %s
                """
                group_by = "GROUP BY time_bucket('1 day', timestamp)"
                resolution_info = {"table": "metrics", "description": "Daily aggregates (manual)", "auto_selected": False}
            elif table_name in ("metrics_1min", "metrics_15min", "metrics_1hour"):
                # Use continuous aggregate
                query = f"""
                    SELECT 
                        {time_column} as timestamp,
                        cpu_percent, ram_percent,
                        net_up, net_down, disk_read, disk_write,
                        ping, cpu_temp, load_avg,
                        cpu_max, cpu_min, ram_max, ram_min,
                        NULL as disk_json
                    FROM {table_name}
                    WHERE agent_id = %s
                """
                group_by = ""
            else:
                # Raw metrics
                query = """
                    SELECT timestamp, cpu_percent, ram_percent,
                           net_up, net_down, disk_read, disk_write,
                           ping, cpu_temp, load_avg, disk_json,
                           NULL as cpu_max, NULL as cpu_min,
                           NULL as ram_max, NULL as ram_min
                    FROM metrics
                    WHERE agent_id = %s
                """
                group_by = ""
            
            # Build params list for psycopg2 (will use %s placeholders)
            params = [agent_id]
            
            # Add time range filters
            if start_dt:
                query += f" AND {time_column} >= %s"
                params.append(start_dt)
            if end_dt:
                query += f" AND {time_column} <= %s"
                params.append(end_dt)
            
            # Add grouping and ordering
            if group_by:
                query += f" {group_by}"
            query += f" ORDER BY {time_column} ASC"
            
            # Add limit
            if limit:
                query += " LIMIT %s"
                params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Format results with consistent structure
            results = []
            for row in rows:
                # Parse disk_json if present
                extra_data = {}
                if row.get('disk_json'):
                    if isinstance(row['disk_json'], str):
                        extra_data = json.loads(row['disk_json'])
                    elif isinstance(row['disk_json'], dict):
                        extra_data = row['disk_json']
                
                metric = {
                    "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                    "cpu_percent": float(row['cpu_percent']) if row['cpu_percent'] else 0.0,
                    "ram_percent": float(row['ram_percent']) if row['ram_percent'] else 0.0,
                    "net_sent_bps": float(row['net_up']) if row['net_up'] else 0.0,
                    "net_recv_bps": float(row['net_down']) if row['net_down'] else 0.0,
                    "disk_read_bps": float(row['disk_read']) if row['disk_read'] else 0.0,
                    "disk_write_bps": float(row['disk_write']) if row['disk_write'] else 0.0,
                    "ping_latency_ms": float(row['ping']) if row['ping'] else 0.0,
                    "cpu_temp": float(row['cpu_temp']) if row['cpu_temp'] else 0.0,
                    "load_avg": float(row['load_avg']) if row['load_avg'] else 0.0,
                    "disks": extra_data.get('disks', []),
                    "cpu_name": extra_data.get('cpu_name', ''),
                    "gpu_percent": extra_data.get('gpu_percent', 0.0),
                    "gpu_temp": extra_data.get('gpu_temp', 0.0),
                    "gpu_name": extra_data.get('gpu_name', ''),
                    "is_vm": extra_data.get('is_vm', False),
                }
                
                # Add min/max if from continuous aggregate
                if row.get('cpu_max') is not None:
                    metric["cpu_max"] = float(row['cpu_max'])
                    metric["cpu_min"] = float(row['cpu_min']) if row.get('cpu_min') else 0.0
                    metric["ram_max"] = float(row['ram_max']) if row.get('ram_max') else 0.0
                    metric["ram_min"] = float(row['ram_min']) if row.get('ram_min') else 0.0
                
                results.append(metric)
        
        # Performance logging
        query_duration_ms = (time_module.time() - query_start) * 1000
        if query_duration_ms > 500:
            print(f"⚠️ Slow metrics query for {agent_id}: {query_duration_ms:.1f}ms "
                  f"(table={resolution_info['table']}, rows={len(results)})")
        
        # Store resolution info in results for API to access
        # We return just the list for backwards compatibility,
        # but the API layer can call get_last_query_resolution() if needed
        self._last_query_resolution = resolution_info
        self._last_query_duration_ms = query_duration_ms
        self._last_query_row_count = len(results)
        
        return results
    
    def get_last_query_resolution(self) -> dict:
        """Get resolution info from the last get_agent_metrics() call"""
        return getattr(self, '_last_query_resolution', {"table": "metrics", "description": "Raw data"})
    
    def get_last_query_stats(self) -> dict:
        """Get performance stats from the last query"""
        return {
            "resolution": getattr(self, '_last_query_resolution', {}),
            "duration_ms": getattr(self, '_last_query_duration_ms', 0),
            "row_count": getattr(self, '_last_query_row_count', 0)
        }
    
    # ==================== Process Snapshots ====================
    
    def insert_process_snapshot(self, agent_id: str, timestamp: datetime, 
                                  processes: List[dict]) -> None:
        """Insert a process snapshot for an agent"""
        try:
            self.pool.execute("""
                INSERT INTO process_snapshots (agent_id, timestamp, json_data)
                VALUES (%s, %s, %s)
            """, (agent_id, timestamp, json.dumps(processes)))
        except Exception as e:
            print(f"Error inserting process snapshot: {e}")
    
    def get_latest_process_snapshot(self, agent_id: str) -> Optional[dict]:
        """Get the latest process snapshot for an agent"""
        row = self.pool.fetchone("""
            SELECT timestamp, json_data, created_at
            FROM process_snapshots
            WHERE agent_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (agent_id,))
        
        if not row:
            return None
        
        return {
            "timestamp": row['timestamp'].isoformat(),
            "processes": row['json_data'] if isinstance(row['json_data'], list) else json.loads(row['json_data']),
            "created_at": row['created_at'].isoformat()
        }
    
    def get_process_snapshots_range(self, agent_id: str, start_time: datetime, 
                                          end_time: datetime) -> List[dict]:
        """Get all process snapshots for an agent within a time range"""
        rows = self.pool.fetchall("""
            SELECT timestamp, json_data, created_at
            FROM process_snapshots
            WHERE agent_id = %s AND timestamp BETWEEN %s AND %s
            ORDER BY timestamp DESC
        """, (agent_id, start_time, end_time))
        
        return [
            {
                "timestamp": row['timestamp'].isoformat(),
                "processes": row['json_data'] if isinstance(row['json_data'], list) else json.loads(row['json_data']),
                "created_at": row['created_at'].isoformat()
            }
            for row in rows
        ]
    
    # ==================== Alert Methods ====================
    
    def get_alert_rules(self, agent_id: str) -> Optional[dict]:
        """Get alert rules for an agent"""
        row = self.pool.fetchone("""
            SELECT * FROM alert_rules WHERE agent_id = %s
        """, (agent_id,))
        
        if not row:
            return None
        
        return dict(row)
    
    def upsert_alert_rules(self, agent_id: str, rules: dict) -> None:
        """Update or insert alert rules for an agent"""
        self.pool.execute("""
            INSERT INTO alert_rules (
                agent_id, monitor_uptime, cpu_percent_threshold, 
                ram_percent_threshold, disk_free_percent_threshold,
                cpu_temp_threshold, network_bandwidth_mbps_threshold, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (agent_id) DO UPDATE SET
                monitor_uptime = EXCLUDED.monitor_uptime,
                cpu_percent_threshold = EXCLUDED.cpu_percent_threshold,
                ram_percent_threshold = EXCLUDED.ram_percent_threshold,
                disk_free_percent_threshold = EXCLUDED.disk_free_percent_threshold,
                cpu_temp_threshold = EXCLUDED.cpu_temp_threshold,
                network_bandwidth_mbps_threshold = EXCLUDED.network_bandwidth_mbps_threshold,
                updated_at = NOW()
        """, (
            agent_id,
            rules.get('monitor_uptime', True),
            rules.get('cpu_percent_threshold'),
            rules.get('ram_percent_threshold'),
            rules.get('disk_free_percent_threshold'),
            rules.get('cpu_temp_threshold'),
            rules.get('network_bandwidth_mbps_threshold')
        ))
    
    def get_active_alerts(self, agent_id: str = None) -> List[dict]:
        """Get active alerts, optionally filtered by agent"""
        if agent_id:
            rows = self.pool.fetchall("""
                SELECT * FROM active_alerts 
                WHERE agent_id = %s AND is_active = TRUE
                ORDER BY triggered_at DESC
            """, (agent_id,))
        else:
            rows = self.pool.fetchall("""
                SELECT * FROM active_alerts 
                WHERE is_active = TRUE
                ORDER BY triggered_at DESC
            """)
        
        return [dict(row) for row in rows]
    
    def create_alert_async(self, agent_id: str, alert_type: str, threshold_value: float,
                          current_value: float, message: str, severity: str = 'warning') -> int:
        """Create a new active alert (returns alert id)"""
        with self.pool.dict_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO active_alerts 
                    (agent_id, alert_type, threshold_value, current_value, message, severity, triggered_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id
                """, (agent_id, alert_type, threshold_value, current_value, message, severity))
                row = cur.fetchone()
                return row['id'] if row else 0
    
    def resolve_alert(self, agent_id_or_alert_id, alert_type: str = None) -> None:
        """
        Resolve an active alert.
        Can be called as:
        - resolve_alert(alert_id) - resolve by alert ID
        - resolve_alert(agent_id, alert_type) - resolve by agent and type
        """
        if alert_type is not None:
            # Resolve by agent_id and alert_type
            self.pool.execute("""
                UPDATE active_alerts 
                SET is_active = FALSE, resolved_at = NOW()
                WHERE agent_id = %s AND alert_type = %s AND is_active = TRUE
            """, (agent_id_or_alert_id, alert_type))
        else:
            # Resolve by alert ID
            self.pool.execute("""
                UPDATE active_alerts 
                SET is_active = FALSE, resolved_at = NOW()
                WHERE id = %s
            """, (agent_id_or_alert_id,))
    
    # ==================== Log Settings ====================
    
    def get_agent_log_settings(self, agent_id: str) -> Optional[dict]:
        """Get log settings for an agent, returns defaults if none exist"""
        try:
            row = self.pool.fetchone("SELECT * FROM agent_log_settings WHERE agent_id = %s", (agent_id,))
            if not row:
                # Return default settings with logging enabled
                return {
                    "agent_id": agent_id,
                    "logging_enabled": True,
                    "log_level_threshold": "ERROR",
                    "log_retention_days": 7,
                    "watch_docker_containers": False,
                    "watch_system_logs": True,
                    "watch_security_logs": True,
                    "troubleshooting_mode": False
                }
            return dict(row)
        except Exception as e:
            print(f"Error getting agent log settings: {e}")
            # Return defaults on error too
            return {
                "agent_id": agent_id,
                "logging_enabled": True,
                "log_level_threshold": "ERROR",
                "log_retention_days": 7,
                "watch_docker_containers": False,
                "watch_system_logs": True,
                "watch_security_logs": True,
                "troubleshooting_mode": False
            }
    
    def upsert_agent_log_settings(self, agent_id: str, settings: dict) -> None:
        """Update or insert log settings for an agent"""
        self.pool.execute("""
            INSERT INTO agent_log_settings (
                agent_id, logging_enabled, log_level_threshold,
                log_retention_days, watch_docker_containers,
                watch_system_logs, watch_security_logs,
                troubleshooting_mode, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (agent_id) DO UPDATE SET
                logging_enabled = EXCLUDED.logging_enabled,
                log_level_threshold = EXCLUDED.log_level_threshold,
                log_retention_days = EXCLUDED.log_retention_days,
                watch_docker_containers = EXCLUDED.watch_docker_containers,
                watch_system_logs = EXCLUDED.watch_system_logs,
                watch_security_logs = EXCLUDED.watch_security_logs,
                troubleshooting_mode = EXCLUDED.troubleshooting_mode,
                updated_at = NOW()
        """, (
            agent_id,
            settings.get('logging_enabled', True),
            settings.get('log_level_threshold', 'ERROR'),
            settings.get('log_retention_days', 7),
            settings.get('watch_docker_containers', False),
            settings.get('watch_system_logs', True),
            settings.get('watch_security_logs', True),
            settings.get('troubleshooting_mode', False)
        ))
    
    # ==================== Raw Logs ====================
    
    def insert_raw_logs(self, logs: List[dict]) -> int:
        """Bulk insert raw log entries"""
        if not logs:
            return 0
        
        try:
            records = []
            for log in logs:
                ts = log['timestamp']
                if isinstance(ts, str):
                    # Handle 'Z' suffix for UTC
                    ts = ts.replace('Z', '+00:00')
                    # Handle timestamps with more than 6 decimal places (Windows sends 7)
                    # Python's fromisoformat only supports up to 6 decimal places
                    import re
                    ts = re.sub(r'(\.\d{6})\d+', r'\1', ts)
                    ts = datetime.fromisoformat(ts)
                
                records.append((
                    log['agent_id'],
                    ts,
                    log.get('severity', log.get('level', 'INFO')),
                    log.get('source', ''),
                    log.get('message', ''),
                    json.dumps(log.get('metadata', {}))
                ))
            
            # Bulk insert using connection pool
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    execute_values(cur, """
                        INSERT INTO raw_logs (agent_id, timestamp, severity, source, message, metadata)
                        VALUES %s
                    """, records)
            
            return len(records)
        except Exception as e:
            print(f"Error inserting raw logs: {e}")
            return 0
    
    def query_raw_logs(
        self,
        agent_id: str = None,
        agent_ids: List[str] = None,
        limit: int = 100,
        offset: int = 0,
        severity: str = None,
        source: str = None,
        search: str = None,
        start_time: datetime = None,
        end_time: datetime = None
    ) -> List[dict]:
        """Query raw logs with filtering. Supports single agent_id or multiple agent_ids."""
        query = """
            SELECT id, agent_id, timestamp, severity, source, message, metadata, created_at
            FROM raw_logs
            WHERE 1=1
        """
        params = []
        
        # Handle agent filtering - support both single and multiple agents
        if agent_ids and len(agent_ids) > 0:
            placeholders = ', '.join(['%s'] * len(agent_ids))
            query += f" AND agent_id IN ({placeholders})"
            params.extend(agent_ids)
        elif agent_id:
            query += " AND agent_id = %s"
            params.append(agent_id)
        
        if severity:
            severities = [s.strip() for s in severity.split(',')]
            placeholders = ', '.join(['%s'] * len(severities))
            query += f" AND severity IN ({placeholders})"
            params.extend(severities)
        
        if source:
            query += " AND source = %s"
            params.append(source)
        
        if search:
            query += " AND message ILIKE %s"
            params.append(f'%{search}%')
        
        if start_time:
            query += " AND timestamp >= %s"
            params.append(start_time)
        
        if end_time:
            query += " AND timestamp <= %s"
            params.append(end_time)
        
        query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        rows = self.pool.fetchall(query, tuple(params))
        
        return [
            {
                "id": row['id'],
                "agent_id": row['agent_id'],
                "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                "severity": row['severity'],
                "source": row['source'],
                "message": row['message'],
                "metadata": row['metadata'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None
            }
            for row in rows
        ]
    
    def get_raw_log_stats(self, agent_id: str, hours: int = 24) -> dict:
        """Get log statistics for an agent"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        rows = self.pool.fetchall("""
            SELECT severity, COUNT(*) as count
            FROM raw_logs
            WHERE agent_id = %s AND timestamp >= %s
            GROUP BY severity
        """, (agent_id, cutoff))
        
        stats = {'critical': 0, 'error': 0, 'warning': 0, 'info': 0}
        for row in rows:
            sev = row['severity'].lower()
            if sev in stats:
                stats[sev] = row['count']
            elif sev == 'warn':
                stats['warning'] = row['count']
        
        return stats
    
    # The duplicate get_raw_log_stats was removed - sync version defined earlier
    
    # ==================== System Settings ====================
    
    def get_setting(self, key: str) -> Optional[str]:
        """Get a system setting"""
        row = self.pool.fetchone("""
            SELECT value FROM system_settings WHERE key = %s
        """, (key,))
        return row['value'] if row else None
    
    def set_setting(self, key: str, value: str, description: str = None) -> None:
        """Set a system setting"""
        self.pool.execute("""
            INSERT INTO system_settings (key, value, description, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                description = COALESCE(EXCLUDED.description, system_settings.description),
                updated_at = NOW()
        """, (key, value, description))
    
    def get_all_settings(self) -> dict:
        """Get all system settings"""
        rows = self.pool.fetchall("SELECT key, value FROM system_settings")
        return {row['key']: row['value'] for row in rows}
    
    # Method aliases for main.py compatibility
    def get_all_system_settings(self) -> dict:
        """Get all system settings as dict (alias for get_all_settings)"""
        return self.get_all_settings()
    
    def set_system_setting_async(self, key: str, value: str, description: str = None) -> bool:
        """Set a system setting (alias for set_setting with bool return)"""
        self.set_setting(key, value, description)
        return True
    
    def get_public_app_url(self) -> str:
        """Get the configured public app URL"""
        return self.get_system_setting("public_app_url", "")
    
    # ==================== Uptime Monitoring ====================
    
    def get_agents_to_check_uptime(self) -> List[dict]:
        """Get agents that have uptime monitoring enabled"""
        rows = self.pool.fetchall("""
            SELECT a.agent_id, a.hostname, a.last_seen, a.status
            FROM agents a
            LEFT JOIN alert_rules ar ON a.agent_id = ar.agent_id
            WHERE a.enabled = TRUE
            AND (ar.monitor_uptime IS NULL OR ar.monitor_uptime = TRUE)
        """)
        
        return [
            {
                "agent_id": row['agent_id'],
                "hostname": row['hostname'],
                "last_seen": row['last_seen'].isoformat() if row['last_seen'] else None,
                "status": row['status']
            }
            for row in rows
        ]
    
    def check_agent_offline(self, agent_id: str, hostname: str, last_seen: str,
                            offline_threshold_seconds: int = 120) -> dict:
        """Check if an agent is offline and create/resolve alerts accordingly"""
        try:
            # Parse last_seen timestamp
            if isinstance(last_seen, str):
                if 'T' in last_seen:
                    last_seen_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00').replace('+00:00', ''))
                else:
                    last_seen_dt = datetime.strptime(last_seen.split('+')[0], "%Y-%m-%d %H:%M:%S")
            else:
                last_seen_dt = last_seen
        except Exception as e:
            print(f"Error parsing last_seen for {agent_id}: {e}")
            return {"checked": False, "error": str(e)}
        
        # Make both timezone-naive for comparison
        if last_seen_dt.tzinfo:
            last_seen_dt = last_seen_dt.replace(tzinfo=None)
        
        seconds_offline = (datetime.now() - last_seen_dt).total_seconds()
        
        if seconds_offline > offline_threshold_seconds:
            # Agent is offline - update status and create alert
            self.update_agent_status(agent_id, "offline")
            alert = self.create_alert_async(
                agent_id=agent_id,
                alert_type="agent_offline",
                threshold_value=offline_threshold_seconds,
                current_value=seconds_offline,
                message=f"Agent '{hostname}' has been offline for {int(seconds_offline)}s",
                severity="critical"
            )
            return {"checked": True, "offline": True, "seconds_offline": seconds_offline, "alert": alert}
        else:
            # Agent is online - resolve any offline alert
            self.resolve_alert(agent_id, "agent_offline")
            return {"checked": True, "offline": False, "seconds_offline": seconds_offline}
    
    def update_agent_status(self, agent_id: str, status: str) -> None:
        """Update agent status"""
        self.pool.execute("""
            UPDATE agents SET status = %s WHERE agent_id = %s
        """, (status, agent_id))
    
    # ==================== Alert Methods (additional) ====================
    
    def update_alert_rules(self, agent_id: str, rules: dict) -> dict:
        """Update alert rules for an agent and return updated rules"""
        self.upsert_alert_rules(agent_id, rules)
        return self.get_alert_rules(agent_id)
    
    def get_alert_history(self, agent_id: str = None, limit: int = 100) -> List[dict]:
        """Get alert history including resolved alerts"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            if agent_id:
                cursor.execute("""
                    SELECT id, agent_id, alert_type, threshold_value, current_value,
                           message, severity, is_active, triggered_at, resolved_at
                    FROM active_alerts
                    WHERE agent_id = %s
                    ORDER BY triggered_at DESC
                    LIMIT %s
                """, (agent_id, limit))
            else:
                cursor.execute("""
                    SELECT id, agent_id, alert_type, threshold_value, current_value,
                           message, severity, is_active, triggered_at, resolved_at
                    FROM active_alerts
                    ORDER BY triggered_at DESC
                    LIMIT %s
                """, (limit,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def resolve_alert_by_id(self, alert_id: int) -> bool:
        """Resolve an alert by its ID"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE active_alerts
                SET is_active = FALSE, resolved_at = NOW()
                WHERE id = %s AND is_active = TRUE
            """, (alert_id,))
            affected = cursor.rowcount
            conn.commit()
            return affected > 0
    
    # ==================== Log Settings (aliases for main.py compatibility) ====================
    
    def get_log_settings(self, agent_id: str) -> dict:
        """Get log settings for an agent (alias for get_agent_log_settings)"""
        return self.get_agent_log_settings(agent_id)
    
    def update_log_settings(self, agent_id: str, settings: dict) -> dict:
        """Update log settings for an agent"""
        self.upsert_agent_log_settings(agent_id, settings)
        return self.get_agent_log_settings(agent_id)
    
    # ==================== Raw Log Methods (aliases) ====================
    
    def ingest_raw_logs(self, agent_id: str, logs: list) -> dict:
        """Ingest raw logs from an agent"""
        log_entries = []
        for log in logs:
            log_entries.append({
                'agent_id': agent_id,
                'timestamp': log.get('timestamp', datetime.now().isoformat()),
                'source': log.get('source', 'unknown'),
                'severity': log.get('severity', log.get('level', 'info')),
                'message': log.get('message', ''),
                'metadata': log.get('metadata', {})
            })
        
        inserted = self.insert_raw_logs(log_entries)
        return {
            "inserted": inserted,
            "total": len(logs),
            "agent_id": agent_id
        }
    
    def get_raw_logs(self, agent_id: str = None, agent_ids: List[str] = None,
                     severity: str = None, source: str = None, 
                     start_time: str = None, end_time: str = None,
                     search: str = None, limit: int = 100, offset: int = 0) -> dict:
        """Query raw logs with filtering (alias for query_raw_logs)"""
        logs = self.query_raw_logs(
            agent_id=agent_id, agent_ids=agent_ids, limit=limit, offset=offset,
            severity=severity, source=source, search=search,
            start_time=start_time, end_time=end_time
        )
        return {
            "logs": logs,
            "count": len(logs),
            "limit": limit,
            "offset": offset
        }
    
    def get_log_stats(self, agent_id: str = None) -> dict:
        """Get log statistics for dashboard"""
        stats = self.get_raw_log_stats(agent_id, hours=24)
        return {
            "agent_id": agent_id,
            "last_24h": stats,
            "timestamp": datetime.now().isoformat()
        }
    
    # ==================== Log Reaper ====================
    
    def reap_old_logs(self) -> dict:
        """Clean up old logs based on retention settings"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            
            # Get agents with retention settings
            cursor.execute("""
                SELECT 
                    a.agent_id,
                    a.hostname,
                    COALESCE(ls.log_retention_days, 7) as retention_days
                FROM agents a
                LEFT JOIN agent_log_settings ls ON a.agent_id = ls.agent_id
            """)
            rows = cursor.fetchall()
            
            total_deleted = 0
            details = []
            
            for row in rows:
                agent_id = row['agent_id']
                hostname = row['hostname']
                retention_days = row['retention_days']
                
                cutoff = datetime.now() - timedelta(days=retention_days)
                
                # Delete old raw_logs
                cursor.execute("""
                    DELETE FROM raw_logs
                    WHERE agent_id = %s AND timestamp < %s
                """, (agent_id, cutoff))
                
                deleted = cursor.rowcount
                total_deleted += deleted
                
                if deleted > 0:
                    details.append({
                        "agent_id": agent_id,
                        "hostname": hostname,
                        "retention_days": retention_days,
                        "logs_deleted": deleted
                    })
                    print(f"🧹 Reaped {deleted} logs for {hostname}")
            
            conn.commit()
            
            return {
                "total_deleted": total_deleted,
                "agents_processed": len(rows),
                "details": details,
                "timestamp": datetime.now().isoformat()
            }
    
    # ==================== Metrics Evaluation ====================
    
    def evaluate_metrics(self, agent_id: str, metrics: dict) -> List[dict]:
        """Evaluate metrics against alert rules (stub - returns empty for now)"""
        # Alert evaluation is a non-critical feature, return empty to avoid errors
        # Full implementation can be added later
        return []
    
    # ==================== Template Log Methods (Qdrant compat stubs) ====================
    
    def ingest_logs(self, logs: list) -> dict:
        """Ingest template-based logs (stub for Qdrant compatibility)"""
        # This is for the Qdrant log template deduplication system
        # For PostgreSQL, we just insert as raw logs
        return {
            "new_templates": 0,
            "total_occurrences": len(logs),
            "errors": []
        }
    
    def query_logs(self, agent_id: str = None, level: str = None, search: str = None,
                   limit: int = 50, offset: int = 0) -> dict:
        """Query template logs (maps to raw_logs for PostgreSQL)"""
        logs = self.query_raw_logs(
            agent_id=agent_id, 
            severity=level,
            search=search,
            limit=limit, 
            offset=offset
        )
        return {
            "logs": logs,
            "total": len(logs),
            "limit": limit,
            "offset": offset
        }

    # ==================== SETUP WIZARD ====================
    
    def is_setup_complete(self) -> bool:
        """Check if the initial setup has been completed (sync)"""
        import psycopg2
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            # Check if setup_config table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'setup_config'
                )
            """)
            row = cursor.fetchone()
            if not row or not row[0]:
                conn.close()
                return False
            
            # Check if setup is marked complete
            cursor.execute("SELECT value FROM setup_config WHERE key = 'setup_complete'")
            row = cursor.fetchone()
            conn.close()
            
            return row is not None and row[0] == '1'
        except Exception as e:
            print(f"Error checking setup status: {e}")
            return False
    
    def is_setup_required(self) -> bool:
        """Check if setup is required (sync method using psycopg2)"""
        return not self.is_setup_complete()
    
    def get_setup_config(self) -> dict:
        """Get all setup configuration values (sync)"""
        import psycopg2
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'setup_config'
                )
            """)
            row = cursor.fetchone()
            if not row or not row[0]:
                conn.close()
                return {}
            
            cursor.execute("SELECT key, value FROM setup_config")
            rows = cursor.fetchall()
            conn.close()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            print(f"Error getting setup config: {e}")
            return {}
    
    def complete_setup(self, admin_username: str, admin_password: str, 
                       instance_name: str = "LogLibrarian",
                       deployment_profile: str = "homelab",
                       default_retention_days: int = 30,
                       timezone: str = "UTC",
                       instance_api_key: str = None,
                       server_address: str = "") -> dict:
        """
        Complete the initial setup wizard (sync).
        Creates admin user and stores configuration including instance API key.
        
        Args:
            admin_username: Admin account username
            admin_password: Admin account password
            instance_name: Name of this LogLibrarian instance
            deployment_profile: Deployment profile (homelab, small_business, production)
            default_retention_days: Default data retention in days
            timezone: Instance timezone
            instance_api_key: The API key all scribes must use to connect
            server_address: External IP/hostname for scribe connections
        """
        import psycopg2
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            # Create setup_config table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS setup_config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Check if already set up
            cursor.execute("SELECT value FROM setup_config WHERE key = 'setup_complete'")
            if cursor.fetchone():
                conn.close()
                return {"success": False, "error": "Setup already completed"}
            
            # Validate inputs
            if not admin_username or len(admin_username) < 3:
                conn.close()
                return {"success": False, "error": "Username must be at least 3 characters"}
            if not admin_password or len(admin_password) < 6:
                conn.close()
                return {"success": False, "error": "Password must be at least 6 characters"}
            if not instance_api_key or len(instance_api_key) < 32:
                conn.close()
                return {"success": False, "error": "Instance API key must be at least 32 characters"}
            
            # Create users table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT false,
                    role TEXT DEFAULT 'user',
                    is_setup_complete BOOLEAN DEFAULT false,
                    assigned_profile_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Create janitor_settings table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS janitor_settings (
                    id INTEGER PRIMARY KEY,
                    retention_days INTEGER DEFAULT 30,
                    cleanup_hour INTEGER DEFAULT 3,
                    enabled BOOLEAN DEFAULT true,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Delete any existing users (fresh start)
            cursor.execute("DELETE FROM users")
            
            # Create admin user
            password_hash = self._hash_password(admin_password)
            cursor.execute("""
                INSERT INTO users (username, password_hash, is_admin, role, is_setup_complete)
                VALUES (%s, %s, true, 'admin', true)
            """, (admin_username, password_hash))
            
            # Store setup configuration including instance API key
            config_items = [
                ('setup_complete', '1'),
                ('instance_name', instance_name),
                ('deployment_profile', deployment_profile),
                ('default_retention_days', str(default_retention_days)),
                ('timezone', timezone),
                ('setup_timestamp', datetime.now().isoformat()),
                ('database_type', 'postgresql'),
                ('instance_api_key', instance_api_key),
                ('server_address', server_address)
            ]
            
            for key, value in config_items:
                cursor.execute("""
                    INSERT INTO setup_config (key, value, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """, (key, value))
            
            # Also set the selected_lan_ip system setting if server_address is provided
            if server_address:
                # Ensure system_settings table exists
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        description TEXT,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                # Set the selected_lan_ip to match the server_address
                cursor.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('selected_lan_ip', %s, 'Server address for scribe install scripts', NOW())
                    ON CONFLICT(key) DO UPDATE SET 
                        value = EXCLUDED.value,
                        description = EXCLUDED.description,
                        updated_at = NOW()
                """, (server_address,))
            
            # Update default retention in janitor settings
            cursor.execute("""
                INSERT INTO janitor_settings (id, retention_days, cleanup_hour, enabled, updated_at)
                VALUES (1, %s, 3, true, NOW())
                ON CONFLICT (id) DO UPDATE SET retention_days = EXCLUDED.retention_days, updated_at = NOW()
            """, (default_retention_days,))
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "admin_username": admin_username,
                "instance_name": instance_name,
                "deployment_profile": deployment_profile
            }
            
        except Exception as e:
            print(f"Error completing setup: {e}")
            return {"success": False, "error": str(e)}
    
    def get_instance_name(self) -> str:
        """Get the configured instance name (sync)"""
        config = self.get_setup_config()
        return config.get('instance_name', 'LogLibrarian')
    
    def get_instance_api_key(self) -> Optional[str]:
        """Get the instance API key from setup_config"""
        config = self.get_setup_config()
        return config.get('instance_api_key')
    
    def regenerate_instance_api_key(self, new_key: str) -> bool:
        """Regenerate the instance API key (admin only)"""
        import psycopg2
        try:
            if not new_key or len(new_key) < 32:
                return False
            
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE setup_config 
                SET value = %s, updated_at = NOW()
                WHERE key = 'instance_api_key'
            """, (new_key,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error regenerating instance API key: {e}")
            return False
    
    # ==================== API KEY METHODS ====================
    
    def get_default_api_key(self) -> Optional[str]:
        """Get the default API key for agent installations (sync).
        
        Prioritizes the instance_api_key from setup_config (created during setup wizard)
        over the legacy api_keys table.
        """
        import psycopg2
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            # FIRST: Check for instance_api_key in setup_config (preferred)
            cursor.execute("""
                SELECT value FROM setup_config WHERE key = 'instance_api_key'
            """)
            row = cursor.fetchone()
            if row and row[0]:
                conn.close()
                return row[0]
            
            # FALLBACK: Check legacy api_keys table
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'api_keys'
                )
            """)
            if not cursor.fetchone()[0]:
                # Create api_keys table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        api_key TEXT NOT NULL,
                        key_hash TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT true,
                        created_at TIMESTAMP DEFAULT NOW(),
                        last_used_at TIMESTAMP
                    )
                """)
                conn.commit()
            
            cursor.execute("""
                SELECT api_key FROM api_keys 
                WHERE name = 'Default Key' AND is_active = true
                LIMIT 1
            """)
            row = cursor.fetchone()
            
            if not row:
                # Create default API key
                import secrets
                import hashlib
                api_key = secrets.token_urlsafe(32)
                key_hash = hashlib.sha256(api_key.encode()).hexdigest()
                
                cursor.execute("""
                    INSERT INTO api_keys (name, api_key, key_hash, is_active)
                    VALUES ('Default Key', %s, %s, true)
                """, (api_key, key_hash))
                conn.commit()
                conn.close()
                return api_key
            
            conn.close()
            return row[0] if row else None
        except Exception as e:
            print(f"Error getting default API key: {e}")
            return None
    
    def validate_api_key(self, api_key: str) -> bool:
        """Validate an API key - returns True if valid (sync)"""
        import psycopg2
        import hashlib
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            cursor.execute("""
                SELECT id FROM api_keys WHERE key_hash = %s AND is_active = true
            """, (key_hash,))
            row = cursor.fetchone()
            
            if row:
                # Update last used timestamp
                cursor.execute("""
                    UPDATE api_keys SET last_used_at = NOW() WHERE id = %s
                """, (row[0],))
                conn.commit()
            
            conn.close()
            return row is not None
        except Exception as e:
            print(f"Error validating API key: {e}")
            return False
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash"""
        import bcrypt
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception:
            return False
    
    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Get user by username (sync)"""
        import psycopg2
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, password_hash, is_admin, role, assigned_profile_id
                FROM users WHERE username = %s
            """, (username,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "id": row[0],
                    "username": row[1],
                    "password_hash": row[2],
                    "is_admin": row[3],
                    "role": row[4],
                    "assigned_profile_id": row[5]
                }
            return None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None
    
    def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """Authenticate a user, returns user dict if successful (sync)"""
        user = self.get_user_by_username(username)
        if user and self._verify_password(password, user["password_hash"]):
            return {
                "id": user["id"],
                "username": user["username"],
                "is_admin": user["is_admin"],
                "role": user["role"],
                "assigned_profile_id": user["assigned_profile_id"]
            }
        return None
    
    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        """Get a user by ID"""
        row = self.pool.fetchone("""
            SELECT id, username, password_hash, is_admin, role, assigned_profile_id, created_at
            FROM users WHERE id = %s
        """, (user_id,))
        
        if row:
            return {
                "id": row["id"],
                "username": row["username"],
                "password_hash": row["password_hash"],
                "is_admin": bool(row["is_admin"]),
                "role": row["role"] or ('admin' if row["is_admin"] else 'user'),
                "assigned_profile_id": row["assigned_profile_id"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            }
        return None
    
    def create_user(self, username: str, password: str, is_admin: bool = False, 
                    role: str = None, assigned_profile_id: str = None) -> Optional[int]:
        """Create a new user, returns user ID or None if failed"""
        try:
            password_hash = self._hash_password(password)
            actual_role = role if role else ('admin' if is_admin else 'user')
            
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (username, password_hash, is_admin, role, assigned_profile_id, is_setup_complete)
                    VALUES (%s, %s, %s, %s, %s, true)
                    RETURNING id
                """, (username, password_hash, is_admin, actual_role, assigned_profile_id))
                
                user_id = cursor.fetchone()['id']
                conn.commit()
                return user_id
        except Exception as e:
            print(f"Error creating user: {e}")
            return None
    
    def update_user_password(self, user_id: int, new_password: str) -> bool:
        """Update a user's password"""
        try:
            password_hash = self._hash_password(new_password)
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET password_hash = %s, updated_at = NOW()
                    WHERE id = %s
                """, (password_hash, user_id))
                success = cursor.rowcount > 0
                conn.commit()
                return success
        except Exception as e:
            print(f"Error updating password: {e}")
            return False
    
    def delete_user(self, user_id: int) -> bool:
        """Delete a user by ID"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                success = cursor.rowcount > 0
                conn.commit()
                return success
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False
    
    def get_all_users(self) -> List[dict]:
        """Get all users (without password hashes)"""
        rows = self.pool.fetchall("""
            SELECT id, username, is_admin, role, assigned_profile_id, created_at FROM users
            ORDER BY created_at ASC
        """)
        
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "is_admin": bool(row["is_admin"]),
                "role": row["role"] or ('admin' if row["is_admin"] else 'user'),
                "assigned_profile_id": row["assigned_profile_id"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            }
            for row in rows
        ]
    
    def update_user(self, user_id: int, role: str = None, assigned_profile_id: str = None, 
                    is_admin: bool = None) -> bool:
        """Update user's role and assigned profile"""
        try:
            updates = []
            params = []
            
            if role is not None:
                updates.append("role = %s")
                params.append(role)
                if is_admin is None:
                    updates.append("is_admin = %s")
                    params.append(role == 'admin')
            
            if is_admin is not None:
                updates.append("is_admin = %s")
                params.append(is_admin)
            
            if assigned_profile_id is not None:
                updates.append("assigned_profile_id = %s")
                params.append(assigned_profile_id if assigned_profile_id else None)
            
            if not updates:
                return True
            
            updates.append("updated_at = NOW()")
            params.append(user_id)
            
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    UPDATE users SET {', '.join(updates)}
                    WHERE id = %s
                """, params)
                success = cursor.rowcount > 0
                conn.commit()
                return success
        except Exception as e:
            print(f"Error updating user: {e}")
            return False
    
    def get_user_count(self) -> int:
        """Get total number of users"""
        row = self.pool.fetchone("SELECT COUNT(*) as count FROM users")
        return row['count'] if row else 0

    # =============================================
    # SESSION MANAGEMENT METHODS
    # =============================================
    
    def create_session(self, token: str, user: dict, expires_at: datetime) -> bool:
        """Create a new session in the database"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sessions (token, user_id, username, is_admin, role, assigned_profile_id, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (token) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        username = EXCLUDED.username,
                        is_admin = EXCLUDED.is_admin,
                        role = EXCLUDED.role,
                        assigned_profile_id = EXCLUDED.assigned_profile_id,
                        expires_at = EXCLUDED.expires_at,
                        created_at = NOW()
                """, (
                    token,
                    user["id"],
                    user["username"],
                    user.get("is_admin", False),
                    user.get("role", "admin" if user.get("is_admin") else "user"),
                    user.get("assigned_profile_id"),
                    expires_at
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error creating session: {e}")
            return False
    
    def get_session(self, token: str) -> Optional[dict]:
        """Get session by token, returns None if expired or not found"""
        try:
            row = self.pool.fetchone("""
                SELECT token, user_id, username, is_admin, role, assigned_profile_id, created_at, expires_at
                FROM sessions
                WHERE token = %s AND expires_at > NOW()
            """, (token,))
            
            if row:
                return {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "is_admin": bool(row["is_admin"]),
                    "role": row["role"],
                    "assigned_profile_id": row["assigned_profile_id"],
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"]
                }
            return None
        except Exception as e:
            print(f"Error getting session: {e}")
            return None
    
    def delete_session(self, token: str) -> bool:
        """Delete a session (logout)"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting session: {e}")
            return False
    
    def delete_user_sessions(self, user_id: int) -> bool:
        """Delete all sessions for a user (force logout everywhere)"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting user sessions: {e}")
            return False
    
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions, returns count of deleted sessions"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE expires_at <= NOW()")
                deleted = cursor.rowcount
                conn.commit()
                return deleted
        except Exception as e:
            print(f"Error cleaning up sessions: {e}")
            return 0

    # =============================================
    # SYNC BOOKMARKS & WATCHDOG METHODS
    # =============================================
    
    def get_all_bookmarks(self, active_only: bool = False) -> List[dict]:
        """Get all bookmarks across all tenants (for monitor engine) - sync using psycopg2"""
        import psycopg2
        import psycopg2.extras
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # First check if bookmarks table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'bookmarks'
                )
            """)
            table_exists = cursor.fetchone()['exists']
            
            if not table_exists:
                # Table doesn't exist, return empty list
                conn.close()
                return []
            
            if active_only:
                cursor.execute("SELECT * FROM bookmarks WHERE active = true ORDER BY name")
            else:
                cursor.execute("SELECT * FROM bookmarks ORDER BY name")
            
            results = cursor.fetchall()
            conn.close()
            return [dict(row) for row in results]
            
        except Exception as e:
            print(f"Error getting bookmarks: {e}")
            return []
    
    def mark_stale_agents_offline(self, offline_threshold_seconds: int = 120) -> List[str]:
        """
        Mark agents as offline if their last_seen exceeds the threshold (sync using psycopg2).
        Returns: List of agent_ids that were marked offline
        """
        import psycopg2
        import psycopg2.extras
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Find agents that should be marked offline
            cursor.execute("""
                SELECT agent_id, hostname 
                FROM agents 
                WHERE status = 'online' 
                AND last_seen < NOW() - INTERVAL '%s seconds'
            """, (offline_threshold_seconds,))
            
            stale_agents = cursor.fetchall()
            
            if stale_agents:
                agent_ids = [a['agent_id'] for a in stale_agents]
                
                # Mark them offline
                cursor.execute("""
                    UPDATE agents SET status = 'offline' 
                    WHERE agent_id = ANY(%s)
                """, (agent_ids,))
                conn.commit()
                
                # Note: We'll skip alert creation for sync method to keep it simple
                # Alerts can be created asynchronously by the watchdog
                
                for agent in stale_agents:
                    print(f"🔴 Agent '{agent['hostname']}' marked offline (no heartbeat for {offline_threshold_seconds}s)")
                
                conn.close()
                return agent_ids
            
            conn.close()
            return []
            
        except Exception as e:
            print(f"Error marking stale agents offline: {e}")
            return []
    
    def create_alert(self, agent_id: str, alert_type: str, threshold_value: float,
                     current_value: float, message: str, severity: str = "warning") -> None:
        """Create a new alert (sync using psycopg2)"""
        import psycopg2
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO alerts (agent_id, alert_type, threshold_value, current_value, 
                                   message, severity, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'active', NOW())
            """, (agent_id, alert_type, threshold_value, current_value, message, severity))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Error creating alert: {e}")

    # =============================================
    # STUB METHODS FOR FEATURE PARITY
    # These return sensible defaults to prevent 500 errors
    # =============================================
    
    def get_agents_for_user(self, user: dict) -> List[dict]:
        """Get agents filtered by user's role with calculated uptime percentage (sync using psycopg2)"""
        import psycopg2
        import psycopg2.extras
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            cursor.execute("""
                SELECT agent_id, hostname, status, public_ip, first_seen, 
                       last_seen, enabled, display_name, system_info,
                       connection_address, os, uptime_seconds, uptime_window
                FROM agents
                ORDER BY last_seen DESC
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            result = []
            now = datetime.utcnow()
            
            # Map uptime_window values to timedelta
            window_to_timedelta = {
                'daily': timedelta(hours=24),
                'weekly': timedelta(days=7),
                'monthly': timedelta(days=30),
                'quarterly': timedelta(days=90),
                'yearly': timedelta(days=365)
            }
            
            for row in rows:
                system_info = None
                if row['system_info']:
                    system_info = json.loads(row['system_info']) if isinstance(row['system_info'], str) else row['system_info']
                
                # Get uptime window setting (default to monthly)
                uptime_window = row.get('uptime_window') or 'monthly'
                window_delta = window_to_timedelta.get(uptime_window, timedelta(days=30))
                
                # Calculate uptime percentage based on the configured window
                start_date = now - window_delta
                uptime_data = self.calculate_agent_uptime(
                    agent_id=row['agent_id'],
                    start_date=start_date,
                    end_date=now,
                    heartbeat_ttl_seconds=120
                )
                uptime_percentage = uptime_data.get('uptime_percentage')
                
                result.append({
                    "agent_id": row['agent_id'],
                    "hostname": row['hostname'],
                    "status": row['status'],
                    "public_ip": row['public_ip'] or '',
                    "first_seen": row['first_seen'].isoformat() if row['first_seen'] else None,
                    "last_seen": row['last_seen'].isoformat() if row['last_seen'] else None,
                    "enabled": row['enabled'],
                    "display_name": row['display_name'] or '',
                    "system_info": system_info,
                    "connection_address": row['connection_address'] or '',
                    "os": row['os'] or '',
                    "uptime_seconds": row['uptime_seconds'] or 0,
                    "uptime_window": uptime_window,
                    "uptime_percentage": round(uptime_percentage, 1) if uptime_percentage is not None else None
                })
            return result
        except Exception as e:
            print(f"Error getting agents for user: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    # ==========================================
    # Notification Channels (Apprise-based)
    # ==========================================
    
    def _mask_url(self, url: str) -> str:
        """Mask sensitive parts of notification URLs for display"""
        if not url:
            return ""
        import re
        # Discord webhooks
        url = re.sub(r'(discord\.com/api/webhooks/\d+/)[^/\s]+', r'\1***', url)
        # Slack webhooks
        url = re.sub(r'(hooks\.slack\.com/services/)[^\s]+', r'\1***', url)
        # Generic token/key masking
        url = re.sub(r'([?&](token|key|apikey|api_key)=)[^&\s]+', r'\1***', url, flags=re.IGNORECASE)
        return url
    
    def get_notification_channels(self, tenant_id: str = "default") -> list:
        """Get all notification channels for a tenant"""
        rows = self.pool.fetchall("""
            SELECT id, tenant_id, name, channel_type, url, events, enabled, created_at, updated_at
            FROM notification_channels
            WHERE tenant_id = %s
            ORDER BY created_at DESC
        """, (tenant_id,))
        
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "name": row["name"],
                "channel_type": row["channel_type"],
                "url": row["url"],
                "url_masked": self._mask_url(row["url"]),
                "events": row["events"] if isinstance(row["events"], list) else json.loads(row["events"]) if row["events"] else [],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
            }
            for row in rows
        ]
    
    def create_notification_channel(self, name: str, channel_type: str, url: str, 
                                    events: list = None, tenant_id: str = "default") -> dict:
        """Create a new notification channel"""
        now = datetime.now()
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notification_channels (tenant_id, name, channel_type, url, events, enabled, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, true, %s, %s)
                RETURNING id
            """, (tenant_id, name, channel_type, url, json.dumps(events or ["all"]), now, now))
            
            channel_id = cursor.fetchone()['id']
            conn.commit()
            
            return {
                "id": channel_id,
                "name": name,
                "channel_type": channel_type,
                "url_masked": self._mask_url(url),
                "events": events or ["all"],
                "enabled": True,
                "created_at": now.isoformat()
            }
    
    def update_notification_channel(self, channel_id: int, updates: dict, tenant_id: str = "default") -> dict:
        """Update a notification channel"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            
            set_parts = []
            values = []
            
            if "name" in updates:
                set_parts.append("name = %s")
                values.append(updates["name"])
            if "channel_type" in updates:
                set_parts.append("channel_type = %s")
                values.append(updates["channel_type"])
            if "url" in updates:
                set_parts.append("url = %s")
                values.append(updates["url"])
            if "events" in updates:
                set_parts.append("events = %s")
                values.append(json.dumps(updates["events"]))
            if "enabled" in updates:
                set_parts.append("enabled = %s")
                values.append(updates["enabled"])
            
            set_parts.append("updated_at = %s")
            values.append(datetime.now())
            
            values.extend([channel_id, tenant_id])
            
            cursor.execute(f"""
                UPDATE notification_channels
                SET {', '.join(set_parts)}
                WHERE id = %s AND tenant_id = %s
            """, values)
            
            conn.commit()
            
            if cursor.rowcount == 0:
                return None
        
        # Fetch updated record
        channels = self.get_notification_channels(tenant_id)
        return next((c for c in channels if c["id"] == channel_id), None)
    
    def delete_notification_channel(self, channel_id: int, tenant_id: str = "default") -> bool:
        """Delete a notification channel"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM notification_channels
                WHERE id = %s AND tenant_id = %s
            """, (channel_id, tenant_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    
    def get_notification_channel_by_id(self, channel_id: int, tenant_id: str = "default") -> dict:
        """Get a single notification channel by ID"""
        row = self.pool.fetchone("""
            SELECT id, tenant_id, name, channel_type, url, events, enabled, created_at, updated_at
            FROM notification_channels
            WHERE id = %s AND tenant_id = %s
        """, (channel_id, tenant_id))
        
        if not row:
            return None
        
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "name": row["name"],
            "channel_type": row["channel_type"],
            "url": row["url"],
            "url_masked": self._mask_url(row["url"]),
            "events": row["events"] if isinstance(row["events"], list) else json.loads(row["events"]) if row["events"] else [],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
        }
    
    def add_notification_history(self, channel_id: int, event_type: str, title: str, 
                                 body: str, status: str, error: str = None) -> int:
        """Record a notification attempt"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notification_history (channel_id, event_type, title, body, status, error)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (channel_id, event_type, title, body, status, error))
            
            history_id = cursor.fetchone()['id']
            conn.commit()
            return history_id
    
    def get_notification_history(self, tenant_id: str = "default", limit: int = 100) -> list:
        """Get notification history for a tenant"""
        rows = self.pool.fetchall("""
            SELECT h.id, h.channel_id, c.name as channel_name, h.event_type, 
                   h.title, h.body, h.status, h.error, h.created_at
            FROM notification_history h
            JOIN notification_channels c ON h.channel_id = c.id
            WHERE c.tenant_id = %s
            ORDER BY h.created_at DESC
            LIMIT %s
        """, (tenant_id, limit))
        
        return [
            {
                "id": row["id"],
                "channel_id": row["channel_id"],
                "channel_name": row["channel_name"],
                "event_type": row["event_type"],
                "title": row["title"],
                "body": row["body"],
                "status": row["status"],
                "error": row["error"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            }
            for row in rows
        ]
    
    # ==========================================
    # Unified Alert Rules (V2 - Global/Agent/Bookmark)
    # ==========================================
    
    def get_alert_rules_v2(self, tenant_id: str = "default", scope: str = None, 
                           target_id: str = None) -> list:
        """Get alert rules, optionally filtered by scope and target"""
        query = """
            SELECT id, tenant_id, name, description, scope, target_id, metric, 
                   operator, threshold, channels, cooldown_minutes, enabled, 
                   created_at, updated_at, profile_id, profile_agents, profile_bookmarks
            FROM alert_rules_v2
            WHERE tenant_id = %s
        """
        params = [tenant_id]
        
        if scope:
            query += " AND scope = %s"
            params.append(scope)
        
        if target_id:
            query += " AND (target_id = %s OR target_id IS NULL)"
            params.append(target_id)
        
        query += " ORDER BY scope, created_at DESC"
        
        rows = self.pool.fetchall(query, tuple(params))
        
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "name": row["name"],
                "description": row["description"],
                "scope": row["scope"],
                "target_id": row["target_id"],
                "metric": row["metric"],
                "operator": row["operator"],
                "threshold": row["threshold"],
                "channels": row["channels"] if isinstance(row["channels"], list) else json.loads(row["channels"]) if row["channels"] else [],
                "cooldown_minutes": row["cooldown_minutes"],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "profile_id": row["profile_id"],
                "profile_agents": row["profile_agents"] if isinstance(row["profile_agents"], list) else json.loads(row["profile_agents"]) if row["profile_agents"] else [],
                "profile_bookmarks": row["profile_bookmarks"] if isinstance(row["profile_bookmarks"], list) else json.loads(row["profile_bookmarks"]) if row["profile_bookmarks"] else []
            }
            for row in rows
        ]
    
    def get_global_alert_rules(self, tenant_id: str = "default") -> list:
        """Get all global alert rules"""
        return self.get_alert_rules_v2(tenant_id, scope="global")
    
    def create_alert_rule_v2(self, name: str, scope: str, metric: str, operator: str, 
                             threshold: str, channels: list = None, target_id: str = None,
                             description: str = None, cooldown_minutes: int = 5,
                             profile_id: str = None, profile_agents: list = None,
                             profile_bookmarks: list = None,
                             tenant_id: str = "default") -> dict:
        """Create a new alert rule"""
        now = datetime.now()
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alert_rules_v2 
                (tenant_id, name, description, scope, target_id, metric, operator, 
                 threshold, channels, cooldown_minutes, enabled, created_at, updated_at,
                 profile_id, profile_agents, profile_bookmarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s)
                RETURNING id
            """, (tenant_id, name, description, scope, target_id, metric, operator,
                  threshold, json.dumps(channels or []), cooldown_minutes, now, now,
                  profile_id, json.dumps(profile_agents or []), json.dumps(profile_bookmarks or [])))
            
            rule_id = cursor.fetchone()['id']
            conn.commit()
            
            return {
                "id": rule_id,
                "name": name,
                "description": description,
                "scope": scope,
                "target_id": target_id,
                "metric": metric,
                "operator": operator,
                "threshold": threshold,
                "channels": channels or [],
                "cooldown_minutes": cooldown_minutes,
                "enabled": True,
                "created_at": now.isoformat(),
                "profile_id": profile_id,
                "profile_agents": profile_agents or [],
                "profile_bookmarks": profile_bookmarks or []
            }
    
    def update_alert_rule_v2(self, rule_id: int, updates: dict, tenant_id: str = "default") -> dict:
        """Update an alert rule"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            
            set_parts = []
            values = []
            
            for field in ["name", "description", "scope", "target_id", "metric", 
                          "operator", "threshold", "cooldown_minutes", "profile_id"]:
                if field in updates:
                    set_parts.append(f"{field} = %s")
                    values.append(updates[field])
            
            if "channels" in updates:
                set_parts.append("channels = %s")
                values.append(json.dumps(updates["channels"]))
            
            if "profile_agents" in updates:
                set_parts.append("profile_agents = %s")
                values.append(json.dumps(updates["profile_agents"]))
            
            if "profile_bookmarks" in updates:
                set_parts.append("profile_bookmarks = %s")
                values.append(json.dumps(updates["profile_bookmarks"]))
            
            if "enabled" in updates:
                set_parts.append("enabled = %s")
                values.append(updates["enabled"])
            
            set_parts.append("updated_at = %s")
            values.append(datetime.now())
            
            values.extend([rule_id, tenant_id])
            
            cursor.execute(f"""
                UPDATE alert_rules_v2
                SET {', '.join(set_parts)}
                WHERE id = %s AND tenant_id = %s
            """, values)
            
            conn.commit()
            
            if cursor.rowcount == 0:
                return None
        
        # Fetch updated rule
        rules = self.get_alert_rules_v2(tenant_id)
        return next((r for r in rules if r["id"] == rule_id), None)
    
    def delete_alert_rule_v2(self, rule_id: int, tenant_id: str = "default") -> bool:
        """Delete an alert rule"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM alert_rules_v2
                WHERE id = %s AND tenant_id = %s
            """, (rule_id, tenant_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    
    def get_effective_rules_for_target(self, target_type: str, target_id: str, 
                                       tenant_id: str = "default") -> list:
        """
        Get all effective alert rules for a target (agent or bookmark),
        including global rules with any overrides applied.
        """
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            
            # Get global rules with any overrides
            cursor.execute("""
                SELECT r.*, o.override_type, o.modified_threshold, o.modified_channels
                FROM alert_rules_v2 r
                LEFT JOIN alert_rule_overrides o 
                    ON r.id = o.rule_id 
                    AND o.target_type = %s 
                    AND o.target_id = %s
                WHERE r.tenant_id = %s AND r.scope = 'global' AND r.enabled = true
            """, (target_type, target_id, tenant_id))
            
            global_rules = cursor.fetchall()
            
            # Get target-specific rules
            cursor.execute("""
                SELECT * FROM alert_rules_v2
                WHERE tenant_id = %s AND scope = %s AND target_id = %s AND enabled = true
            """, (tenant_id, target_type, target_id))
            
            target_rules = cursor.fetchall()
        
        effective_rules = []
        
        # Process global rules with overrides
        for row in global_rules:
            rule = dict(row)
            
            # Apply override if exists
            if rule.get('override_type') == 'disable':
                continue  # Skip disabled rules
            elif rule.get('override_type') == 'modify':
                if rule.get('modified_threshold'):
                    rule['threshold'] = rule['modified_threshold']
                if rule.get('modified_channels'):
                    rule['channels'] = json.loads(rule['modified_channels']) if isinstance(rule['modified_channels'], str) else rule['modified_channels']
            
            # Parse JSON fields
            rule['channels'] = rule['channels'] if isinstance(rule['channels'], list) else json.loads(rule['channels']) if rule['channels'] else []
            rule['profile_agents'] = rule['profile_agents'] if isinstance(rule['profile_agents'], list) else json.loads(rule['profile_agents']) if rule['profile_agents'] else []
            rule['profile_bookmarks'] = rule['profile_bookmarks'] if isinstance(rule['profile_bookmarks'], list) else json.loads(rule['profile_bookmarks']) if rule['profile_bookmarks'] else []
            
            effective_rules.append(rule)
        
        # Add target-specific rules
        for row in target_rules:
            rule = dict(row)
            rule['channels'] = rule['channels'] if isinstance(rule['channels'], list) else json.loads(rule['channels']) if rule['channels'] else []
            rule['profile_agents'] = rule['profile_agents'] if isinstance(rule['profile_agents'], list) else json.loads(rule['profile_agents']) if rule['profile_agents'] else []
            rule['profile_bookmarks'] = rule['profile_bookmarks'] if isinstance(rule['profile_bookmarks'], list) else json.loads(rule['profile_bookmarks']) if rule['profile_bookmarks'] else []
            effective_rules.append(rule)
        
        return effective_rules
    
    def set_rule_override(self, rule_id: int, target_type: str, target_id: str,
                          override_type: str, modified_threshold: str = None,
                          modified_channels: list = None, tenant_id: str = "default") -> dict:
        """Set an override for a global rule on a specific target"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO alert_rule_overrides 
                (rule_id, target_type, target_id, override_type, modified_threshold, modified_channels)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (rule_id, target_type, target_id) DO UPDATE SET
                    override_type = EXCLUDED.override_type,
                    modified_threshold = EXCLUDED.modified_threshold,
                    modified_channels = EXCLUDED.modified_channels
                RETURNING id
            """, (rule_id, target_type, target_id, override_type, 
                  modified_threshold, json.dumps(modified_channels) if modified_channels else None))
            
            override_id = cursor.fetchone()['id']
            conn.commit()
            
            return {
                "id": override_id,
                "rule_id": rule_id,
                "target_type": target_type,
                "target_id": target_id,
                "override_type": override_type,
                "modified_threshold": modified_threshold,
                "modified_channels": modified_channels
            }
    
    def remove_rule_override(self, rule_id: int, target_type: str, target_id: str) -> bool:
        """Remove an override for a global rule"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM alert_rule_overrides
                WHERE rule_id = %s AND target_type = %s AND target_id = %s
            """, (rule_id, target_type, target_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    
    def get_rule_overrides_for_target(self, target_type: str, target_id: str) -> list:
        """Get all rule overrides for a target"""
        rows = self.pool.fetchall("""
            SELECT o.id, o.rule_id, r.name as rule_name, o.target_type, o.target_id,
                   o.override_type, o.modified_threshold, o.modified_channels
            FROM alert_rule_overrides o
            JOIN alert_rules_v2 r ON o.rule_id = r.id
            WHERE o.target_type = %s AND o.target_id = %s
        """, (target_type, target_id))
        
        return [
            {
                "id": row["id"],
                "rule_id": row["rule_id"],
                "rule_name": row["rule_name"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "override_type": row["override_type"],
                "modified_threshold": row["modified_threshold"],
                "modified_channels": row["modified_channels"] if isinstance(row["modified_channels"], list) else json.loads(row["modified_channels"]) if row["modified_channels"] else None
            }
            for row in rows
        ]
    
    # ==========================================
    # Report Profiles
    # ==========================================
    
    def create_report_profile(self, tenant_id: str, name: str, description: str = None,
                              frequency: str = "MONTHLY",
                              sla_target: float = 99.9,
                              schedule_hour: int = 7,
                              recipient_emails: List[str] = None,
                              monitor_scope_tags: List[str] = None,
                              monitor_scope_ids: List[str] = None,
                              scribe_scope_tags: List[str] = None,
                              scribe_scope_ids: List[str] = None) -> dict:
        """Create a new report profile"""
        import secrets
        profile_id = f"rp_{secrets.token_hex(8)}"
        now = datetime.now()
        
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO report_profiles (id, tenant_id, name, description, frequency, sla_target, schedule_hour,
                                             recipient_emails, monitor_scope_tags,
                                             monitor_scope_ids, scribe_scope_tags,
                                             scribe_scope_ids, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (profile_id, tenant_id, name, description, frequency, sla_target, schedule_hour,
                  json.dumps(recipient_emails or []),
                  json.dumps(monitor_scope_tags or []),
                  json.dumps(monitor_scope_ids or []),
                  json.dumps(scribe_scope_tags or []),
                  json.dumps(scribe_scope_ids or []),
                  now, now))
            
            row = cursor.fetchone()
            conn.commit()
            
            return self._parse_report_profile(dict(row)) if row else None
    
    def _parse_report_profile(self, row: dict) -> dict:
        """Parse JSON fields in report profile row"""
        if row:
            for field in ['recipient_emails', 'monitor_scope_tags', 'monitor_scope_ids',
                         'scribe_scope_tags', 'scribe_scope_ids']:
                if row.get(field):
                    if isinstance(row[field], list):
                        pass  # Already a list
                    else:
                        try:
                            row[field] = json.loads(row[field])
                        except:
                            row[field] = []
                else:
                    row[field] = []
            # Ensure frequency has a default
            if not row.get('frequency'):
                row['frequency'] = 'MONTHLY'
            # Ensure sla_target has a default
            if row.get('sla_target') is None:
                row['sla_target'] = 99.9
            # Ensure schedule_hour has a default
            if row.get('schedule_hour') is None:
                row['schedule_hour'] = 7
            # Convert datetime fields
            if row.get('created_at') and hasattr(row['created_at'], 'isoformat'):
                row['created_at'] = row['created_at'].isoformat()
            if row.get('updated_at') and hasattr(row['updated_at'], 'isoformat'):
                row['updated_at'] = row['updated_at'].isoformat()
        return row
    
    def get_report_profile(self, tenant_id: str, profile_id: str) -> Optional[dict]:
        """Get a report profile by ID"""
        row = self.pool.fetchone("""
            SELECT * FROM report_profiles 
            WHERE id = %s AND tenant_id = %s
        """, (profile_id, tenant_id))
        
        return self._parse_report_profile(dict(row)) if row else None
    
    def get_report_profiles(self, tenant_id: str) -> List[dict]:
        """Get all report profiles for a tenant"""
        rows = self.pool.fetchall("""
            SELECT * FROM report_profiles 
            WHERE tenant_id = %s
            ORDER BY name ASC
        """, (tenant_id,))
        
        return [self._parse_report_profile(dict(row)) for row in rows]
    
    def get_report_profile_by_id(self, profile_id: str) -> Optional[dict]:
        """Get a report profile by ID only (for internal use)"""
        row = self.pool.fetchone("""
            SELECT * FROM report_profiles WHERE id = %s
        """, (profile_id,))
        
        return self._parse_report_profile(dict(row)) if row else None
    
    def update_report_profile(self, tenant_id: str, profile_id: str, **kwargs) -> Optional[dict]:
        """Update a report profile"""
        allowed_fields = ['name', 'description', 'frequency', 'sla_target', 'schedule_hour', 'recipient_emails', 
                         'monitor_scope_tags', 'monitor_scope_ids',
                         'scribe_scope_tags', 'scribe_scope_ids']
        
        # Fields that need JSON serialization
        json_fields = ['recipient_emails', 'monitor_scope_tags', 'monitor_scope_ids',
                      'scribe_scope_tags', 'scribe_scope_ids']
        
        updates = []
        params = []
        
        for field in allowed_fields:
            if field in kwargs:
                updates.append(f"{field} = %s")
                value = kwargs[field]
                if field in json_fields:
                    value = json.dumps(value if value else [])
                params.append(value)
        
        if not updates:
            return self.get_report_profile(tenant_id, profile_id)
        
        updates.append("updated_at = %s")
        params.append(datetime.now())
        params.extend([profile_id, tenant_id])
        
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE report_profiles SET {', '.join(updates)} 
                WHERE id = %s AND tenant_id = %s
                RETURNING *
            """, params)
            row = cursor.fetchone()
            conn.commit()
            
            return self._parse_report_profile(dict(row)) if row else None
    
    def delete_report_profile(self, tenant_id: str, profile_id: str) -> bool:
        """Delete a report profile"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM report_profiles 
                WHERE id = %s AND tenant_id = %s
            """, (profile_id, tenant_id))
            conn.commit()
            
            return cursor.rowcount > 0
    
    def get_all_report_profiles_for_scheduling(self) -> List[dict]:
        """Get all report profiles across all tenants for scheduling purposes"""
        rows = self.pool.fetchall("""
            SELECT * FROM report_profiles ORDER BY tenant_id, name
        """)
        
        return [self._parse_report_profile(dict(row)) for row in rows]
    
    # ==========================================
    # Monitor Groups
    # ==========================================
    
    def create_monitor_group(self, tenant_id: str, name: str, weight: int = 0) -> dict:
        """Create a new monitor group"""
        import secrets
        group_id = f"grp_{secrets.token_hex(8)}"
        now = datetime.now()
        
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO monitor_groups (id, tenant_id, name, weight, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, tenant_id, name, weight, created_at, updated_at
            """, (group_id, tenant_id, name, weight, now, now))
            
            row = cursor.fetchone()
            conn.commit()
            
            return {
                "id": row['id'],
                "tenant_id": row['tenant_id'],
                "name": row['name'],
                "weight": row['weight'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
            }
    
    def get_monitor_groups(self, tenant_id: str) -> List[dict]:
        """Get all monitor groups for a tenant"""
        rows = self.pool.fetchall("""
            SELECT id, tenant_id, name, weight, created_at, updated_at
            FROM monitor_groups
            WHERE tenant_id = %s
            ORDER BY weight ASC, name ASC
        """, (tenant_id,))
        
        return [
            {
                "id": row['id'],
                "tenant_id": row['tenant_id'],
                "name": row['name'],
                "weight": row['weight'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
            }
            for row in rows
        ]
    
    def update_monitor_group(self, tenant_id: str, group_id: str, name: str = None, weight: int = None) -> dict:
        """Update a monitor group"""
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if weight is not None:
            updates.append("weight = %s")
            params.append(weight)
        
        if not updates:
            return self.get_monitor_group(tenant_id, group_id)
        
        updates.append("updated_at = %s")
        params.append(datetime.now())
        params.extend([group_id, tenant_id])
        
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE monitor_groups
                SET {', '.join(updates)}
                WHERE id = %s AND tenant_id = %s
            """, params)
            conn.commit()
        
        return self.get_monitor_group(tenant_id, group_id)
    
    def get_monitor_group(self, tenant_id: str, group_id: str) -> Optional[dict]:
        """Get a single monitor group"""
        row = self.pool.fetchone("""
            SELECT id, tenant_id, name, weight, created_at, updated_at
            FROM monitor_groups
            WHERE id = %s AND tenant_id = %s
        """, (group_id, tenant_id))
        
        if not row:
            return None
        
        return {
            "id": row['id'],
            "tenant_id": row['tenant_id'],
            "name": row['name'],
            "weight": row['weight'],
            "created_at": row['created_at'].isoformat() if row['created_at'] else None,
            "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
        }
    
    def delete_monitor_group(self, tenant_id: str, group_id: str, delete_monitors: bool = False) -> bool:
        """Delete a monitor group"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            
            if delete_monitors:
                # Delete bookmark checks first
                cursor.execute("""
                    DELETE FROM bookmark_checks 
                    WHERE bookmark_id IN (SELECT id FROM bookmarks WHERE group_id = %s AND tenant_id = %s)
                """, (group_id, tenant_id))
                # Then delete bookmarks
                cursor.execute("""
                    DELETE FROM bookmarks 
                    WHERE group_id = %s AND tenant_id = %s
                """, (group_id, tenant_id))
            else:
                # Just ungroup the monitors
                cursor.execute("""
                    UPDATE bookmarks SET group_id = NULL 
                    WHERE group_id = %s AND tenant_id = %s
                """, (group_id, tenant_id))
            
            # Delete the group
            cursor.execute("""
                DELETE FROM monitor_groups 
                WHERE id = %s AND tenant_id = %s
            """, (group_id, tenant_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    
    # ==========================================
    # Bookmarks (Monitors)
    # ==========================================
    
    def create_bookmark(self, tenant_id: str, name: str, type: str, target: str, 
                       group_id: str = None, port: int = None,
                       interval_seconds: int = 60, timeout_seconds: int = 10,
                       max_retries: int = 1, retry_interval: int = 30,
                       resend_notification: int = 0, upside_down: bool = False,
                       active: bool = True, tags: str = None, description: str = None) -> dict:
        """Create a new bookmark/monitor"""
        import secrets
        bookmark_id = f"bm_{secrets.token_hex(8)}"
        now = datetime.now()
        
        # Validate interval_seconds minimum of 20 seconds
        if interval_seconds < 20:
            interval_seconds = 20
        
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bookmarks (id, tenant_id, group_id, name, type, target, port, 
                                      interval_seconds, timeout_seconds, max_retries,
                                      retry_interval, resend_notification, upside_down,
                                      active, tags, description, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (bookmark_id, tenant_id, group_id, name, type, target, port,
                  interval_seconds, timeout_seconds, max_retries, retry_interval,
                  resend_notification, upside_down, active, tags, description, now, now))
            
            row = cursor.fetchone()
            conn.commit()
            return dict(row)
    
    def get_bookmark(self, tenant_id: str, bookmark_id: str) -> Optional[dict]:
        """Get a bookmark by ID"""
        row = self.pool.fetchone("""
            SELECT * FROM bookmarks 
            WHERE id = %s AND tenant_id = %s
        """, (bookmark_id, tenant_id))
        
        return dict(row) if row else None
    
    def get_bookmarks(self, tenant_id: str = None, group_id: str = None) -> List[dict]:
        """Get bookmarks, optionally filtered by group, with latest status"""
        if group_id:
            rows = self.pool.fetchall("""
                SELECT b.*, 
                       (SELECT status FROM bookmark_checks 
                        WHERE bookmark_id = b.id 
                        ORDER BY created_at DESC LIMIT 1) as last_status,
                       (SELECT latency_ms FROM bookmark_checks 
                        WHERE bookmark_id = b.id 
                        ORDER BY created_at DESC LIMIT 1) as last_latency,
                       (SELECT created_at FROM bookmark_checks 
                        WHERE bookmark_id = b.id 
                        ORDER BY created_at DESC LIMIT 1) as last_check_at
                FROM bookmarks b
                WHERE b.tenant_id = %s AND b.group_id = %s
                ORDER BY b.name ASC
            """, (tenant_id, group_id))
        else:
            rows = self.pool.fetchall("""
                SELECT b.*, 
                       (SELECT status FROM bookmark_checks 
                        WHERE bookmark_id = b.id 
                        ORDER BY created_at DESC LIMIT 1) as last_status,
                       (SELECT latency_ms FROM bookmark_checks 
                        WHERE bookmark_id = b.id 
                        ORDER BY created_at DESC LIMIT 1) as last_latency,
                       (SELECT created_at FROM bookmark_checks 
                        WHERE bookmark_id = b.id 
                        ORDER BY created_at DESC LIMIT 1) as last_check_at
                FROM bookmarks b
                WHERE b.tenant_id = %s
                ORDER BY b.name ASC
            """, (tenant_id,))
        
        bookmarks = []
        for row in rows:
            b = dict(row)
            if b.get("last_status") is not None:
                b["latest_check"] = {
                    "status": b["last_status"],
                    "latency_ms": b["last_latency"],
                    "created_at": b["last_check_at"].isoformat() if b["last_check_at"] else None
                }
            else:
                b["latest_check"] = None
            bookmarks.append(b)
        return bookmarks
    
    def get_bookmarks_for_user(self, user: dict) -> List[dict]:
        """Get bookmarks filtered by user's role"""
        # Admin users see all bookmarks
        if user.get("role") == "admin" or user.get("is_admin"):
            return self.get_bookmarks(tenant_id="default")
        
        # Regular users with no profile see nothing
        profile_id = user.get("assigned_profile_id")
        if not profile_id:
            return []
        
        # TODO: Filter by profile when report_profiles is implemented
        return self.get_bookmarks(tenant_id="default")
    
    def update_bookmark(self, tenant_id: str, bookmark_id: str, **kwargs) -> dict:
        """Update a bookmark"""
        updates = []
        params = []
        
        allowed_fields = ['name', 'type', 'target', 'group_id', 'port', 'interval_seconds',
                         'timeout_seconds', 'max_retries', 'retry_interval', 'resend_notification',
                         'upside_down', 'active', 'tags', 'description']
        
        for field in allowed_fields:
            if field in kwargs:
                updates.append(f"{field} = %s")
                params.append(kwargs[field])
        
        if not updates:
            return self.get_bookmark(tenant_id, bookmark_id)
        
        updates.append("updated_at = %s")
        params.append(datetime.now())
        params.extend([bookmark_id, tenant_id])
        
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE bookmarks
                SET {', '.join(updates)}
                WHERE id = %s AND tenant_id = %s
            """, params)
            conn.commit()
        
        return self.get_bookmark(tenant_id, bookmark_id)
    
    def delete_bookmark(self, tenant_id: str, bookmark_id: str) -> bool:
        """Delete a bookmark and its checks"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            # Delete checks first
            cursor.execute("DELETE FROM bookmark_checks WHERE bookmark_id = %s", (bookmark_id,))
            # Delete bookmark
            cursor.execute("""
                DELETE FROM bookmarks 
                WHERE id = %s AND tenant_id = %s
            """, (bookmark_id, tenant_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    
    def add_bookmark_check(self, bookmark_id: str, status: int, latency_ms: int = None, 
                          message: str = None) -> int:
        """Record a bookmark check result"""
        with self.pool.dict_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bookmark_checks (bookmark_id, status, latency_ms, message)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (bookmark_id, status, latency_ms, message))
            check_id = cursor.fetchone()['id']
            conn.commit()
            return check_id
    
    # Alias for compatibility with SQLite naming
    def record_bookmark_check(self, bookmark_id: str, status: int, 
                             latency_ms: int = None, message: str = None) -> dict:
        """Record a check result for a bookmark (alias for add_bookmark_check)"""
        check_id = self.add_bookmark_check(bookmark_id, status, latency_ms, message)
        return {"id": check_id, "bookmark_id": bookmark_id, "status": status, 
                "latency_ms": latency_ms, "message": message}
    
    def get_bookmark_checks(self, bookmark_id: str, limit: int = 60) -> List[dict]:
        """Get recent check history for a bookmark"""
        rows = self.pool.fetchall("""
            SELECT id, bookmark_id, status, latency_ms, message, created_at
            FROM bookmark_checks
            WHERE bookmark_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (bookmark_id, limit))
        
        return [
            {
                "id": row['id'],
                "bookmark_id": row['bookmark_id'],
                "status": row['status'],
                "latency_ms": row['latency_ms'],
                "message": row['message'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None
            }
            for row in rows
        ]
    
    def get_bookmark_with_checks(self, tenant_id: str, bookmark_id: str, check_limit: int = 60) -> dict:
        """Get a bookmark with its recent check history"""
        bookmark = self.get_bookmark(tenant_id, bookmark_id)
        if not bookmark:
            return None
        
        bookmark['checks'] = self.get_bookmark_checks(bookmark_id, check_limit)
        return bookmark
    
    def get_bookmark_checks_range(self, tenant_id: str, bookmark_id: str, hours: int = 24) -> List[dict]:
        """Get bookmark checks within a time range"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=hours)
        
        rows = self.pool.fetchall("""
            SELECT bc.id, bc.bookmark_id, bc.status, bc.latency_ms, bc.message, bc.created_at
            FROM bookmark_checks bc
            JOIN bookmarks b ON bc.bookmark_id = b.id
            WHERE bc.bookmark_id = %s AND b.tenant_id = %s AND bc.created_at >= %s
            ORDER BY bc.created_at DESC
        """, (bookmark_id, tenant_id, cutoff))
        
        return [
            {
                "id": row['id'],
                "bookmark_id": row['bookmark_id'],
                "status": row['status'],
                "latency_ms": row['latency_ms'],
                "message": row['message'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None
            }
            for row in rows
        ]
    
    def calculate_bookmark_uptime(self, bookmark_id: str, start_date: datetime, 
                                   end_date: datetime) -> dict:
        """
        Calculate bookmark uptime statistics for a given time period.
        
        Returns:
            dict with:
            - uptime_percentage: float (0-100) or None if no data
            - total_checks: int
            - successful_checks: int
            - failed_checks: int
            - incidents: int (transitions from up to down)
            - avg_response_ms: float or None
            - status: 'healthy', 'degraded', 'down', 'no_data'
        """
        # Get bookmark creation date
        bookmark = self.pool.fetchone(
            "SELECT created_at FROM bookmarks WHERE id = %s",
            (bookmark_id,)
        )
        
        if not bookmark:
            return {
                "uptime_percentage": None,
                "total_checks": 0,
                "successful_checks": 0,
                "failed_checks": 0,
                "incidents": 0,
                "avg_response_ms": None,
                "status": "not_found"
            }
        
        # Smart Start: Adjust start date if bookmark was created after report start
        bookmark_created = bookmark['created_at']
        if bookmark_created and bookmark_created > start_date:
            adjusted_start = bookmark_created
        else:
            adjusted_start = start_date
        
        # Get check statistics for the period
        stats = self.pool.fetchone("""
            SELECT 
                COUNT(*) as total_checks,
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as successful_checks,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as failed_checks,
                AVG(CASE WHEN status = 1 AND latency_ms IS NOT NULL THEN latency_ms END) as avg_response_ms
            FROM bookmark_checks
            WHERE bookmark_id = %s 
              AND created_at >= %s 
              AND created_at <= %s
        """, (bookmark_id, adjusted_start, end_date))
        
        total = int(stats['total_checks'] or 0)
        successful = int(stats['successful_checks'] or 0)
        failed = int(stats['failed_checks'] or 0)
        avg_response = float(stats['avg_response_ms']) if stats['avg_response_ms'] is not None else None
        
        if total == 0:
            return {
                "uptime_percentage": None,
                "total_checks": 0,
                "successful_checks": 0,
                "failed_checks": 0,
                "incidents": 0,
                "avg_response_ms": None,
                "status": "no_data"
            }
        
        uptime_pct = (successful / total) * 100
        
        # Count incidents (transitions from up to down)
        checks = self.pool.fetchall("""
            SELECT status
            FROM bookmark_checks
            WHERE bookmark_id = %s 
              AND created_at >= %s 
              AND created_at <= %s
            ORDER BY created_at ASC
        """, (bookmark_id, adjusted_start, end_date))
        
        incidents = 0
        prev_status = 1  # Assume started up
        for row in checks:
            if row['status'] == 0 and prev_status == 1:
                incidents += 1
            prev_status = row['status']
        
        # Determine health status
        if uptime_pct >= 99.9:
            status = "healthy"
        elif uptime_pct >= 95:
            status = "degraded"
        else:
            status = "down"
        
        return {
            "uptime_percentage": round(uptime_pct, 2),
            "total_checks": total,
            "successful_checks": successful,
            "failed_checks": failed,
            "incidents": incidents,
            "avg_response_ms": round(avg_response, 1) if avg_response else None,
            "status": status
        }
    
    def get_bookmarks_tree(self, tenant_id: str = None) -> dict:
        """Get bookmarks organized by groups with latest status"""
        if not tenant_id:
            tenant_id = "default"
        
        # Get all groups
        groups = self.get_monitor_groups(tenant_id)
        
        # Get all bookmarks with status
        bookmarks = self.get_bookmarks(tenant_id)
        
        # Organize into tree structure
        tree = {
            "groups": [],
            "ungrouped": []
        }
        
        # Create group lookup
        group_lookup = {g["id"]: {**g, "bookmarks": []} for g in groups}
        
        for bookmark in bookmarks:
            if bookmark.get("group_id") and bookmark["group_id"] in group_lookup:
                group_lookup[bookmark["group_id"]]["bookmarks"].append(bookmark)
            else:
                tree["ungrouped"].append(bookmark)
        
        tree["groups"] = list(group_lookup.values())
        
        return tree
    
    def get_bookmarks_tree_for_user(self, user: dict) -> dict:
        """Get bookmarks tree filtered by user's role"""
        # Admin users see everything
        if user.get("role") == "admin" or user.get("is_admin"):
            return self.get_bookmarks_tree("default")
        
        # Regular users with no profile see nothing
        profile_id = user.get("assigned_profile_id")
        if not profile_id:
            return {"groups": [], "ungrouped": []}
        
        # TODO: Filter by profile when fully implemented
        return self.get_bookmarks_tree("default")
    
    def increment_online_agents_uptime(self, increment_seconds: int = 60) -> int:
        """Increment uptime counter for online agents"""
        import psycopg2
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE agents 
                SET uptime_seconds = COALESCE(uptime_seconds, 0) + %s 
                WHERE status = 'online'
            """, (increment_seconds,))
            count = cursor.rowcount
            conn.commit()
            conn.close()
            return count
        except Exception as e:
            print(f"Error incrementing uptime: {e}")
            return 0
    
    # ==========================================
    # AI Reports
    # ==========================================
    
    def create_ai_report(self, report_type: str, title: str, content: str, 
                        agent_id: str = None, metadata: dict = None) -> int:
        """Create a new AI report"""
        try:
            meta_json = json.dumps(metadata) if metadata else "{}"
            
            row = self.pool.fetchone("""
                INSERT INTO ai_reports (type, title, content, agent_id, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (report_type, title, content, agent_id, meta_json))
            
            return row['id'] if row else -1
        except Exception as e:
            print(f"Error creating AI report: {e}")
            return -1
    
    # Alias for create_ai_report
    def save_ai_report(self, report_type: str, title: str, content: str, 
                      agent_id: str = None, metadata: dict = None) -> int:
        """Save an AI report (alias for create_ai_report)"""
        return self.create_ai_report(report_type, title, content, agent_id, metadata)
    
    def get_profile_reports(self, profile_id: str, limit: int = 50) -> List[dict]:
        """Get reports for a specific profile from ai_reports table"""
        # Query reports where metadata contains the profile_id
        rows = self.pool.fetchall("""
            SELECT id, created_at, type, title, content, is_read, metadata, agent_id, feedback 
            FROM ai_reports 
            WHERE metadata::jsonb->>'profile_id' = %s
            ORDER BY created_at DESC 
            LIMIT %s
        """, (profile_id, limit))
        
        reports = []
        for row in rows:
            metadata = {}
            try:
                if row['metadata']:
                    metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
            except:
                pass
            
            # Check if we have embedded report_data
            report_data = metadata.get('report_data', {})
            
            reports.append({
                "id": row['id'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                "type": row['type'],
                "title": row['title'],
                "content": row['content'],
                "is_read": row['is_read'],
                "has_pdf": False,  # PDF generation not implemented yet
                "report_data": report_data
            })
        
        return reports
    
    def get_profile_report_pdf(self, profile_id: str, report_id: str) -> bytes:
        """Get PDF content for a report (not implemented - returns None)"""
        # PDF generation not implemented for stat reports
        return None
    
    def get_ai_reports(self, report_type: str = None, limit: int = 50, 
                      unread_only: bool = False, agent_id: str = None) -> List[dict]:
        """Get AI reports with optional filtering"""
        query = "SELECT id, created_at, type, title, content, is_read, metadata, agent_id, feedback FROM ai_reports WHERE 1=1"
        params = []
        
        if report_type:
            query += " AND type = %s"
            params.append(report_type)
        
        if unread_only:
            query += " AND is_read = FALSE"
        
        if agent_id:
            query += " AND agent_id = %s"
            params.append(agent_id)
        
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        
        rows = self.pool.fetchall(query, tuple(params))
        
        reports = []
        for row in rows:
            metadata = {}
            try:
                if row['metadata']:
                    metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
            except:
                pass
            
            reports.append({
                "id": row['id'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                "type": row['type'],
                "title": row['title'],
                "content": row['content'],
                "is_read": row['is_read'],
                "metadata": metadata,
                "agent_id": row['agent_id'],
                "feedback": row['feedback']
            })
        
        return reports
    
    def get_ai_report(self, report_id: int) -> Optional[dict]:
        """Get a single AI report by ID"""
        row = self.pool.fetchone("""
            SELECT id, created_at, type, title, content, is_read, metadata, agent_id, feedback 
            FROM ai_reports WHERE id = %s
        """, (report_id,))
        
        if not row:
            return None
        
        metadata = {}
        try:
            if row['metadata']:
                metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
        except:
            pass
        
        return {
            "id": row['id'],
            "created_at": row['created_at'].isoformat() if row['created_at'] else None,
            "type": row['type'],
            "title": row['title'],
            "content": row['content'],
            "is_read": row['is_read'],
            "metadata": metadata,
            "agent_id": row['agent_id'],
            "feedback": row['feedback']
        }
    
    def mark_ai_report_read(self, report_id: int) -> bool:
        """Mark an AI report as read"""
        try:
            self.pool.execute("UPDATE ai_reports SET is_read = TRUE WHERE id = %s", (report_id,))
            return True
        except Exception as e:
            print(f"Error marking report as read: {e}")
            return False
    
    def mark_all_ai_reports_read(self, report_type: str = None) -> int:
        """Mark all AI reports as read, optionally filtered by type"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                if report_type:
                    cursor.execute("UPDATE ai_reports SET is_read = TRUE WHERE type = %s AND is_read = FALSE", (report_type,))
                else:
                    cursor.execute("UPDATE ai_reports SET is_read = TRUE WHERE is_read = FALSE")
                count = cursor.rowcount
                conn.commit()
                return count
        except Exception as e:
            print(f"Error marking reports as read: {e}")
            return 0
    
    def get_unread_ai_report_count(self) -> dict:
        """Get count of unread reports by type"""
        rows = self.pool.fetchall("""
            SELECT type, COUNT(*) as count FROM ai_reports WHERE is_read = FALSE GROUP BY type
        """)
        
        counts = {"total": 0}
        for row in rows:
            counts[row['type']] = row['count']
            counts["total"] += row['count']
        
        return counts
    
    def delete_ai_report(self, report_id: int) -> bool:
        """Delete an AI report"""
        try:
            self.pool.execute("DELETE FROM ai_reports WHERE id = %s", (report_id,))
            return True
        except Exception as e:
            print(f"Error deleting AI report: {e}")
            return False
    
    def set_ai_report_feedback(self, report_id: int, feedback: str) -> bool:
        """Set feedback for an AI report (up, down, or null to clear)"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE ai_reports SET feedback = %s WHERE id = %s", (feedback, report_id))
                if cursor.rowcount == 0:
                    return False
                conn.commit()
                return True
        except Exception as e:
            print(f"Error setting AI report feedback: {e}")
            return False
    
    # ==========================================
    # AI Model Cache
    # ==========================================
    
    def get_ai_model_cache(self, model_id: str) -> Optional[dict]:
        """Get cached model info"""
        row = self.pool.fetchone("""
            SELECT model_id, file_path, file_hash, file_size_mb, is_downloaded, 
                   download_progress, downloaded_at, last_used_at
            FROM ai_model_cache WHERE model_id = %s
        """, (model_id,))
        
        if not row:
            return None
        
        return {
            "model_id": row['model_id'],
            "file_path": row['file_path'],
            "file_hash": row['file_hash'],
            "file_size_mb": row['file_size_mb'],
            "is_downloaded": row['is_downloaded'],
            "download_progress": row['download_progress'],
            "downloaded_at": row['downloaded_at'].isoformat() if row['downloaded_at'] else None,
            "last_used_at": row['last_used_at'].isoformat() if row['last_used_at'] else None
        }
    
    def get_all_ai_models(self) -> List[dict]:
        """Get all cached models"""
        rows = self.pool.fetchall("""
            SELECT model_id, file_path, file_hash, file_size_mb, is_downloaded, 
                   download_progress, downloaded_at, last_used_at
            FROM ai_model_cache ORDER BY last_used_at DESC NULLS LAST
        """)
        
        models = []
        for row in rows:
            models.append({
                "model_id": row['model_id'],
                "file_path": row['file_path'],
                "file_hash": row['file_hash'],
                "file_size_mb": row['file_size_mb'],
                "is_downloaded": row['is_downloaded'],
                "download_progress": row['download_progress'],
                "downloaded_at": row['downloaded_at'].isoformat() if row['downloaded_at'] else None,
                "last_used_at": row['last_used_at'].isoformat() if row['last_used_at'] else None
            })
        
        return models
    
    def upsert_ai_model_cache(self, model_id: str, file_path: str, file_hash: str = "",
                             file_size_mb: float = 0, is_downloaded: bool = False,
                             download_progress: float = 0) -> bool:
        """Create or update model cache entry"""
        try:
            self.pool.execute("""
                INSERT INTO ai_model_cache (model_id, file_path, file_hash, file_size_mb, 
                                           is_downloaded, download_progress, downloaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() ELSE NULL END)
                ON CONFLICT(model_id) DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    file_hash = EXCLUDED.file_hash,
                    file_size_mb = EXCLUDED.file_size_mb,
                    is_downloaded = EXCLUDED.is_downloaded,
                    download_progress = EXCLUDED.download_progress,
                    downloaded_at = CASE WHEN EXCLUDED.is_downloaded THEN NOW() ELSE ai_model_cache.downloaded_at END
            """, (model_id, file_path, file_hash, file_size_mb, is_downloaded, download_progress, is_downloaded))
            return True
        except Exception as e:
            print(f"Error upserting AI model cache: {e}")
            return False
    
    def update_ai_model_progress(self, model_id: str, progress: float) -> bool:
        """Update download progress for a model"""
        try:
            self.pool.execute("""
                UPDATE ai_model_cache SET download_progress = %s WHERE model_id = %s
            """, (progress, model_id))
            return True
        except Exception as e:
            print(f"Error updating model progress: {e}")
            return False
    
    def mark_ai_model_downloaded(self, model_id: str, file_hash: str = "") -> bool:
        """Mark a model as fully downloaded"""
        try:
            self.pool.execute("""
                UPDATE ai_model_cache 
                SET is_downloaded = TRUE, download_progress = 100, downloaded_at = NOW(), file_hash = %s
                WHERE model_id = %s
            """, (file_hash, model_id))
            return True
        except Exception as e:
            print(f"Error marking model as downloaded: {e}")
            return False
    
    def update_ai_model_last_used(self, model_id: str) -> bool:
        """Update the last_used_at timestamp for a model"""
        try:
            self.pool.execute("""
                UPDATE ai_model_cache SET last_used_at = NOW() WHERE model_id = %s
            """, (model_id,))
            return True
        except Exception as e:
            print(f"Error updating model last used: {e}")
            return False
    
    def delete_ai_model_cache(self, model_id: str) -> bool:
        """Delete a model from cache"""
        try:
            self.pool.execute("DELETE FROM ai_model_cache WHERE model_id = %s", (model_id,))
            return True
        except Exception as e:
            print(f"Error deleting AI model cache: {e}")
            return False
    
    # ==========================================
    # AI Conversations
    # ==========================================
    
    def create_conversation(self, title: str = "New Chat") -> Optional[dict]:
        """Create a new conversation thread"""
        import uuid
        
        try:
            conversation_id = str(uuid.uuid4())
            now = datetime.now()
            
            self.pool.execute("""
                INSERT INTO ai_conversations (id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
            """, (conversation_id, title, now, now))
            
            return {
                "id": conversation_id,
                "title": title,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat()
            }
        except Exception as e:
            print(f"Error creating conversation: {e}")
            return None
    
    def get_conversations(self, limit: int = 50) -> List[dict]:
        """Get all conversations, newest first"""
        rows = self.pool.fetchall("""
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM ai_messages WHERE conversation_id = c.id) as message_count
            FROM ai_conversations c
            ORDER BY c.updated_at DESC
            LIMIT %s
        """, (limit,))
        
        conversations = []
        for row in rows:
            conversations.append({
                "id": row['id'],
                "title": row['title'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None,
                "message_count": row['message_count']
            })
        
        return conversations
    
    def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """Get a single conversation with its messages"""
        row = self.pool.fetchone("""
            SELECT id, title, created_at, updated_at
            FROM ai_conversations WHERE id = %s
        """, (conversation_id,))
        
        if not row:
            return None
        
        conversation = {
            "id": row['id'],
            "title": row['title'],
            "created_at": row['created_at'].isoformat() if row['created_at'] else None,
            "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None,
            "messages": []
        }
        
        # Get messages
        message_rows = self.pool.fetchall("""
            SELECT id, role, content, created_at
            FROM ai_messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC
        """, (conversation_id,))
        
        for msg in message_rows:
            conversation["messages"].append({
                "id": msg['id'],
                "role": msg['role'],
                "content": msg['content'],
                "created_at": msg['created_at'].isoformat() if msg['created_at'] else None
            })
        
        return conversation
    
    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """Update conversation title"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE ai_conversations 
                    SET title = %s, updated_at = NOW()
                    WHERE id = %s
                """, (title, conversation_id))
                success = cursor.rowcount > 0
                conn.commit()
                return success
        except Exception as e:
            print(f"Error updating conversation title: {e}")
            return False
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages"""
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                # Messages will be deleted by CASCADE
                cursor.execute("DELETE FROM ai_conversations WHERE id = %s", (conversation_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting conversation: {e}")
            return False
    
    def add_message(self, conversation_id: str, role: str, content: str) -> Optional[dict]:
        """Add a message to a conversation"""
        import uuid
        
        try:
            message_id = str(uuid.uuid4())
            now = datetime.now()
            
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO ai_messages (id, conversation_id, role, content, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (message_id, conversation_id, role, content, now))
                
                # Update conversation's updated_at
                cursor.execute("""
                    UPDATE ai_conversations SET updated_at = %s WHERE id = %s
                """, (now, conversation_id))
                
                conn.commit()
            
            return {
                "id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": now.isoformat()
            }
        except Exception as e:
            print(f"Error adding message: {e}")
            return None
    
    def get_recent_messages(self, conversation_id: str, limit: int = 10) -> List[dict]:
        """Get the most recent messages from a conversation for context"""
        rows = self.pool.fetchall("""
            SELECT id, role, content, created_at
            FROM ai_messages
            WHERE conversation_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (conversation_id, limit))
        
        # Reverse to get chronological order
        messages = []
        for row in reversed(list(rows)):
            messages.append({
                "id": row['id'],
                "role": row['role'],
                "content": row['content'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else None
            })
        
        return messages
    
    def execute_query(self, query: str, params: tuple = None) -> List[dict]:
        """Execute a read-only query and return results as list of dicts"""
        try:
            if params:
                rows = self.pool.fetchall(query, params)
            else:
                rows = self.pool.fetchall(query)
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Query error: {e}")
            return []
    
    # ==========================================
    # TimescaleDB Statistics & Management
    # ==========================================
    
    def get_timescaledb_stats(self) -> dict:
        """Get TimescaleDB hypertable and compression statistics"""
        if not USE_TIMESCALE:
            return {"enabled": False, "message": "TimescaleDB not enabled"}
        
        try:
            stats = {"enabled": True, "hypertables": [], "compression": [], "aggregates": []}
            
            # Get hypertable info
            rows = self.pool.fetchall("""
                SELECT 
                    hypertable_name,
                    num_chunks,
                    compression_enabled,
                    COALESCE(total_bytes, 0) as total_bytes,
                    COALESCE(table_bytes, 0) as table_bytes,
                    COALESCE(index_bytes, 0) as index_bytes
                FROM timescaledb_information.hypertables
                LEFT JOIN (
                    SELECT hypertable_name as ht_name, * 
                    FROM timescaledb_information.hypertable_size_info
                ) sizes ON hypertables.hypertable_name = sizes.ht_name
            """)
            
            for row in rows:
                stats["hypertables"].append({
                    "name": row['hypertable_name'],
                    "chunks": row['num_chunks'],
                    "compression_enabled": row['compression_enabled'],
                    "total_mb": round(row['total_bytes'] / (1024 * 1024), 2) if row['total_bytes'] else 0,
                    "table_mb": round(row['table_bytes'] / (1024 * 1024), 2) if row['table_bytes'] else 0,
                    "index_mb": round(row['index_bytes'] / (1024 * 1024), 2) if row['index_bytes'] else 0
                })
            
            # Get compression stats
            try:
                comp_rows = self.pool.fetchall("""
                    SELECT 
                        hypertable_name,
                        COALESCE(before_compression_total_bytes, 0) as before_bytes,
                        COALESCE(after_compression_total_bytes, 0) as after_bytes
                    FROM timescaledb_information.compression_settings cs
                    JOIN (
                        SELECT hypertable_schema, hypertable_name, 
                               SUM(before_compression_total_bytes) as before_compression_total_bytes,
                               SUM(after_compression_total_bytes) as after_compression_total_bytes
                        FROM timescaledb_information.compressed_chunk_stats
                        GROUP BY hypertable_schema, hypertable_name
                    ) ccs ON cs.hypertable_name = ccs.hypertable_name
                """)
                
                for row in comp_rows:
                    before_mb = row['before_bytes'] / (1024 * 1024) if row['before_bytes'] else 0
                    after_mb = row['after_bytes'] / (1024 * 1024) if row['after_bytes'] else 0
                    ratio = round(before_mb / after_mb, 1) if after_mb > 0 else 0
                    
                    stats["compression"].append({
                        "table": row['hypertable_name'],
                        "before_mb": round(before_mb, 2),
                        "after_mb": round(after_mb, 2),
                        "compression_ratio": ratio
                    })
            except Exception:
                pass  # Compression stats not available
            
            # Get continuous aggregate info
            try:
                agg_rows = self.pool.fetchall("""
                    SELECT 
                        view_name,
                        view_definition IS NOT NULL as is_valid
                    FROM timescaledb_information.continuous_aggregates
                """)
                
                for row in agg_rows:
                    stats["aggregates"].append({
                        "name": row['view_name'],
                        "valid": row['is_valid']
                    })
            except Exception:
                pass
            
            return stats
        except Exception as e:
            return {"enabled": True, "error": str(e)}
    
    def get_chunk_stats(self, table_name: str = "metrics") -> List[dict]:
        """Get detailed chunk statistics for a hypertable"""
        if not USE_TIMESCALE:
            return []
        
        try:
            rows = self.pool.fetchall("""
                SELECT 
                    chunk_name,
                    range_start,
                    range_end,
                    is_compressed,
                    COALESCE(before_compression_total_bytes, after_compression_total_bytes, 0) as total_bytes
                FROM timescaledb_information.chunks
                WHERE hypertable_name = %s
                ORDER BY range_start DESC
                LIMIT 50
            """, (table_name,))
            
            return [
                {
                    "chunk": row['chunk_name'],
                    "start": row['range_start'].isoformat() if row['range_start'] else None,
                    "end": row['range_end'].isoformat() if row['range_end'] else None,
                    "compressed": row['is_compressed'],
                    "size_mb": round(row['total_bytes'] / (1024 * 1024), 2) if row['total_bytes'] else 0
                }
                for row in rows
            ]
        except Exception as e:
            print(f"Error getting chunk stats: {e}")
            return []
    
    def refresh_continuous_aggregate(self, view_name: str, start_time: datetime = None, end_time: datetime = None) -> bool:
        """Manually refresh a continuous aggregate"""
        if not USE_TIMESCALE:
            return False
        
        try:
            if start_time is None:
                start_time = datetime.now() - timedelta(days=1)
            if end_time is None:
                end_time = datetime.now()
            
            self.pool.execute("""
                CALL refresh_continuous_aggregate(%s, %s, %s)
            """, (view_name, start_time, end_time))
            return True
        except Exception as e:
            print(f"Error refreshing continuous aggregate: {e}")
            return False
    
    def get_retention_policy_status(self) -> List[dict]:
        """Get status of all retention policies"""
        if not USE_TIMESCALE:
            return []
        
        try:
            rows = self.pool.fetchall("""
                SELECT 
                    hypertable_name,
                    drop_after,
                    schedule_interval,
                    config
                FROM timescaledb_information.jobs
                WHERE proc_name = 'policy_retention'
            """)
            
            return [
                {
                    "table": row['hypertable_name'],
                    "retention": str(row['drop_after']),
                    "schedule": str(row['schedule_interval']),
                    "config": row['config']
                }
                for row in rows
            ]
        except Exception as e:
            print(f"Error getting retention policies: {e}")
            return []
    
    def manual_cleanup_old_data(self, table_name: str, older_than_days: int) -> int:
        """Manually delete old data from a table (fallback for non-hypertables)"""
        cutoff = datetime.now() - timedelta(days=older_than_days)
        
        try:
            with self.pool.dict_connection() as conn:
                cursor = conn.cursor()
                
                # Determine the timestamp column
                time_col = "timestamp" if table_name in ("metrics", "raw_logs") else "created_at"
                
                cursor.execute(f"""
                    DELETE FROM {table_name}
                    WHERE {time_col} < %s
                """, (cutoff,))
                
                deleted = cursor.rowcount
                conn.commit()
                return deleted
        except Exception as e:
            print(f"Error cleaning up {table_name}: {e}")
            return 0
    
    # ==========================================
    # Health Checks & Monitoring
    # ==========================================
    
    def get_health_status(self) -> dict:
        """
        Comprehensive health check for the database.
        Returns status of connection pool, database, and TimescaleDB features.
        """
        import time as time_module
        
        health = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": {
                "type": "postgresql",
                "timescaledb_enabled": USE_TIMESCALE,
                "connected": False
            },
            "connection_pool": {},
            "queries": {},
            "issues": []
        }
        
        # Test database connection
        try:
            start = time_module.time()
            row = self.pool.fetchone("SELECT 1 as test, NOW() as server_time")
            latency_ms = (time_module.time() - start) * 1000
            
            health["database"]["connected"] = True
            health["database"]["server_time"] = row['server_time'].isoformat() if row else None
            health["queries"]["ping_latency_ms"] = round(latency_ms, 2)
        except Exception as e:
            health["status"] = "unhealthy"
            health["database"]["connected"] = False
            health["issues"].append(f"Database connection failed: {str(e)}")
        
        # Connection pool stats
        try:
            pool_stats = self.pool.get_stats()
            health["connection_pool"] = pool_stats
            
            # Check for pool exhaustion
            if pool_stats.get("available", 0) == 0 and pool_stats.get("in_use", 0) > 0:
                health["issues"].append("Connection pool exhausted - all connections in use")
                health["status"] = "degraded"
        except Exception as e:
            health["issues"].append(f"Could not get pool stats: {str(e)}")
        
        # TimescaleDB specific checks
        if USE_TIMESCALE and health["database"]["connected"]:
            try:
                # Check if TimescaleDB extension is loaded
                row = self.pool.fetchone("""
                    SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'
                """)
                if row:
                    health["database"]["timescaledb_version"] = row['extversion']
                else:
                    health["issues"].append("TimescaleDB extension not found")
                    health["status"] = "degraded"
                
                # Check hypertable status
                rows = self.pool.fetchall("""
                    SELECT hypertable_name, num_chunks 
                    FROM timescaledb_information.hypertables
                """)
                health["database"]["hypertables"] = [
                    {"name": r['hypertable_name'], "chunks": r['num_chunks']}
                    for r in rows
                ]
                
                # Check for background workers
                row = self.pool.fetchone("""
                    SELECT COUNT(*) as job_count 
                    FROM timescaledb_information.jobs 
                    WHERE scheduled = true
                """)
                health["database"]["scheduled_jobs"] = row['job_count'] if row else 0
                
            except Exception as e:
                health["issues"].append(f"TimescaleDB check failed: {str(e)}")
        
        # Set final status
        if health["issues"]:
            if health["status"] != "unhealthy":
                health["status"] = "degraded"
        
        return health
    
    def get_database_stats(self) -> dict:
        """Get comprehensive database statistics"""
        stats = {
            "timestamp": datetime.now().isoformat(),
            "tables": {},
            "total_size_mb": 0,
            "index_size_mb": 0
        }
        
        try:
            # Get size of each table
            rows = self.pool.fetchall("""
                SELECT 
                    relname as table_name,
                    pg_total_relation_size(relid) as total_bytes,
                    pg_relation_size(relid) as table_bytes,
                    pg_indexes_size(relid) as index_bytes,
                    n_live_tup as row_count
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(relid) DESC
            """)
            
            total_size = 0
            total_index = 0
            
            for row in rows:
                table_name = row['table_name']
                total_bytes = row['total_bytes'] or 0
                table_bytes = row['table_bytes'] or 0
                index_bytes = row['index_bytes'] or 0
                
                stats["tables"][table_name] = {
                    "total_mb": round(total_bytes / (1024 * 1024), 2),
                    "table_mb": round(table_bytes / (1024 * 1024), 2),
                    "index_mb": round(index_bytes / (1024 * 1024), 2),
                    "row_count": row['row_count'] or 0
                }
                
                total_size += total_bytes
                total_index += index_bytes
            
            stats["total_size_mb"] = round(total_size / (1024 * 1024), 2)
            stats["index_size_mb"] = round(total_index / (1024 * 1024), 2)
            
            # Get database size
            row = self.pool.fetchone("""
                SELECT pg_database_size(current_database()) as db_size
            """)
            if row:
                stats["database_size_mb"] = round(row['db_size'] / (1024 * 1024), 2)
            
        except Exception as e:
            stats["error"] = str(e)
        
        return stats
    
    def get_query_performance_stats(self) -> List[dict]:
        """Get slow query statistics (requires pg_stat_statements extension)"""
        try:
            rows = self.pool.fetchall("""
                SELECT 
                    LEFT(query, 100) as query_preview,
                    calls,
                    total_exec_time as total_time_ms,
                    mean_exec_time as avg_time_ms,
                    rows as total_rows
                FROM pg_stat_statements
                WHERE userid = (SELECT usesysid FROM pg_user WHERE usename = current_user)
                ORDER BY total_exec_time DESC
                LIMIT 20
            """)
            
            return [
                {
                    "query": row['query_preview'],
                    "calls": row['calls'],
                    "total_ms": round(row['total_time_ms'], 2),
                    "avg_ms": round(row['avg_time_ms'], 2),
                    "rows": row['total_rows']
                }
                for row in rows
            ]
        except Exception:
            # pg_stat_statements extension may not be installed
            return []
    
    def get_connection_pool_stats(self) -> dict:
        """Get connection pool statistics"""
        return self.pool.get_stats()
    
    def cleanup_continuous_aggregates(self, retention_days: dict = None) -> dict:
        """
        Clean up old data from continuous aggregates.
        TimescaleDB retention policies don't apply to continuous aggregates,
        so we need to clean them manually.
        
        Args:
            retention_days: Dict of {aggregate_name: days_to_keep}
                           Defaults: metrics_1min=7, metrics_15min=30, metrics_1hour=365
        """
        if retention_days is None:
            retention_days = {
                "metrics_1min": 7,
                "metrics_15min": 30,
                "metrics_1hour": 365
            }
        
        results = {}
        
        for aggregate, days in retention_days.items():
            cutoff = datetime.now() - timedelta(days=days)
            try:
                with self.pool.dict_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"""
                        DELETE FROM {aggregate}
                        WHERE bucket < %s
                    """, (cutoff,))
                    deleted = cursor.rowcount
                    conn.commit()
                    
                    results[aggregate] = {
                        "deleted": deleted,
                        "cutoff": cutoff.isoformat(),
                        "retention_days": days
                    }
            except Exception as e:
                results[aggregate] = {"error": str(e)}
        
        return results
    
    def run_maintenance(self) -> dict:
        """
        Run database maintenance tasks.
        - Reindex if needed
        - Update statistics
        - Clean up dead tuples
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "tasks": []
        }
        
        try:
            # ANALYZE to update statistics
            self.pool.execute("ANALYZE")
            results["tasks"].append({"task": "ANALYZE", "status": "completed"})
        except Exception as e:
            results["tasks"].append({"task": "ANALYZE", "status": "error", "error": str(e)})
        
        try:
            # Check for tables needing vacuum
            rows = self.pool.fetchall("""
                SELECT relname, n_dead_tup, n_live_tup
                FROM pg_stat_user_tables
                WHERE n_dead_tup > 1000
                ORDER BY n_dead_tup DESC
                LIMIT 5
            """)
            
            for row in rows:
                results["tasks"].append({
                    "task": "VACUUM_RECOMMENDED",
                    "table": row['relname'],
                    "dead_tuples": row['n_dead_tup'],
                    "live_tuples": row['n_live_tup']
                })
        except Exception as e:
            results["tasks"].append({"task": "VACUUM_CHECK", "status": "error", "error": str(e)})
        
        return results
    
    def get_active_queries(self) -> List[dict]:
        """Get currently running queries"""
        try:
            rows = self.pool.fetchall("""
                SELECT 
                    pid,
                    usename,
                    state,
                    LEFT(query, 200) as query,
                    query_start,
                    EXTRACT(EPOCH FROM (NOW() - query_start)) as duration_seconds
                FROM pg_stat_activity
                WHERE state != 'idle'
                  AND pid != pg_backend_pid()
                ORDER BY query_start
            """)
            
            return [
                {
                    "pid": row['pid'],
                    "user": row['usename'],
                    "state": row['state'],
                    "query": row['query'],
                    "started": row['query_start'].isoformat() if row['query_start'] else None,
                    "duration_seconds": round(row['duration_seconds'], 2) if row['duration_seconds'] else 0
                }
                for row in rows
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    def estimate_storage_for_agents(self, agent_count: int, days: int = 30) -> dict:
        """
        Estimate storage requirements for a given number of agents.
        Based on current data patterns.
        """
        try:
            # Get current metrics rate
            row = self.pool.fetchone("""
                SELECT 
                    COUNT(*) as total_rows,
                    COUNT(DISTINCT agent_id) as agent_count,
                    pg_total_relation_size('metrics') as current_size
                FROM metrics
                WHERE timestamp > NOW() - INTERVAL '1 hour'
            """)
            
            if not row or row['agent_count'] == 0:
                return {"error": "Not enough data to estimate"}
            
            rows_per_agent_per_hour = row['total_rows'] / row['agent_count']
            bytes_per_row = row['current_size'] / max(row['total_rows'], 1)
            
            # Calculate estimates
            hours = days * 24
            estimated_rows = agent_count * rows_per_agent_per_hour * hours
            
            # Account for retention (48hr raw + aggregates)
            raw_retention_hours = 48
            raw_rows = agent_count * rows_per_agent_per_hour * raw_retention_hours
            
            # Aggregates are much smaller
            agg_rows = agent_count * hours  # 1 row per agent per hour max
            
            estimated_raw_mb = (raw_rows * bytes_per_row) / (1024 * 1024)
            estimated_agg_mb = (agg_rows * 100) / (1024 * 1024)  # ~100 bytes per aggregate row
            
            # Compression reduces by ~10x
            compressed_mb = (estimated_raw_mb * 0.1) + estimated_agg_mb
            
            return {
                "agent_count": agent_count,
                "days": days,
                "metrics_per_agent_per_hour": round(rows_per_agent_per_hour, 0),
                "estimated_raw_mb": round(estimated_raw_mb, 2),
                "estimated_aggregate_mb": round(estimated_agg_mb, 2),
                "estimated_compressed_mb": round(compressed_mb, 2),
                "recommendation": "Adequate" if compressed_mb < 10000 else "Consider scaling storage"
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_ai_settings(self) -> dict:
        """Get AI settings from system_settings table"""
        import psycopg2
        import psycopg2.extras
        import json
        
        defaults = {
            "enabled": False,
            "provider": None,
            "local_model_id": None,
            "openai_key": None,
            "briefing_time": "08:00",
            "report_style": "concise",
            "feature_flags": {},
            "exec_summary_enabled": False,
            "exec_summary_schedule": "weekly",
            "exec_summary_day_of_week": "1",
            "exec_summary_day_of_month": 1,
            "exec_summary_period_days": "30"
        }
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Get all ai_ prefixed settings
            cursor.execute("SELECT key, value FROM system_settings WHERE key LIKE 'ai_%'")
            rows = cursor.fetchall()
            conn.close()
            
            for row in rows:
                key = row['key'].replace('ai_', '')
                value = row['value']
                
                if key in defaults:
                    # Type conversion
                    if key == 'enabled' or key == 'exec_summary_enabled':
                        defaults[key] = value.lower() == 'true'
                    elif key == 'exec_summary_day_of_month':
                        defaults[key] = int(value) if value else 1
                    elif key == 'feature_flags':
                        try:
                            defaults[key] = json.loads(value) if value else {}
                        except:
                            defaults[key] = {}
                    else:
                        defaults[key] = value if value else defaults[key]
            
            return defaults
        except Exception as e:
            print(f"Error getting AI settings: {e}")
            return defaults
    
    def update_ai_settings(self, enabled: bool = None, provider: str = None, local_model_id: str = None, 
                          openai_key: str = None, briefing_time: str = None, report_style: str = None,
                          feature_flags: dict = None, exec_summary_enabled: bool = None,
                          exec_summary_schedule: str = None, exec_summary_day_of_week: str = None,
                          exec_summary_day_of_month: int = None, exec_summary_period_days: str = None) -> bool:
        """Update AI settings in system_settings table"""
        import psycopg2
        import json
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            # Build updates dict
            updates = {}
            if enabled is not None:
                updates['ai_enabled'] = str(enabled).lower()
            if provider is not None:
                updates['ai_provider'] = provider
            if local_model_id is not None:
                updates['ai_local_model_id'] = local_model_id
            if openai_key is not None:
                updates['ai_openai_key'] = openai_key
            if briefing_time is not None:
                updates['ai_briefing_time'] = briefing_time
            if report_style is not None:
                updates['ai_report_style'] = report_style
            if feature_flags is not None:
                updates['ai_feature_flags'] = json.dumps(feature_flags)
            if exec_summary_enabled is not None:
                updates['ai_exec_summary_enabled'] = str(exec_summary_enabled).lower()
            if exec_summary_schedule is not None:
                updates['ai_exec_summary_schedule'] = exec_summary_schedule
            if exec_summary_day_of_week is not None:
                updates['ai_exec_summary_day_of_week'] = exec_summary_day_of_week
            if exec_summary_day_of_month is not None:
                updates['ai_exec_summary_day_of_month'] = str(exec_summary_day_of_month)
            if exec_summary_period_days is not None:
                updates['ai_exec_summary_period_days'] = exec_summary_period_days
            
            # Upsert each setting
            for key, value in updates.items():
                cursor.execute("""
                    INSERT INTO system_settings (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """, (key, value))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating AI settings: {e}")
            return False
    
    def get_system_setting(self, key: str, default: str = "") -> str:
        """Get a system setting by key"""
        import psycopg2
        import psycopg2.extras
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Check if table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'system_settings'
                )
            """)
            if not cursor.fetchone()['exists']:
                conn.close()
                return default
            
            cursor.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
            row = cursor.fetchone()
            conn.close()
            
            return row['value'] if row else default
        except Exception as e:
            print(f"Error getting system setting: {e}")
            return default
    
    def set_system_setting(self, key: str, value: str, description: str = None) -> bool:
        """Set a system setting"""
        import psycopg2
        
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            
            # Ensure table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    description TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            
            cursor.execute("""
                INSERT INTO system_settings (key, value, description, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT(key) DO UPDATE SET 
                    value = EXCLUDED.value,
                    description = COALESCE(EXCLUDED.description, system_settings.description),
                    updated_at = NOW()
            """, (key, value, description))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error setting system setting: {e}")
            return False

    # =========================================================================
    # BACKUP & MAINTENANCE UTILITIES
    # =========================================================================
    
    def get_backup_info(self) -> dict:
        """
        Get information needed for backup planning.
        
        Returns:
            Dict with database size, table sizes, and backup recommendations
        """
        try:
            result = {
                'database_size': None,
                'tables': [],
                'total_rows': 0,
                'backup_strategy': 'full',
                'estimated_backup_time': 'unknown',
                'recommendations': []
            }
            
            # Get database size
            row = self.pool.fetchone("""
                SELECT pg_database_size(current_database()) as size_bytes,
                       pg_size_pretty(pg_database_size(current_database())) as size_human
            """)
            if row:
                result['database_size'] = {
                    'bytes': row['size_bytes'],
                    'human': row['size_human']
                }
                
                # Estimate backup time (rough: ~100MB/sec for pg_dump)
                size_mb = row['size_bytes'] / (1024 * 1024)
                est_seconds = max(1, size_mb / 100)
                if est_seconds < 60:
                    result['estimated_backup_time'] = f"{int(est_seconds)} seconds"
                elif est_seconds < 3600:
                    result['estimated_backup_time'] = f"{int(est_seconds / 60)} minutes"
                else:
                    result['estimated_backup_time'] = f"{est_seconds / 3600:.1f} hours"
            
            # Get table sizes
            rows = self.pool.fetchall("""
                SELECT 
                    relname as table_name,
                    pg_total_relation_size(c.oid) as total_size,
                    pg_size_pretty(pg_total_relation_size(c.oid)) as size_human,
                    reltuples::bigint as estimated_rows
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' 
                  AND c.relkind = 'r'
                ORDER BY pg_total_relation_size(c.oid) DESC
            """)
            
            for row in rows:
                result['tables'].append({
                    'name': row['table_name'],
                    'size_bytes': row['total_size'],
                    'size_human': row['size_human'],
                    'estimated_rows': row['estimated_rows']
                })
                result['total_rows'] += row['estimated_rows'] or 0
            
            # Generate recommendations
            db_size_gb = (result['database_size']['bytes'] or 0) / (1024**3)
            
            if db_size_gb < 1:
                result['recommendations'].append("Database is small. Full backups recommended daily.")
                result['backup_strategy'] = 'full_daily'
            elif db_size_gb < 10:
                result['recommendations'].append("Consider daily full backups with WAL archiving for point-in-time recovery.")
                result['backup_strategy'] = 'full_daily_with_wal'
            else:
                result['recommendations'].append("Large database. Use pg_basebackup with WAL streaming for minimal downtime.")
                result['recommendations'].append("Consider TimescaleDB's built-in backup features.")
                result['backup_strategy'] = 'incremental_with_wal_streaming'
            
            # Check for continuous aggregates
            agg_row = self.pool.fetchone("""
                SELECT COUNT(*) as count FROM timescaledb_information.continuous_aggregates
            """)
            if agg_row and agg_row['count'] > 0:
                result['recommendations'].append(
                    f"Database has {agg_row['count']} continuous aggregate(s). "
                    "These will be recreated automatically from source data if needed."
                )
            
            return result
        except Exception as e:
            return {'error': str(e)}
    
    def generate_backup_command(self, output_dir: str = '/backups', 
                                 backup_type: str = 'full') -> dict:
        """
        Generate pg_dump commands for backup.
        
        Args:
            output_dir: Directory to store backups
            backup_type: 'full', 'schema_only', 'data_only', 'parallel'
        
        Returns:
            Dict with backup commands and instructions
        """
        from datetime import datetime
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        db_name = DATABASE_URL.split('/')[-1].split('?')[0] if DATABASE_URL else 'librarian'
        
        # Parse connection info
        # Format: postgresql://user:pass@host:port/dbname
        import re
        match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(\w+)', DATABASE_URL or '')
        if match:
            user, password, host, port, dbname = match.groups()
        else:
            user, host, port, dbname = 'postgres', 'localhost', '5432', db_name
        
        result = {
            'commands': {},
            'env_vars': {
                'PGPASSWORD': '(set to your database password)'
            },
            'instructions': [],
            'restore_commands': {}
        }
        
        base_args = f"-h {host} -p {port} -U {user} -d {dbname}"
        
        if backup_type == 'full':
            result['commands']['backup'] = (
                f"pg_dump {base_args} -Fc -f {output_dir}/{dbname}_{timestamp}.dump"
            )
            result['restore_commands']['restore'] = (
                f"pg_restore {base_args} -c {output_dir}/{dbname}_{timestamp}.dump"
            )
            result['instructions'] = [
                "1. Set PGPASSWORD environment variable",
                "2. Run the backup command",
                "3. Verify backup file was created",
                "4. Store backup securely offsite",
                "Note: -Fc creates custom format for efficient restore"
            ]
            
        elif backup_type == 'schema_only':
            result['commands']['backup'] = (
                f"pg_dump {base_args} --schema-only -f {output_dir}/{dbname}_schema_{timestamp}.sql"
            )
            result['restore_commands']['restore'] = (
                f"psql {base_args} -f {output_dir}/{dbname}_schema_{timestamp}.sql"
            )
            result['instructions'] = [
                "Schema-only backup for database structure",
                "Use for creating new empty databases"
            ]
            
        elif backup_type == 'data_only':
            result['commands']['backup'] = (
                f"pg_dump {base_args} --data-only -Fc -f {output_dir}/{dbname}_data_{timestamp}.dump"
            )
            result['restore_commands']['restore'] = (
                f"pg_restore {base_args} --data-only {output_dir}/{dbname}_data_{timestamp}.dump"
            )
            result['instructions'] = [
                "Data-only backup (no schema)",
                "Requires existing schema in target database"
            ]
            
        elif backup_type == 'parallel':
            jobs = 4  # Number of parallel jobs
            result['commands']['backup'] = (
                f"pg_dump {base_args} -Fd -j {jobs} -f {output_dir}/{dbname}_{timestamp}"
            )
            result['restore_commands']['restore'] = (
                f"pg_restore {base_args} -j {jobs} -c {output_dir}/{dbname}_{timestamp}"
            )
            result['instructions'] = [
                f"Parallel backup using {jobs} jobs for faster backup/restore",
                "Creates a directory with multiple files",
                "Best for large databases"
            ]
        
        # Add TimescaleDB-specific notes
        result['timescaledb_notes'] = [
            "Ensure TimescaleDB extension is installed on restore target",
            "Continuous aggregates will be restored automatically",
            "Compression policies will be preserved",
            "For WAL-based backup, configure archive_mode and archive_command"
        ]
        
        return result
    
    def export_table_to_csv(self, table_name: str, output_file: str,
                            where_clause: str = None, columns: List[str] = None) -> dict:
        """
        Export a table to CSV format.
        
        Args:
            table_name: Name of table to export
            output_file: Path to output CSV file
            where_clause: Optional WHERE clause (without 'WHERE')
            columns: Optional list of columns to export
        
        Returns:
            Dict with status and row count
        """
        try:
            # Validate table exists
            exists = self.pool.fetchone("""
                SELECT EXISTS (
                    SELECT FROM pg_tables WHERE tablename = %s AND schemaname = 'public'
                ) as exists
            """, (table_name,))
            
            if not exists or not exists['exists']:
                return {'success': False, 'error': f"Table '{table_name}' not found"}
            
            # Build column list
            col_str = ', '.join(columns) if columns else '*'
            
            # Build query
            query = f"SELECT {col_str} FROM {table_name}"
            if where_clause:
                query += f" WHERE {where_clause}"
            
            # Use COPY for efficient export
            copy_query = f"COPY ({query}) TO STDOUT WITH CSV HEADER"
            
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    with open(output_file, 'w', newline='', encoding='utf-8') as f:
                        cur.copy_expert(copy_query, f)
            
            # Count rows
            import os
            with open(output_file, 'r', encoding='utf-8') as f:
                row_count = sum(1 for _ in f) - 1  # Subtract header
            
            file_size = os.path.getsize(output_file)
            
            return {
                'success': True,
                'table': table_name,
                'output_file': output_file,
                'rows_exported': row_count,
                'file_size_bytes': file_size,
                'file_size_human': self._human_readable_size(file_size)
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def import_csv_to_table(self, table_name: str, input_file: str,
                            truncate_first: bool = False,
                            columns: List[str] = None) -> dict:
        """
        Import CSV data into a table.
        
        Args:
            table_name: Target table name
            input_file: Path to CSV file
            truncate_first: Whether to truncate table before import
            columns: Optional list of columns (must match CSV order)
        
        Returns:
            Dict with status and row count
        """
        try:
            # Validate table exists
            exists = self.pool.fetchone("""
                SELECT EXISTS (
                    SELECT FROM pg_tables WHERE tablename = %s AND schemaname = 'public'
                ) as exists
            """, (table_name,))
            
            if not exists or not exists['exists']:
                return {'success': False, 'error': f"Table '{table_name}' not found"}
            
            # Count rows before
            before = self.pool.fetchone(f"SELECT COUNT(*) as count FROM {table_name}")
            rows_before = before['count'] if before else 0
            
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    if truncate_first:
                        cur.execute(f"TRUNCATE TABLE {table_name} CASCADE")
                    
                    # Build COPY command
                    col_str = f"({', '.join(columns)})" if columns else ""
                    copy_query = f"COPY {table_name} {col_str} FROM STDIN WITH CSV HEADER"
                    
                    with open(input_file, 'r', encoding='utf-8') as f:
                        cur.copy_expert(copy_query, f)
            
            # Count rows after
            after = self.pool.fetchone(f"SELECT COUNT(*) as count FROM {table_name}")
            rows_after = after['count'] if after else 0
            
            return {
                'success': True,
                'table': table_name,
                'input_file': input_file,
                'rows_imported': rows_after - (0 if truncate_first else rows_before),
                'total_rows': rows_after,
                'truncated': truncate_first
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _human_readable_size(self, size_bytes: int) -> str:
        """Convert bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if abs(size_bytes) < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
    
    def vacuum_analyze(self, table_name: str = None, full: bool = False) -> dict:
        """
        Run VACUUM ANALYZE on a table or entire database.
        
        Args:
            table_name: Specific table, or None for all tables
            full: Whether to run VACUUM FULL (reclaims more space but locks table)
        
        Returns:
            Dict with status and timing
        """
        try:
            start_time = datetime.now()
            
            vacuum_type = "VACUUM FULL ANALYZE" if full else "VACUUM ANALYZE"
            target = table_name if table_name else "entire database"
            
            with self.pool.connection() as conn:
                # VACUUM cannot run inside a transaction
                conn.autocommit = True
                with conn.cursor() as cur:
                    if table_name:
                        cur.execute(f"{vacuum_type} {table_name}")
                    else:
                        cur.execute(f"{vacuum_type}")
                conn.autocommit = False
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': True,
                'target': target,
                'vacuum_type': vacuum_type,
                'elapsed_seconds': elapsed,
                'warning': "VACUUM FULL locks the table" if full else None
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def reindex_table(self, table_name: str) -> dict:
        """
        Reindex a table to reclaim space and improve performance.
        
        Args:
            table_name: Table to reindex
        
        Returns:
            Dict with status and timing
        """
        try:
            start_time = datetime.now()
            
            with self.pool.connection() as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(f"REINDEX TABLE {table_name}")
                conn.autocommit = False
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': True,
                'table': table_name,
                'elapsed_seconds': elapsed
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def check_index_health(self) -> dict:
        """
        Check health of all indexes in the database.
        
        Returns:
            Dict with index statistics and recommendations
        """
        try:
            result = {
                'indexes': [],
                'unused_indexes': [],
                'duplicate_indexes': [],
                'recommendations': []
            }
            
            # Get index statistics
            rows = self.pool.fetchall("""
                SELECT
                    schemaname,
                    relname as table_name,
                    indexrelname as index_name,
                    idx_scan as scans,
                    idx_tup_read as tuples_read,
                    idx_tup_fetch as tuples_fetched,
                    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
                FROM pg_stat_user_indexes
                ORDER BY idx_scan ASC
            """)
            
            for row in rows:
                index_info = dict(row)
                result['indexes'].append(index_info)
                
                # Check for unused indexes (0 scans, not primary key)
                if row['scans'] == 0 and not row['index_name'].endswith('_pkey'):
                    result['unused_indexes'].append({
                        'table': row['table_name'],
                        'index': row['index_name'],
                        'size': row['index_size']
                    })
            
            # Check for duplicate indexes
            dup_rows = self.pool.fetchall("""
                SELECT 
                    pg_size_pretty(sum(pg_relation_size(idx))::bigint) as size,
                    (array_agg(idx))[1] as idx1,
                    (array_agg(idx))[2] as idx2
                FROM (
                    SELECT indexrelid::regclass as idx, 
                           (indrelid::text || E'\n' || indclass::text || E'\n' || 
                            indkey::text || E'\n' || coalesce(indexprs::text,'') || E'\n' || 
                            coalesce(indpred::text,'')) as key
                    FROM pg_index
                ) sub
                GROUP BY key HAVING count(*) > 1
            """)
            
            for row in dup_rows:
                result['duplicate_indexes'].append({
                    'index1': str(row['idx1']),
                    'index2': str(row['idx2']),
                    'wasted_size': row['size']
                })
            
            # Generate recommendations
            if result['unused_indexes']:
                result['recommendations'].append(
                    f"Found {len(result['unused_indexes'])} unused indexes. "
                    "Consider dropping them to save space and improve write performance."
                )
            
            if result['duplicate_indexes']:
                result['recommendations'].append(
                    f"Found {len(result['duplicate_indexes'])} duplicate indexes. "
                    "Remove duplicates to save space."
                )
            
            return result
        except Exception as e:
            return {'error': str(e)}


# Singleton instance
_postgres_db: Optional[PostgresDatabaseManager] = None


def get_postgres_db() -> PostgresDatabaseManager:
    """Get or create the PostgreSQL database manager singleton (sync)"""
    global _postgres_db
    if _postgres_db is None:
        _postgres_db = PostgresDatabaseManager()
        _postgres_db.initialize()
    return _postgres_db


def get_postgres_db_sync() -> PostgresDatabaseManager:
    """Get the PostgreSQL database manager (alias for get_postgres_db)"""
    return get_postgres_db()
