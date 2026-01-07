"""
Redis Queue Manager Module

Provides Redis-based message queue for buffering agent metrics between
WebSocket ingestion and database storage. Enables handling burst reconnections
and decouples ingestion from storage.

Features:
- Optional Redis dependency (graceful fallback to direct writes)
- Publish metrics to Redis stream
- Background consumer workers for batch database writes
- Queue depth and consumer lag metrics
- Health check support
- Automatic reconnection handling

Configuration:
- REDIS_URL: Redis connection URL (optional)
- REDIS_QUEUE_ENABLED: Enable/disable Redis queue (default: auto)
- REDIS_STREAM_NAME: Name of the Redis stream (default: metrics_stream)
- REDIS_CONSUMER_GROUP: Consumer group name (default: librarian_consumers)
- REDIS_CONSUMER_BATCH_SIZE: Batch size for consuming (default: 100)
- REDIS_MAX_STREAM_LENGTH: Max stream length before trimming (default: 100000)
"""

import asyncio
import json
import os
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
import traceback

# Configuration from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_QUEUE_ENABLED = os.getenv("REDIS_QUEUE_ENABLED", "auto").lower()
REDIS_STREAM_NAME = os.getenv("REDIS_STREAM_NAME", "metrics_stream")
REDIS_CONSUMER_GROUP = os.getenv("REDIS_CONSUMER_GROUP", "librarian_consumers")
REDIS_CONSUMER_NAME = os.getenv("REDIS_CONSUMER_NAME", f"consumer_{os.getpid()}")
REDIS_CONSUMER_BATCH_SIZE = int(os.getenv("REDIS_CONSUMER_BATCH_SIZE", "100"))
REDIS_MAX_STREAM_LENGTH = int(os.getenv("REDIS_MAX_STREAM_LENGTH", "100000"))
REDIS_CONSUMER_TIMEOUT_MS = int(os.getenv("REDIS_CONSUMER_TIMEOUT_MS", "1000"))


@dataclass
class RedisQueueStats:
    """Statistics for Redis queue monitoring"""
    messages_published: int = 0
    messages_consumed: int = 0
    batches_processed: int = 0
    publish_errors: int = 0
    consume_errors: int = 0
    last_publish_time: float = 0.0
    last_consume_time: float = 0.0
    current_queue_depth: int = 0
    consumer_lag_ms: float = 0.0
    fallback_direct_writes: int = 0
    reconnection_attempts: int = 0
    
    # Rolling latency tracking
    _publish_latencies: List[float] = field(default_factory=list)
    _consume_latencies: List[float] = field(default_factory=list)
    _max_samples: int = 100
    
    def record_publish(self, latency_ms: float):
        """Record a publish operation"""
        self.messages_published += 1
        self.last_publish_time = time.time()
        self._publish_latencies.append(latency_ms)
        if len(self._publish_latencies) > self._max_samples:
            self._publish_latencies.pop(0)
    
    def record_consume(self, count: int, latency_ms: float):
        """Record a consume operation"""
        self.messages_consumed += count
        self.batches_processed += 1
        self.last_consume_time = time.time()
        self._consume_latencies.append(latency_ms)
        if len(self._consume_latencies) > self._max_samples:
            self._consume_latencies.pop(0)
    
    def avg_publish_latency_ms(self) -> float:
        if not self._publish_latencies:
            return 0.0
        return sum(self._publish_latencies) / len(self._publish_latencies)
    
    def avg_consume_latency_ms(self) -> float:
        if not self._consume_latencies:
            return 0.0
        return sum(self._consume_latencies) / len(self._consume_latencies)
    
    def to_dict(self) -> dict:
        """Export stats as dictionary"""
        return {
            "messages_published": self.messages_published,
            "messages_consumed": self.messages_consumed,
            "batches_processed": self.batches_processed,
            "publish_errors": self.publish_errors,
            "consume_errors": self.consume_errors,
            "current_queue_depth": self.current_queue_depth,
            "consumer_lag_ms": round(self.consumer_lag_ms, 2),
            "avg_publish_latency_ms": round(self.avg_publish_latency_ms(), 2),
            "avg_consume_latency_ms": round(self.avg_consume_latency_ms(), 2),
            "fallback_direct_writes": self.fallback_direct_writes,
            "reconnection_attempts": self.reconnection_attempts,
            "throughput": {
                "messages_per_second": self._calc_throughput()
            }
        }
    
    def _calc_throughput(self) -> float:
        """Calculate approximate messages per second"""
        if self.last_publish_time == 0:
            return 0.0
        elapsed = time.time() - (self.last_publish_time - 60)  # Approximate over last minute
        if elapsed > 0:
            return round(self.messages_published / max(elapsed, 1), 2)
        return 0.0


class RedisQueueManager:
    """
    Redis-based message queue for metrics buffering.
    
    Provides optional Redis queueing between WebSocket ingestion and database storage.
    Falls back to direct database writes if Redis is unavailable.
    """
    
    def __init__(
        self,
        redis_url: str = REDIS_URL,
        stream_name: str = REDIS_STREAM_NAME,
        consumer_group: str = REDIS_CONSUMER_GROUP,
        consumer_name: str = REDIS_CONSUMER_NAME,
        batch_size: int = REDIS_CONSUMER_BATCH_SIZE,
        max_stream_length: int = REDIS_MAX_STREAM_LENGTH,
        metrics_buffer_callback: Callable = None,
        fallback_callback: Callable = None
    ):
        """
        Initialize the Redis queue manager.
        
        Args:
            redis_url: Redis connection URL
            stream_name: Name of the Redis stream
            consumer_group: Consumer group name for coordinated consumption
            consumer_name: Unique consumer name within the group
            batch_size: Number of messages to consume per batch
            max_stream_length: Max stream length before auto-trimming
            metrics_buffer_callback: Async callback for batch database writes
            fallback_callback: Callback for direct writes when Redis unavailable
        """
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.batch_size = batch_size
        self.max_stream_length = max_stream_length
        self.metrics_buffer_callback = metrics_buffer_callback
        self.fallback_callback = fallback_callback
        
        # Redis connection
        self._redis: Optional[Any] = None
        self._connected = False
        self._enabled = False
        
        # Control flags
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = RedisQueueStats()
        
        # Lock for connection management
        self._connection_lock = asyncio.Lock()
    
    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected"""
        return self._connected and self._redis is not None
    
    @property
    def is_enabled(self) -> bool:
        """Check if Redis queue is enabled"""
        return self._enabled
    
    async def initialize(self) -> bool:
        """
        Initialize Redis connection and consumer group.
        
        Returns:
            True if Redis is available and configured, False otherwise
        """
        # Check if Redis should be enabled
        if REDIS_QUEUE_ENABLED == "false":
            print("📭 Redis queue disabled by configuration")
            self._enabled = False
            return False
        
        try:
            # Try to import redis
            import redis.asyncio as aioredis
            
            # Connect to Redis
            self._redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0
            )
            
            # Test connection
            await self._redis.ping()
            
            # Create consumer group if it doesn't exist
            try:
                await self._redis.xgroup_create(
                    self.stream_name,
                    self.consumer_group,
                    id="0",
                    mkstream=True
                )
                print(f"✓ Created Redis consumer group: {self.consumer_group}")
            except Exception as e:
                # Group may already exist, which is fine
                if "BUSYGROUP" not in str(e):
                    raise
            
            self._connected = True
            self._enabled = True
            print(f"✓ Redis queue connected: {self.redis_url}")
            print(f"  Stream: {self.stream_name}, Group: {self.consumer_group}")
            return True
            
        except ImportError:
            print("📭 Redis library not installed (pip install redis)")
            self._enabled = False
            return False
        except Exception as e:
            print(f"⚠️ Redis unavailable, falling back to direct writes: {e}")
            self._connected = False
            self._enabled = REDIS_QUEUE_ENABLED == "true"  # Only disable if explicitly required
            if REDIS_QUEUE_ENABLED == "true":
                print("❌ Redis required but unavailable!")
                raise
            return False
    
    async def start(self):
        """Start the consumer worker task"""
        if not self._enabled or not self._connected:
            return
        
        self._running = True
        self._consumer_task = asyncio.create_task(self._consumer_worker())
        print(f"✓ Redis consumer worker started: {self.consumer_name}")
    
    async def stop(self):
        """Stop the consumer worker and close Redis connection"""
        self._running = False
        
        # Wait for consumer task to finish
        if self._consumer_task:
            try:
                self._consumer_task.cancel()
                await asyncio.wait_for(self._consumer_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        
        # Close Redis connection
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
        
        self._connected = False
        print("✓ Redis queue manager stopped")
    
    async def publish_metrics(
        self,
        agent_id: str,
        metrics: List[Dict[str, Any]],
        load_avg: float = 0.0,
        hostname: str = None,
        status: str = None,
        public_ip: str = None,
        processes: List[Dict] = None
    ) -> bool:
        """
        Publish metrics to Redis stream.
        
        Args:
            agent_id: Agent identifier
            metrics: List of metric dictionaries
            load_avg: Load average value
            hostname: Agent hostname
            status: Agent status
            public_ip: Agent public IP
            processes: Process snapshot data
        
        Returns:
            True if published to Redis, False if fallback used
        """
        start_time = time.time()
        
        # If Redis not available, use fallback
        if not self.is_connected:
            return await self._fallback_write(agent_id, metrics, load_avg)
        
        try:
            # Prepare message payload
            message = {
                "agent_id": agent_id,
                "timestamp": datetime.now().isoformat(),
                "metrics": json.dumps(metrics),
                "load_avg": str(load_avg),
            }
            
            # Add optional fields
            if hostname:
                message["hostname"] = hostname
            if status:
                message["status"] = status
            if public_ip:
                message["public_ip"] = public_ip
            if processes:
                message["processes"] = json.dumps(processes)
            
            # Add to stream with auto-trimming
            await self._redis.xadd(
                self.stream_name,
                message,
                maxlen=self.max_stream_length,
                approximate=True
            )
            
            # Record stats
            latency_ms = (time.time() - start_time) * 1000
            self.stats.record_publish(latency_ms)
            
            return True
            
        except Exception as e:
            self.stats.publish_errors += 1
            print(f"⚠️ Redis publish error: {e}")
            
            # Check if connection lost
            await self._check_connection()
            
            # Fallback to direct write
            return await self._fallback_write(agent_id, metrics, load_avg)
    
    async def _fallback_write(
        self,
        agent_id: str,
        metrics: List[Dict[str, Any]],
        load_avg: float
    ) -> bool:
        """Fallback to direct database write when Redis unavailable"""
        self.stats.fallback_direct_writes += 1
        
        if self.fallback_callback:
            try:
                await self.fallback_callback(
                    agent_id=agent_id,
                    metrics=metrics,
                    load_avg=load_avg
                )
                return True
            except Exception as e:
                print(f"❌ Fallback write error: {e}")
                return False
        
        return False
    
    async def _consumer_worker(self):
        """Background worker that consumes from Redis and writes to database"""
        print(f"🔄 Consumer worker started: {self.consumer_name}")
        
        while self._running:
            try:
                if not self.is_connected:
                    await self._reconnect()
                    await asyncio.sleep(1)
                    continue
                
                # Read messages from stream
                messages = await self._redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_name: ">"},
                    count=self.batch_size,
                    block=REDIS_CONSUMER_TIMEOUT_MS
                )
                
                if not messages:
                    continue
                
                start_time = time.time()
                processed_ids = []
                
                # Process each message
                for stream_name, stream_messages in messages:
                    for message_id, data in stream_messages:
                        try:
                            await self._process_message(data)
                            processed_ids.append(message_id)
                        except Exception as e:
                            print(f"⚠️ Error processing message {message_id}: {e}")
                            self.stats.consume_errors += 1
                
                # Acknowledge processed messages
                if processed_ids:
                    await self._redis.xack(
                        self.stream_name,
                        self.consumer_group,
                        *processed_ids
                    )
                    
                    # Record stats
                    latency_ms = (time.time() - start_time) * 1000
                    self.stats.record_consume(len(processed_ids), latency_ms)
                
                # Update queue depth
                await self._update_queue_depth()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ Consumer worker error: {e}")
                self.stats.consume_errors += 1
                await asyncio.sleep(1)
        
        print(f"🛑 Consumer worker stopped: {self.consumer_name}")
    
    async def _process_message(self, data: Dict[str, str]):
        """Process a single message from the stream"""
        agent_id = data.get("agent_id")
        if not agent_id:
            return
        
        # Parse metrics
        metrics_json = data.get("metrics", "[]")
        metrics = json.loads(metrics_json)
        load_avg = float(data.get("load_avg", 0.0))
        
        # Call the metrics buffer callback
        if self.metrics_buffer_callback:
            await self.metrics_buffer_callback(
                agent_id=agent_id,
                metrics=metrics,
                load_avg=load_avg
            )
    
    async def _check_connection(self):
        """Check if Redis connection is still alive"""
        async with self._connection_lock:
            try:
                if self._redis:
                    await self._redis.ping()
            except Exception:
                self._connected = False
    
    async def _reconnect(self):
        """Attempt to reconnect to Redis"""
        async with self._connection_lock:
            if self._connected:
                return
            
            self.stats.reconnection_attempts += 1
            
            try:
                import redis.asyncio as aioredis
                
                if self._redis:
                    try:
                        await self._redis.close()
                    except Exception:
                        pass
                
                self._redis = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_timeout=5.0,
                    socket_connect_timeout=5.0
                )
                
                await self._redis.ping()
                self._connected = True
                print(f"✓ Redis reconnected after {self.stats.reconnection_attempts} attempts")
                
            except Exception as e:
                print(f"⚠️ Redis reconnection failed: {e}")
    
    async def _update_queue_depth(self):
        """Update current queue depth from Redis stream info"""
        try:
            # Get stream info
            info = await self._redis.xinfo_stream(self.stream_name)
            self.stats.current_queue_depth = info.get("length", 0)
            
            # Get pending messages for consumer lag
            pending = await self._redis.xpending(
                self.stream_name,
                self.consumer_group
            )
            if pending and len(pending) >= 4:
                pending_count = pending[0] if pending[0] else 0
                # Estimate lag based on pending count and batch rate
                if self.stats.batches_processed > 0:
                    avg_batch_time = self.stats.avg_consume_latency_ms()
                    self.stats.consumer_lag_ms = pending_count * avg_batch_time / self.batch_size
                    
        except Exception:
            pass
    
    async def get_health(self) -> Dict[str, Any]:
        """
        Get Redis queue health status.
        
        Returns:
            Health status dictionary
        """
        health = {
            "enabled": self._enabled,
            "connected": self._connected,
            "url": self.redis_url if self._enabled else None,
            "stream": self.stream_name if self._enabled else None,
        }
        
        if self._connected:
            try:
                # Ping Redis
                latency_start = time.time()
                await self._redis.ping()
                latency_ms = (time.time() - latency_start) * 1000
                
                # Get stream info
                try:
                    info = await self._redis.xinfo_stream(self.stream_name)
                    health["stream_length"] = info.get("length", 0)
                    health["first_entry"] = info.get("first-entry", [None])[0] if info.get("first-entry") else None
                    health["last_entry"] = info.get("last-entry", [None])[0] if info.get("last-entry") else None
                except Exception:
                    health["stream_length"] = 0
                
                health["ping_latency_ms"] = round(latency_ms, 2)
                health["status"] = "healthy"
                
            except Exception as e:
                health["status"] = "unhealthy"
                health["error"] = str(e)
        else:
            health["status"] = "disconnected" if self._enabled else "disabled"
        
        return health
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return self.stats.to_dict()


# Global Redis queue manager instance
_redis_queue: Optional[RedisQueueManager] = None


def init_redis_queue(
    metrics_buffer_callback: Callable = None,
    fallback_callback: Callable = None
) -> RedisQueueManager:
    """
    Initialize the global Redis queue manager.
    
    Args:
        metrics_buffer_callback: Callback for batch database writes
        fallback_callback: Callback for direct writes when Redis unavailable
    
    Returns:
        RedisQueueManager instance
    """
    global _redis_queue
    _redis_queue = RedisQueueManager(
        metrics_buffer_callback=metrics_buffer_callback,
        fallback_callback=fallback_callback
    )
    return _redis_queue


def get_redis_queue() -> Optional[RedisQueueManager]:
    """Get the global Redis queue manager instance"""
    return _redis_queue
