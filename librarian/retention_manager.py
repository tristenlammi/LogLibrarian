"""
Data Retention Manager (Janitor)

Manages automatic data retention and downsampling for LogLibrarian.
Handles cleanup of old data based on configurable retention policies.

Retention Policy (default):
- Raw metrics (1-2 sec resolution): 48 hours
- 1-minute aggregates: 7 days
- 15-minute aggregates: 30 days
- 1-hour aggregates: 365 days (1 year)
- Raw logs: 7 days (configurable per-agent)

Storage Safety Features:
- Size cap: Deletes oldest rows when storage exceeds max_storage_gb
- Disk space monitoring: Tracks free disk space for panic switch
"""

import asyncio
import os
import shutil
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass


# Configuration from environment
RETENTION_CHECK_INTERVAL_HOURS = int(os.getenv("RETENTION_CHECK_INTERVAL", "1"))

# Size-based cleanup configuration
MAX_STORAGE_GB = float(os.getenv("MAX_STORAGE_GB", "10"))  # Max storage in GB before cleanup
SIZE_CLEANUP_BATCH = int(os.getenv("SIZE_CLEANUP_BATCH", "10000"))  # Rows to delete per batch

# Panic switch configuration (disk space protection)
MIN_FREE_SPACE_GB = float(os.getenv("MIN_FREE_SPACE_GB", "1"))  # Minimum 1GB free
MIN_FREE_SPACE_PERCENT = float(os.getenv("MIN_FREE_SPACE_PERCENT", "5"))  # Minimum 5% free

# Default retention periods (can be overridden)
DEFAULT_RETENTION_POLICIES = {
    "metrics": timedelta(hours=48),          # Raw metrics: 48 hours
    "metrics_1min": timedelta(days=7),       # 1-min aggregates: 7 days
    "metrics_15min": timedelta(days=30),     # 15-min aggregates: 30 days
    "metrics_1hour": timedelta(days=365),    # 1-hour aggregates: 1 year
    "raw_logs": timedelta(days=7),           # Raw logs: 7 days
    "log_occurrences": timedelta(days=30),   # Log occurrences: 30 days
    "process_snapshots": timedelta(days=7),  # Process snapshots: 7 days
    # AI data retention
    "ai_briefings": timedelta(days=90),      # AI briefings: 90 days
    "ai_chat": timedelta(days=30),           # Chat history: 30 days
}


def get_disk_space_info(path: str = ".") -> Dict[str, Any]:
    """
    Get disk space information for the given path.
    
    Returns:
        Dict with total, used, free space in bytes and percentages
    """
    try:
        total, used, free = shutil.disk_usage(path)
        free_percent = (free / total) * 100 if total > 0 else 0
        used_percent = (used / total) * 100 if total > 0 else 0
        
        return {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "free_percent": round(free_percent, 2),
            "used_percent": round(used_percent, 2),
            "path": os.path.abspath(path)
        }
    except Exception as e:
        return {
            "error": str(e),
            "path": path
        }


def check_disk_space_ok(path: str = ".") -> Tuple[bool, str]:
    """
    Check if disk space is above minimum thresholds.
    
    Returns:
        Tuple of (is_ok, message)
    """
    info = get_disk_space_info(path)
    
    if "error" in info:
        # If we can't check, allow operation but warn
        return True, f"Unable to check disk space: {info['error']}"
    
    free_gb = info["free_gb"]
    free_percent = info["free_percent"]
    
    if free_gb < MIN_FREE_SPACE_GB:
        return False, f"PANIC: Disk space critically low! Only {free_gb:.2f}GB free (minimum: {MIN_FREE_SPACE_GB}GB)"
    
    if free_percent < MIN_FREE_SPACE_PERCENT:
        return False, f"PANIC: Disk space critically low! Only {free_percent:.1f}% free (minimum: {MIN_FREE_SPACE_PERCENT}%)"
    
    return True, f"Disk space OK: {free_gb:.2f}GB ({free_percent:.1f}%) free"


@dataclass
class CleanupResult:
    """Result of a single table cleanup operation"""
    table_name: str
    rows_deleted: int
    duration_ms: float
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "table_name": self.table_name,
            "rows_deleted": self.rows_deleted,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error
        }


@dataclass
class RetentionRunResult:
    """Result of a full retention run"""
    run_timestamp: datetime
    total_rows_deleted: int
    total_duration_ms: float
    cleanup_results: List[CleanupResult]
    
    def to_dict(self) -> dict:
        return {
            "run_timestamp": self.run_timestamp.isoformat(),
            "total_rows_deleted": self.total_rows_deleted,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "tables_cleaned": len(self.cleanup_results),
            "details": [r.to_dict() for r in self.cleanup_results]
        }


class RetentionManager:
    """
    Manages data retention and cleanup for TimescaleDB and SQLite.
    
    Features:
    - Time-based retention: Deletes data older than retention period
    - Size-based cleanup: Deletes oldest rows when storage exceeds max_storage_gb
    - Disk space monitoring: Provides disk space info for panic switch
    
    For TimescaleDB:
    - Uses native retention policies for hypertables (raw data)
    - Manually cleans continuous aggregates (they don't support retention policies)
    
    For SQLite:
    - Performs direct DELETE operations based on timestamp
    """
    
    def __init__(self, db_manager, use_postgres: bool = False):
        self.db_manager = db_manager
        self.use_postgres = use_postgres
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run: Optional[RetentionRunResult] = None
        
        # Storage limits (will be loaded from DB)
        self.max_storage_gb = MAX_STORAGE_GB
        self.size_cleanup_batch = SIZE_CLEANUP_BATCH
        
        # Allow custom retention policies
        self.retention_policies = DEFAULT_RETENTION_POLICIES.copy()
        
        # Load settings from database
        self._load_settings_from_db()
    
    def _load_settings_from_db(self):
        """Load janitor settings from the database"""
        global MIN_FREE_SPACE_GB
        try:
            # Load max storage
            max_storage = self.db_manager.get_system_setting("max_storage_gb", "")
            if max_storage:
                self.max_storage_gb = float(max_storage)
                print(f"  📦 Max storage: {self.max_storage_gb} GB")
            
            # Load min free space
            min_free = self.db_manager.get_system_setting("min_free_space_gb", "")
            if min_free:
                MIN_FREE_SPACE_GB = float(min_free)
                print(f"  💾 Min free space: {MIN_FREE_SPACE_GB} GB")
            
            # Load retention policies
            raw_logs_days = self.db_manager.get_system_setting("retention_raw_logs_days", "")
            if raw_logs_days:
                self.retention_policies["raw_logs"] = timedelta(days=int(raw_logs_days))
                print(f"  📝 Raw logs retention: {raw_logs_days} days")
            
            metrics_hours = self.db_manager.get_system_setting("retention_metrics_hours", "")
            if metrics_hours:
                self.retention_policies["metrics"] = timedelta(hours=int(metrics_hours))
                print(f"  📊 Metrics retention: {metrics_hours} hours")
            
            snapshots_days = self.db_manager.get_system_setting("retention_process_snapshots_days", "")
            if snapshots_days:
                self.retention_policies["process_snapshots"] = timedelta(days=int(snapshots_days))
                print(f"  🔄 Process snapshots retention: {snapshots_days} days")
            
            # Load AI data retention policies
            ai_briefings_days = self.db_manager.get_system_setting("retention_ai_briefings_days", "")
            if ai_briefings_days:
                self.retention_policies["ai_briefings"] = timedelta(days=int(ai_briefings_days))
                print(f"  📋 AI briefings retention: {ai_briefings_days} days")
            
            ai_chat_days = self.db_manager.get_system_setting("retention_ai_chat_days", "")
            if ai_chat_days:
                self.retention_policies["ai_chat"] = timedelta(days=int(ai_chat_days))
                print(f"  💬 AI chat retention: {ai_chat_days} days")
                
        except Exception as e:
            print(f"⚠️ Could not load janitor settings from DB, using defaults: {e}")
    
    def get_retention_policy(self) -> Dict[str, Any]:
        """Get current retention policy configuration"""
        disk_info = get_disk_space_info(".")
        return {
            "policies": {
                name: {
                    "retention_period": str(td),
                    "retention_hours": td.total_seconds() / 3600,
                    "retention_days": td.days if td.days > 0 else round(td.total_seconds() / 86400, 2)
                }
                for name, td in self.retention_policies.items()
            },
            "check_interval_hours": RETENTION_CHECK_INTERVAL_HOURS,
            "max_storage_gb": self.max_storage_gb,
            "size_cleanup_batch": self.size_cleanup_batch,
            "disk_space": disk_info,
            "panic_switch": {
                "min_free_space_gb": MIN_FREE_SPACE_GB,
                "min_free_space_percent": MIN_FREE_SPACE_PERCENT
            },
            "last_run": self._last_run.to_dict() if self._last_run else None,
            "use_postgres": self.use_postgres
        }
    
    async def start(self):
        """Start the background retention task"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._retention_loop())
        print(f"🗑️ Retention manager started (check interval: {RETENTION_CHECK_INTERVAL_HOURS}h)")
    
    async def stop(self):
        """Stop the retention task"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("🗑️ Retention manager stopped")
    
    async def _retention_loop(self):
        """Background loop that runs cleanup periodically"""
        # Initial delay: wait 5 minutes after startup before first run
        await asyncio.sleep(300)
        
        while self._running:
            try:
                print("🧹 Janitor: Running scheduled retention cleanup...")
                
                # Step 1: Time-based cleanup
                result = await self.run_cleanup()
                print(f"🧹 Janitor: Time-based cleanup complete: {result.total_rows_deleted} rows deleted in {result.total_duration_ms:.1f}ms")
                
                # Step 2: Size-based cleanup (safety net)
                size_deleted = await self.cleanup_by_size()
                if size_deleted > 0:
                    print(f"🧹 Janitor: Size-based cleanup removed {size_deleted} additional rows")
                
                # Step 3: Log disk space status
                disk_ok, disk_msg = check_disk_space_ok(".")
                if not disk_ok:
                    print(f"⚠️ CRITICAL: {disk_msg}")
                else:
                    disk_info = get_disk_space_info(".")
                    print(f"💾 Disk status: {disk_info.get('free_gb', '?')}GB free ({disk_info.get('free_percent', '?')}%)")
                    
            except Exception as e:
                print(f"❌ Janitor error: {e}")
            
            # Wait for next check interval
            await asyncio.sleep(RETENTION_CHECK_INTERVAL_HOURS * 3600)
    
    async def run_cleanup(self) -> RetentionRunResult:
        """
        Run full retention cleanup across all tables.
        
        Returns:
            RetentionRunResult with details of what was cleaned
        """
        start_time = time.time()
        run_timestamp = datetime.now()
        cleanup_results: List[CleanupResult] = []
        
        if self.use_postgres:
            cleanup_results = await self._cleanup_postgres()
        else:
            cleanup_results = self._cleanup_sqlite()
        
        total_rows = sum(r.rows_deleted for r in cleanup_results)
        total_duration = (time.time() - start_time) * 1000
        
        self._last_run = RetentionRunResult(
            run_timestamp=run_timestamp,
            total_rows_deleted=total_rows,
            total_duration_ms=total_duration,
            cleanup_results=cleanup_results
        )
        
        # Log to database if using PostgreSQL
        if self.use_postgres:
            await self._log_cleanup_results(cleanup_results)
        
        return self._last_run
    
    async def cleanup_by_size(self) -> int:
        """
        Size-based cleanup safety net.
        
        If the database exceeds max_storage_gb, delete the oldest rows in batches
        until storage is under the limit.
        
        Returns:
            Total number of rows deleted
        """
        total_deleted = 0
        max_iterations = 100  # Safety limit to prevent infinite loops
        
        for iteration in range(max_iterations):
            # Check current storage size
            stats = await self.get_storage_stats()
            
            if "error" in stats:
                print(f"⚠️ Cannot check storage size: {stats['error']}")
                break
            
            # Calculate current size in GB
            if self.use_postgres:
                # Sum up all hypertable sizes
                current_size_bytes = sum(
                    ht.get("size_bytes", 0) or 0 
                    for ht in stats.get("hypertables", {}).values()
                )
            else:
                current_size_bytes = stats.get("file_size_bytes", 0)
            
            current_size_gb = current_size_bytes / (1024**3)
            
            # Check if we're under the limit
            if current_size_gb <= self.max_storage_gb:
                if iteration > 0:
                    print(f"🧹 Size cleanup complete: now at {current_size_gb:.2f}GB (limit: {self.max_storage_gb}GB)")
                break
            
            print(f"⚠️ Storage size ({current_size_gb:.2f}GB) exceeds limit ({self.max_storage_gb}GB). Cleaning oldest data...")
            
            # Delete oldest rows from the largest tables
            deleted = await self._delete_oldest_rows()
            total_deleted += deleted
            
            if deleted == 0:
                print("⚠️ No more rows to delete, but still over size limit")
                break
        
        return total_deleted
    
    async def _delete_oldest_rows(self) -> int:
        """
        Delete the oldest batch of rows from raw_logs and metrics tables.
        
        Returns:
            Number of rows deleted
        """
        if self.use_postgres:
            return await self._delete_oldest_postgres()
        else:
            return self._delete_oldest_sqlite()
    
    async def _delete_oldest_postgres(self) -> int:
        """Delete oldest rows from PostgreSQL tables"""
        total_deleted = 0
        
        try:
            async_db = self.db_manager._async_db if hasattr(self.db_manager, '_async_db') else self.db_manager
            
            async with async_db.connection() as conn:
                # Delete oldest raw_logs first (usually largest)
                result = await conn.execute(f"""
                    DELETE FROM raw_logs
                    WHERE id IN (
                        SELECT id FROM raw_logs
                        ORDER BY timestamp ASC
                        LIMIT {self.size_cleanup_batch}
                    )
                """)
                raw_deleted = int(result.split()[-1]) if result and 'DELETE' in result else 0
                total_deleted += raw_deleted
                
                # Delete oldest metrics if raw_logs didn't have enough
                if raw_deleted < self.size_cleanup_batch // 2:
                    result = await conn.execute(f"""
                        DELETE FROM metrics
                        WHERE id IN (
                            SELECT id FROM metrics
                            ORDER BY timestamp ASC
                            LIMIT {self.size_cleanup_batch}
                        )
                    """)
                    metrics_deleted = int(result.split()[-1]) if result and 'DELETE' in result else 0
                    total_deleted += metrics_deleted
                    
        except Exception as e:
            print(f"❌ Error deleting oldest rows (PostgreSQL): {e}")
        
        return total_deleted
    
    def _delete_oldest_sqlite(self) -> int:
        """Delete oldest rows from SQLite tables"""
        import sqlite3
        
        SQLITE_DB_PATH = "./loglibrarian.db"
        total_deleted = 0
        
        try:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            
            # Delete oldest raw_logs first
            cursor.execute(f"""
                DELETE FROM raw_logs
                WHERE id IN (
                    SELECT id FROM raw_logs
                    ORDER BY timestamp ASC
                    LIMIT {self.size_cleanup_batch}
                )
            """)
            raw_deleted = cursor.rowcount
            total_deleted += raw_deleted
            
            # Delete oldest metrics if needed
            if raw_deleted < self.size_cleanup_batch // 2:
                cursor.execute(f"""
                    DELETE FROM metrics
                    WHERE id IN (
                        SELECT id FROM metrics
                        ORDER BY timestamp ASC
                        LIMIT {self.size_cleanup_batch}
                    )
                """)
                metrics_deleted = cursor.rowcount
                total_deleted += metrics_deleted
            
            conn.commit()
            conn.close()
            
            if total_deleted > 0:
                # VACUUM to reclaim space (SQLite specific)
                conn = sqlite3.connect(SQLITE_DB_PATH)
                conn.execute("VACUUM")
                conn.close()
                
        except Exception as e:
            print(f"❌ Error deleting oldest rows (SQLite): {e}")
        
        return total_deleted
    
    async def _cleanup_postgres(self) -> List[CleanupResult]:
        """
        Cleanup for PostgreSQL/TimescaleDB.
        
        Note: TimescaleDB hypertables use native retention policies.
        We manually clean continuous aggregates here.
        """
        results = []
        
        # Clean continuous aggregates (they don't support native retention policies)
        aggregate_tables = [
            ("metrics_1min", "bucket", self.retention_policies["metrics_1min"]),
            ("metrics_15min", "bucket", self.retention_policies["metrics_15min"]),
            ("metrics_1hour", "bucket", self.retention_policies["metrics_1hour"]),
        ]
        
        for table_name, time_column, retention in aggregate_tables:
            result = self._cleanup_postgres_table_sync(table_name, time_column, retention)
            results.append(result)
        
        # Clean process_snapshots (not a hypertable)
        result = self._cleanup_postgres_table_sync(
            "process_snapshots", 
            "timestamp", 
            self.retention_policies.get("process_snapshots", timedelta(days=7))
        )
        results.append(result)
        
        # Note: metrics, raw_logs, log_occurrences are cleaned by TimescaleDB retention policies
        # We can optionally check their status
        for table in ["metrics", "raw_logs", "log_occurrences"]:
            info = self._get_hypertable_info_sync(table)
            if info:
                results.append(CleanupResult(
                    table_name=table,
                    rows_deleted=0,  # Cleaned by TimescaleDB
                    duration_ms=0,
                    error=None
                ))
        
        return results
    
    def _cleanup_postgres_table_sync(
        self, 
        table_name: str, 
        time_column: str, 
        retention: timedelta
    ) -> CleanupResult:
        """Clean a single PostgreSQL table using sync connection"""
        start = time.time()
        cutoff = datetime.now() - retention
        
        try:
            # Use the db_manager's cleanup method if available
            if hasattr(self.db_manager, 'cleanup_continuous_aggregates'):
                result = self.db_manager.cleanup_continuous_aggregates({table_name: retention.days})
                rows_deleted = result.get(table_name, {}).get("deleted", 0)
            else:
                # Direct SQL using connection pool
                from db_connection_pool import get_pool
                pool = get_pool()
                
                with pool.dict_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"""
                        DELETE FROM {table_name}
                        WHERE {time_column} < %s
                    """, (cutoff,))
                    rows_deleted = cursor.rowcount
                    conn.commit()
            
            duration_ms = (time.time() - start) * 1000
            
            if rows_deleted > 0:
                print(f"  🗑️ {table_name}: deleted {rows_deleted} rows older than {retention}")
            
            return CleanupResult(
                table_name=table_name,
                rows_deleted=rows_deleted,
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            print(f"  ❌ {table_name}: error - {e}")
            return CleanupResult(
                table_name=table_name,
                rows_deleted=0,
                duration_ms=duration_ms,
                error=str(e)
            )
    
    def _get_hypertable_info_sync(self, table_name: str) -> Optional[dict]:
        """Get info about a TimescaleDB hypertable using sync connection"""
        try:
            if hasattr(self.db_manager, 'pool'):
                row = self.db_manager.pool.fetchone("""
                    SELECT 
                        hypertable_name,
                        num_chunks,
                        compression_enabled
                    FROM timescaledb_information.hypertables
                    WHERE hypertable_name = %s
                """, (table_name,))
                
                if row:
                    return dict(row)
            return None
        except Exception:
            return None
    
    def _log_cleanup_results_sync(self, results: List[CleanupResult]):
        """Log cleanup results to the database using sync connection"""
        try:
            if not hasattr(self.db_manager, 'pool'):
                return
                
            for result in results:
                self.db_manager.pool.execute("""
                    INSERT INTO retention_cleanup_log 
                    (table_name, rows_deleted, duration_ms, error_message)
                    VALUES (%s, %s, %s, %s)
                """, (result.table_name, result.rows_deleted, result.duration_ms, result.error))
                
                # Update retention_policies table
                self.db_manager.pool.execute("""
                    UPDATE retention_policies
                    SET last_cleanup = NOW(),
                        rows_deleted_last_run = %s,
                        updated_at = NOW()
                    WHERE table_name = %s
                """, (result.rows_deleted, result.table_name))
        except Exception as e:
            print(f"Error logging cleanup results: {e}")
    
    # Keep async versions for backward compatibility
    async def _cleanup_postgres_table(
        self, 
        table_name: str, 
        time_column: str, 
        retention: timedelta
    ) -> CleanupResult:
        """Clean a single PostgreSQL table (async wrapper for sync method)"""
        return self._cleanup_postgres_table_sync(table_name, time_column, retention)
    
    async def _get_hypertable_info(self, table_name: str) -> Optional[dict]:
        """Get info about a TimescaleDB hypertable (async wrapper)"""
        return self._get_hypertable_info_sync(table_name)
    
    async def _log_cleanup_results(self, results: List[CleanupResult]):
        """Log cleanup results to the database (async wrapper)"""
        self._log_cleanup_results_sync(results)
    
    def _cleanup_sqlite(self) -> List[CleanupResult]:
        """
        Cleanup for SQLite.
        
        SQLite doesn't have continuous aggregates, so we clean raw tables directly.
        Also cleans AI data (briefings, tips, chat history).
        """
        import sqlite3
        
        SQLITE_DB_PATH = "./loglibrarian.db"
        results = []
        
        # Tables to clean: (table_name, time_column, retention)
        tables = [
            ("metrics", "timestamp", self.retention_policies["metrics"]),
            ("raw_logs", "timestamp", self.retention_policies.get("raw_logs", timedelta(days=7))),
            ("log_occurrences", "timestamp", self.retention_policies.get("log_occurrences", timedelta(days=30))),
            ("process_snapshots", "timestamp", self.retention_policies.get("process_snapshots", timedelta(days=7))),
        ]
        
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()
        
        for table_name, time_column, retention in tables:
            start = time.time()
            cutoff = (datetime.now() - retention).isoformat()
            
            try:
                cursor.execute(f"""
                    DELETE FROM {table_name}
                    WHERE datetime({time_column}) < datetime(?)
                """, (cutoff,))
                
                rows_deleted = cursor.rowcount
                conn.commit()
                
                duration_ms = (time.time() - start) * 1000
                
                if rows_deleted > 0:
                    print(f"  🗑️ {table_name}: deleted {rows_deleted} rows older than {retention}")
                
                results.append(CleanupResult(
                    table_name=table_name,
                    rows_deleted=rows_deleted,
                    duration_ms=duration_ms
                ))
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                print(f"  ❌ {table_name}: error - {e}")
                results.append(CleanupResult(
                    table_name=table_name,
                    rows_deleted=0,
                    duration_ms=duration_ms,
                    error=str(e)
                ))
        
        # Cleanup AI data
        ai_cleanup_results = self._cleanup_sqlite_ai_data(cursor, conn)
        results.extend(ai_cleanup_results)
        
        conn.close()
        return results
    
    def _cleanup_sqlite_ai_data(self, cursor, conn) -> List[CleanupResult]:
        """
        Clean up AI-related data (briefings, alerts, postmortems, chat history).
        """
        results = []
        
        # AI Reports (briefings, alerts, postmortems)
        briefing_retention = self.retention_policies.get("ai_briefings", timedelta(days=90))
        
        # Cleanup all AI reports using briefings retention
        start = time.time()
        briefing_cutoff = (datetime.now() - briefing_retention).isoformat()
        try:
            cursor.execute("""
                DELETE FROM ai_reports
                WHERE datetime(created_at) < datetime(?)
            """, (briefing_cutoff,))
            rows_deleted = cursor.rowcount
            conn.commit()
            duration_ms = (time.time() - start) * 1000
            if rows_deleted > 0:
                print(f"  🗑️ ai_reports: deleted {rows_deleted} rows older than {briefing_retention}")
            results.append(CleanupResult(
                table_name="ai_reports",
                rows_deleted=rows_deleted,
                duration_ms=duration_ms
            ))
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            print(f"  ❌ ai_reports: error - {e}")
            results.append(CleanupResult(
                table_name="ai_reports",
                rows_deleted=0,
                duration_ms=duration_ms,
                error=str(e)
            ))
        
        # Cleanup chat history (conversations and messages)
        chat_retention = self.retention_policies.get("ai_chat", timedelta(days=30))
        start = time.time()
        chat_cutoff = (datetime.now() - chat_retention).isoformat()
        try:
            # Delete old conversations (CASCADE will delete their messages)
            cursor.execute("""
                DELETE FROM ai_conversations
                WHERE datetime(updated_at) < datetime(?)
            """, (chat_cutoff,))
            rows_deleted = cursor.rowcount
            conn.commit()
            duration_ms = (time.time() - start) * 1000
            if rows_deleted > 0:
                print(f"  🗑️ ai_conversations: deleted {rows_deleted} conversations older than {chat_retention}")
            results.append(CleanupResult(
                table_name="ai_conversations",
                rows_deleted=rows_deleted,
                duration_ms=duration_ms
            ))
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            print(f"  ❌ ai_conversations: error - {e}")
            results.append(CleanupResult(
                table_name="ai_conversations",
                rows_deleted=0,
                duration_ms=duration_ms,
                error=str(e)
            ))
        
        return results
    
    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics for monitoring"""
        if self.use_postgres:
            return await self._get_postgres_storage_stats()
        else:
            return self._get_sqlite_storage_stats()
    
    async def _get_postgres_storage_stats(self) -> Dict[str, Any]:
        """Get PostgreSQL/TimescaleDB storage statistics"""
        try:
            async_db = self.db_manager._async_db if hasattr(self.db_manager, '_async_db') else self.db_manager
            
            async with async_db.connection() as conn:
                # Get hypertable sizes
                rows = await conn.fetch("""
                    SELECT 
                        hypertable_name,
                        hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass) as total_bytes,
                        num_chunks
                    FROM timescaledb_information.hypertables
                """)
                
                hypertables = {}
                for row in rows:
                    hypertables[row['hypertable_name']] = {
                        "size_bytes": row['total_bytes'],
                        "size_mb": round(row['total_bytes'] / 1024 / 1024, 2) if row['total_bytes'] else 0,
                        "num_chunks": row['num_chunks']
                    }
                
                # Get continuous aggregate sizes
                cagg_rows = await conn.fetch("""
                    SELECT 
                        view_name,
                        pg_total_relation_size(format('%I.%I', view_schema, view_name)::regclass) as total_bytes
                    FROM timescaledb_information.continuous_aggregates
                """)
                
                aggregates = {}
                for row in cagg_rows:
                    aggregates[row['view_name']] = {
                        "size_bytes": row['total_bytes'],
                        "size_mb": round(row['total_bytes'] / 1024 / 1024, 2) if row['total_bytes'] else 0
                    }
                
                # Get row counts
                counts = {}
                for table in ['metrics', 'raw_logs', 'agents']:
                    row = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {table}")
                    counts[table] = row['count'] if row else 0
                
                return {
                    "hypertables": hypertables,
                    "continuous_aggregates": aggregates,
                    "row_counts": counts,
                    "database": "postgresql"
                }
        except Exception as e:
            return {"error": str(e), "database": "postgresql"}
    
    def _get_sqlite_storage_stats(self) -> Dict[str, Any]:
        """Get SQLite storage statistics"""
        import sqlite3
        import os
        
        SQLITE_DB_PATH = "./loglibrarian.db"
        
        try:
            # Get file size
            file_size = os.path.getsize(SQLITE_DB_PATH) if os.path.exists(SQLITE_DB_PATH) else 0
            
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            
            # Get row counts
            counts = {}
            for table in ['metrics', 'raw_logs', 'agents', 'log_occurrences']:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = cursor.fetchone()[0]
                except:
                    counts[table] = 0
            
            conn.close()
            
            return {
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size / 1024 / 1024, 2),
                "row_counts": counts,
                "database": "sqlite"
            }
        except Exception as e:
            return {"error": str(e), "database": "sqlite"}


# Global instance
_retention_manager: Optional[RetentionManager] = None


def get_retention_manager() -> Optional[RetentionManager]:
    """Get the global retention manager instance"""
    return _retention_manager


def init_retention_manager(db_manager, use_postgres: bool = False) -> RetentionManager:
    """Initialize the global retention manager"""
    global _retention_manager
    _retention_manager = RetentionManager(db_manager, use_postgres)
    return _retention_manager
