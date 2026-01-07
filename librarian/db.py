import json
import sqlite3
import os
import shutil
import secrets
import hashlib
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

from models import LogEntry


# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = "log_templates"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 produces 384-dimensional vectors
SQLITE_DB_PATH = "./loglibrarian.db"

# Report storage configuration
REPORT_STORAGE_ROOT = os.getenv("REPORT_STORAGE_ROOT", "/storage/reports/profiles")


class DatabaseManager:
    def __init__(self):
        # Initialize Qdrant client (disabled for now - can run without it)
        try:
            self.qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)
            self._init_qdrant_collection()
            print("Qdrant initialized successfully")
        except Exception as e:
            print(f"Qdrant initialization failed: {e}")
            print("Running without Qdrant - log template search will be disabled")
            self.qdrant_client = None
            self.embedding_model = None
        
        # Initialize SQLite database
        self._init_sqlite_db()
        
        # Cache for template_ids already in Qdrant
        self.template_cache = set()
    
    def _init_qdrant_collection(self):
        """Initialize Qdrant collection if it doesn't exist"""
        try:
            collections = self.qdrant_client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if COLLECTION_NAME not in collection_names:
                self.qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=VECTOR_SIZE,
                        distance=Distance.COSINE
                    )
                )
                print(f"Created Qdrant collection: {COLLECTION_NAME}")
            else:
                print(f"Qdrant collection '{COLLECTION_NAME}' already exists")
        except Exception as e:
            print(f"Error initializing Qdrant: {e}")
            raise
    
    def _init_sqlite_db(self):
        """Initialize SQLite database schema"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Create log_occurrences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS log_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                variables TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for log_occurrences
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_template_id ON log_occurrences(template_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON log_occurrences(timestamp)
        """)
        
        # Create templates_metadata table for tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS templates_metadata (
                template_id TEXT PRIMARY KEY,
                template_text TEXT NOT NULL,
                first_seen DATETIME NOT NULL,
                last_seen DATETIME NOT NULL,
                occurrence_count INTEGER DEFAULT 1
            )
        """)
        
        # Create agents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                status TEXT NOT NULL,
                public_ip TEXT DEFAULT '',
                display_name TEXT DEFAULT '',
                os TEXT DEFAULT '',
                first_seen DATETIME NOT NULL,
                last_seen DATETIME NOT NULL,
                enabled INTEGER DEFAULT 1,
                connection_address TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                uptime_seconds INTEGER DEFAULT 0
            )
        """)
        
        # Migration: Add uptime_seconds column if it doesn't exist (for existing DBs)
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN uptime_seconds INTEGER DEFAULT 0")
            conn.commit()
            print("Migration: Added uptime_seconds column to agents table")
            
            # Reset existing agents to start fresh at 100% uptime
            # Set created_at to NOW so (uptime_seconds / (NOW - created_at)) = 100% initially
            cursor.execute("""
                UPDATE agents 
                SET created_at = CURRENT_TIMESTAMP, uptime_seconds = 0
            """)
            conn.commit()
            print("Migration: Reset created_at for existing agents to start fresh uptime tracking")
        except:
            pass  # Column already exists
        
        # Migration: Add tags column for scribe tagging
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN tags TEXT DEFAULT ''")
            conn.commit()
            print("Migration: Added tags column to agents table")
        except:
            pass  # Column already exists
        
        # Migration: Add auth_token column for agent authentication
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN auth_token_hash TEXT DEFAULT ''")
            conn.commit()
            print("Migration: Added auth_token_hash column to agents table")
        except:
            pass  # Column already exists
        
        # Migration: Add uptime_window column for configurable availability window
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN uptime_window TEXT DEFAULT 'monthly'")
            conn.commit()
            print("Migration: Added uptime_window column to agents table")
        except:
            pass  # Column already exists
        
        # Create agent_heartbeats table for historical uptime tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                status TEXT NOT NULL DEFAULT 'online',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create indexes for efficient heartbeat queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_heartbeats_agent_timestamp 
            ON agent_heartbeats(agent_id, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp 
            ON agent_heartbeats(timestamp)
        """)
        
        # Create metrics table for system metrics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                cpu_percent REAL NOT NULL,
                ram_percent REAL NOT NULL,
                net_up REAL DEFAULT 0.0,
                net_down REAL DEFAULT 0.0,
                disk_read REAL DEFAULT 0.0,
                disk_write REAL DEFAULT 0.0,
                ping REAL DEFAULT 0.0,
                cpu_temp REAL DEFAULT 0.0,
                load_avg REAL DEFAULT 0.0,
                disk_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create index for metrics
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_timestamp ON metrics(agent_id, timestamp)
        """)
        
        # Create process_snapshots table for storing top processes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS process_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                json_data TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create index for process_snapshots
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_snapshot_timestamp ON process_snapshots(agent_id, timestamp)
        """)
        
        # Create alert_rules table for per-agent alert thresholds
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                agent_id TEXT PRIMARY KEY,
                monitor_uptime INTEGER DEFAULT 1,
                cpu_percent_threshold REAL DEFAULT NULL,
                ram_percent_threshold REAL DEFAULT NULL,
                disk_free_percent_threshold REAL DEFAULT NULL,
                cpu_temp_threshold REAL DEFAULT NULL,
                network_bandwidth_mbps_threshold REAL DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create active_alerts table for tracking current alerts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                threshold_value REAL,
                current_value REAL,
                message TEXT NOT NULL,
                severity TEXT DEFAULT 'warning',
                triggered_at DATETIME NOT NULL,
                resolved_at DATETIME DEFAULT NULL,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create indexes for active_alerts
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_alert_agent_active ON active_alerts(agent_id, is_active)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_alert_type_active ON active_alerts(alert_type, is_active)
        """)
        
        # Create agent_log_settings table for per-agent log configuration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_log_settings (
                agent_id TEXT PRIMARY KEY,
                logging_enabled INTEGER DEFAULT 1,
                log_level_threshold TEXT DEFAULT 'ERROR',
                log_retention_days INTEGER DEFAULT 7,
                watch_docker_containers INTEGER DEFAULT 0,
                watch_system_logs INTEGER DEFAULT 1,
                watch_security_logs INTEGER DEFAULT 1,
                troubleshooting_mode INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create raw_logs table for storing actual log entries
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                severity TEXT NOT NULL,
                source TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create indexes for raw_logs (critical for performance)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_logs_agent_timestamp ON raw_logs(agent_id, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_logs_severity ON raw_logs(agent_id, severity)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_logs_source ON raw_logs(agent_id, source)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_logs_cleanup ON raw_logs(agent_id, timestamp)
        """)
        
        # Create system_settings table for global configuration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Initialize default settings
        cursor.execute("""
            INSERT OR IGNORE INTO system_settings (key, value, description)
            VALUES ('public_app_url', '', 'Public URL for agent connections (e.g., https://scribe.example.com)')
        """)
        
        # Initialize janitor/storage settings
        janitor_defaults = [
            ('max_storage_gb', '10', 'Maximum database storage in GB before cleanup triggers'),
            ('min_free_space_gb', '1', 'Minimum free disk space in GB - stops ingestion if below'),
            ('retention_raw_logs_days', '7', 'Days to keep raw log entries'),
            ('retention_metrics_hours', '48', 'Hours to keep raw metrics data'),
            ('retention_process_snapshots_days', '7', 'Days to keep process snapshots'),
        ]
        for key, value, description in janitor_defaults:
            cursor.execute("""
                INSERT OR IGNORE INTO system_settings (key, value, description)
                VALUES (?, ?, ?)
            """, (key, value, description))
        
        # ==================== AI MODULE TABLES ====================
        
        # AI Settings - stores user preferences for AI features
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                provider TEXT DEFAULT 'local',
                local_model_id TEXT DEFAULT 'gemma-2-2b',
                openai_key TEXT DEFAULT '',
                feature_flags TEXT DEFAULT '{"daily_briefing": true, "tips": true, "alert_analysis": true, "post_mortem": true}',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Initialize default AI settings (single row)
        cursor.execute("""
            INSERT OR IGNORE INTO ai_settings (id, provider, local_model_id, feature_flags)
            VALUES (1, 'local', 'gemma-2-2b', '{"daily_briefing": true, "tips": true, "alert_analysis": true, "post_mortem": true}')
        """)
        
        # AI Reports - stores generated AI content (briefings, tips, alerts, post-mortems)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}',
                agent_id TEXT DEFAULT NULL,
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
            )
        """)
        
        # Create indexes for ai_reports
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_reports_type ON ai_reports(type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_reports_created ON ai_reports(created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_reports_unread ON ai_reports(is_read, created_at DESC)
        """)
        
        # AI Model Cache - tracks downloaded local models
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_model_cache (
                model_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                file_hash TEXT DEFAULT '',
                file_size_mb REAL DEFAULT 0,
                is_downloaded INTEGER DEFAULT 0,
                download_progress REAL DEFAULT 0,
                downloaded_at DATETIME,
                last_used_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # AI Conversations - chat thread history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New Chat',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create index for conversations
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_conversations_updated ON ai_conversations(updated_at DESC)
        """)
        
        # AI Messages - individual messages in conversations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES ai_conversations(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for messages
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_messages_conversation ON ai_messages(conversation_id, created_at ASC)
        """)
        
        # =====================================
        # Bookmarks / Uptime Monitoring Tables
        # =====================================
        
        # Monitor Groups - for organizing bookmarks
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitor_groups (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                name TEXT NOT NULL,
                weight INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Bookmarks - the monitors themselves
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                group_id TEXT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('http', 'icmp', 'tcp-port')),
                target TEXT NOT NULL,
                port INTEGER,
                interval_seconds INTEGER DEFAULT 60,
                timeout_seconds INTEGER DEFAULT 10,
                max_retries INTEGER DEFAULT 1,
                retry_interval INTEGER DEFAULT 30,
                resend_notification INTEGER DEFAULT 0,
                upside_down INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                tags TEXT,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES monitor_groups(id) ON DELETE SET NULL
            )
        """)
        
        # Migration: Add tags and description columns if they don't exist
        try:
            cursor.execute("ALTER TABLE bookmarks ADD COLUMN tags TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE bookmarks ADD COLUMN description TEXT")
        except:
            pass
        
        # Bookmark Checks - history of check results
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookmark_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bookmark_id TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status INTEGER NOT NULL CHECK(status IN (0, 1)),
                latency_ms INTEGER,
                message TEXT,
                FOREIGN KEY (bookmark_id) REFERENCES bookmarks(id) ON DELETE CASCADE
            )
        """)
        
        # Index for fast history retrieval
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bookmark_checks_history 
            ON bookmark_checks(bookmark_id, created_at DESC)
        """)
        
        # =====================================
        # Notification & Alert System Tables
        # =====================================
        
        # Notification Channels - Discord, Slack, Email, etc via Apprise
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                name TEXT NOT NULL,
                channel_type TEXT NOT NULL DEFAULT 'custom',
                url TEXT NOT NULL,
                events TEXT DEFAULT '[]',
                enabled INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Notification History - track sent notifications
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES notification_channels(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_history_created
            ON notification_history(created_at DESC)
        """)
        
        # Unified Alert Rules - supports global, agent, bookmark, and profile scopes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                name TEXT NOT NULL,
                description TEXT,
                scope TEXT NOT NULL CHECK(scope IN ('global', 'agent', 'bookmark', 'profile')),
                target_id TEXT,
                profile_id TEXT,
                profile_agents TEXT DEFAULT '[]',
                profile_bookmarks TEXT DEFAULT '[]',
                metric TEXT NOT NULL,
                operator TEXT NOT NULL CHECK(operator IN ('gt', 'lt', 'eq', 'ne', 'gte', 'lte', 'contains')),
                threshold TEXT NOT NULL,
                channels TEXT DEFAULT '[]',
                cooldown_minutes INTEGER DEFAULT 5,
                enabled INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_alert_rules_v2_scope
            ON alert_rules_v2(tenant_id, scope, target_id)
        """)
        
        # Alert Rule Overrides - per-agent/bookmark overrides for global rules
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_rule_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL,
                target_type TEXT NOT NULL CHECK(target_type IN ('agent', 'bookmark')),
                target_id TEXT NOT NULL,
                override_type TEXT NOT NULL CHECK(override_type IN ('disable', 'modify')),
                modified_threshold TEXT,
                modified_channels TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (rule_id) REFERENCES alert_rules_v2(id) ON DELETE CASCADE,
                UNIQUE(rule_id, target_type, target_id)
            )
        """)
        
        # Report Profiles - saved report configurations for multi-tenant reporting
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report_profiles (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                name TEXT NOT NULL,
                description TEXT,
                recipient_emails TEXT,
                monitor_scope_tags TEXT,
                monitor_scope_ids TEXT,
                scribe_scope_tags TEXT,
                scribe_scope_ids TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Index for fast tenant lookup
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_profiles_tenant 
            ON report_profiles(tenant_id)
        """)
        
        # Users table for authentication
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                role TEXT DEFAULT 'user',
                assigned_profile_id TEXT,
                is_setup_complete INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assigned_profile_id) REFERENCES report_profiles(id) ON DELETE SET NULL
            )
        """)
        
        conn.commit()
        
        # Run migrations
        self._run_migrations(cursor)
        
        conn.commit()
        conn.close()
        print(f"SQLite database initialized at {SQLITE_DB_PATH}")
    
    def _run_migrations(self, cursor):
        """Run database migrations for schema updates"""
        try:
            cursor.execute("PRAGMA table_info(agents)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Migration: Add 'enabled' column to agents table if it doesn't exist
            if 'enabled' not in columns:
                print("Running migration: Adding 'enabled' column to agents table")
                cursor.execute("ALTER TABLE agents ADD COLUMN enabled INTEGER DEFAULT 1")
                print("✓ Migration completed: 'enabled' column added")
            
            # Migration: Add 'display_name' column to agents table if it doesn't exist
            if 'display_name' not in columns:
                print("Running migration: Adding 'display_name' column to agents table")
                cursor.execute("ALTER TABLE agents ADD COLUMN display_name TEXT DEFAULT ''")
                print("✓ Migration completed: 'display_name' column added")
            
            # Migration: Add 'connection_address' column to agents table if it doesn't exist
            if 'connection_address' not in columns:
                print("Running migration: Adding 'connection_address' column to agents table")
                cursor.execute("ALTER TABLE agents ADD COLUMN connection_address TEXT DEFAULT ''")
                print("✓ Migration completed: 'connection_address' column added")
            
            # Migration: Add 'system_info' column to agents table if it doesn't exist
            if 'system_info' not in columns:
                print("Running migration: Adding 'system_info' column to agents table")
                cursor.execute("ALTER TABLE agents ADD COLUMN system_info TEXT DEFAULT ''")
                print("✓ Migration completed: 'system_info' column added")
            
            # Server startup: Reset uptime tracking for all agents
            # Since we can't track uptime when the server was down, reset everyone to start fresh
            # Agents will be marked offline by the watchdog if they don't reconnect
            cursor.execute("""
                UPDATE agents 
                SET created_at = datetime('now'), uptime_seconds = 0, status = 'offline'
            """)
            print("✓ Server startup: Reset uptime tracking for all agents (they'll come online when they reconnect)")
            
            # Migration: Add reliability settings to bookmarks table
            cursor.execute("PRAGMA table_info(bookmarks)")
            bookmark_columns = [row[1] for row in cursor.fetchall()]
            
            if 'max_retries' not in bookmark_columns:
                print("Running migration: Adding 'max_retries' column to bookmarks table")
                cursor.execute("ALTER TABLE bookmarks ADD COLUMN max_retries INTEGER DEFAULT 1")
                print("✓ Migration completed: 'max_retries' column added")
            
            if 'retry_interval' not in bookmark_columns:
                print("Running migration: Adding 'retry_interval' column to bookmarks table")
                cursor.execute("ALTER TABLE bookmarks ADD COLUMN retry_interval INTEGER DEFAULT 30")
                print("✓ Migration completed: 'retry_interval' column added")
            
            if 'resend_notification' not in bookmark_columns:
                print("Running migration: Adding 'resend_notification' column to bookmarks table")
                cursor.execute("ALTER TABLE bookmarks ADD COLUMN resend_notification INTEGER DEFAULT 0")
                print("✓ Migration completed: 'resend_notification' column added")
            
            if 'upside_down' not in bookmark_columns:
                print("Running migration: Adding 'upside_down' column to bookmarks table")
                cursor.execute("ALTER TABLE bookmarks ADD COLUMN upside_down INTEGER DEFAULT 0")
                print("✓ Migration completed: 'upside_down' column added")
            
            # Migration: Add RBAC columns to users table
            cursor.execute("PRAGMA table_info(users)")
            user_columns = [row[1] for row in cursor.fetchall()]
            
            if 'role' not in user_columns:
                print("Running migration: Adding 'role' column to users table")
                cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
                # Set existing admins to admin role
                cursor.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1")
                print("✓ Migration completed: 'role' column added")
            
            if 'assigned_profile_id' not in user_columns:
                print("Running migration: Adding 'assigned_profile_id' column to users table")
                cursor.execute("ALTER TABLE users ADD COLUMN assigned_profile_id TEXT")
                print("✓ Migration completed: 'assigned_profile_id' column added")
            
            # Migration: Add profile scope columns to alert_rules_v2 table
            cursor.execute("PRAGMA table_info(alert_rules_v2)")
            alert_rule_columns = [row[1] for row in cursor.fetchall()]
            
            if 'profile_id' not in alert_rule_columns:
                print("Running migration: Adding 'profile_id' column to alert_rules_v2 table")
                cursor.execute("ALTER TABLE alert_rules_v2 ADD COLUMN profile_id TEXT")
                print("✓ Migration completed: 'profile_id' column added")
            
            if 'profile_agents' not in alert_rule_columns:
                print("Running migration: Adding 'profile_agents' column to alert_rules_v2 table")
                cursor.execute("ALTER TABLE alert_rules_v2 ADD COLUMN profile_agents TEXT DEFAULT '[]'")
                print("✓ Migration completed: 'profile_agents' column added")
            
            if 'profile_bookmarks' not in alert_rule_columns:
                print("Running migration: Adding 'profile_bookmarks' column to alert_rules_v2 table")
                cursor.execute("ALTER TABLE alert_rules_v2 ADD COLUMN profile_bookmarks TEXT DEFAULT '[]'")
                print("✓ Migration completed: 'profile_bookmarks' column added")
            
            # Initialize default API key (single-user mode)
            self._init_default_api_key(cursor)
            
        except Exception as e:
            print(f"Migration error: {e}")
    
    def _init_default_api_key(self, cursor):
        """Initialize the default API key for single-user mode"""
        import secrets
        import hashlib
        
        # Check if api_keys table exists with correct schema
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'")
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            # Check if the table has the 'api_key' column (single-user schema)
            cursor.execute("PRAGMA table_info(api_keys)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'api_key' not in columns:
                # Old multi-tenant schema - drop and recreate
                print("Migrating api_keys table to single-user schema...")
                cursor.execute("DROP TABLE api_keys")
                table_exists = False
        
        if not table_exists:
            # Create simple api_keys table for single-user mode
            cursor.execute("""
                CREATE TABLE api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_used_at DATETIME,
                    is_active INTEGER DEFAULT 1
                )
            """)
        
        # Check if default key exists
        cursor.execute("SELECT COUNT(*) FROM api_keys WHERE name = 'Default Key'")
        if cursor.fetchone()[0] == 0:
            print("Creating default API key for single-user mode...")
            
            # Generate a secure API key
            api_key = f"ll_{secrets.token_urlsafe(32)}"
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            key_id = f"key_{secrets.token_hex(8)}"
            now = datetime.utcnow().isoformat()
            
            cursor.execute("""
                INSERT INTO api_keys (id, name, api_key, key_hash, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (key_id, "Default Key", api_key, key_hash, now))
            
            print("")
            print("=" * 60)
            print("🔑 DEFAULT API KEY CREATED")
            print("=" * 60)
            print(f"   {api_key}")
            print("=" * 60)
            print("This key is used automatically for agent installations.")
            print("You can also find it in the dashboard under 'Add Agent'.")
            print("")
    
    def get_default_api_key(self) -> Optional[str]:
        """Get the default API key for agent installations"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT api_key FROM api_keys 
            WHERE name = 'Default Key' AND is_active = 1
            LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()
        
        return row[0] if row else None
    
    def validate_api_key(self, api_key: str) -> bool:
        """Validate an API key - returns True if valid"""
        import hashlib
        
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        cursor.execute("""
            SELECT id FROM api_keys WHERE key_hash = ? AND is_active = 1
        """, (key_hash,))
        row = cursor.fetchone()
        
        if row:
            # Update last used timestamp
            cursor.execute("""
                UPDATE api_keys SET last_used_at = ? WHERE id = ?
            """, (datetime.utcnow().isoformat(), row[0]))
            conn.commit()
        
        conn.close()
        return row is not None
    
    def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text"""
        embedding = self.embedding_model.encode(text)
        return embedding.tolist()
    
    def _template_exists_in_qdrant(self, template_id: str) -> bool:
        """Check if template exists in Qdrant"""
        # Check cache first
        if template_id in self.template_cache:
            return True
        
        try:
            # Search for exact template_id in Qdrant
            result = self.qdrant_client.retrieve(
                collection_name=COLLECTION_NAME,
                ids=[template_id]
            )
            exists = len(result) > 0
            if exists:
                self.template_cache.add(template_id)
            return exists
        except Exception:
            return False
    
    def _upsert_template_to_qdrant(self, template_id: str, template_text: str):
        """Insert new template into Qdrant"""
        try:
            # Generate embedding
            embedding = self._generate_embedding(template_text)
            
            # Create point
            point = PointStruct(
                id=template_id,
                vector=embedding,
                payload={
                    "text": template_text,
                    "template_id": template_id
                }
            )
            
            # Upsert to Qdrant
            self.qdrant_client.upsert(
                collection_name=COLLECTION_NAME,
                points=[point]
            )
            
            # Add to cache
            self.template_cache.add(template_id)
            print(f"Upserted new template to Qdrant: {template_id[:16]}...")
        except Exception as e:
            print(f"Error upserting template to Qdrant: {e}")
            raise
    
    def _insert_occurrence_to_sqlite(self, log: LogEntry):
        """Insert log occurrence into SQLite"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Serialize variables to JSON
            variables_json = json.dumps(log.variables)
            
            # Insert occurrence
            cursor.execute("""
                INSERT INTO log_occurrences (template_id, timestamp, variables)
                VALUES (?, ?, ?)
            """, (log.template_id, log.timestamp, variables_json))
            
            # Update or insert template metadata
            cursor.execute("""
                INSERT INTO templates_metadata (template_id, template_text, first_seen, last_seen, occurrence_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(template_id) DO UPDATE SET
                    last_seen = ?,
                    occurrence_count = occurrence_count + 1
            """, (
                log.template_id,
                log.template_text,
                log.timestamp,
                log.timestamp,
                log.timestamp
            ))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error inserting occurrence to SQLite: {e}")
            raise
        finally:
            conn.close()
    
    def ingest_logs(self, logs: List[LogEntry]) -> dict:
        """
        Ingest a batch of logs into the database
        
        For each log:
        1. Check if template_id exists in Qdrant
        2. If NEW: Generate embedding and upsert to Qdrant
        3. ALWAYS: Insert occurrence to SQLite
        
        Returns summary statistics
        """
        new_templates = 0
        total_occurrences = 0
        errors = []
        
        for log in logs:
            try:
                # Check if template is new
                is_new = not self._template_exists_in_qdrant(log.template_id)
                
                # If new template, add to Qdrant
                if is_new:
                    self._upsert_template_to_qdrant(log.template_id, log.template_text)
                    new_templates += 1
                
                # Always insert occurrence to SQLite
                self._insert_occurrence_to_sqlite(log)
                total_occurrences += 1
                
            except Exception as e:
                errors.append(f"Error processing log {log.template_id[:16]}: {str(e)}")
                continue
        
        return {
            "new_templates": new_templates,
            "total_occurrences": total_occurrences,
            "errors": errors
        }
    
    def search_similar_templates(self, query: str, limit: int = 10) -> List[dict]:
        """Search for similar log templates using semantic search"""
        try:
            # Generate embedding for query
            query_embedding = self._generate_embedding(query)
            
            # Search in Qdrant
            results = self.qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_embedding,
                limit=limit
            )
            
            return [
                {
                    "template_id": result.id,
                    "template_text": result.payload.get("text"),
                    "score": result.score
                }
                for result in results
            ]
        except Exception as e:
            print(f"Error searching templates: {e}")
            return []
    
    def get_template_occurrences(self, template_id: str, limit: int = 100) -> List[dict]:
        """Get recent occurrences of a specific template"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT timestamp, variables, created_at
            FROM log_occurrences
            WHERE template_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (template_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "timestamp": row[0],
                "variables": json.loads(row[1]) if row[1] else [],
                "created_at": row[2]
            }
            for row in rows
        ]
    
    def upsert_agent(self, agent_id: str, hostname: str, status: str, last_seen: datetime = None, 
                     public_ip: str = "", connection_address: str = None, os: str = "") -> None:
        """Upsert agent information including public IP, connection address, and OS.
        
        When an agent comes online after being offline, reset uptime tracking so it starts fresh at 100%.
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            if last_seen is None:
                last_seen = datetime.utcnow()
            if connection_address is None:
                connection_address = ""
            # First ensure os column exists (for existing DBs)
            try:
                cursor.execute("ALTER TABLE agents ADD COLUMN os TEXT DEFAULT ''")
                conn.commit()
            except:
                pass  # Column already exists
            
            # Check if this is an offline -> online transition
            cursor.execute("SELECT status FROM agents WHERE agent_id = ?", (agent_id,))
            row = cursor.fetchone()
            was_offline = row and row[0] == 'offline'
            is_new = row is None
            
            if status == 'online' and (was_offline or is_new):
                # Reset uptime tracking when agent comes online
                # This ensures they start at 100% uptime from this moment
                cursor.execute("""
                    INSERT INTO agents (agent_id, hostname, status, public_ip, os, first_seen, last_seen, connection_address, created_at, uptime_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 0)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        hostname = ?,
                        status = ?,
                        public_ip = ?,
                        os = CASE WHEN ? != '' THEN ? ELSE os END,
                        last_seen = ?,
                        connection_address = ?,
                        created_at = datetime('now'),
                        uptime_seconds = 0
                """, (
                    agent_id,
                    hostname,
                    status,
                    public_ip,
                    os,
                    last_seen,
                    last_seen,
                    connection_address,
                    hostname,
                    status,
                    public_ip,
                    os,
                    os,
                    last_seen,
                    connection_address
                ))
            else:
                # Normal update - don't touch uptime tracking
                cursor.execute("""
                    INSERT INTO agents (agent_id, hostname, status, public_ip, os, first_seen, last_seen, connection_address)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        hostname = ?,
                        status = ?,
                        public_ip = ?,
                        os = CASE WHEN ? != '' THEN ? ELSE os END,
                        last_seen = ?,
                        connection_address = ?
                """, (
                    agent_id,
                    hostname,
                    status,
                    public_ip,
                    os,
                    last_seen,
                    last_seen,
                    connection_address,
                    hostname,
                    status,
                    public_ip,
                    os,
                    os,
                    last_seen,
                    connection_address
                ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error upserting agent: {e}")
            raise
        finally:
            conn.close()
    
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
        
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "UPDATE agents SET auth_token_hash = ? WHERE agent_id = ?",
                (token_hash, agent_id)
            )
            conn.commit()
            print(f"🔐 Generated auth token for agent {agent_id}")
            return token
        except Exception as e:
            conn.rollback()
            print(f"Error generating agent token: {e}")
            raise
        finally:
            conn.close()
    
    def validate_agent_token(self, agent_id: str, token: str) -> Tuple[bool, str]:
        """
        Validate an agent's authentication token.
        
        Returns:
            Tuple of (is_valid, reason)
            - (True, "valid") if token is valid
            - (True, "new_agent") if agent doesn't exist yet (first registration)
            - (True, "no_token") if agent exists but has no token (legacy agent, will get token)
            - (False, "invalid_token") if token doesn't match
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT auth_token_hash FROM agents WHERE agent_id = ?",
                (agent_id,)
            )
            row = cursor.fetchone()
            
            # Agent doesn't exist yet - this is first registration
            if row is None:
                return (True, "new_agent")
            
            stored_hash = row[0]
            
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
                
        finally:
            conn.close()
    
    def get_agent_has_token(self, agent_id: str) -> bool:
        """Check if an agent has an auth token set."""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT auth_token_hash FROM agents WHERE agent_id = ?",
                (agent_id,)
            )
            row = cursor.fetchone()
            return row is not None and bool(row[0])
        finally:
            conn.close()
    
    def bulk_insert_metrics(self, agent_id: str, metrics: List[dict], load_avg: float = 0.0) -> int:
        """
        Bulk insert metrics for an agent
        
        Args:
            agent_id: Agent identifier
            metrics: List of metric dicts with keys: timestamp, cpu_percent, ram_percent,
                    net_sent_bps, net_recv_bps, disk_read_bps, disk_write_bps,
                    ping_latency_ms, cpu_temp, gpu_percent, gpu_temp, gpu_name, is_vm, disks
            load_avg: 15-minute load average (same for all metrics in batch)
        
        Returns:
            Number of rows inserted
        """
        if not metrics:
            return 0
        
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Prepare data for bulk insert
            rows = []
            for metric in metrics:
                # Build extra data JSON with disks and GPU info
                extra_data = {
                    'disks': metric.get('disks', []),
                    'cpu_name': metric.get('cpu_name', ''),
                    'gpu_percent': metric.get('gpu_percent', 0.0),
                    'gpu_temp': metric.get('gpu_temp', 0.0),
                    'gpu_name': metric.get('gpu_name', ''),
                    'is_vm': metric.get('is_vm', False)
                }
                
                rows.append((
                    agent_id,
                    metric['timestamp'],
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
            
            # Use executemany for efficient bulk insert
            cursor.executemany("""
                INSERT INTO metrics (
                    agent_id, timestamp, cpu_percent, ram_percent,
                    net_up, net_down, disk_read, disk_write,
                    ping, cpu_temp, load_avg, disk_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            
            conn.commit()
            inserted_count = cursor.rowcount
            
            print(f"Bulk inserted {inserted_count} metrics for agent {agent_id}")
            return inserted_count
            
        except Exception as e:
            conn.rollback()
            print(f"Error bulk inserting metrics: {e}")
            raise
        finally:
            conn.close()
    
    def get_agent_metrics(
        self, 
        agent_id: str, 
        limit: int = 100,
        start_time: str = None,
        end_time: str = None,
        downsample: str = None
    ) -> List[dict]:
        """Get metrics for an agent with optional time range and downsampling"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Build query based on downsampling and time range
        if downsample == '10min':
            # Aggregate by 10 minutes
            query = """
                SELECT 
                    datetime((strftime('%s', timestamp) / 600) * 600, 'unixepoch') as timestamp,
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
                    MAX(created_at) as created_at
                FROM metrics
                WHERE agent_id = ?
            """
        elif downsample == 'hour':
            # Aggregate by hour
            query = """
                SELECT 
                    strftime('%Y-%m-%d %H:00:00', timestamp) as timestamp,
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
                    MAX(created_at) as created_at
                FROM metrics
                WHERE agent_id = ?
            """
        elif downsample == 'day':
            # Aggregate by day
            query = """
                SELECT 
                    strftime('%Y-%m-%d 00:00:00', timestamp) as timestamp,
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
                    MAX(created_at) as created_at
                FROM metrics
                WHERE agent_id = ?
            """
        else:
            # Raw data
            query = """
                SELECT timestamp, cpu_percent, ram_percent,
                       net_up, net_down, disk_read, disk_write,
                       ping, cpu_temp, load_avg, disk_json, created_at
                FROM metrics
                WHERE agent_id = ?
            """
        
        # Add time range filters - use datetime() for proper comparison
        # This handles both ISO formats (with T) and space-separated formats
        params = [agent_id]
        if start_time:
            # Convert start_time to comparable format
            # Replace 'Z' with '+00:00' and 'T' with space for SQLite compatibility
            normalized_start = start_time.replace('T', ' ').replace('Z', '+00:00')
            query += " AND datetime(timestamp) >= datetime(?)"
            params.append(normalized_start)
        if end_time:
            normalized_end = end_time.replace('T', ' ').replace('Z', '+00:00')
            query += " AND datetime(timestamp) <= datetime(?)"
            params.append(normalized_end)
        
        # Add grouping for downsampling
        if downsample:
            if downsample == '10min':
                query += " GROUP BY datetime((strftime('%s', timestamp) / 600) * 600, 'unixepoch')"
            elif downsample == 'hour':
                query += " GROUP BY strftime('%Y-%m-%d %H:00:00', timestamp)"
            else:  # day
                query += " GROUP BY strftime('%Y-%m-%d', timestamp)"
        
        # When limit is specified without time range, get the NEWEST records first
        # then reverse for chronological order (charts need oldest->newest)
        needs_reverse = limit and not start_time and not end_time
        
        if needs_reverse:
            # Get newest first to apply LIMIT to recent data
            query += " ORDER BY timestamp DESC"
        else:
            # With time range, just order chronologically
            query += " ORDER BY timestamp ASC"
        
        # Add limit if provided
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        # Reverse to get chronological order if we selected newest-first
        if needs_reverse:
            rows = list(reversed(rows))
        
        results = []
        for row in rows:
            # Parse disk_json which may contain disks and GPU data
            extra_data = {}
            if row[10]:
                try:
                    parsed = json.loads(row[10])
                    # Handle both old format (list of disks) and new format (dict with disks + GPU)
                    if isinstance(parsed, list):
                        extra_data = {'disks': parsed}
                    else:
                        extra_data = parsed
                except:
                    extra_data = {}
            
            results.append({
                "timestamp": row[0],
                "cpu_percent": row[1],
                "ram_percent": row[2],
                "net_sent_bps": row[3],  # Match frontend naming
                "net_recv_bps": row[4],
                "disk_read_bps": row[5],
                "disk_write_bps": row[6],
                "ping_latency_ms": row[7],
                "cpu_temp": row[8],
                "load_avg": row[9],
                "disks": extra_data.get('disks', []),
                "cpu_name": extra_data.get('cpu_name', ''),
                "gpu_percent": extra_data.get('gpu_percent', 0.0),
                "gpu_temp": extra_data.get('gpu_temp', 0.0),
                "gpu_name": extra_data.get('gpu_name', ''),
                "is_vm": extra_data.get('is_vm', False),
                "created_at": row[11]
            })
        
        return results
    
    def get_all_agents(self) -> List[dict]:
        """Get all registered agents with uptime data"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # First ensure os column exists (for existing DBs)
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN os TEXT DEFAULT ''")
            conn.commit()
        except:
            pass  # Column already exists
        
        # Ensure uptime_seconds column exists
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN uptime_seconds INTEGER DEFAULT 0")
            conn.commit()
        except:
            pass  # Column already exists
        
        # Ensure tags column exists
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN tags TEXT DEFAULT ''")
            conn.commit()
        except:
            pass  # Column already exists
        
        # Ensure uptime_window column exists
        try:
            cursor.execute("ALTER TABLE agents ADD COLUMN uptime_window TEXT DEFAULT 'monthly'")
            conn.commit()
        except:
            pass  # Column already exists
        
        cursor.execute("""
            SELECT agent_id, hostname, status, public_ip, first_seen, last_seen, 
                   enabled, display_name, connection_address, system_info, os,
                   uptime_seconds, created_at, tags, uptime_window
            FROM agents
            ORDER BY last_seen DESC
        """)
        
        rows = cursor.fetchall()
        
        # Define uptime window durations in seconds
        UPTIME_WINDOWS = {
            'daily': 86400,      # 24 hours
            'weekly': 604800,    # 7 days
            'monthly': 2592000,  # 30 days
            'quarterly': 7776000, # 90 days
            'yearly': 31536000   # 365 days
        }
        
        results = []
        for row in rows:
            system_info = {}
            if len(row) > 9 and row[9]:
                try:
                    system_info = json.loads(row[9])
                except:
                    pass
            
            # Get uptime_window setting (default to 'monthly')
            uptime_window = row[14] if len(row) > 14 and row[14] else 'monthly'
            window_seconds = UPTIME_WINDOWS.get(uptime_window, UPTIME_WINDOWS['monthly'])
            
            # Calculate availability percentage based on heartbeat records within the window
            agent_id = row[0]
            status = row[2]
            created_at = row[12] if len(row) > 12 else row[4]  # fallback to first_seen
            uptime_seconds_accumulated = row[11] if len(row) > 11 else 0
            
            # Calculate availability from heartbeats within the configured window
            availability_percentage = self._calculate_window_availability(
                agent_id, window_seconds, created_at, status, cursor if conn else None
            )
            
            results.append({
                "agent_id": agent_id,
                "hostname": row[1],
                "status": status,
                "public_ip": row[3],
                "first_seen": row[4],
                "last_seen": row[5],
                "enabled": row[6] if len(row) > 6 else True,
                "display_name": row[7] if len(row) > 7 else "",
                "connection_address": row[8] if len(row) > 8 else "",
                "system_info": system_info,
                "os": row[10] if len(row) > 10 else "",
                "uptime_seconds": uptime_seconds_accumulated or 0,
                "uptime_percentage": availability_percentage,
                "uptime_window": uptime_window,
                "created_at": created_at,
                "tags": row[13] if len(row) > 13 else ""
            })
        
        conn.close()
        return results
    
    def _calculate_window_availability(self, agent_id: str, window_seconds: int, 
                                        created_at: str, current_status: str,
                                        cursor=None) -> float:
        """
        Calculate availability percentage based on heartbeat records within a time window.
        
        Uses the formula: (Actual Online Seconds / Expected Seconds) * 100
        
        Args:
            agent_id: The agent to calculate availability for
            window_seconds: The time window in seconds (e.g., 86400 for daily)
            created_at: Agent's creation timestamp
            current_status: Current agent status ('online' or 'offline')
            cursor: Optional database cursor (will create one if not provided)
        
        Returns:
            Availability percentage (0.0 to 100.0)
        """
        need_close = False
        if cursor is None:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            need_close = True
        
        try:
            now = datetime.now()
            window_start = now - timedelta(seconds=window_seconds)
            
            # Parse created_at to determine adjusted start
            try:
                if created_at:
                    if 'T' in str(created_at):
                        created_dt = datetime.fromisoformat(str(created_at).replace('Z', '').split('+')[0])
                    else:
                        created_dt = datetime.strptime(str(created_at)[:19], '%Y-%m-%d %H:%M:%S')
                else:
                    created_dt = window_start
            except:
                created_dt = window_start
            
            # Adjusted start: MAX(window_start, agent_created)
            adjusted_start = max(window_start, created_dt)
            total_possible_seconds = (now - adjusted_start).total_seconds()
            
            # Grace period: If less than 60 seconds of data, return 100%
            if total_possible_seconds < 60:
                return 100.0
            
            # Query heartbeats within the window
            cursor.execute("""
                SELECT timestamp, status FROM agent_heartbeats
                WHERE agent_id = ?
                AND timestamp >= ?
                AND timestamp <= ?
                ORDER BY timestamp ASC
            """, (agent_id, adjusted_start.strftime('%Y-%m-%d %H:%M:%S'), 
                  now.strftime('%Y-%m-%d %H:%M:%S')))
            
            heartbeats = cursor.fetchall()
            
            if not heartbeats:
                # No heartbeats in window - check if agent is currently online
                # If online now, give benefit of doubt (could be newly online)
                if current_status == 'online':
                    return 100.0
                return 0.0
            
            # Calculate uptime from heartbeats
            # Each heartbeat covers ~60s (heartbeat interval) + 60s grace = 120s TTL
            heartbeat_ttl = 120  # seconds
            uptime_seconds = 0
            prev_time = adjusted_start
            
            for hb in heartbeats:
                hb_time_str = hb[0]
                try:
                    if 'T' in str(hb_time_str):
                        hb_time = datetime.fromisoformat(str(hb_time_str).replace('Z', '').split('+')[0])
                    else:
                        hb_time = datetime.strptime(str(hb_time_str)[:19], '%Y-%m-%d %H:%M:%S')
                except:
                    continue
                
                gap = (hb_time - prev_time).total_seconds()
                
                # If gap is within TTL, count as uptime
                if gap <= heartbeat_ttl:
                    uptime_seconds += gap
                else:
                    # Only count TTL portion as uptime
                    uptime_seconds += heartbeat_ttl
                
                prev_time = hb_time
            
            # Handle time from last heartbeat to now
            last_hb_str = heartbeats[-1][0]
            try:
                if 'T' in str(last_hb_str):
                    last_hb = datetime.fromisoformat(str(last_hb_str).replace('Z', '').split('+')[0])
                else:
                    last_hb = datetime.strptime(str(last_hb_str)[:19], '%Y-%m-%d %H:%M:%S')
                
                remaining = (now - last_hb).total_seconds()
                if remaining <= heartbeat_ttl:
                    uptime_seconds += remaining
                else:
                    uptime_seconds += heartbeat_ttl
            except:
                pass
            
            # Calculate percentage, cap at 100%
            uptime_seconds = min(uptime_seconds, total_possible_seconds)
            availability = (uptime_seconds / total_possible_seconds) * 100
            return round(min(availability, 100.0), 2)
            
        except Exception as e:
            print(f"Error calculating window availability for {agent_id}: {e}")
            return 100.0  # Default to 100% on error
        finally:
            if need_close:
                conn.close()
    
    def update_agent_uptime_window(self, agent_id: str, uptime_window: str) -> bool:
        """
        Update the availability window setting for an agent.
        
        Args:
            agent_id: The agent to update
            uptime_window: One of 'daily', 'weekly', 'monthly', 'quarterly', 'yearly'
        
        Returns:
            True if successful, False otherwise
        """
        valid_windows = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
        if uptime_window not in valid_windows:
            raise ValueError(f"Invalid uptime_window: {uptime_window}. Must be one of {valid_windows}")
        
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE agents SET uptime_window = ? WHERE agent_id = ?
            """, (uptime_window, agent_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating uptime_window for {agent_id}: {e}")
            return False
        finally:
            conn.close()
    
    def get_agents_for_user(self, user: dict) -> List[dict]:
        """Get agents filtered by user's role and assigned profile.
        
        - Admin role: Returns ALL agents
        - User role: Returns only agents matching their assigned profile's scope
        - User with no profile: Returns empty list
        """
        all_agents = self.get_all_agents()
        
        # Admin users see everything
        if user.get("role") == "admin" or user.get("is_admin"):
            return all_agents
        
        # User with no assigned profile sees nothing
        profile_id = user.get("assigned_profile_id")
        if not profile_id:
            return []
        
        # Get the profile to determine scope
        profile = self.get_report_profile_by_id(profile_id)
        if not profile:
            return []
        
        return self._filter_agents_by_profile(all_agents, profile)
    
    def _filter_agents_by_profile(self, agents: List[dict], profile: dict) -> List[dict]:
        """Filter agents based on profile scope settings."""
        scribe_scope_ids = profile.get("scribe_scope_ids") or []
        scribe_scope_tags = profile.get("scribe_scope_tags") or []
        
        # If no scope defined, include all agents
        if not scribe_scope_ids and not scribe_scope_tags:
            return agents
        
        filtered = []
        for agent in agents:
            # Check if agent ID is in scope
            if agent["agent_id"] in scribe_scope_ids:
                filtered.append(agent)
                continue
            
            # Check if any agent tag matches scope tags
            agent_tags = []
            if agent.get("tags"):
                if isinstance(agent["tags"], list):
                    agent_tags = agent["tags"]
                elif isinstance(agent["tags"], str):
                    agent_tags = [t.strip() for t in agent["tags"].split(",") if t.strip()]
            
            for tag in agent_tags:
                if tag in scribe_scope_tags:
                    filtered.append(agent)
                    break
        
        return filtered
    
    def get_bookmarks_for_user(self, user: dict) -> List[dict]:
        """Get bookmarks filtered by user's role and assigned profile.
        
        - Admin role: Returns ALL bookmarks (ignores tenant_id)
        - User role: Returns only bookmarks matching their assigned profile's scope
        - User with no profile: Returns empty list
        """
        # Admin users see everything - fetch all bookmarks ignoring tenant
        if user.get("role") == "admin" or user.get("is_admin"):
            return self._get_all_bookmarks_no_tenant()
        
        # User with no assigned profile sees nothing
        profile_id = user.get("assigned_profile_id")
        if not profile_id:
            return []
        
        # Get the profile to determine scope
        profile = self.get_report_profile_by_id(profile_id)
        if not profile:
            return []
        
        # Get all bookmarks and filter
        all_bookmarks = self._get_all_bookmarks_no_tenant()
        return self._filter_bookmarks_by_profile(all_bookmarks, profile)
    
    def _get_all_bookmarks_no_tenant(self) -> List[dict]:
        """Get ALL bookmarks regardless of tenant_id"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
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
                ORDER BY b.name ASC
            """)
            
            bookmarks = []
            for row in cursor.fetchall():
                bookmark = dict(row)
                # Parse tags if stored as JSON or comma-separated
                if bookmark.get('tags'):
                    try:
                        bookmark['tags'] = json.loads(bookmark['tags'])
                    except:
                        # Assume comma-separated
                        bookmark['tags'] = [t.strip() for t in bookmark['tags'].split(',') if t.strip()]
                else:
                    bookmark['tags'] = []
                bookmarks.append(bookmark)
            
            return bookmarks
        finally:
            conn.close()
    
    def _filter_bookmarks_by_profile(self, bookmarks: List[dict], profile: dict) -> List[dict]:
        """Filter bookmarks based on profile scope settings."""
        monitor_scope_ids = profile.get("monitor_scope_ids") or []
        monitor_scope_tags = profile.get("monitor_scope_tags") or []
        
        # If no scope defined, include all bookmarks
        if not monitor_scope_ids and not monitor_scope_tags:
            return bookmarks
        
        filtered = []
        for bookmark in bookmarks:
            # Check if bookmark ID is in scope
            if bookmark["id"] in monitor_scope_ids:
                filtered.append(bookmark)
                continue
            
            # Check if any bookmark tag matches scope tags
            bookmark_tags = bookmark.get("tags") or []
            if isinstance(bookmark_tags, str):
                bookmark_tags = [t.strip() for t in bookmark_tags.split(",") if t.strip()]
            
            for tag in bookmark_tags:
                if tag in monitor_scope_tags:
                    filtered.append(bookmark)
                    break
        
        return filtered
    
    def get_report_profile_by_id(self, profile_id: str) -> Optional[dict]:
        """Get a report profile by ID (without tenant check - for RBAC)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM report_profiles WHERE id = ?", (profile_id,))
            row = cursor.fetchone()
            return self._parse_report_profile(dict(row)) if row else None
        finally:
            conn.close()
    
    def record_agent_heartbeat(self, agent_id: str, status: str = 'online') -> None:
        """Record a heartbeat for an agent for historical uptime tracking"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO agent_heartbeats (agent_id, timestamp, status)
                VALUES (?, datetime('now'), ?)
            """, (agent_id, status))
            conn.commit()
        except Exception as e:
            # Table might not exist yet, try to create it
            try:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS agent_heartbeats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent_id TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        status TEXT NOT NULL DEFAULT 'online',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_heartbeats_agent_timestamp 
                    ON agent_heartbeats(agent_id, timestamp DESC)
                """)
                cursor.execute("""
                    INSERT INTO agent_heartbeats (agent_id, timestamp, status)
                    VALUES (?, datetime('now'), ?)
                """, (agent_id, status))
                conn.commit()
            except Exception as e2:
                print(f"Error recording heartbeat: {e2}")
        finally:
            conn.close()
    
    def record_bulk_heartbeats(self, agent_ids: list, status: str = 'online') -> int:
        """Record heartbeats for multiple agents at once (more efficient)"""
        if not agent_ids:
            return 0
            
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Ensure table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_heartbeats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    status TEXT NOT NULL DEFAULT 'online',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Bulk insert
            cursor.executemany("""
                INSERT INTO agent_heartbeats (agent_id, timestamp, status)
                VALUES (?, datetime('now'), ?)
            """, [(agent_id, status) for agent_id in agent_ids])
            
            conn.commit()
            return len(agent_ids)
        except Exception as e:
            print(f"Error recording bulk heartbeats: {e}")
            return 0
        finally:
            conn.close()
    
    def calculate_agent_uptime(self, agent_id: str, start_date: datetime, end_date: datetime = None, 
                               heartbeat_ttl_seconds: int = 120) -> dict:
        """
        Calculate historical uptime for an agent based on heartbeat records.
        
        Implements "Smart Start" logic:
        - Adjusted_Start = MAX(Report_Start_Date, Agent_Created_At)
        - Total_Possible_Seconds = (Report_End_Date - Adjusted_Start).total_seconds()
        - Percentage = (Uptime_Seconds / Total_Possible_Seconds) * 100, capped at 100%
        
        Args:
            agent_id: The agent to calculate uptime for
            start_date: Start of the reporting period
            end_date: End of the reporting period (defaults to now)
            heartbeat_ttl_seconds: How long a heartbeat is considered valid (2x expected interval)
                                   Default 120s = 2 minutes (assuming 60s heartbeat interval)
        
        Returns:
            dict with uptime_percentage, total_seconds, uptime_seconds, downtime_seconds
            Returns uptime_percentage=None if agent didn't exist during period or period too short
        """
        if end_date is None:
            end_date = datetime.utcnow()
            
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Step 1: Get the agent's creation timestamp (first_seen)
            cursor.execute("""
                SELECT first_seen FROM agents WHERE agent_id = ?
            """, (agent_id,))
            row = cursor.fetchone()
            
            if not row or not row[0]:
                return {
                    "uptime_percentage": None,
                    "total_seconds": 0,
                    "uptime_seconds": 0,
                    "downtime_seconds": 0,
                    "heartbeat_count": 0,
                    "status": "unknown_agent"
                }
            
            # Parse first_seen timestamp
            first_seen_str = row[0]
            try:
                if 'T' in str(first_seen_str):
                    agent_created = datetime.fromisoformat(str(first_seen_str).replace('Z', '').split('+')[0])
                else:
                    agent_created = datetime.strptime(str(first_seen_str)[:19], '%Y-%m-%d %H:%M:%S')
            except Exception as e:
                print(f"[DEBUG] Error parsing first_seen for {agent_id}: {e}")
                agent_created = start_date
            
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
            
            # Total_Possible_Seconds = (Report_End_Date - Adjusted_Start)
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
            
            # Step 4: Get ALL heartbeats for this agent (we need to find the first one)
            cursor.execute("""
                SELECT MIN(timestamp) FROM agent_heartbeats WHERE agent_id = ?
            """, (agent_id,))
            first_hb_row = cursor.fetchone()
            
            # If no heartbeats ever exist, check if agent has been around long enough
            if not first_hb_row or not first_hb_row[0]:
                # No heartbeats ever - deployment might have failed
                return {
                    "uptime_percentage": 0.0,
                    "total_seconds": total_possible_seconds,
                    "uptime_seconds": 0,
                    "downtime_seconds": total_possible_seconds,
                    "heartbeat_count": 0,
                    "status": "no_heartbeats_ever",
                    "adjusted_start": adjusted_start.isoformat()
                }
            
            # Parse first heartbeat timestamp
            first_hb_str = first_hb_row[0]
            try:
                if 'T' in str(first_hb_str):
                    first_heartbeat_time = datetime.fromisoformat(str(first_hb_str).replace('Z', '').split('+')[0])
                else:
                    first_heartbeat_time = datetime.strptime(str(first_hb_str)[:19], '%Y-%m-%d %H:%M:%S')
            except:
                first_heartbeat_time = adjusted_start
            
            # CRITICAL FIX: If heartbeat recording started AFTER the agent was created,
            # we can only measure from when heartbeats started, not from agent creation
            # This prevents penalizing agents that existed before heartbeat tracking was added
            measurement_start = max(adjusted_start, first_heartbeat_time)
            
            # Recalculate total possible seconds from when we can actually measure
            total_possible_seconds = (end_date - measurement_start).total_seconds()
            
            if total_possible_seconds < 60:
                # Not enough data to calculate - return 100% (benefit of doubt)
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
            # Use strftime for consistent format matching the stored timestamps (space, not T)
            cursor.execute("""
                SELECT timestamp, status FROM agent_heartbeats
                WHERE agent_id = ?
                AND timestamp >= ?
                AND timestamp <= ?
                ORDER BY timestamp ASC
            """, (agent_id, measurement_start.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S')))
            
            heartbeats = cursor.fetchall()
            
            if not heartbeats:
                # No heartbeats in measurement window = offline during this period
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
                hb_time_str = hb[0]
                
                try:
                    if 'T' in str(hb_time_str):
                        hb_time = datetime.fromisoformat(str(hb_time_str).replace('Z', '').split('+')[0])
                    else:
                        hb_time = datetime.strptime(str(hb_time_str)[:19], '%Y-%m-%d %H:%M:%S')
                except:
                    continue
                
                gap = (hb_time - prev_time).total_seconds()
                
                # If gap is within TTL, count entire gap as uptime
                if gap <= heartbeat_ttl_seconds:
                    uptime_seconds += gap
                else:
                    # Only the TTL portion before this heartbeat was "up"
                    uptime_seconds += heartbeat_ttl_seconds
                
                prev_time = hb_time
            
            # Step 7: Handle time from last heartbeat to end_date
            last_hb_time_str = heartbeats[-1][0]
            try:
                if 'T' in str(last_hb_time_str):
                    last_hb_time = datetime.fromisoformat(str(last_hb_time_str).replace('Z', '').split('+')[0])
                else:
                    last_hb_time = datetime.strptime(str(last_hb_time_str)[:19], '%Y-%m-%d %H:%M:%S')
                
                remaining = (end_date - last_hb_time).total_seconds()
                if remaining <= heartbeat_ttl_seconds:
                    uptime_seconds += remaining
                else:
                    uptime_seconds += heartbeat_ttl_seconds
            except:
                pass
            
            # Step 8: Calculate percentage with cap at 100%
            uptime_seconds = min(uptime_seconds, total_possible_seconds)
            downtime_seconds = total_possible_seconds - uptime_seconds
            uptime_percentage = (uptime_seconds / total_possible_seconds) * 100
            
            # Cap at 100% due to potential timestamp mismatches
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
            
        except Exception as e:
            print(f"Error calculating agent uptime: {e}")
            import traceback
            traceback.print_exc()
            return {
                "uptime_percentage": None,
                "total_seconds": 0,
                "uptime_seconds": 0,
                "downtime_seconds": 0,
                "heartbeat_count": 0,
                "status": "error",
                "error": str(e)
            }
        finally:
            conn.close()
    
    def cleanup_old_heartbeats(self, days_to_keep: int = 30) -> int:
        """Remove heartbeats older than the specified number of days"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM agent_heartbeats
                WHERE timestamp < datetime('now', ? || ' days')
            """, (f"-{days_to_keep}",))
            
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        except Exception as e:
            print(f"Error cleaning up heartbeats: {e}")
            return 0
        finally:
            conn.close()
    
    def delete_agent(self, agent_id: str) -> None:
        """Delete an agent and all its associated data"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Delete from all tables (log_occurrences doesn't have agent_id, so skip it)
            cursor.execute("DELETE FROM process_snapshots WHERE agent_id = ?", (agent_id,))
            cursor.execute("DELETE FROM metrics WHERE agent_id = ?", (agent_id,))
            cursor.execute("DELETE FROM agent_heartbeats WHERE agent_id = ?", (agent_id,))
            cursor.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            
            conn.commit()
            print(f"Deleted agent {agent_id} and all associated data")
        except Exception as e:
            conn.rollback()
            print(f"Error deleting agent: {e}")
            raise
        finally:
            conn.close()
    
    def disable_agent(self, agent_id: str) -> None:
        """Disable an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE agents SET enabled = 0, status = 'disabled' WHERE agent_id = ?", (agent_id,))
            conn.commit()
            print(f"Disabled agent {agent_id}")
        except Exception as e:
            conn.rollback()
            print(f"Error disabling agent: {e}")
            raise
        finally:
            conn.close()
    
    def enable_agent(self, agent_id: str) -> None:
        """Enable an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE agents SET enabled = 1, status = 'offline' WHERE agent_id = ?", (agent_id,))
            conn.commit()
            print(f"Enabled agent {agent_id}")
        except Exception as e:
            conn.rollback()
            print(f"Error enabling agent: {e}")
            raise
        finally:
            conn.close()
    
    def update_agent_tags(self, agent_id: str, tags: str) -> None:
        """Update the tags for an agent (comma-separated string)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE agents SET tags = ? WHERE agent_id = ?", (tags, agent_id))
            conn.commit()
            print(f"Updated tags for agent {agent_id} to '{tags}'")
        except Exception as e:
            conn.rollback()
            print(f"Error updating agent tags: {e}")
            raise
        finally:
            conn.close()
    
    def update_agent_display_name(self, agent_id: str, display_name: str) -> None:
        """Update the display name of an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE agents SET display_name = ? WHERE agent_id = ?", (display_name, agent_id))
            conn.commit()
            print(f"Updated display name for agent {agent_id} to '{display_name}'")
        except Exception as e:
            conn.rollback()
            print(f"Error updating agent display name: {e}")
            raise
        finally:
            conn.close()
    
    def update_agent_system_info(self, agent_id: str, system_info: dict) -> None:
        """Update the system info JSON for an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            json_data = json.dumps(system_info)
            cursor.execute("UPDATE agents SET system_info = ? WHERE agent_id = ?", (json_data, agent_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error updating agent system info: {e}")
            raise
        finally:
            conn.close()
    
    def get_agent_system_info(self, agent_id: str) -> dict:
        """Get system info for an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT system_info FROM agents WHERE agent_id = ?", (agent_id,))
            row = cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return {}
        except Exception as e:
            print(f"Error getting agent system info: {e}")
            return {}
        finally:
            conn.close()
    
    def insert_process_snapshot(self, agent_id: str, timestamp: datetime, processes: List[dict]) -> None:
        """Insert a process snapshot for an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            json_data = json.dumps(processes)
            
            cursor.execute("""
                INSERT INTO process_snapshots (agent_id, timestamp, json_data)
                VALUES (?, ?, ?)
            """, (agent_id, timestamp, json_data))
            
            conn.commit()
            print(f"Inserted process snapshot for agent {agent_id} with {len(processes)} processes")
            
        except Exception as e:
            conn.rollback()
            print(f"Error inserting process snapshot: {e}")
            raise
        finally:
            conn.close()
    
    def get_latest_process_snapshot(self, agent_id: str) -> dict:
        """Get the latest process snapshot for an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT timestamp, json_data, created_at
            FROM process_snapshots
            WHERE agent_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (agent_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            "timestamp": row[0],
            "processes": json.loads(row[1]),
            "created_at": row[2]
        }

    def get_process_snapshots_range(self, agent_id: str, start_time: datetime, end_time: datetime) -> List[dict]:
        """Get all process snapshots for an agent within a time range"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT timestamp, json_data, created_at
            FROM process_snapshots
            WHERE agent_id = ?
            AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
        """, (agent_id, start_time.isoformat(), end_time.isoformat()))
        
        rows = cursor.fetchall()
        conn.close()
        
        snapshots = []
        for row in rows:
            snapshots.append({
                "timestamp": row[0],
                "processes": json.loads(row[1]),
                "created_at": row[2]
            })
        
        return snapshots

    def query_logs(
        self, 
        agent_id: str = None,
        level: str = None, 
        search: str = None, 
        limit: int = 50, 
        offset: int = 0
    ) -> dict:
        """
        Query logs with filtering and pagination
        
        Args:
            agent_id: Filter by agent (optional - for future use)
            level: Filter by log level (error, warning, info, debug)
            search: Full-text search on template_text
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            dict with logs, total_count, and metadata
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Build query dynamically based on filters
        where_clauses = []
        params = []
        
        # Level filtering (search for level keywords in template_text)
        if level:
            level_upper = level.upper()
            where_clauses.append("(tm.template_text LIKE ? OR tm.template_text LIKE ? OR tm.template_text LIKE ?)")
            params.extend([f"%[{level_upper}]%", f"%{level_upper}:%", f"%<{level_upper}>%"])
        
        # Full-text search on template_text
        if search:
            where_clauses.append("tm.template_text LIKE ?")
            params.append(f"%{search}%")
        
        # Build WHERE clause
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
        
        # Count total matching logs (for pagination metadata)
        count_query = f"""
            SELECT COUNT(*)
            FROM log_occurrences lo
            JOIN templates_metadata tm ON lo.template_id = tm.template_id
            {where_sql}
        """
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()[0]
        
        # Fetch logs with limit and offset
        query = f"""
            SELECT 
                lo.id,
                lo.template_id,
                tm.template_text,
                lo.timestamp,
                lo.variables,
                lo.created_at
            FROM log_occurrences lo
            JOIN templates_metadata tm ON lo.template_id = tm.template_id
            {where_sql}
            ORDER BY lo.timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        # Parse results
        logs = []
        for row in rows:
            # Reconstruct full log message by replacing tokens with variables
            template_text = row[2]
            variables = json.loads(row[4]) if row[4] else []
            
            # Simple reconstruction: replace <TOKEN> with actual values
            full_message = template_text
            for var in variables:
                # Replace first occurrence of <...> pattern
                if '<' in full_message:
                    start = full_message.find('<')
                    end = full_message.find('>', start)
                    if end != -1:
                        full_message = full_message[:start] + str(var) + full_message[end+1:]
            
            # Extract log level from template
            level_detected = "INFO"  # default
            for lvl in ["ERROR", "WARN", "WARNING", "INFO", "DEBUG", "FATAL", "TRACE"]:
                if lvl in template_text.upper():
                    level_detected = lvl if lvl != "WARN" else "WARNING"
                    break
            
            logs.append({
                "id": row[0],
                "template_id": row[1],
                "template": row[2],
                "message": full_message,
                "level": level_detected,
                "timestamp": row[3],
                "variables": variables,
                "created_at": row[5]
            })
        
        return {
            "logs": logs,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total_count
        }
    
    # ======================
    # Alert Rules Management
    # ======================
    
    def get_alert_rules(self, agent_id: str) -> dict:
        """Get alert rules for an agent, creating default rules if none exist"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                agent_id,
                monitor_uptime,
                cpu_percent_threshold,
                ram_percent_threshold,
                disk_free_percent_threshold,
                cpu_temp_threshold,
                network_bandwidth_mbps_threshold,
                created_at,
                updated_at
            FROM alert_rules
            WHERE agent_id = ?
        """, (agent_id,))
        
        row = cursor.fetchone()
        
        if not row:
            # Create default rules for this agent
            cursor.execute("""
                INSERT INTO alert_rules (agent_id, monitor_uptime)
                VALUES (?, 1)
            """, (agent_id,))
            conn.commit()
            
            return {
                "agent_id": agent_id,
                "monitor_uptime": True,
                "cpu_percent_threshold": None,
                "ram_percent_threshold": None,
                "disk_free_percent_threshold": None,
                "cpu_temp_threshold": None,
                "network_bandwidth_mbps_threshold": None,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
        
        conn.close()
        
        return {
            "agent_id": row[0],
            "monitor_uptime": bool(row[1]),
            "cpu_percent_threshold": row[2],
            "ram_percent_threshold": row[3],
            "disk_free_percent_threshold": row[4],
            "cpu_temp_threshold": row[5],
            "network_bandwidth_mbps_threshold": row[6],
            "created_at": row[7],
            "updated_at": row[8]
        }
    
    def update_alert_rules(self, agent_id: str, rules: dict) -> dict:
        """Update alert rules for an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Ensure rules exist first
        self.get_alert_rules(agent_id)
        
        cursor.execute("""
            UPDATE alert_rules
            SET 
                monitor_uptime = ?,
                cpu_percent_threshold = ?,
                ram_percent_threshold = ?,
                disk_free_percent_threshold = ?,
                cpu_temp_threshold = ?,
                network_bandwidth_mbps_threshold = ?,
                updated_at = ?
            WHERE agent_id = ?
        """, (
            1 if rules.get("monitor_uptime", True) else 0,
            rules.get("cpu_percent_threshold"),
            rules.get("ram_percent_threshold"),
            rules.get("disk_free_percent_threshold"),
            rules.get("cpu_temp_threshold"),
            rules.get("network_bandwidth_mbps_threshold"),
            datetime.now().isoformat(),
            agent_id
        ))
        
        conn.commit()
        conn.close()
        
        return self.get_alert_rules(agent_id)
    
    def get_active_alerts(self, agent_id: str = None) -> list:
        """Get active alerts, optionally filtered by agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        if agent_id:
            cursor.execute("""
                SELECT 
                    id, agent_id, alert_type, threshold_value, current_value,
                    message, severity, triggered_at, resolved_at, is_active, created_at
                FROM active_alerts
                WHERE agent_id = ? AND is_active = 1
                ORDER BY triggered_at DESC
            """, (agent_id,))
        else:
            cursor.execute("""
                SELECT 
                    id, agent_id, alert_type, threshold_value, current_value,
                    message, severity, triggered_at, resolved_at, is_active, created_at
                FROM active_alerts
                WHERE is_active = 1
                ORDER BY triggered_at DESC
            """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "id": row[0],
                "agent_id": row[1],
                "alert_type": row[2],
                "threshold_value": row[3],
                "current_value": row[4],
                "message": row[5],
                "severity": row[6],
                "triggered_at": row[7],
                "resolved_at": row[8],
                "is_active": bool(row[9]),
                "created_at": row[10]
            }
            for row in rows
        ]
    
    def get_alert_history(self, agent_id: str = None, limit: int = 100) -> list:
        """Get alert history (including resolved alerts)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        if agent_id:
            cursor.execute("""
                SELECT 
                    id, agent_id, alert_type, threshold_value, current_value,
                    message, severity, triggered_at, resolved_at, is_active, created_at
                FROM active_alerts
                WHERE agent_id = ?
                ORDER BY triggered_at DESC
                LIMIT ?
            """, (agent_id, limit))
        else:
            cursor.execute("""
                SELECT 
                    id, agent_id, alert_type, threshold_value, current_value,
                    message, severity, triggered_at, resolved_at, is_active, created_at
                FROM active_alerts
                ORDER BY triggered_at DESC
                LIMIT ?
            """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "id": row[0],
                "agent_id": row[1],
                "alert_type": row[2],
                "threshold_value": row[3],
                "current_value": row[4],
                "message": row[5],
                "severity": row[6],
                "triggered_at": row[7],
                "resolved_at": row[8],
                "is_active": bool(row[9]),
                "created_at": row[10]
            }
            for row in rows
        ]
    
    def create_alert(self, agent_id: str, alert_type: str, threshold_value: float, 
                     current_value: float, message: str, severity: str = "warning") -> dict:
        """Create a new active alert if one doesn't already exist for this type"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Check if active alert of same type already exists
        cursor.execute("""
            SELECT id FROM active_alerts
            WHERE agent_id = ? AND alert_type = ? AND is_active = 1
        """, (agent_id, alert_type))
        
        existing = cursor.fetchone()
        if existing:
            # Update the current value on existing alert
            cursor.execute("""
                UPDATE active_alerts
                SET current_value = ?
                WHERE id = ?
            """, (current_value, existing[0]))
            conn.commit()
            conn.close()
            return {"id": existing[0], "action": "updated"}
        
        # Create new alert
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO active_alerts 
            (agent_id, alert_type, threshold_value, current_value, message, severity, triggered_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (agent_id, alert_type, threshold_value, current_value, message, severity, now))
        
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        print(f"🚨 Alert created: {alert_type} for {agent_id} - {message}")
        return {"id": alert_id, "action": "created"}
    
    def resolve_alert(self, agent_id: str, alert_type: str) -> bool:
        """Resolve an active alert"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE active_alerts
            SET is_active = 0, resolved_at = ?
            WHERE agent_id = ? AND alert_type = ? AND is_active = 1
        """, (now, agent_id, alert_type))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if affected > 0:
            print(f"✅ Alert resolved: {alert_type} for {agent_id}")
        
        return affected > 0
    
    def resolve_alert_by_id(self, alert_id: int) -> bool:
        """Resolve an alert by ID"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE active_alerts
            SET is_active = 0, resolved_at = ?
            WHERE id = ? AND is_active = 1
        """, (now, alert_id))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    def evaluate_metrics(self, agent_id: str, metrics: dict) -> list:
        """Evaluate metrics against alert rules and create/resolve alerts"""
        rules = self.get_alert_rules(agent_id)
        triggered_alerts = []
        
        # CPU Check
        if rules.get("cpu_percent_threshold") is not None:
            threshold = rules["cpu_percent_threshold"]
            current = metrics.get("cpu_percent", 0)
            if current > threshold:
                alert = self.create_alert(
                    agent_id=agent_id,
                    alert_type="cpu_high",
                    threshold_value=threshold,
                    current_value=current,
                    message=f"CPU usage {current:.1f}% exceeds threshold {threshold}%",
                    severity="warning" if current < threshold * 1.2 else "critical"
                )
                if alert["action"] == "created":
                    triggered_alerts.append(alert)
            else:
                self.resolve_alert(agent_id, "cpu_high")
        
        # RAM Check
        if rules.get("ram_percent_threshold") is not None:
            threshold = rules["ram_percent_threshold"]
            current = metrics.get("ram_percent", 0)
            if current > threshold:
                alert = self.create_alert(
                    agent_id=agent_id,
                    alert_type="ram_high",
                    threshold_value=threshold,
                    current_value=current,
                    message=f"RAM usage {current:.1f}% exceeds threshold {threshold}%",
                    severity="warning" if current < threshold * 1.2 else "critical"
                )
                if alert["action"] == "created":
                    triggered_alerts.append(alert)
            else:
                self.resolve_alert(agent_id, "ram_high")
        
        # CPU Temperature Check
        if rules.get("cpu_temp_threshold") is not None:
            threshold = rules["cpu_temp_threshold"]
            current = metrics.get("cpu_temp", 0)
            if current > 0 and current > threshold:  # Only check if temp is available
                alert = self.create_alert(
                    agent_id=agent_id,
                    alert_type="cpu_temp_high",
                    threshold_value=threshold,
                    current_value=current,
                    message=f"CPU temperature {current:.1f}°C exceeds threshold {threshold}°C",
                    severity="warning" if current < threshold + 10 else "critical"
                )
                if alert["action"] == "created":
                    triggered_alerts.append(alert)
            else:
                self.resolve_alert(agent_id, "cpu_temp_high")
        
        # Network Bandwidth Check (combined up+down in Mbps)
        if rules.get("network_bandwidth_mbps_threshold") is not None:
            threshold = rules["network_bandwidth_mbps_threshold"]
            net_up_mbps = metrics.get("net_up", 0) / 1_000_000  # Convert bps to Mbps
            net_down_mbps = metrics.get("net_down", 0) / 1_000_000
            current = max(net_up_mbps, net_down_mbps)  # Check the higher of the two
            if current > threshold:
                alert = self.create_alert(
                    agent_id=agent_id,
                    alert_type="network_high",
                    threshold_value=threshold,
                    current_value=current,
                    message=f"Network bandwidth {current:.2f} Mbps exceeds threshold {threshold} Mbps",
                    severity="warning"
                )
                if alert["action"] == "created":
                    triggered_alerts.append(alert)
            else:
                self.resolve_alert(agent_id, "network_high")
        
        # Disk Free Space Check (from disk_json)
        if rules.get("disk_free_percent_threshold") is not None:
            threshold = rules["disk_free_percent_threshold"]
            disks = metrics.get("disks", [])
            
            for disk in disks:
                if isinstance(disk, dict):
                    total = disk.get("total", 1)
                    free = disk.get("free", 0)
                    mount = disk.get("mount", "unknown")
                    free_percent = (free / total * 100) if total > 0 else 100
                    
                    if free_percent < threshold:  # Alert if FREE space is BELOW threshold
                        alert = self.create_alert(
                            agent_id=agent_id,
                            alert_type=f"disk_low_{mount}",
                            threshold_value=threshold,
                            current_value=free_percent,
                            message=f"Disk {mount} has only {free_percent:.1f}% free (threshold: {threshold}%)",
                            severity="warning" if free_percent > threshold * 0.5 else "critical"
                        )
                        if alert["action"] == "created":
                            triggered_alerts.append(alert)
                    else:
                        self.resolve_alert(agent_id, f"disk_low_{mount}")
        
        return triggered_alerts
    
    def get_agents_to_check_uptime(self) -> list:
        """Get agents with monitor_uptime enabled for heartbeat checking"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                a.agent_id,
                a.hostname,
                a.last_seen,
                ar.monitor_uptime
            FROM agents a
            LEFT JOIN alert_rules ar ON a.agent_id = ar.agent_id
            WHERE a.enabled = 1 AND (ar.monitor_uptime = 1 OR ar.monitor_uptime IS NULL)
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "agent_id": row[0],
                "hostname": row[1],
                "last_seen": row[2],
                "monitor_uptime": bool(row[3]) if row[3] is not None else True
            }
            for row in rows
        ]
    
    def check_agent_offline(self, agent_id: str, hostname: str, last_seen: str, 
                           offline_threshold_seconds: int = 120) -> dict:
        """Check if an agent is offline and create/resolve alerts accordingly"""
        try:
            # Parse last_seen timestamp
            if 'T' in last_seen:
                last_seen_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00').replace('+00:00', ''))
            else:
                last_seen_dt = datetime.strptime(last_seen.split('+')[0].split('-')[0] if '+' in last_seen or last_seen.count('-') > 2 else last_seen, 
                                                  "%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"Error parsing last_seen for {agent_id}: {e}")
            return {"checked": False, "error": str(e)}
        
        seconds_offline = (datetime.now() - last_seen_dt).total_seconds()
        
        if seconds_offline > offline_threshold_seconds:
            # Agent is offline
            alert = self.create_alert(
                agent_id=agent_id,
                alert_type="agent_offline",
                threshold_value=offline_threshold_seconds,
                current_value=seconds_offline,
                message=f"Agent '{hostname}' has been offline for {int(seconds_offline)}s",
                severity="critical"
            )
            # Mark agent as offline in database
            self.set_agent_status(agent_id, 'offline')
            return {"checked": True, "offline": True, "seconds_offline": seconds_offline, "alert": alert}
        else:
            # Agent is online - resolve any offline alert
            self.resolve_alert(agent_id, "agent_offline")
            return {"checked": True, "offline": False, "seconds_offline": seconds_offline}
    
    def set_agent_status(self, agent_id: str, status: str) -> bool:
        """Set agent status (online/offline)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE agents SET status = ? WHERE agent_id = ?
            """, (status, agent_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error setting agent status: {e}")
            return False
        finally:
            conn.close()
    
    def increment_online_agents_uptime(self, increment_seconds: int = 60) -> int:
        """
        Increment uptime_seconds for all agents that are currently online.
        Called by the heartbeat monitor every 60 seconds.
        
        Returns: Number of agents updated
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE agents 
                SET uptime_seconds = uptime_seconds + ?
                WHERE status = 'online'
            """, (increment_seconds,))
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"Error incrementing uptime: {e}")
            return 0
        finally:
            conn.close()
    
    def mark_stale_agents_offline(self, offline_threshold_seconds: int = 120) -> List[str]:
        """
        Mark agents as offline if their last_seen exceeds the threshold.
        
        Returns: List of agent_ids that were marked offline
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Find agents that should be marked offline
            # Using SQLite's datetime functions
            cursor.execute("""
                SELECT agent_id, hostname 
                FROM agents 
                WHERE status = 'online' 
                AND datetime(last_seen) < datetime('now', ? || ' seconds')
            """, (f'-{offline_threshold_seconds}',))
            
            stale_agents = cursor.fetchall()
            
            if stale_agents:
                # Mark them offline
                agent_ids = [a[0] for a in stale_agents]
                placeholders = ','.join(['?' for _ in agent_ids])
                cursor.execute(f"""
                    UPDATE agents SET status = 'offline' 
                    WHERE agent_id IN ({placeholders})
                """, agent_ids)
                conn.commit()
                
                # Create alerts for each
                for agent_id, hostname in stale_agents:
                    self.create_alert(
                        agent_id=agent_id,
                        alert_type="agent_offline",
                        threshold_value=offline_threshold_seconds,
                        current_value=offline_threshold_seconds,
                        message=f"Agent '{hostname}' went offline (no heartbeat for {offline_threshold_seconds}s)",
                        severity="critical"
                    )
                
                return agent_ids
            
            return []
        except Exception as e:
            print(f"Error marking stale agents offline: {e}")
            return []
        finally:
            conn.close()
    
    def get_agent_uptime_stats(self, agent_id: str) -> dict:
        """Get uptime statistics for an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    uptime_seconds,
                    created_at,
                    first_seen,
                    status
                FROM agents 
                WHERE agent_id = ?
            """, (agent_id,))
            
            row = cursor.fetchone()
            if not row:
                return {"error": "Agent not found"}
            
            uptime_seconds = row[0] or 0
            created_at = row[1] or row[2]  # Use created_at, fallback to first_seen
            status = row[3]
            
            # Calculate total possible seconds since creation
            try:
                if created_at:
                    if 'T' in str(created_at):
                        created_dt = datetime.fromisoformat(str(created_at).replace('Z', '+00:00').replace('+00:00', ''))
                    else:
                        created_dt = datetime.strptime(str(created_at)[:19], '%Y-%m-%d %H:%M:%S')
                    
                    total_seconds = (datetime.now() - created_dt).total_seconds()
                    uptime_percentage = (uptime_seconds / total_seconds * 100) if total_seconds > 0 else 0
                else:
                    total_seconds = 0
                    uptime_percentage = 0
            except Exception as e:
                print(f"Error calculating uptime percentage: {e}")
                total_seconds = 0
                uptime_percentage = 0
            
            return {
                "agent_id": agent_id,
                "status": status,
                "uptime_seconds": uptime_seconds,
                "total_seconds": int(total_seconds),
                "uptime_percentage": round(uptime_percentage, 2),
                "created_at": created_at
            }
        except Exception as e:
            print(f"Error getting uptime stats: {e}")
            return {"error": str(e)}
        finally:
            conn.close()

    # ==========================================
    # Notification Channels (Apprise-based)
    # ==========================================
    
    def get_notification_channels(self, tenant_id: str = "default") -> list:
        """Get all notification channels for a tenant"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT id, tenant_id, name, channel_type, url, events, enabled, created_at, updated_at
                FROM notification_channels
                WHERE tenant_id = ?
                ORDER BY created_at DESC
            """, (tenant_id,))
            
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "tenant_id": row["tenant_id"],
                    "name": row["name"],
                    "channel_type": row["channel_type"],
                    "url": row["url"],
                    "url_masked": self._mask_url(row["url"]),
                    "events": json.loads(row["events"]) if row["events"] else [],
                    "enabled": bool(row["enabled"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
                for row in rows
            ]
        except Exception as e:
            print(f"Error fetching notification channels: {e}")
            return []
        finally:
            conn.close()
    
    def _mask_url(self, url: str) -> str:
        """Mask sensitive parts of notification URLs for display"""
        if not url:
            return ""
        # Mask webhook tokens and API keys
        import re
        # Discord webhooks
        url = re.sub(r'(discord\.com/api/webhooks/\d+/)[^/\s]+', r'\1***', url)
        # Slack webhooks
        url = re.sub(r'(hooks\.slack\.com/services/)[^\s]+', r'\1***', url)
        # Generic token/key masking
        url = re.sub(r'([?&](token|key|apikey|api_key)=)[^&\s]+', r'\1***', url, flags=re.IGNORECASE)
        return url
    
    def create_notification_channel(self, name: str, channel_type: str, url: str, 
                                    events: list = None, tenant_id: str = "default") -> dict:
        """Create a new notification channel"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO notification_channels (tenant_id, name, channel_type, url, events, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """, (tenant_id, name, channel_type, url, json.dumps(events or ["all"]), now, now))
            
            channel_id = cursor.lastrowid
            conn.commit()
            
            return {
                "id": channel_id,
                "name": name,
                "channel_type": channel_type,
                "url_masked": self._mask_url(url),
                "events": events or ["all"],
                "enabled": True,
                "created_at": now
            }
        except Exception as e:
            print(f"Error creating notification channel: {e}")
            raise
        finally:
            conn.close()
    
    def update_notification_channel(self, channel_id: int, updates: dict, tenant_id: str = "default") -> dict:
        """Update a notification channel"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Build dynamic update query
            set_parts = []
            values = []
            
            if "name" in updates:
                set_parts.append("name = ?")
                values.append(updates["name"])
            if "channel_type" in updates:
                set_parts.append("channel_type = ?")
                values.append(updates["channel_type"])
            if "url" in updates:
                set_parts.append("url = ?")
                values.append(updates["url"])
            if "events" in updates:
                set_parts.append("events = ?")
                values.append(json.dumps(updates["events"]))
            if "enabled" in updates:
                set_parts.append("enabled = ?")
                values.append(1 if updates["enabled"] else 0)
            
            set_parts.append("updated_at = ?")
            values.append(datetime.now().isoformat())
            
            values.extend([channel_id, tenant_id])
            
            cursor.execute(f"""
                UPDATE notification_channels
                SET {', '.join(set_parts)}
                WHERE id = ? AND tenant_id = ?
            """, values)
            
            conn.commit()
            
            if cursor.rowcount == 0:
                return None
            
            # Fetch updated record
            channels = self.get_notification_channels(tenant_id)
            return next((c for c in channels if c["id"] == channel_id), None)
        except Exception as e:
            print(f"Error updating notification channel: {e}")
            raise
        finally:
            conn.close()
    
    def delete_notification_channel(self, channel_id: int, tenant_id: str = "default") -> bool:
        """Delete a notification channel"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM notification_channels
                WHERE id = ? AND tenant_id = ?
            """, (channel_id, tenant_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting notification channel: {e}")
            return False
        finally:
            conn.close()
    
    def get_notification_channel_by_id(self, channel_id: int, tenant_id: str = "default") -> dict:
        """Get a single notification channel by ID"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT id, tenant_id, name, channel_type, url, events, enabled, created_at, updated_at
                FROM notification_channels
                WHERE id = ? AND tenant_id = ?
            """, (channel_id, tenant_id))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "name": row["name"],
                "channel_type": row["channel_type"],
                "url": row["url"],
                "url_masked": self._mask_url(row["url"]),
                "events": json.loads(row["events"]) if row["events"] else [],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        except Exception as e:
            print(f"Error fetching notification channel: {e}")
            return None
        finally:
            conn.close()
    
    def add_notification_history(self, channel_id: int, event_type: str, title: str, 
                                 body: str, status: str, error: str = None) -> int:
        """Record a notification attempt"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO notification_history (channel_id, event_type, title, body, status, error)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (channel_id, event_type, title, body, status, error))
            
            history_id = cursor.lastrowid
            conn.commit()
            return history_id
        except Exception as e:
            print(f"Error recording notification history: {e}")
            return None
        finally:
            conn.close()
    
    def get_notification_history(self, tenant_id: str = "default", limit: int = 100) -> list:
        """Get notification history for a tenant"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT h.id, h.channel_id, c.name as channel_name, h.event_type, 
                       h.title, h.body, h.status, h.error, h.created_at
                FROM notification_history h
                JOIN notification_channels c ON h.channel_id = c.id
                WHERE c.tenant_id = ?
                ORDER BY h.created_at DESC
                LIMIT ?
            """, (tenant_id, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error fetching notification history: {e}")
            return []
        finally:
            conn.close()

    # ==========================================
    # Unified Alert Rules (V2 - Global/Agent/Bookmark)
    # ==========================================
    
    def get_alert_rules_v2(self, tenant_id: str = "default", scope: str = None, 
                           target_id: str = None) -> list:
        """Get alert rules, optionally filtered by scope and target"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT id, tenant_id, name, description, scope, target_id, metric, 
                       operator, threshold, channels, cooldown_minutes, enabled, 
                       created_at, updated_at, profile_id, profile_agents, profile_bookmarks
                FROM alert_rules_v2
                WHERE tenant_id = ?
            """
            params = [tenant_id]
            
            if scope:
                query += " AND scope = ?"
                params.append(scope)
            
            if target_id:
                query += " AND (target_id = ? OR target_id IS NULL)"
                params.append(target_id)
            
            query += " ORDER BY scope, created_at DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
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
                    "channels": json.loads(row["channels"]) if row["channels"] else [],
                    "cooldown_minutes": row["cooldown_minutes"],
                    "enabled": bool(row["enabled"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "profile_id": row["profile_id"],
                    "profile_agents": json.loads(row["profile_agents"]) if row["profile_agents"] else [],
                    "profile_bookmarks": json.loads(row["profile_bookmarks"]) if row["profile_bookmarks"] else []
                }
                for row in rows
            ]
        except Exception as e:
            print(f"Error fetching alert rules: {e}")
            return []
        finally:
            conn.close()
    
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
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO alert_rules_v2 
                (tenant_id, name, description, scope, target_id, metric, operator, 
                 threshold, channels, cooldown_minutes, enabled, created_at, updated_at,
                 profile_id, profile_agents, profile_bookmarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """, (tenant_id, name, description, scope, target_id, metric, operator,
                  threshold, json.dumps(channels or []), cooldown_minutes, now, now,
                  profile_id, json.dumps(profile_agents or []), json.dumps(profile_bookmarks or [])))
            
            rule_id = cursor.lastrowid
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
                "created_at": now,
                "profile_id": profile_id,
                "profile_agents": profile_agents or [],
                "profile_bookmarks": profile_bookmarks or []
            }
        except Exception as e:
            print(f"Error creating alert rule: {e}")
            raise
        finally:
            conn.close()
    
    def update_alert_rule_v2(self, rule_id: int, updates: dict, tenant_id: str = "default") -> dict:
        """Update an alert rule"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            set_parts = []
            values = []
            
            for field in ["name", "description", "scope", "target_id", "metric", 
                          "operator", "threshold", "cooldown_minutes", "profile_id"]:
                if field in updates:
                    set_parts.append(f"{field} = ?")
                    values.append(updates[field])
            
            if "channels" in updates:
                set_parts.append("channels = ?")
                values.append(json.dumps(updates["channels"]))
            
            if "profile_agents" in updates:
                set_parts.append("profile_agents = ?")
                values.append(json.dumps(updates["profile_agents"]))
            
            if "profile_bookmarks" in updates:
                set_parts.append("profile_bookmarks = ?")
                values.append(json.dumps(updates["profile_bookmarks"]))
                set_parts.append("channels = ?")
                values.append(json.dumps(updates["channels"]))
            
            if "enabled" in updates:
                set_parts.append("enabled = ?")
                values.append(1 if updates["enabled"] else 0)
            
            set_parts.append("updated_at = ?")
            values.append(datetime.now().isoformat())
            
            values.extend([rule_id, tenant_id])
            
            cursor.execute(f"""
                UPDATE alert_rules_v2
                SET {', '.join(set_parts)}
                WHERE id = ? AND tenant_id = ?
            """, values)
            
            conn.commit()
            
            if cursor.rowcount == 0:
                return None
            
            # Fetch updated rule
            rules = self.get_alert_rules_v2(tenant_id)
            return next((r for r in rules if r["id"] == rule_id), None)
        except Exception as e:
            print(f"Error updating alert rule: {e}")
            raise
        finally:
            conn.close()
    
    def delete_alert_rule_v2(self, rule_id: int, tenant_id: str = "default") -> bool:
        """Delete an alert rule"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM alert_rules_v2
                WHERE id = ? AND tenant_id = ?
            """, (rule_id, tenant_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting alert rule: {e}")
            return False
        finally:
            conn.close()
    
    def get_effective_rules_for_target(self, target_type: str, target_id: str, 
                                       tenant_id: str = "default") -> list:
        """
        Get all effective alert rules for a target (agent or bookmark),
        including global rules with any overrides applied.
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Get global rules
            cursor.execute("""
                SELECT r.*, o.override_type, o.modified_threshold, o.modified_channels
                FROM alert_rules_v2 r
                LEFT JOIN alert_rule_overrides o 
                    ON r.id = o.rule_id 
                    AND o.target_type = ? 
                    AND o.target_id = ?
                WHERE r.tenant_id = ? AND r.scope = 'global' AND r.enabled = 1
            """, (target_type, target_id, tenant_id))
            
            global_rules = cursor.fetchall()
            
            # Get target-specific rules
            cursor.execute("""
                SELECT * FROM alert_rules_v2
                WHERE tenant_id = ? AND scope = ? AND target_id = ? AND enabled = 1
            """, (tenant_id, target_type, target_id))
            
            specific_rules = cursor.fetchall()
            
            effective = []
            
            # Process global rules with overrides
            for row in global_rules:
                if row["override_type"] == "disable":
                    continue  # Skip disabled rules
                
                rule = {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "scope": "global",
                    "metric": row["metric"],
                    "operator": row["operator"],
                    "threshold": row["modified_threshold"] if row["override_type"] == "modify" else row["threshold"],
                    "channels": json.loads(row["modified_channels"]) if row["modified_channels"] else json.loads(row["channels"]),
                    "cooldown_minutes": row["cooldown_minutes"],
                    "is_overridden": row["override_type"] is not None,
                    "override_type": row["override_type"]
                }
                effective.append(rule)
            
            # Add target-specific rules
            for row in specific_rules:
                rule = {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "scope": row["scope"],
                    "metric": row["metric"],
                    "operator": row["operator"],
                    "threshold": row["threshold"],
                    "channels": json.loads(row["channels"]) if row["channels"] else [],
                    "cooldown_minutes": row["cooldown_minutes"],
                    "is_overridden": False,
                    "override_type": None
                }
                effective.append(rule)
            
            return effective
        except Exception as e:
            print(f"Error getting effective rules: {e}")
            return []
        finally:
            conn.close()
    
    def set_rule_override(self, rule_id: int, target_type: str, target_id: str,
                          override_type: str, modified_threshold: str = None,
                          modified_channels: list = None) -> bool:
        """Set an override for a global rule on a specific target"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO alert_rule_overrides 
                (rule_id, target_type, target_id, override_type, modified_threshold, modified_channels)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_id, target_type, target_id) 
                DO UPDATE SET 
                    override_type = excluded.override_type,
                    modified_threshold = excluded.modified_threshold,
                    modified_channels = excluded.modified_channels
            """, (rule_id, target_type, target_id, override_type, modified_threshold,
                  json.dumps(modified_channels) if modified_channels else None))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Error setting rule override: {e}")
            return False
        finally:
            conn.close()
    
    def remove_rule_override(self, rule_id: int, target_type: str, target_id: str) -> bool:
        """Remove an override for a rule"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM alert_rule_overrides
                WHERE rule_id = ? AND target_type = ? AND target_id = ?
            """, (rule_id, target_type, target_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error removing rule override: {e}")
            return False
        finally:
            conn.close()
    
    def get_rule_overrides_for_target(self, target_type: str, target_id: str) -> list:
        """Get all rule overrides for a specific target"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT o.*, r.name as rule_name, r.metric, r.threshold as original_threshold
                FROM alert_rule_overrides o
                JOIN alert_rules_v2 r ON o.rule_id = r.id
                WHERE o.target_type = ? AND o.target_id = ?
            """, (target_type, target_id))
            
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "rule_id": row["rule_id"],
                    "rule_name": row["rule_name"],
                    "metric": row["metric"],
                    "original_threshold": row["original_threshold"],
                    "override_type": row["override_type"],
                    "modified_threshold": row["modified_threshold"],
                    "modified_channels": json.loads(row["modified_channels"]) if row["modified_channels"] else None
                }
                for row in rows
            ]
        except Exception as e:
            print(f"Error getting rule overrides: {e}")
            return []
        finally:
            conn.close()

    # =============================
    # Log Settings & Raw Logs
    # =============================
    
    def get_log_settings(self, agent_id: str) -> dict:
        """Get log settings for an agent, creating defaults if none exist"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                agent_id,
                logging_enabled,
                log_level_threshold,
                log_retention_days,
                watch_docker_containers,
                watch_system_logs,
                watch_security_logs,
                troubleshooting_mode,
                created_at,
                updated_at
            FROM agent_log_settings
            WHERE agent_id = ?
        """, (agent_id,))
        
        row = cursor.fetchone()
        
        if not row:
            # Create default settings for this agent
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO agent_log_settings (agent_id, created_at, updated_at)
                VALUES (?, ?, ?)
            """, (agent_id, now, now))
            conn.commit()
            conn.close()
            
            return {
                "agent_id": agent_id,
                "logging_enabled": True,
                "log_level_threshold": "ERROR",
                "log_retention_days": 7,
                "watch_docker_containers": False,
                "watch_system_logs": True,
                "watch_security_logs": True,
                "troubleshooting_mode": False,
                "created_at": now,
                "updated_at": now
            }
        
        conn.close()
        
        return {
            "agent_id": row[0],
            "logging_enabled": bool(row[1]),
            "log_level_threshold": row[2],
            "log_retention_days": row[3],
            "watch_docker_containers": bool(row[4]),
            "watch_system_logs": bool(row[5]),
            "watch_security_logs": bool(row[6]),
            "troubleshooting_mode": bool(row[7]),
            "created_at": row[8],
            "updated_at": row[9]
        }
    
    def update_log_settings(self, agent_id: str, settings: dict) -> dict:
        """Update log settings for an agent"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Ensure settings exist first
        self.get_log_settings(agent_id)
        
        # Handle troubleshooting mode - if enabled, force INFO level
        log_level = settings.get("log_level_threshold", "ERROR")
        if settings.get("troubleshooting_mode", False):
            log_level = "INFO"
        
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE agent_log_settings
            SET 
                logging_enabled = ?,
                log_level_threshold = ?,
                log_retention_days = ?,
                watch_docker_containers = ?,
                watch_system_logs = ?,
                watch_security_logs = ?,
                troubleshooting_mode = ?,
                updated_at = ?
            WHERE agent_id = ?
        """, (
            1 if settings.get("logging_enabled", True) else 0,
            log_level,
            settings.get("log_retention_days", 7),
            1 if settings.get("watch_docker_containers", False) else 0,
            1 if settings.get("watch_system_logs", True) else 0,
            1 if settings.get("watch_security_logs", True) else 0,
            1 if settings.get("troubleshooting_mode", False) else 0,
            now,
            agent_id
        ))
        
        conn.commit()
        conn.close()
        
        return self.get_log_settings(agent_id)
    
    def ingest_raw_logs(self, agent_id: str, logs: list) -> dict:
        """Ingest a batch of raw logs from an agent"""
        if not logs:
            return {"inserted": 0, "agent_id": agent_id}
        
        # Check if logging is enabled for this agent
        settings = self.get_log_settings(agent_id)
        if not settings.get("logging_enabled", True):
            return {"inserted": 0, "agent_id": agent_id, "reason": "logging_disabled"}
        
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        inserted = 0
        level_threshold = settings.get("log_level_threshold", "ERROR")
        level_priority = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3, "CRITICAL": 4, "FATAL": 4}
        threshold_priority = level_priority.get(level_threshold.upper(), 3)
        
        for log_entry in logs:
            severity = log_entry.get("severity", "INFO").upper()
            log_priority = level_priority.get(severity, 1)
            
            # Filter by level threshold (unless troubleshooting mode)
            if not settings.get("troubleshooting_mode") and log_priority < threshold_priority:
                continue
            
            timestamp = log_entry.get("timestamp", datetime.now().isoformat())
            source = log_entry.get("source", "System")
            message = log_entry.get("message", "")
            metadata = json.dumps(log_entry.get("metadata", {})) if log_entry.get("metadata") else None
            
            cursor.execute("""
                INSERT INTO raw_logs (agent_id, timestamp, severity, source, message, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (agent_id, timestamp, severity, source, message, metadata))
            inserted += 1
        
        conn.commit()
        conn.close()
        
        if inserted > 0:
            print(f"📝 Ingested {inserted} logs for agent {agent_id}")
        
        return {"inserted": inserted, "agent_id": agent_id}
    
    def get_raw_logs(self, agent_id: str = None, severity: str = None, source: str = None,
                     start_time: str = None, end_time: str = None, 
                     search: str = None, limit: int = 100, offset: int = 0) -> dict:
        """Query raw logs with filtering and pagination"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Build query dynamically
        where_clauses = []
        params = []
        
        if agent_id:
            where_clauses.append("agent_id = ?")
            params.append(agent_id)
        
        if severity:
            # Support comma-separated severities
            severities = [s.strip().upper() for s in severity.split(",")]
            placeholders = ",".join(["?" for _ in severities])
            where_clauses.append(f"UPPER(severity) IN ({placeholders})")
            params.extend(severities)
        
        if source:
            where_clauses.append("UPPER(source) = UPPER(?)")
            params.append(source)
        
        if start_time:
            where_clauses.append("datetime(timestamp) >= datetime(?)")
            params.append(start_time)
        
        if end_time:
            where_clauses.append("datetime(timestamp) <= datetime(?)")
            params.append(end_time)
        
        if search:
            where_clauses.append("message LIKE ?")
            params.append(f"%{search}%")
        
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
        
        # Count total
        count_query = f"SELECT COUNT(*) FROM raw_logs {where_sql}"
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()[0]
        
        # Fetch logs with pagination
        query = f"""
            SELECT id, agent_id, timestamp, severity, source, message, metadata, created_at
            FROM raw_logs
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        logs = [
            {
                "id": row[0],
                "agent_id": row[1],
                "timestamp": row[2],
                "severity": row[3],
                "source": row[4],
                "message": row[5],
                "metadata": json.loads(row[6]) if row[6] else None,
                "created_at": row[7]
            }
            for row in rows
        ]
        
        return {
            "logs": logs,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total_count
        }
    
    def reap_old_logs(self) -> dict:
        """
        The Reaper: Clean up old logs based on per-agent retention settings.
        This should be called by a daily cron job.
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Get all agents with their retention settings
        cursor.execute("""
            SELECT 
                a.agent_id,
                a.hostname,
                COALESCE(ls.log_retention_days, 7) as retention_days
            FROM agents a
            LEFT JOIN agent_log_settings ls ON a.agent_id = ls.agent_id
        """)
        
        agents = cursor.fetchall()
        total_deleted = 0
        details = []
        
        for agent_id, hostname, retention_days in agents:
            # Calculate cutoff timestamp
            cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
            
            # Delete old logs for this agent
            cursor.execute("""
                DELETE FROM raw_logs 
                WHERE agent_id = ? AND datetime(timestamp) < datetime(?)
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
                print(f"🧹 Reaped {deleted} logs for {hostname} (retention: {retention_days} days)")
        
        conn.commit()
        conn.close()
        
        print(f"🧹 Log Reaper complete: {total_deleted} total logs deleted")
        
        return {
            "total_deleted": total_deleted,
            "agents_processed": len(agents),
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_log_stats(self, agent_id: str = None) -> dict:
        """Get log statistics for dashboard display"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        if agent_id:
            # Stats for specific agent
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN UPPER(severity) = 'CRITICAL' THEN 1 ELSE 0 END) as critical,
                    SUM(CASE WHEN UPPER(severity) = 'ERROR' THEN 1 ELSE 0 END) as error,
                    SUM(CASE WHEN UPPER(severity) IN ('WARN', 'WARNING') THEN 1 ELSE 0 END) as warning,
                    SUM(CASE WHEN UPPER(severity) = 'INFO' THEN 1 ELSE 0 END) as info,
                    MIN(timestamp) as oldest,
                    MAX(timestamp) as newest
                FROM raw_logs
                WHERE agent_id = ?
            """, (agent_id,))
        else:
            # Global stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN UPPER(severity) = 'CRITICAL' THEN 1 ELSE 0 END) as critical,
                    SUM(CASE WHEN UPPER(severity) = 'ERROR' THEN 1 ELSE 0 END) as error,
                    SUM(CASE WHEN UPPER(severity) IN ('WARN', 'WARNING') THEN 1 ELSE 0 END) as warning,
                    SUM(CASE WHEN UPPER(severity) = 'INFO' THEN 1 ELSE 0 END) as info,
                    MIN(timestamp) as oldest,
                    MAX(timestamp) as newest
                FROM raw_logs
            """)
        
        row = cursor.fetchone()
        conn.close()
        
        return {
            "total": row[0] or 0,
            "critical": row[1] or 0,
            "error": row[2] or 0,
            "warning": row[3] or 0,
            "info": row[4] or 0,
            "oldest": row[5],
            "newest": row[6]
        }

    # ==================== SYSTEM SETTINGS ====================
    
    def get_system_setting(self, key: str, default: str = "") -> str:
        """Get a system setting by key"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        
        return row[0] if row else default
    
    def set_system_setting(self, key: str, value: str, description: str = None) -> bool:
        """Set a system setting"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            if description:
                cursor.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET 
                        value = excluded.value,
                        description = excluded.description,
                        updated_at = datetime('now')
                """, (key, value, description))
            else:
                cursor.execute("""
                    INSERT INTO system_settings (key, value, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET 
                        value = excluded.value,
                        updated_at = datetime('now')
                """, (key, value))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error setting system setting: {e}")
            conn.close()
            return False
    
    def get_all_system_settings(self) -> dict:
        """Get all system settings as a dictionary"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT key, value, description, updated_at FROM system_settings")
        rows = cursor.fetchall()
        conn.close()
        
        settings = {}
        for row in rows:
            settings[row[0]] = {
                "value": row[1],
                "description": row[2],
                "updated_at": row[3]
            }
        
        return settings
    
    def get_public_app_url(self) -> str:
        """Get the configured public app URL, empty string if not set"""
        return self.get_system_setting("public_app_url", "")

    # ==================== USER MANAGEMENT ====================
    
    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_password(self, password: str, stored_hash: str) -> bool:
        """Verify a password against its bcrypt hash"""
        import bcrypt
        try:
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        except Exception:
            # Fallback for legacy SHA-256 hashes during migration
            try:
                if ':' in stored_hash:
                    salt, hash_value = stored_hash.split(":")
                    check_hash = hashlib.sha256((salt + password).encode()).hexdigest()
                    return check_hash == hash_value
            except:
                pass
            return False
    
    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Get a user by username"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, username, password_hash, is_admin, role, assigned_profile_id, is_setup_complete, created_at
            FROM users WHERE username = ?
        """, (username,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "username": row[1],
                "password_hash": row[2],
                "is_admin": bool(row[3]),
                "role": row[4] or ('admin' if row[3] else 'user'),
                "assigned_profile_id": row[5],
                "is_setup_complete": bool(row[6]),
                "created_at": row[7]
            }
        return None
    
    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        """Get a user by ID"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, username, password_hash, is_admin, role, assigned_profile_id, is_setup_complete, created_at
            FROM users WHERE id = ?
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "username": row[1],
                "password_hash": row[2],
                "is_admin": bool(row[3]),
                "role": row[4] or ('admin' if row[3] else 'user'),
                "assigned_profile_id": row[5],
                "is_setup_complete": bool(row[6]),
                "created_at": row[7]
            }
        return None
    
    def create_user(self, username: str, password: str, is_admin: bool = False, 
                    role: str = None, assigned_profile_id: str = None) -> Optional[int]:
        """Create a new user, returns user ID or None if failed"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            password_hash = self.hash_password(password)
            # Determine role - admin users get 'admin' role by default
            actual_role = role if role else ('admin' if is_admin else 'user')
            cursor.execute("""
                INSERT INTO users (username, password_hash, is_admin, role, assigned_profile_id, is_setup_complete)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (username, password_hash, 1 if is_admin else 0, actual_role, assigned_profile_id))
            conn.commit()
            user_id = cursor.lastrowid
            conn.close()
            return user_id
        except sqlite3.IntegrityError:
            # Username already exists
            conn.close()
            return None
        except Exception as e:
            print(f"Error creating user: {e}")
            conn.close()
            return None
    
    def update_user_password(self, user_id: int, new_password: str) -> bool:
        """Update a user's password"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            password_hash = self.hash_password(new_password)
            cursor.execute("""
                UPDATE users SET password_hash = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (password_hash, user_id))
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            return success
        except Exception as e:
            print(f"Error updating password: {e}")
            conn.close()
            return False
    
    def delete_user(self, user_id: int) -> bool:
        """Delete a user by ID"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            return success
        except Exception as e:
            print(f"Error deleting user: {e}")
            conn.close()
            return False
    
    def get_all_users(self) -> List[dict]:
        """Get all users (without password hashes)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, username, is_admin, role, assigned_profile_id, created_at FROM users
            ORDER BY created_at ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "id": row[0],
                "username": row[1],
                "is_admin": bool(row[2]),
                "role": row[3] or ('admin' if row[2] else 'user'),
                "assigned_profile_id": row[4],
                "created_at": row[5]
            }
            for row in rows
        ]
    
    def update_user(self, user_id: int, role: str = None, assigned_profile_id: str = None, 
                    is_admin: bool = None) -> bool:
        """Update user's role and assigned profile"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            updates = []
            params = []
            
            if role is not None:
                updates.append("role = ?")
                params.append(role)
                # Sync is_admin with role
                if is_admin is None:
                    updates.append("is_admin = ?")
                    params.append(1 if role == 'admin' else 0)
            
            if is_admin is not None:
                updates.append("is_admin = ?")
                params.append(1 if is_admin else 0)
            
            if assigned_profile_id is not None:
                updates.append("assigned_profile_id = ?")
                # Allow clearing the profile by passing empty string
                params.append(assigned_profile_id if assigned_profile_id else None)
            
            if not updates:
                return True
            
            updates.append("updated_at = datetime('now')")
            params.append(user_id)
            
            cursor.execute(f"""
                UPDATE users SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            return success
        except Exception as e:
            print(f"Error updating user: {e}")
            conn.close()
            return False
    
    def get_user_count(self) -> int:
        """Get total number of users"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def is_setup_required(self) -> bool:
        """Check if initial setup is required (no users exist)"""
        return self.get_user_count() == 0
    
    def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """Authenticate a user, returns user dict if successful"""
        user = self.get_user_by_username(username)
        if user and self.verify_password(password, user["password_hash"]):
            # Return user without password hash
            return {
                "id": user["id"],
                "username": user["username"],
                "is_admin": user["is_admin"],
                "role": user["role"],
                "assigned_profile_id": user["assigned_profile_id"]
            }
        return None
    
    def reset_to_default_admin(self) -> str:
        """Reset to default admin account, returns the username"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Delete all users
        cursor.execute("DELETE FROM users")
        conn.commit()
        conn.close()
        
        return "admin"

    # ==================== AI SETTINGS ====================
    
    def get_ai_settings(self) -> dict:
        """Get AI settings"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Check columns exist and migrate if needed
        cursor.execute("PRAGMA table_info(ai_settings)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Migrate: add new columns if missing
        if 'enabled' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN enabled INTEGER DEFAULT 0")
            conn.commit()
        if 'briefing_time' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN briefing_time TEXT DEFAULT '08:00'")
            conn.commit()
        if 'report_style' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN report_style TEXT DEFAULT 'concise'")
            conn.commit()
        if 'exec_summary_enabled' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_enabled INTEGER DEFAULT 0")
            conn.commit()
        if 'exec_summary_schedule' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_schedule TEXT DEFAULT 'weekly'")
            conn.commit()
        if 'exec_summary_day_of_week' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_day_of_week TEXT DEFAULT '1'")
            conn.commit()
        if 'exec_summary_day_of_month' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_day_of_month INTEGER DEFAULT 1")
            conn.commit()
        if 'exec_summary_period_days' not in columns:
            cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_period_days TEXT DEFAULT '30'")
            conn.commit()
        
        cursor.execute("""
            SELECT enabled, provider, local_model_id, openai_key, feature_flags, briefing_time, report_style,
                   exec_summary_enabled, exec_summary_schedule, exec_summary_day_of_week, exec_summary_day_of_month, exec_summary_period_days, updated_at 
            FROM ai_settings WHERE id = 1
        """)
        row = cursor.fetchone()
        conn.close()
        
        if row:
            feature_flags = {}
            try:
                feature_flags = json.loads(row[4]) if row[4] else {}
            except:
                pass
            
            return {
                "enabled": bool(row[0]),
                "provider": row[1] or "local",
                "local_model_id": row[2] or "gemma-2-2b",
                "openai_key": row[3] or "",
                "feature_flags": feature_flags,
                "briefing_time": row[5] or "08:00",
                "report_style": row[6] or "concise",
                "exec_summary_enabled": bool(row[7]) if row[7] is not None else False,
                "exec_summary_schedule": row[8] or "weekly",
                "exec_summary_day_of_week": row[9] or "1",
                "exec_summary_day_of_month": row[10] or 1,
                "exec_summary_period_days": row[11] or "30",
                "updated_at": row[12]
            }
        
        # Return defaults if no settings exist
        return {
            "enabled": False,
            "provider": "local",
            "local_model_id": "gemma-2-2b",
            "openai_key": "",
            "feature_flags": {"daily_briefing": True, "alert_analysis": True},
            "briefing_time": "08:00",
            "report_style": "concise",
            "exec_summary_enabled": False,
            "exec_summary_schedule": "weekly",
            "exec_summary_day_of_week": "1",
            "exec_summary_day_of_month": 1,
            "exec_summary_period_days": "30",
            "updated_at": None
        }
    
    def update_ai_settings(self, enabled: bool = None, provider: str = None, local_model_id: str = None, 
                          openai_key: str = None, briefing_time: str = None, report_style: str = None,
                          feature_flags: dict = None, exec_summary_enabled: bool = None,
                          exec_summary_schedule: str = None, exec_summary_day_of_week: str = None,
                          exec_summary_day_of_month: int = None, exec_summary_period_days: str = None) -> bool:
        """Update AI settings"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Ensure all columns exist (migration)
            cursor.execute("PRAGMA table_info(ai_settings)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'enabled' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN enabled INTEGER DEFAULT 0")
            if 'briefing_time' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN briefing_time TEXT DEFAULT '08:00'")
            if 'report_style' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN report_style TEXT DEFAULT 'concise'")
            if 'exec_summary_enabled' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_enabled INTEGER DEFAULT 0")
            if 'exec_summary_schedule' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_schedule TEXT DEFAULT 'weekly'")
            if 'exec_summary_day_of_week' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_day_of_week TEXT DEFAULT '1'")
            if 'exec_summary_day_of_month' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_day_of_month INTEGER DEFAULT 1")
            if 'exec_summary_period_days' not in columns:
                cursor.execute("ALTER TABLE ai_settings ADD COLUMN exec_summary_period_days TEXT DEFAULT '30'")
            conn.commit()
            
            # Get current settings
            current = self.get_ai_settings()
            
            # Build update
            new_enabled = 1 if enabled else 0 if enabled is False else (1 if current.get("enabled") else 0)
            new_provider = provider if provider is not None else current["provider"]
            new_model = local_model_id if local_model_id is not None else current["local_model_id"]
            new_key = openai_key if openai_key is not None else current["openai_key"]
            new_time = briefing_time if briefing_time is not None else current.get("briefing_time", "08:00")
            new_style = report_style if report_style is not None else current.get("report_style", "concise")
            new_flags = json.dumps(feature_flags) if feature_flags is not None else json.dumps(current["feature_flags"])
            
            # Executive Summary settings
            new_exec_enabled = 1 if exec_summary_enabled else 0 if exec_summary_enabled is False else (1 if current.get("exec_summary_enabled") else 0)
            new_exec_schedule = exec_summary_schedule if exec_summary_schedule is not None else current.get("exec_summary_schedule", "weekly")
            new_exec_dow = exec_summary_day_of_week if exec_summary_day_of_week is not None else current.get("exec_summary_day_of_week", "1")
            new_exec_dom = exec_summary_day_of_month if exec_summary_day_of_month is not None else current.get("exec_summary_day_of_month", 1)
            new_exec_period = exec_summary_period_days if exec_summary_period_days is not None else current.get("exec_summary_period_days", "30")
            
            cursor.execute("""
                INSERT INTO ai_settings (id, enabled, provider, local_model_id, openai_key, feature_flags, briefing_time, report_style,
                    exec_summary_enabled, exec_summary_schedule, exec_summary_day_of_week, exec_summary_day_of_month, exec_summary_period_days, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    enabled = excluded.enabled,
                    provider = excluded.provider,
                    local_model_id = excluded.local_model_id,
                    openai_key = excluded.openai_key,
                    feature_flags = excluded.feature_flags,
                    briefing_time = excluded.briefing_time,
                    report_style = excluded.report_style,
                    exec_summary_enabled = excluded.exec_summary_enabled,
                    exec_summary_schedule = excluded.exec_summary_schedule,
                    exec_summary_day_of_week = excluded.exec_summary_day_of_week,
                    exec_summary_day_of_month = excluded.exec_summary_day_of_month,
                    exec_summary_period_days = excluded.exec_summary_period_days,
                    updated_at = datetime('now')
            """, (new_enabled, new_provider, new_model, new_key, new_flags, new_time, new_style,
                  new_exec_enabled, new_exec_schedule, new_exec_dow, new_exec_dom, new_exec_period))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating AI settings: {e}")
            conn.close()
            return False

    # ==================== AI REPORTS ====================
    
    def create_ai_report(self, report_type: str, title: str, content: str, 
                        agent_id: str = None, metadata: dict = None) -> int:
        """Create a new AI report"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            meta_json = json.dumps(metadata) if metadata else "{}"
            
            cursor.execute("""
                INSERT INTO ai_reports (type, title, content, agent_id, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, (report_type, title, content, agent_id, meta_json))
            
            report_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return report_id
        except Exception as e:
            print(f"Error creating AI report: {e}")
            conn.close()
            return -1
    
    def get_ai_reports(self, report_type: str = None, limit: int = 50, 
                      unread_only: bool = False, agent_id: str = None) -> List[dict]:
        """Get AI reports with optional filtering"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Check if feedback column exists
        cursor.execute("PRAGMA table_info(ai_reports)")
        columns = [col[1] for col in cursor.fetchall()]
        has_feedback = 'feedback' in columns
        
        if has_feedback:
            query = "SELECT id, created_at, type, title, content, is_read, metadata, agent_id, feedback FROM ai_reports WHERE 1=1"
        else:
            query = "SELECT id, created_at, type, title, content, is_read, metadata, agent_id FROM ai_reports WHERE 1=1"
        params = []
        
        if report_type:
            query += " AND type = ?"
            params.append(report_type)
        
        if unread_only:
            query += " AND is_read = 0"
        
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        reports = []
        for row in rows:
            metadata = {}
            try:
                metadata = json.loads(row[6]) if row[6] else {}
            except:
                pass
            
            report = {
                "id": row[0],
                "created_at": row[1],
                "type": row[2],
                "title": row[3],
                "content": row[4],
                "is_read": bool(row[5]),
                "metadata": metadata,
                "agent_id": row[7]
            }
            
            if has_feedback:
                report["feedback"] = row[8]
            
            reports.append(report)
        
        return reports
    
    def get_ai_report(self, report_id: int) -> dict:
        """Get a single AI report by ID"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, created_at, type, title, content, is_read, metadata, agent_id 
            FROM ai_reports WHERE id = ?
        """, (report_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        metadata = {}
        try:
            metadata = json.loads(row[6]) if row[6] else {}
        except:
            pass
        
        return {
            "id": row[0],
            "created_at": row[1],
            "type": row[2],
            "title": row[3],
            "content": row[4],
            "is_read": bool(row[5]),
            "metadata": metadata,
            "agent_id": row[7]
        }
    
    def mark_ai_report_read(self, report_id: int) -> bool:
        """Mark an AI report as read"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE ai_reports SET is_read = 1 WHERE id = ?", (report_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error marking report as read: {e}")
            conn.close()
            return False
    
    def mark_all_ai_reports_read(self, report_type: str = None) -> int:
        """Mark all AI reports as read, optionally filtered by type"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            if report_type:
                cursor.execute("UPDATE ai_reports SET is_read = 1 WHERE type = ? AND is_read = 0", (report_type,))
            else:
                cursor.execute("UPDATE ai_reports SET is_read = 1 WHERE is_read = 0")
            
            count = cursor.rowcount
            conn.commit()
            conn.close()
            return count
        except Exception as e:
            print(f"Error marking reports as read: {e}")
            conn.close()
            return 0
    
    def get_unread_ai_report_count(self) -> dict:
        """Get count of unread reports by type"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT type, COUNT(*) FROM ai_reports WHERE is_read = 0 GROUP BY type
        """)
        rows = cursor.fetchall()
        conn.close()
        
        counts = {"total": 0}
        for row in rows:
            counts[row[0]] = row[1]
            counts["total"] += row[1]
        
        return counts
    
    def delete_ai_report(self, report_id: int) -> bool:
        """Delete an AI report"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM ai_reports WHERE id = ?", (report_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting AI report: {e}")
            conn.close()
            return False
    
    def set_ai_report_feedback(self, report_id: int, feedback: str) -> bool:
        """Set feedback for an AI report (up, down, or null to clear)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Ensure feedback column exists (migration)
            cursor.execute("PRAGMA table_info(ai_reports)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'feedback' not in columns:
                cursor.execute("ALTER TABLE ai_reports ADD COLUMN feedback TEXT DEFAULT NULL")
            
            cursor.execute("UPDATE ai_reports SET feedback = ? WHERE id = ?", (feedback, report_id))
            if cursor.rowcount == 0:
                conn.close()
                return False
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error setting AI report feedback: {e}")
            conn.close()
            return False

    # ==================== AI MODEL CACHE ====================
    
    def get_ai_model_cache(self, model_id: str) -> dict:
        """Get cached model info"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT model_id, file_path, file_hash, file_size_mb, is_downloaded, 
                   download_progress, downloaded_at, last_used_at
            FROM ai_model_cache WHERE model_id = ?
        """, (model_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            "model_id": row[0],
            "file_path": row[1],
            "file_hash": row[2],
            "file_size_mb": row[3],
            "is_downloaded": bool(row[4]),
            "download_progress": row[5],
            "downloaded_at": row[6],
            "last_used_at": row[7]
        }
    
    def get_all_ai_models(self) -> List[dict]:
        """Get all cached models"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT model_id, file_path, file_hash, file_size_mb, is_downloaded, 
                   download_progress, downloaded_at, last_used_at
            FROM ai_model_cache ORDER BY last_used_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        models = []
        for row in rows:
            models.append({
                "model_id": row[0],
                "file_path": row[1],
                "file_hash": row[2],
                "file_size_mb": row[3],
                "is_downloaded": bool(row[4]),
                "download_progress": row[5],
                "downloaded_at": row[6],
                "last_used_at": row[7]
            })
        
        return models
    
    def upsert_ai_model_cache(self, model_id: str, file_path: str, file_hash: str = "",
                             file_size_mb: float = 0, is_downloaded: bool = False,
                             download_progress: float = 0) -> bool:
        """Create or update model cache entry"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            downloaded_at = "datetime('now')" if is_downloaded else "NULL"
            
            cursor.execute(f"""
                INSERT INTO ai_model_cache (model_id, file_path, file_hash, file_size_mb, 
                                           is_downloaded, download_progress, downloaded_at)
                VALUES (?, ?, ?, ?, ?, ?, {downloaded_at if is_downloaded else 'NULL'})
                ON CONFLICT(model_id) DO UPDATE SET
                    file_path = excluded.file_path,
                    file_hash = excluded.file_hash,
                    file_size_mb = excluded.file_size_mb,
                    is_downloaded = excluded.is_downloaded,
                    download_progress = excluded.download_progress,
                    downloaded_at = CASE WHEN excluded.is_downloaded = 1 THEN datetime('now') ELSE downloaded_at END
            """, (model_id, file_path, file_hash, file_size_mb, int(is_downloaded), download_progress))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error upserting AI model cache: {e}")
            conn.close()
            return False
    
    def update_ai_model_progress(self, model_id: str, progress: float) -> bool:
        """Update download progress for a model"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE ai_model_cache SET download_progress = ? WHERE model_id = ?
            """, (progress, model_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating model progress: {e}")
            conn.close()
            return False
    
    def mark_ai_model_downloaded(self, model_id: str, file_hash: str = "") -> bool:
        """Mark a model as fully downloaded"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE ai_model_cache 
                SET is_downloaded = 1, download_progress = 100, downloaded_at = datetime('now'), file_hash = ?
                WHERE model_id = ?
            """, (file_hash, model_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error marking model as downloaded: {e}")
            conn.close()
            return False
    
    def update_ai_model_last_used(self, model_id: str) -> bool:
        """Update the last_used_at timestamp for a model"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE ai_model_cache SET last_used_at = datetime('now') WHERE model_id = ?
            """, (model_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating model last used: {e}")
            conn.close()
            return False
    
    def delete_ai_model_cache(self, model_id: str) -> bool:
        """Delete a model from cache"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM ai_model_cache WHERE model_id = ?", (model_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting AI model cache: {e}")
            conn.close()
            return False

    # ==================== AI CONVERSATIONS ====================
    
    def create_conversation(self, title: str = "New Chat") -> dict:
        """Create a new conversation thread"""
        import uuid
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            conversation_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO ai_conversations (id, title, created_at, updated_at)
                VALUES (?, ?, datetime('now'), datetime('now'))
            """, (conversation_id, title))
            conn.commit()
            conn.close()
            
            return {
                "id": conversation_id,
                "title": title,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
        except Exception as e:
            print(f"Error creating conversation: {e}")
            conn.close()
            return None
    
    def get_conversations(self, limit: int = 50) -> List[dict]:
        """Get all conversations, newest first"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM ai_messages WHERE conversation_id = c.id) as message_count
            FROM ai_conversations c
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        conversations = []
        for row in rows:
            conversations.append({
                "id": row[0],
                "title": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "message_count": row[4]
            })
        
        return conversations
    
    def get_conversation(self, conversation_id: str) -> dict:
        """Get a single conversation with its messages"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        # Get conversation
        cursor.execute("""
            SELECT id, title, created_at, updated_at
            FROM ai_conversations WHERE id = ?
        """, (conversation_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None
        
        conversation = {
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "messages": []
        }
        
        # Get messages
        cursor.execute("""
            SELECT id, role, content, created_at
            FROM ai_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
        """, (conversation_id,))
        messages = cursor.fetchall()
        conn.close()
        
        for msg in messages:
            conversation["messages"].append({
                "id": msg[0],
                "role": msg[1],
                "content": msg[2],
                "created_at": msg[3]
            })
        
        return conversation
    
    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """Update conversation title"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE ai_conversations 
                SET title = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (title, conversation_id))
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating conversation title: {e}")
            conn.close()
            return False
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Delete messages first (or rely on CASCADE if supported)
            cursor.execute("DELETE FROM ai_messages WHERE conversation_id = ?", (conversation_id,))
            cursor.execute("DELETE FROM ai_conversations WHERE id = ?", (conversation_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting conversation: {e}")
            conn.close()
            return False
    
    def add_message(self, conversation_id: str, role: str, content: str) -> dict:
        """Add a message to a conversation"""
        import uuid
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            message_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO ai_messages (id, conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (message_id, conversation_id, role, content))
            
            # Update conversation's updated_at
            cursor.execute("""
                UPDATE ai_conversations SET updated_at = datetime('now') WHERE id = ?
            """, (conversation_id,))
            
            conn.commit()
            conn.close()
            
            return {
                "id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": datetime.now().isoformat()
            }
        except Exception as e:
            print(f"Error adding message: {e}")
            conn.close()
            return None
    
    def get_recent_messages(self, conversation_id: str, limit: int = 10) -> List[dict]:
        """Get the most recent messages from a conversation for context"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, role, content, created_at
            FROM ai_messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (conversation_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        # Reverse to get chronological order
        messages = []
        for row in reversed(rows):
            messages.append({
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "created_at": row[3]
            })
        
        return messages

    # ==================== AI CONTEXT HELPER METHODS (READ-ONLY) ====================
    
    def execute_query(self, query: str, params: tuple = None) -> List[dict]:
        """Execute a read-only query and return results as list of dicts"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]
            return result
        except Exception as e:
            print(f"Query error: {e}")
            return []
        finally:
            conn.close()
    
    def get_logs(self, agent_id: str = None, limit: int = 100, level: str = None) -> List[dict]:
        """Get logs with optional filtering"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            query = "SELECT agent_id, timestamp, severity as level, source, message FROM raw_logs"
            conditions = []
            params = []
            
            if agent_id:
                conditions.append("agent_id = ?")
                params.append(agent_id)
            
            if level:
                conditions.append("UPPER(severity) = UPPER(?)")
                params.append(level)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error getting logs: {e}")
            return []
        finally:
            conn.close()
    
    def search_logs(self, query: str, agent_id: str = None, limit: int = 50) -> List[dict]:
        """Search logs by message content"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            sql = """
                SELECT agent_id, timestamp, severity as level, source, message 
                FROM raw_logs
                WHERE message LIKE ?
            """
            params = [f"%{query}%"]
            
            if agent_id:
                sql += " AND agent_id = ?"
                params.append(agent_id)
            
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error searching logs: {e}")
            return []
        finally:
            conn.close()
    
    # =====================================
    # Bookmark / Uptime Monitor Methods
    # =====================================
    
    def create_monitor_group(self, tenant_id: str, name: str, weight: int = 0) -> dict:
        """Create a new monitor group"""
        import secrets
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            group_id = f"grp_{secrets.token_hex(8)}"
            now = datetime.utcnow().isoformat()
            
            cursor.execute("""
                INSERT INTO monitor_groups (id, tenant_id, name, weight, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (group_id, tenant_id, name, weight, now))
            
            conn.commit()
            
            cursor.execute("SELECT * FROM monitor_groups WHERE id = ?", (group_id,))
            return dict(cursor.fetchone())
        finally:
            conn.close()
    
    def get_monitor_groups(self, tenant_id: str) -> List[dict]:
        """Get all monitor groups ordered by weight, with monitor count"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT g.*, 
                       (SELECT COUNT(*) FROM bookmarks WHERE group_id = g.id AND tenant_id = g.tenant_id) as monitor_count
                FROM monitor_groups g
                WHERE g.tenant_id = ? 
                ORDER BY g.weight ASC, g.name ASC
            """, (tenant_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def update_monitor_group(self, tenant_id: str, group_id: str, name: str = None, weight: int = None) -> dict:
        """Update a monitor group"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if weight is not None:
                updates.append("weight = ?")
                params.append(weight)
            
            if updates:
                params.extend([group_id, tenant_id])
                cursor.execute(f"""
                    UPDATE monitor_groups SET {', '.join(updates)} 
                    WHERE id = ? AND tenant_id = ?
                """, params)
                conn.commit()
            
            cursor.execute("""
                SELECT * FROM monitor_groups 
                WHERE id = ? AND tenant_id = ?
            """, (group_id, tenant_id))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def delete_monitor_group(self, tenant_id: str, group_id: str, delete_monitors: bool = False) -> bool:
        """Delete a monitor group. If delete_monitors is True, delete all monitors in the group.
        Otherwise, set their group_id to NULL (ungroup them)."""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            if delete_monitors:
                # First delete all bookmark checks for monitors in this group
                cursor.execute("""
                    DELETE FROM bookmark_checks 
                    WHERE bookmark_id IN (SELECT id FROM bookmarks WHERE group_id = ? AND tenant_id = ?)
                """, (group_id, tenant_id))
                # Then delete all monitors in this group
                cursor.execute("""
                    DELETE FROM bookmarks 
                    WHERE group_id = ? AND tenant_id = ?
                """, (group_id, tenant_id))
            else:
                # Just ungroup the monitors (set group_id to NULL)
                cursor.execute("""
                    UPDATE bookmarks SET group_id = NULL 
                    WHERE group_id = ? AND tenant_id = ?
                """, (group_id, tenant_id))
            
            # Delete the group itself
            cursor.execute("""
                DELETE FROM monitor_groups 
                WHERE id = ? AND tenant_id = ?
            """, (group_id, tenant_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def create_bookmark(self, tenant_id: str, name: str, type: str, target: str, 
                       group_id: str = None, port: int = None,
                       interval_seconds: int = 60, timeout_seconds: int = 10,
                       max_retries: int = 1, retry_interval: int = 30,
                       resend_notification: int = 0, upside_down: bool = False,
                       active: bool = True, tags: str = None, description: str = None) -> dict:
        """Create a new bookmark/monitor"""
        import secrets
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Validate interval_seconds minimum of 20 seconds
        if interval_seconds < 20:
            interval_seconds = 20
        
        try:
            bookmark_id = f"bm_{secrets.token_hex(8)}"
            now = datetime.utcnow().isoformat()
            
            cursor.execute("""
                INSERT INTO bookmarks (id, tenant_id, group_id, name, type, target, port, 
                                      interval_seconds, timeout_seconds, max_retries,
                                      retry_interval, resend_notification, upside_down,
                                      active, tags, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (bookmark_id, tenant_id, group_id, name, type, target, port,
                  interval_seconds, timeout_seconds, max_retries, retry_interval,
                  resend_notification, 1 if upside_down else 0, 1 if active else 0, 
                  tags, description, now, now))
            
            conn.commit()
            
            cursor.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,))
            return dict(cursor.fetchone())
        finally:
            conn.close()
    
    def get_bookmark(self, tenant_id: str, bookmark_id: str) -> dict:
        """Get a bookmark by ID"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM bookmarks 
                WHERE id = ? AND tenant_id = ?
            """, (bookmark_id, tenant_id))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def get_bookmarks(self, tenant_id: str, group_id: str = None) -> List[dict]:
        """Get bookmarks, optionally filtered by group, with latest status"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if group_id:
                cursor.execute("""
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
                    WHERE b.tenant_id = ? AND b.group_id = ?
                    ORDER BY b.name ASC
                """, (tenant_id, group_id))
            else:
                cursor.execute("""
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
                    WHERE b.tenant_id = ?
                    ORDER BY b.name ASC
                """, (tenant_id,))
            
            bookmarks = []
            for row in cursor.fetchall():
                b = dict(row)
                # Add latest_check as nested object for convenience
                if b.get("last_status") is not None:
                    b["latest_check"] = {
                        "status": b["last_status"],
                        "latency_ms": b["last_latency"],
                        "created_at": b["last_check_at"]
                    }
                else:
                    b["latest_check"] = None
                bookmarks.append(b)
            return bookmarks
        finally:
            conn.close()
    
    def get_all_bookmarks(self, active_only: bool = False) -> List[dict]:
        """Get all bookmarks across all tenants (for monitor engine)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if active_only:
                cursor.execute("SELECT * FROM bookmarks WHERE active = 1 ORDER BY name")
            else:
                cursor.execute("SELECT * FROM bookmarks ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_bookmarks_tree(self, tenant_id: str) -> dict:
        """Get bookmarks organized by groups with latest status"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Get all groups for this tenant
            cursor.execute("""
                SELECT * FROM monitor_groups 
                WHERE tenant_id = ?
                ORDER BY weight ASC, name ASC
            """, (tenant_id,))
            groups = [dict(row) for row in cursor.fetchall()]
            
            # Get all bookmarks with their latest check status
            cursor.execute("""
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
                WHERE b.tenant_id = ?
                ORDER BY b.name ASC
            """, (tenant_id,))
            bookmarks = [dict(row) for row in cursor.fetchall()]
            
            # Organize into tree structure
            tree = {
                "groups": [],
                "ungrouped": []
            }
            
            # Create group lookup
            group_lookup = {g["id"]: {**g, "bookmarks": []} for g in groups}
            
            for bookmark in bookmarks:
                # Add latest check info
                if bookmark.get("last_status") is not None:
                    bookmark["latest_check"] = {
                        "status": bookmark["last_status"],
                        "latency_ms": bookmark["last_latency"],
                        "created_at": bookmark["last_check_at"]
                    }
                else:
                    bookmark["latest_check"] = None
                
                if bookmark["group_id"] and bookmark["group_id"] in group_lookup:
                    group_lookup[bookmark["group_id"]]["bookmarks"].append(bookmark)
                else:
                    tree["ungrouped"].append(bookmark)
            
            tree["groups"] = list(group_lookup.values())
            
            return tree
        finally:
            conn.close()
    
    def get_bookmarks_tree_for_user(self, user: dict) -> dict:
        """Get bookmarks tree filtered by user's role and assigned profile.
        
        - Admin role: Returns ALL bookmarks in tree structure
        - User role: Returns only bookmarks matching their assigned profile's scope
        - User with no profile: Returns empty tree
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Admin users see everything
            if user.get("role") == "admin" or user.get("is_admin"):
                # Get all groups
                cursor.execute("""
                    SELECT * FROM monitor_groups 
                    ORDER BY weight ASC, name ASC
                """)
                groups = [dict(row) for row in cursor.fetchall()]
                
                # Get all bookmarks with status
                cursor.execute("""
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
                    ORDER BY b.name ASC
                """)
                bookmarks = [dict(row) for row in cursor.fetchall()]
            else:
                # Non-admin: filter by assigned profile
                profile_id = user.get("assigned_profile_id")
                if not profile_id:
                    return {"groups": [], "ungrouped": []}
                
                profile = self.get_report_profile_by_id(profile_id)
                if not profile:
                    return {"groups": [], "ungrouped": []}
                
                # Get all bookmarks and filter
                cursor.execute("""
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
                    ORDER BY b.name ASC
                """)
                all_bookmarks = [dict(row) for row in cursor.fetchall()]
                
                # Filter bookmarks by profile scope
                monitor_scope_ids = profile.get("monitor_scope_ids") or []
                monitor_scope_tags = profile.get("monitor_scope_tags") or []
                
                if monitor_scope_ids or monitor_scope_tags:
                    bookmarks = []
                    for bookmark in all_bookmarks:
                        # Check if bookmark ID is in scope
                        if bookmark["id"] in monitor_scope_ids:
                            bookmarks.append(bookmark)
                            continue
                        
                        # Check if any bookmark tag matches scope tags
                        bookmark_tags = bookmark.get("tags") or []
                        if isinstance(bookmark_tags, str):
                            try:
                                bookmark_tags = json.loads(bookmark_tags)
                            except:
                                bookmark_tags = [t.strip() for t in bookmark_tags.split(',') if t.strip()]
                        
                        if any(tag in monitor_scope_tags for tag in bookmark_tags):
                            bookmarks.append(bookmark)
                else:
                    # No scope defined - include all bookmarks
                    bookmarks = all_bookmarks
                
                # Get groups that contain these filtered bookmarks
                group_ids = set(b.get("group_id") for b in bookmarks if b.get("group_id"))
                if group_ids:
                    placeholders = ','.join('?' * len(group_ids))
                    cursor.execute(f"""
                        SELECT * FROM monitor_groups 
                        WHERE id IN ({placeholders})
                        ORDER BY weight ASC, name ASC
                    """, tuple(group_ids))
                    groups = [dict(row) for row in cursor.fetchall()]
                else:
                    groups = []
            
            # Organize into tree structure
            tree = {
                "groups": [],
                "ungrouped": []
            }
            
            # Create group lookup
            group_lookup = {g["id"]: {**g, "bookmarks": []} for g in groups}
            
            for bookmark in bookmarks:
                # Parse tags if needed
                if bookmark.get("tags"):
                    if isinstance(bookmark["tags"], str):
                        try:
                            bookmark["tags"] = json.loads(bookmark["tags"])
                        except:
                            bookmark["tags"] = [t.strip() for t in bookmark["tags"].split(',') if t.strip()]
                else:
                    bookmark["tags"] = []
                
                # Add latest check info
                if bookmark.get("last_status") is not None:
                    bookmark["latest_check"] = {
                        "status": bookmark["last_status"],
                        "latency_ms": bookmark["last_latency"],
                        "created_at": bookmark["last_check_at"]
                    }
                else:
                    bookmark["latest_check"] = None
                
                if bookmark["group_id"] and bookmark["group_id"] in group_lookup:
                    group_lookup[bookmark["group_id"]]["bookmarks"].append(bookmark)
                else:
                    tree["ungrouped"].append(bookmark)
            
            tree["groups"] = list(group_lookup.values())
            
            return tree
        finally:
            conn.close()
    
    def update_bookmark(self, tenant_id: str, bookmark_id: str, **kwargs) -> dict:
        """Update a bookmark"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Validate interval_seconds minimum of 20 seconds
        if 'interval_seconds' in kwargs and kwargs['interval_seconds'] < 20:
            kwargs['interval_seconds'] = 20
        
        allowed_fields = ['name', 'type', 'target', 'port', 'group_id', 
                         'interval_seconds', 'timeout_seconds', 'max_retries',
                         'retry_interval', 'resend_notification', 'upside_down', 'active',
                         'tags', 'description']
        
        try:
            updates = []
            params = []
            
            for field in allowed_fields:
                if field in kwargs:
                    updates.append(f"{field} = ?")
                    value = kwargs[field]
                    if field in ('active', 'upside_down'):
                        value = 1 if value else 0
                    params.append(value)
            
            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.utcnow().isoformat())
                params.extend([bookmark_id, tenant_id])
                
                cursor.execute(f"""
                    UPDATE bookmarks SET {', '.join(updates)} 
                    WHERE id = ? AND tenant_id = ?
                """, params)
                conn.commit()
            
            cursor.execute("""
                SELECT * FROM bookmarks 
                WHERE id = ? AND tenant_id = ?
            """, (bookmark_id, tenant_id))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def delete_bookmark(self, tenant_id: str, bookmark_id: str) -> bool:
        """Delete a bookmark and its check history"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Verify bookmark belongs to tenant
            cursor.execute("""
                SELECT id FROM bookmarks WHERE id = ? AND tenant_id = ?
            """, (bookmark_id, tenant_id))
            if not cursor.fetchone():
                return False
            
            # Delete check history first (foreign key)
            cursor.execute("DELETE FROM bookmark_checks WHERE bookmark_id = ?", (bookmark_id,))
            cursor.execute("DELETE FROM bookmarks WHERE id = ? AND tenant_id = ?", (bookmark_id, tenant_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def record_bookmark_check(self, bookmark_id: str, status: int, 
                             latency_ms: int = None, message: str = None) -> dict:
        """Record a check result for a bookmark"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            now = datetime.utcnow().isoformat() + 'Z'  # Add Z suffix to indicate UTC
            
            cursor.execute("""
                INSERT INTO bookmark_checks (bookmark_id, created_at, status, latency_ms, message)
                VALUES (?, ?, ?, ?, ?)
            """, (bookmark_id, now, status, latency_ms, message))
            
            conn.commit()
            
            cursor.execute("""
                SELECT * FROM bookmark_checks WHERE id = ?
            """, (cursor.lastrowid,))
            return dict(cursor.fetchone())
        finally:
            conn.close()
    
    def get_bookmark_checks(self, bookmark_id: str, limit: int = 60) -> List[dict]:
        """Get recent check history for a bookmark"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM bookmark_checks 
                WHERE bookmark_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (bookmark_id, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_bookmark_with_checks(self, tenant_id: str, bookmark_id: str, check_limit: int = 60) -> dict:
        """Get bookmark details with recent check history"""
        bookmark = self.get_bookmark(tenant_id, bookmark_id)
        if not bookmark:
            return None
        
        checks = self.get_bookmark_checks(bookmark_id, check_limit)
        bookmark["checks"] = checks
        
        # Calculate uptime percentage from checks
        if checks:
            up_count = sum(1 for c in checks if c["status"] == 1)
            bookmark["uptime_percent"] = round((up_count / len(checks)) * 100, 1)
            bookmark["avg_latency"] = round(
                sum(c["latency_ms"] or 0 for c in checks if c["status"] == 1) / max(up_count, 1), 1
            )
        else:
            bookmark["uptime_percent"] = None
            bookmark["avg_latency"] = None
        
        return bookmark
    
    def cleanup_old_bookmark_checks(self, days: int = 30) -> int:
        """Delete bookmark checks older than specified days"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            cursor.execute("""
                DELETE FROM bookmark_checks WHERE created_at < ?
            """, (cutoff,))
            conn.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"🧹 Cleaned up {deleted} old bookmark checks (older than {days} days)")
            return deleted
        finally:
            conn.close()

    def get_bookmark_checks_range(self, tenant_id: str, bookmark_id: int, hours: int = 24) -> List[dict]:
        """Get bookmark checks within a time range"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            cursor.execute("""
                SELECT bc.* FROM bookmark_checks bc
                JOIN bookmarks b ON bc.bookmark_id = b.id
                WHERE bc.bookmark_id = ? AND b.tenant_id = ? AND bc.created_at >= ?
                ORDER BY bc.created_at DESC
            """, (bookmark_id, tenant_id, cutoff))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


    # ==================== REPORT PROFILES ====================
    
    def _get_profile_storage_path(self, profile_id: str) -> Path:
        """Get the storage path for a profile's reports"""
        return Path(REPORT_STORAGE_ROOT) / profile_id
    
    def _ensure_profile_storage(self, profile_id: str) -> Path:
        """Create the storage folder for a profile if it doesn't exist"""
        path = self._get_profile_storage_path(profile_id)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _delete_profile_storage(self, profile_id: str) -> bool:
        """Recursively delete the storage folder for a profile"""
        path = self._get_profile_storage_path(profile_id)
        if path.exists():
            try:
                shutil.rmtree(path)
                return True
            except Exception as e:
                print(f"Warning: Failed to delete profile storage {path}: {e}")
                return False
        return True
    
    def save_profile_report(self, profile_id: str, report_data: dict, pdf_content: bytes = None) -> dict:
        """Save a report to the profile's storage folder with rotation"""
        storage_path = self._ensure_profile_storage(profile_id)
        
        # Get max reports setting (default 12)
        max_reports = int(self.get_system_setting("max_exec_reports_per_profile", "12"))
        
        # Rotate: Delete oldest reports if at or above the limit
        self._rotate_profile_reports(storage_path, max_reports)
        
        # Generate timestamp-based filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_id = f"report_{timestamp}"
        
        # Save meta.json
        meta_path = storage_path / f"{report_id}_meta.json"
        meta_data = {
            "id": report_id,
            "profile_id": profile_id,
            "generated_at": datetime.utcnow().isoformat(),
            **report_data
        }
        with open(meta_path, 'w') as f:
            json.dump(meta_data, f, indent=2, default=str)
        
        # Save PDF if provided
        pdf_path = None
        if pdf_content:
            pdf_path = storage_path / f"{report_id}.pdf"
            with open(pdf_path, 'wb') as f:
                f.write(pdf_content)
        
        return {
            "report_id": report_id,
            "meta_path": str(meta_path),
            "pdf_path": str(pdf_path) if pdf_path else None
        }
    
    def _rotate_profile_reports(self, storage_path: Path, max_reports: int):
        """Delete oldest reports to stay within max_reports limit"""
        try:
            # Get all meta.json files sorted by creation time (oldest first)
            meta_files = list(storage_path.glob("*_meta.json"))
            
            # Sort by file modification time (oldest first)
            meta_files.sort(key=lambda f: f.stat().st_mtime)
            
            # Calculate how many to delete (need to make room for new one)
            files_to_delete = len(meta_files) - max_reports + 1
            
            if files_to_delete > 0:
                for meta_file in meta_files[:files_to_delete]:
                    # Extract report_id from filename
                    report_id = meta_file.stem.replace("_meta", "")
                    
                    # Delete meta.json
                    try:
                        meta_file.unlink()
                    except Exception as e:
                        print(f"Warning: Failed to delete {meta_file}: {e}")
                    
                    # Delete associated PDF if exists
                    pdf_file = storage_path / f"{report_id}.pdf"
                    if pdf_file.exists():
                        try:
                            pdf_file.unlink()
                        except Exception as e:
                            print(f"Warning: Failed to delete {pdf_file}: {e}")
                    
                    print(f"Rotated old report: {report_id}")
        except Exception as e:
            print(f"Warning: Report rotation failed: {e}")
    
    def get_profile_reports(self, profile_id: str) -> List[dict]:
        """Get all reports for a profile from storage"""
        storage_path = self._get_profile_storage_path(profile_id)
        reports = []
        
        if not storage_path.exists():
            return reports
        
        for meta_file in sorted(storage_path.glob("*_meta.json"), reverse=True):
            try:
                with open(meta_file, 'r') as f:
                    meta_data = json.load(f)
                    # Check if PDF exists
                    report_id = meta_data.get("id", meta_file.stem.replace("_meta", ""))
                    pdf_path = storage_path / f"{report_id}.pdf"
                    meta_data["has_pdf"] = pdf_path.exists()
                    reports.append(meta_data)
            except Exception as e:
                print(f"Warning: Failed to load report meta {meta_file}: {e}")
        
        return reports
    
    def get_profile_report_pdf(self, profile_id: str, report_id: str) -> bytes:
        """Get PDF content for a specific report"""
        storage_path = self._get_profile_storage_path(profile_id)
        pdf_path = storage_path / f"{report_id}.pdf"
        
        if pdf_path.exists():
            with open(pdf_path, 'rb') as f:
                return f.read()
        return None
    
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
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            profile_id = f"rp_{secrets.token_hex(8)}"
            now = datetime.utcnow().isoformat()
            
            # Ensure frequency and sla_target columns exist
            cursor.execute("PRAGMA table_info(report_profiles)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'frequency' not in columns:
                cursor.execute("ALTER TABLE report_profiles ADD COLUMN frequency TEXT DEFAULT 'MONTHLY'")
            if 'sla_target' not in columns:
                cursor.execute("ALTER TABLE report_profiles ADD COLUMN sla_target REAL DEFAULT 99.9")
            if 'schedule_hour' not in columns:
                cursor.execute("ALTER TABLE report_profiles ADD COLUMN schedule_hour INTEGER DEFAULT 7")
            
            # Store arrays as JSON strings
            cursor.execute("""
                INSERT INTO report_profiles (id, tenant_id, name, description, frequency, sla_target, schedule_hour,
                                             recipient_emails, monitor_scope_tags,
                                             monitor_scope_ids, scribe_scope_tags,
                                             scribe_scope_ids, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (profile_id, tenant_id, name, description, frequency, sla_target, schedule_hour,
                  json.dumps(recipient_emails or []),
                  json.dumps(monitor_scope_tags or []),
                  json.dumps(monitor_scope_ids or []),
                  json.dumps(scribe_scope_tags or []),
                  json.dumps(scribe_scope_ids or []),
                  now, now))
            
            conn.commit()
            
            # Create storage folder for this profile
            self._ensure_profile_storage(profile_id)
            
            cursor.execute("SELECT * FROM report_profiles WHERE id = ?", (profile_id,))
            row = cursor.fetchone()
            return self._parse_report_profile(dict(row))
        finally:
            conn.close()
    
    def _parse_report_profile(self, row: dict) -> dict:
        """Parse JSON fields in report profile row"""
        if row:
            for field in ['recipient_emails', 'monitor_scope_tags', 'monitor_scope_ids',
                         'scribe_scope_tags', 'scribe_scope_ids']:
                if row.get(field):
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
        return row
    
    def get_report_profile(self, tenant_id: str, profile_id: str) -> dict:
        """Get a report profile by ID"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM report_profiles 
                WHERE id = ? AND tenant_id = ?
            """, (profile_id, tenant_id))
            row = cursor.fetchone()
            return self._parse_report_profile(dict(row)) if row else None
        finally:
            conn.close()
    
    def get_report_profiles(self, tenant_id: str) -> List[dict]:
        """Get all report profiles for a tenant"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM report_profiles 
                WHERE tenant_id = ?
                ORDER BY name ASC
            """, (tenant_id,))
            return [self._parse_report_profile(dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def update_report_profile(self, tenant_id: str, profile_id: str, **kwargs) -> dict:
        """Update a report profile"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        allowed_fields = ['name', 'description', 'frequency', 'sla_target', 'schedule_hour', 'recipient_emails', 
                         'monitor_scope_tags', 'monitor_scope_ids',
                         'scribe_scope_tags', 'scribe_scope_ids']
        
        # Fields that need JSON serialization
        json_fields = ['recipient_emails', 'monitor_scope_tags', 'monitor_scope_ids',
                      'scribe_scope_tags', 'scribe_scope_ids']
        
        try:
            # Ensure frequency, sla_target, and schedule_hour columns exist
            cursor.execute("PRAGMA table_info(report_profiles)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'frequency' not in columns:
                cursor.execute("ALTER TABLE report_profiles ADD COLUMN frequency TEXT DEFAULT 'MONTHLY'")
            if 'sla_target' not in columns:
                cursor.execute("ALTER TABLE report_profiles ADD COLUMN sla_target REAL DEFAULT 99.9")
            if 'schedule_hour' not in columns:
                cursor.execute("ALTER TABLE report_profiles ADD COLUMN schedule_hour INTEGER DEFAULT 7")
            
            updates = []
            params = []
            
            for field in allowed_fields:
                if field in kwargs:
                    updates.append(f"{field} = ?")
                    value = kwargs[field]
                    if field in json_fields:
                        value = json.dumps(value if value else [])
                    params.append(value)
            
            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.utcnow().isoformat())
                params.extend([profile_id, tenant_id])
                
                cursor.execute(f"""
                    UPDATE report_profiles SET {', '.join(updates)} 
                    WHERE id = ? AND tenant_id = ?
                """, params)
                conn.commit()
            
            cursor.execute("""
                SELECT * FROM report_profiles 
                WHERE id = ? AND tenant_id = ?
            """, (profile_id, tenant_id))
            row = cursor.fetchone()
            return self._parse_report_profile(dict(row)) if row else None
        finally:
            conn.close()
    
    def delete_report_profile(self, tenant_id: str, profile_id: str) -> bool:
        """Delete a report profile and its storage folder"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM report_profiles 
                WHERE id = ? AND tenant_id = ?
            """, (profile_id, tenant_id))
            conn.commit()
            
            deleted = cursor.rowcount > 0
            
            # If DB delete succeeded, also delete the storage folder
            if deleted:
                self._delete_profile_storage(profile_id)
            
            return deleted
        finally:
            conn.close()
    
    def get_all_report_profiles_for_scheduling(self) -> List[dict]:
        """Get all report profiles across all tenants for scheduling purposes"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Ensure frequency column exists
            cursor.execute("PRAGMA table_info(report_profiles)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'frequency' not in columns:
                cursor.execute("ALTER TABLE report_profiles ADD COLUMN frequency TEXT DEFAULT 'MONTHLY'")
                conn.commit()
            
            cursor.execute("SELECT * FROM report_profiles ORDER BY tenant_id, name")
            return [self._parse_report_profile(dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==================== SETUP WIZARD ====================
    
    def is_setup_complete(self) -> bool:
        """Check if the initial setup has been completed"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Check if setup_config table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='setup_config'")
            if not cursor.fetchone():
                return False
            
            # Check if setup is marked complete
            cursor.execute("SELECT value FROM setup_config WHERE key = 'setup_complete'")
            row = cursor.fetchone()
            return row is not None and row[0] == '1'
        except Exception as e:
            print(f"Error checking setup status: {e}")
            return False
        finally:
            conn.close()
    
    def get_setup_config(self) -> dict:
        """Get all setup configuration values"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='setup_config'")
            if not cursor.fetchone():
                return {}
            
            cursor.execute("SELECT key, value FROM setup_config")
            return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            print(f"Error getting setup config: {e}")
            return {}
        finally:
            conn.close()
    
    def complete_setup(self, admin_username: str, admin_password: str, 
                      instance_name: str = "LogLibrarian",
                      deployment_profile: str = "homelab",
                      default_retention_days: int = 30,
                      timezone: str = "UTC",
                      instance_api_key: str = None) -> dict:
        """
        Complete the initial setup wizard.
        Creates admin user and stores configuration including instance API key.
        
        Args:
            admin_username: Admin account username
            admin_password: Admin account password
            instance_name: Name of this LogLibrarian instance
            deployment_profile: Deployment profile (homelab, small_business, production)
            default_retention_days: Default data retention in days
            timezone: Instance timezone
            instance_api_key: The API key all scribes must use to connect
        
        Returns: dict with success status and any errors
        """
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Create setup_config table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS setup_config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Check if already set up
            cursor.execute("SELECT value FROM setup_config WHERE key = 'setup_complete'")
            if cursor.fetchone():
                return {"success": False, "error": "Setup already completed"}
            
            # Validate inputs
            if not admin_username or len(admin_username) < 3:
                return {"success": False, "error": "Username must be at least 3 characters"}
            if not admin_password or len(admin_password) < 6:
                return {"success": False, "error": "Password must be at least 6 characters"}
            if not instance_api_key or len(instance_api_key) < 32:
                return {"success": False, "error": "Instance API key must be at least 32 characters"}
            
            # Delete any existing users (fresh start)
            cursor.execute("DELETE FROM users")
            
            # Create admin user
            password_hash = self.hash_password(admin_password)
            cursor.execute("""
                INSERT INTO users (username, password_hash, is_admin, role, is_setup_complete)
                VALUES (?, ?, 1, 'admin', 1)
            """, (admin_username, password_hash))
            
            # Store setup configuration including instance API key
            config_items = [
                ('setup_complete', '1'),
                ('instance_name', instance_name),
                ('deployment_profile', deployment_profile),
                ('default_retention_days', str(default_retention_days)),
                ('timezone', timezone),
                ('setup_timestamp', datetime.now().isoformat()),
                ('database_type', 'sqlite'),
                ('instance_api_key', instance_api_key)
            ]
            
            for key, value in config_items:
                cursor.execute("""
                    INSERT OR REPLACE INTO setup_config (key, value, updated_at)
                    VALUES (?, ?, datetime('now'))
                """, (key, value))
            
            # Update default retention in janitor settings
            cursor.execute("""
                INSERT OR REPLACE INTO janitor_settings (id, retention_days, cleanup_hour, enabled, updated_at)
                VALUES (1, ?, 3, 1, datetime('now'))
            """, (default_retention_days,))
            
            conn.commit()
            
            return {
                "success": True,
                "admin_username": admin_username,
                "instance_name": instance_name,
                "deployment_profile": deployment_profile
            }
            
        except Exception as e:
            print(f"Error completing setup: {e}")
            conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            conn.close()
    
    def get_instance_name(self) -> str:
        """Get the configured instance name"""
        config = self.get_setup_config()
        return config.get('instance_name', 'LogLibrarian')
    
    def get_instance_api_key(self) -> Optional[str]:
        """Get the instance API key from setup_config"""
        config = self.get_setup_config()
        return config.get('instance_api_key')
    
    def regenerate_instance_api_key(self, new_key: str) -> bool:
        """Regenerate the instance API key (admin only)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        try:
            if not new_key or len(new_key) < 32:
                return False
            
            cursor.execute("""
                UPDATE setup_config 
                SET value = ?, updated_at = datetime('now')
                WHERE key = 'instance_api_key'
            """, (new_key,))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error regenerating instance API key: {e}")
            return False
        finally:
            conn.close()


# Global database manager instance
db_manager = DatabaseManager()
