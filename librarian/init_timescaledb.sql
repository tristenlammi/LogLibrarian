-- LogLibrarian TimescaleDB Initialization Script
-- This script sets up the database schema with TimescaleDB hypertables
-- for efficient time-series data storage and querying.

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ============================================
-- Core Tables
-- ============================================

-- Agents table
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    status TEXT NOT NULL,
    public_ip TEXT DEFAULT '',
    display_name TEXT DEFAULT '',
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_last_seen ON agents(last_seen DESC);

-- ============================================
-- Metrics Table (TimescaleDB Hypertable)
-- ============================================

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
);

-- Convert to hypertable with 1-day chunks
SELECT create_hypertable('metrics', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Optimized indexes for time-range queries
CREATE INDEX IF NOT EXISTS idx_metrics_agent_time ON metrics (agent_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics (timestamp DESC);

-- Enable compression for older chunks (after 7 days)
ALTER TABLE metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id',
    timescaledb.compress_orderby = 'timestamp DESC'
);

-- Add compression policy (compress chunks older than 7 days)
SELECT add_compression_policy('metrics', INTERVAL '7 days', if_not_exists => TRUE);

-- ============================================
-- Process Snapshots Table
-- ============================================

CREATE TABLE IF NOT EXISTS process_snapshots (
    id BIGSERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    json_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_process_agent_time ON process_snapshots (agent_id, timestamp DESC);

-- ============================================
-- Alert Tables
-- ============================================

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
);

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
);

CREATE INDEX IF NOT EXISTS idx_alert_agent_active ON active_alerts (agent_id, is_active);
CREATE INDEX IF NOT EXISTS idx_alert_type_active ON active_alerts (alert_type, is_active);

-- ============================================
-- Log Settings Table
-- ============================================

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
);

-- ============================================
-- Raw Logs Table (TimescaleDB Hypertable)
-- ============================================

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
);

-- Convert to hypertable
SELECT create_hypertable('raw_logs', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Optimized indexes
CREATE INDEX IF NOT EXISTS idx_raw_logs_agent_time ON raw_logs (agent_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_raw_logs_severity ON raw_logs (agent_id, severity);
CREATE INDEX IF NOT EXISTS idx_raw_logs_source ON raw_logs (agent_id, source);

-- Enable compression
ALTER TABLE raw_logs SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id',
    timescaledb.compress_orderby = 'timestamp DESC'
);

SELECT add_compression_policy('raw_logs', INTERVAL '7 days', if_not_exists => TRUE);

-- ============================================
-- System Settings Table
-- ============================================

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default settings
INSERT INTO system_settings (key, value, description)
VALUES ('public_app_url', '', 'Public URL for agent connections')
ON CONFLICT (key) DO NOTHING;

-- ============================================
-- Template/Log Deduplication Tables
-- ============================================

CREATE TABLE IF NOT EXISTS templates_metadata (
    template_id TEXT PRIMARY KEY,
    template_text TEXT NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    occurrence_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS log_occurrences (
    id BIGSERIAL,
    template_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    variables JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

SELECT create_hypertable('log_occurrences', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_log_occurrences_template ON log_occurrences (template_id, timestamp DESC);

-- ============================================
-- Continuous Aggregates for Downsampled Data
-- ============================================

-- 1-minute aggregates (for 24-hour views)
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_1min
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
    MIN(ram_percent) AS ram_min
FROM metrics
GROUP BY bucket, agent_id
WITH NO DATA;

-- Refresh policy for 1-minute aggregates
SELECT add_continuous_aggregate_policy('metrics_1min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);

-- 15-minute aggregates (for 7-day views)
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_15min
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
    MAX(ram_percent) AS ram_max
FROM metrics
GROUP BY bucket, agent_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('metrics_15min',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE
);

-- 1-hour aggregates (for 30-day views)
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_1hour
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
    MAX(ram_percent) AS ram_max
FROM metrics
GROUP BY bucket, agent_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('metrics_1hour',
    start_offset => INTERVAL '4 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- ============================================
-- Data Retention Policies
-- ============================================

-- Raw metrics: keep 48 hours (high resolution data)
SELECT add_retention_policy('metrics', INTERVAL '48 hours', if_not_exists => TRUE);

-- Raw logs: keep 7 days
SELECT add_retention_policy('raw_logs', INTERVAL '7 days', if_not_exists => TRUE);

-- Log occurrences: keep 30 days
SELECT add_retention_policy('log_occurrences', INTERVAL '30 days', if_not_exists => TRUE);

-- Note: Continuous aggregates retention is managed by the application
-- because TimescaleDB continuous aggregates don't support add_retention_policy directly.
-- Retention policies for aggregates:
-- - metrics_1min: 7 days
-- - metrics_15min: 30 days  
-- - metrics_1hour: 365 days (1 year)

-- ============================================
-- Retention Policy Tracking Table
-- ============================================

CREATE TABLE IF NOT EXISTS retention_policies (
    table_name TEXT PRIMARY KEY,
    retention_interval TEXT NOT NULL,
    description TEXT,
    last_cleanup TIMESTAMPTZ,
    rows_deleted_last_run BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default retention policies
INSERT INTO retention_policies (table_name, retention_interval, description)
VALUES 
    ('metrics', '48 hours', 'Raw metrics at 1-2 second resolution'),
    ('metrics_1min', '7 days', '1-minute aggregated metrics'),
    ('metrics_15min', '30 days', '15-minute aggregated metrics'),
    ('metrics_1hour', '365 days', '1-hour aggregated metrics (1 year)'),
    ('raw_logs', '7 days', 'Raw log entries'),
    ('log_occurrences', '30 days', 'Log template occurrences')
ON CONFLICT (table_name) DO NOTHING;

-- ============================================
-- Cleanup History Log
-- ============================================

CREATE TABLE IF NOT EXISTS retention_cleanup_log (
    id BIGSERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    table_name TEXT NOT NULL,
    rows_deleted BIGINT NOT NULL DEFAULT 0,
    duration_ms REAL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cleanup_log_time ON retention_cleanup_log (run_timestamp DESC);

-- ============================================
-- Grant Permissions (adjust as needed)
-- ============================================

-- If you have a specific app user, uncomment and modify:
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO loglibrarian_app;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO loglibrarian_app;

-- Verify setup
SELECT 
    hypertable_name
FROM timescaledb_information.hypertables;

SELECT 'TimescaleDB initialization complete!' AS status;
