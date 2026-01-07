"""
Metrics Buffer Module

Provides efficient batched insertion of metrics data with support for both
SQLite and PostgreSQL backends. Accumulates metrics and flushes them in batches
for improved database performance.

Features:
- Configurable flush interval (default 1 second)
- Configurable max buffer size (default 500 rows)
- Background flush task
- Graceful shutdown with data preservation
- Performance metrics tracking
- Backpressure warnings
"""

import asyncio
import time
import os
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field
import threading


# Configuration
FLUSH_INTERVAL_SECONDS = float(os.getenv("METRICS_FLUSH_INTERVAL", "1.0"))
MAX_BUFFER_SIZE = int(os.getenv("METRICS_MAX_BUFFER_SIZE", "500"))
BACKPRESSURE_WARNING_SIZE = int(os.getenv("METRICS_BACKPRESSURE_SIZE", "1000"))
SMALL_DEPLOYMENT_THRESHOLD = int(os.getenv("SMALL_DEPLOYMENT_AGENTS", "10"))


@dataclass
class BufferStats:
    """Statistics for metrics buffer performance monitoring"""
    total_inserts: int = 0
    total_flushes: int = 0
    total_rows_flushed: int = 0
    last_flush_time: float = 0.0
    last_flush_latency_ms: float = 0.0
    avg_flush_latency_ms: float = 0.0
    max_buffer_size_seen: int = 0
    backpressure_warnings: int = 0
    flush_errors: int = 0
    
    # Rolling averages
    _latency_samples: List[float] = field(default_factory=list)
    _max_samples: int = 100
    
    def record_flush(self, rows: int, latency_ms: float):
        """Record a flush operation"""
        self.total_flushes += 1
        self.total_rows_flushed += rows
        self.last_flush_time = time.time()
        self.last_flush_latency_ms = latency_ms
        
        # Update rolling average
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > self._max_samples:
            self._latency_samples.pop(0)
        self.avg_flush_latency_ms = sum(self._latency_samples) / len(self._latency_samples)
    
    def record_insert(self, count: int = 1):
        """Record metrics added to buffer"""
        self.total_inserts += count
    
    def record_buffer_size(self, size: int):
        """Record current buffer size"""
        if size > self.max_buffer_size_seen:
            self.max_buffer_size_seen = size
    
    def to_dict(self) -> dict:
        """Export stats as dictionary"""
        return {
            "total_inserts": self.total_inserts,
            "total_flushes": self.total_flushes,
            "total_rows_flushed": self.total_rows_flushed,
            "inserts_per_second": self._calculate_inserts_per_sec(),
            "last_flush_latency_ms": round(self.last_flush_latency_ms, 2),
            "avg_flush_latency_ms": round(self.avg_flush_latency_ms, 2),
            "max_buffer_size_seen": self.max_buffer_size_seen,
            "backpressure_warnings": self.backpressure_warnings,
            "flush_errors": self.flush_errors
        }
    
    def _calculate_inserts_per_sec(self) -> float:
        """Calculate approximate inserts per second"""
        if self.total_flushes == 0:
            return 0.0
        # Rough estimate based on total rows and flushes
        elapsed = time.time() - (self.last_flush_time - (self.total_flushes * FLUSH_INTERVAL_SECONDS))
        if elapsed > 0:
            return round(self.total_rows_flushed / max(elapsed, 1), 2)
        return 0.0


class MetricsBuffer:
    """
    Buffered metrics insertion manager.
    
    Accumulates metrics from multiple agents and flushes them in batches
    for improved database performance.
    
    Thread-safe for concurrent metric additions.
    """
    
    def __init__(
        self,
        db_insert_func: Callable,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
        max_buffer_size: int = MAX_BUFFER_SIZE,
        use_postgres: bool = False
    ):
        """
        Initialize the metrics buffer.
        
        Args:
            db_insert_func: Function to call for database insertion
            flush_interval: Seconds between automatic flushes
            max_buffer_size: Max rows before forcing a flush
            use_postgres: Whether using PostgreSQL backend
        """
        self.db_insert_func = db_insert_func
        self.flush_interval = flush_interval
        self.max_buffer_size = max_buffer_size
        self.use_postgres = use_postgres
        
        # Buffer storage: {agent_id: [metrics_list]}
        self._buffer: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._buffer_lock = asyncio.Lock()
        
        # Load average cache per agent (updated with each batch)
        self._load_avg_cache: Dict[str, float] = {}
        
        # Statistics
        self.stats = BufferStats()
        
        # Control flags
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        
        # Track active agent count for small deployment detection
        self._active_agents: set = set()
    
    @property
    def buffer_size(self) -> int:
        """Get current total buffer size across all agents"""
        return sum(len(metrics) for metrics in self._buffer.values())
    
    @property
    def is_small_deployment(self) -> bool:
        """Check if this is a small deployment (should use immediate inserts)"""
        return len(self._active_agents) < SMALL_DEPLOYMENT_THRESHOLD and not self.use_postgres
    
    async def start(self):
        """Start the background flush task"""
        if self._running:
            return
        
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        print(f"📊 Metrics buffer started (flush interval: {self.flush_interval}s, max buffer: {self.max_buffer_size})")
    
    async def stop(self):
        """Stop the buffer and flush remaining data"""
        print("📊 Metrics buffer stopping...")
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush to ensure no data loss
        await self.flush(force=True)
        print(f"📊 Metrics buffer stopped. Final stats: {self.stats.to_dict()}")
    
    async def add_metrics(
        self,
        agent_id: str,
        metrics: List[Dict[str, Any]],
        load_avg: float = 0.0
    ) -> int:
        """
        Add metrics to the buffer.
        
        Args:
            agent_id: Agent identifier
            metrics: List of metric dictionaries
            load_avg: 15-minute load average for this agent
        
        Returns:
            Number of metrics added (or inserted if small deployment)
        """
        if not metrics:
            return 0
        
        # Track active agents
        self._active_agents.add(agent_id)
        
        # For small SQLite deployments, insert immediately for simplicity
        if self.is_small_deployment:
            return self._immediate_insert(agent_id, metrics, load_avg)
        
        async with self._buffer_lock:
            # Add to buffer
            self._buffer[agent_id].extend(metrics)
            self._load_avg_cache[agent_id] = load_avg
            
            # Update stats
            self.stats.record_insert(len(metrics))
            current_size = self.buffer_size
            self.stats.record_buffer_size(current_size)
            
            # Check for backpressure
            if current_size > BACKPRESSURE_WARNING_SIZE:
                self.stats.backpressure_warnings += 1
                print(f"⚠️ Metrics buffer backpressure warning! Size: {current_size} rows")
        
        # Check if we need to flush due to size
        if self.buffer_size >= self.max_buffer_size:
            await self.flush()
        
        return len(metrics)
    
    def _immediate_insert(self, agent_id: str, metrics: List[Dict], load_avg: float) -> int:
        """Immediate insert for small deployments (SQLite)"""
        try:
            result = self.db_insert_func(agent_id, metrics, load_avg)
            self.stats.record_insert(len(metrics))
            self.stats.record_flush(len(metrics), 0)
            return result if isinstance(result, int) else len(metrics)
        except Exception as e:
            print(f"❌ Immediate insert error for {agent_id}: {e}")
            self.stats.flush_errors += 1
            return 0
    
    async def flush(self, force: bool = False):
        """
        Flush buffered metrics to the database.
        
        Args:
            force: If True, flush even if buffer is small
        """
        async with self._buffer_lock:
            if not self._buffer and not force:
                return
            
            # Snapshot and clear buffer atomically
            buffer_snapshot = dict(self._buffer)
            load_avg_snapshot = dict(self._load_avg_cache)
            self._buffer.clear()
            self._load_avg_cache.clear()
        
        if not buffer_snapshot:
            return
        
        total_rows = sum(len(m) for m in buffer_snapshot.values())
        start_time = time.time()
        
        try:
            if self.use_postgres:
                await self._flush_postgres(buffer_snapshot, load_avg_snapshot)
            else:
                self._flush_sqlite(buffer_snapshot, load_avg_snapshot)
            
            latency_ms = (time.time() - start_time) * 1000
            self.stats.record_flush(total_rows, latency_ms)
            
            if total_rows > 100:
                print(f"📊 Flushed {total_rows} metrics in {latency_ms:.1f}ms")
                
        except Exception as e:
            print(f"❌ Flush error: {e}")
            self.stats.flush_errors += 1
            
            # Re-add failed data to buffer for retry
            async with self._buffer_lock:
                for agent_id, metrics in buffer_snapshot.items():
                    self._buffer[agent_id].extend(metrics)
                self._load_avg_cache.update(load_avg_snapshot)
    
    def _flush_sqlite(self, buffer: Dict[str, List], load_avgs: Dict[str, float]):
        """Flush to SQLite using individual bulk inserts per agent"""
        for agent_id, metrics in buffer.items():
            if not metrics:
                continue
            try:
                load_avg = load_avgs.get(agent_id, 0.0)
                self.db_insert_func(agent_id, metrics, load_avg)
            except Exception as e:
                print(f"❌ SQLite flush error for {agent_id}: {e}")
                raise
    
    async def _flush_postgres(self, buffer: Dict[str, List], load_avgs: Dict[str, float]):
        """
        Flush to PostgreSQL using efficient batch operations.
        
        Uses asyncpg's copy_records_to_table for maximum performance.
        """
        for agent_id, metrics in buffer.items():
            if not metrics:
                continue
            try:
                load_avg = load_avgs.get(agent_id, 0.0)
                # db_insert_func handles the async operation
                result = self.db_insert_func(agent_id, metrics, load_avg)
                # If it's a coroutine, await it
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"❌ PostgreSQL flush error for {agent_id}: {e}")
                raise
    
    async def _flush_loop(self):
        """Background task that periodically flushes the buffer"""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                if self.buffer_size > 0:
                    await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Flush loop error: {e}")
                self.stats.flush_errors += 1
    
    def get_stats(self) -> dict:
        """Get buffer statistics"""
        stats = self.stats.to_dict()
        stats["current_buffer_size"] = self.buffer_size
        stats["active_agents"] = len(self._active_agents)
        stats["is_small_deployment"] = self.is_small_deployment
        stats["use_postgres"] = self.use_postgres
        return stats


# Global buffer instance (initialized in main.py)
_metrics_buffer: Optional[MetricsBuffer] = None


def get_metrics_buffer() -> Optional[MetricsBuffer]:
    """Get the global metrics buffer instance"""
    return _metrics_buffer


def init_metrics_buffer(
    db_insert_func: Callable,
    use_postgres: bool = False
) -> MetricsBuffer:
    """Initialize the global metrics buffer"""
    global _metrics_buffer
    _metrics_buffer = MetricsBuffer(
        db_insert_func=db_insert_func,
        use_postgres=use_postgres
    )
    return _metrics_buffer
