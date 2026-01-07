"""
PostgreSQL Connection Pool Manager

Provides thread-safe connection pooling for psycopg2.
This module ensures efficient database connections for high-concurrency
scenarios (1000+ scribe agents).

Features:
- ThreadedConnectionPool for concurrent access
- Automatic connection validation
- Context manager for safe connection handling
- Connection health checks
"""

import os
import threading
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool
import psycopg2.extras


# Configuration from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/loglibrarian")
POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN", "5"))
POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX", "50"))


class ConnectionPool:
    """
    Thread-safe PostgreSQL connection pool.
    
    Usage:
        pool = ConnectionPool()
        
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                
        # Or for dict cursors:
        with pool.dict_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM agents")
                rows = cur.fetchall()  # Returns list of dicts
    """
    
    _instance: Optional['ConnectionPool'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern - only one pool per process"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._initialized = True
        self._connect_lock = threading.Lock()
        
    def initialize(self):
        """Initialize the connection pool"""
        if self._pool is not None:
            return
            
        with self._connect_lock:
            if self._pool is not None:
                return
                
            print(f"🔌 Initializing PostgreSQL connection pool (min={POOL_MIN_SIZE}, max={POOL_MAX_SIZE})")
            
            # Parse DATABASE_URL for logging (hide password)
            try:
                if '@' in DATABASE_URL:
                    visible_url = DATABASE_URL.split('@')[1]
                else:
                    visible_url = DATABASE_URL
                print(f"   Connecting to: {visible_url}")
            except:
                pass
            
            self._pool = pool.ThreadedConnectionPool(
                minconn=POOL_MIN_SIZE,
                maxconn=POOL_MAX_SIZE,
                dsn=DATABASE_URL
            )
            
            # Verify connection works
            conn = self._pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                print("✅ PostgreSQL connection pool initialized")
            finally:
                self._pool.putconn(conn)
    
    def close(self):
        """Close all connections in the pool"""
        if self._pool:
            self._pool.closeall()
            self._pool = None
            print("🔌 PostgreSQL connection pool closed")
    
    @contextmanager
    def connection(self):
        """
        Get a connection from the pool (context manager).
        
        Usage:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
        """
        if self._pool is None:
            self.initialize()
            
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)
    
    @contextmanager
    def dict_connection(self):
        """
        Get a connection with RealDictCursor factory (returns dicts).
        
        Usage:
            with pool.dict_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM agents")
                    rows = cur.fetchall()  # List of dicts
        """
        if self._pool is None:
            self.initialize()
            
        conn = self._pool.getconn()
        # Set cursor factory for this connection
        original_factory = conn.cursor_factory
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.cursor_factory = original_factory
            self._pool.putconn(conn)
    
    @contextmanager
    def cursor(self):
        """
        Get a cursor directly (commits on success, rollback on error).
        
        Usage:
            with pool.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                yield cur
    
    @contextmanager
    def dict_cursor(self):
        """
        Get a dict cursor directly (returns dicts).
        
        Usage:
            with pool.dict_cursor() as cur:
                cur.execute("SELECT * FROM agents")
                rows = cur.fetchall()
        """
        with self.dict_connection() as conn:
            with conn.cursor() as cur:
                yield cur
    
    def execute(self, query: str, params: tuple = None) -> int:
        """
        Execute a query and return affected row count.
        
        Usage:
            count = pool.execute("UPDATE agents SET status = %s WHERE agent_id = %s", ('online', 'agent1'))
        """
        with self.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount
    
    def fetchone(self, query: str, params: tuple = None) -> Optional[dict]:
        """
        Execute a query and return single row as dict.
        
        Usage:
            agent = pool.fetchone("SELECT * FROM agents WHERE agent_id = %s", ('agent1',))
        """
        with self.dict_cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()
    
    def fetchall(self, query: str, params: tuple = None) -> list:
        """
        Execute a query and return all rows as list of dicts.
        
        Usage:
            agents = pool.fetchall("SELECT * FROM agents WHERE status = %s", ('online',))
        """
        with self.dict_cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()
    
    def fetchval(self, query: str, params: tuple = None):
        """
        Execute a query and return single value.
        
        Usage:
            count = pool.fetchval("SELECT COUNT(*) FROM agents")
        """
        with self.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return row[0] if row else None
    
    @property
    def is_initialized(self) -> bool:
        """Check if pool is initialized"""
        return self._pool is not None
    
    def get_pool_stats(self) -> dict:
        """Get pool statistics"""
        if self._pool is None:
            return {"initialized": False}
        
        return {
            "initialized": True,
            "min_connections": POOL_MIN_SIZE,
            "max_connections": POOL_MAX_SIZE,
            # Note: ThreadedConnectionPool doesn't expose current usage
        }
    
    def get_stats(self) -> dict:
        """Get comprehensive pool statistics including connection tracking"""
        if self._pool is None:
            return {
                "initialized": False,
                "status": "not_initialized"
            }
        
        stats = {
            "initialized": True,
            "status": "healthy",
            "min_connections": POOL_MIN_SIZE,
            "max_connections": POOL_MAX_SIZE,
            "pool_type": "ThreadedConnectionPool"
        }
        
        # Try to get actual connection count from internal pool state
        try:
            # ThreadedConnectionPool uses _pool (available) and _used
            available = len(getattr(self._pool, '_pool', []))
            used = len(getattr(self._pool, '_used', {}))
            
            stats["available"] = available
            stats["in_use"] = used
            stats["total_active"] = available + used
            stats["utilization_percent"] = round((used / POOL_MAX_SIZE) * 100, 1) if POOL_MAX_SIZE > 0 else 0
            
            # Warn if pool is getting full
            if stats["utilization_percent"] > 80:
                stats["status"] = "warning_high_utilization"
            if available == 0 and used >= POOL_MAX_SIZE:
                stats["status"] = "critical_exhausted"
        except Exception:
            # Can't access internal state, just report basic info
            pass
        
        return stats


# Global pool instance
_pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    """Get the global connection pool instance"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool()
    return _pool


def init_pool():
    """Initialize the global connection pool"""
    pool = get_pool()
    pool.initialize()
    return pool


def close_pool():
    """Close the global connection pool"""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
