"""
Bookmark Monitor Engine
=======================
Background service that performs periodic health checks on bookmarks.
Supports HTTP, ICMP (ping), and TCP port checks.
"""

import asyncio
import aiohttp
import socket
import subprocess
import platform
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class CheckResult:
    """Result of a health check"""
    status: int  # 1 = Up, 0 = Down
    latency_ms: int
    message: str


class BookmarkMonitor:
    """
    Background monitoring engine for bookmarks.
    Spawns async tasks for each active bookmark based on their intervals.
    """
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.running = False
        self.tasks: Dict[str, asyncio.Task] = {}
        self.check_tasks: Dict[str, asyncio.Task] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
    
    async def start(self):
        """Start the monitoring engine"""
        if self.running:
            return
        
        self.running = True
        print("📡 Bookmark Monitor starting...")
        
        # Start the bookmark refresh loop (checks for new/updated bookmarks)
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        
        # Start the daily cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # Initial load of bookmarks
        await self._sync_monitors()
        
        print("📡 Bookmark Monitor started")
    
    async def stop(self):
        """Stop the monitoring engine"""
        if not self.running:
            return
        
        self.running = False
        print("📡 Bookmark Monitor stopping...")
        
        # Cancel all check tasks
        for task in self.check_tasks.values():
            task.cancel()
        
        # Cancel refresh and cleanup tasks
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        
        # Wait for all tasks to complete
        all_tasks = list(self.check_tasks.values())
        if self._refresh_task:
            all_tasks.append(self._refresh_task)
        if self._cleanup_task:
            all_tasks.append(self._cleanup_task)
        
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        
        # Close shared HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
        
        self.check_tasks.clear()
        print("📡 Bookmark Monitor stopped")
    
    async def sync_bookmarks(self):
        """Public method to trigger a sync of bookmarks"""
        await self._sync_monitors()
    
    async def perform_check(self, bookmark: dict) -> CheckResult:
        """Public method to perform a single check (for manual triggers)"""
        return await self._perform_check(bookmark)
    
    async def _refresh_loop(self):
        """Periodically refresh the list of monitors"""
        while self.running:
            try:
                await asyncio.sleep(30)  # Check for changes every 30 seconds
                await self._sync_monitors()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"📡 Error in refresh loop: {e}")
    
    async def _cleanup_loop(self):
        """Daily cleanup of old check records"""
        while self.running:
            try:
                # Run cleanup once per day
                await asyncio.sleep(86400)  # 24 hours
                self.db.cleanup_old_bookmark_checks(days=30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"📡 Error in cleanup loop: {e}")
    
    async def _sync_monitors(self):
        """Sync running monitors with database"""
        try:
            bookmarks = self.db.get_all_bookmarks(active_only=True)
            active_ids = set(b["id"] for b in bookmarks)
            running_ids = set(self.check_tasks.keys())
            
            # Start monitors for new bookmarks
            for bookmark in bookmarks:
                if bookmark["id"] not in running_ids:
                    self._start_monitor(bookmark)
            
            # Stop monitors for removed/deactivated bookmarks
            for bookmark_id in running_ids - active_ids:
                self._stop_monitor(bookmark_id)
            
            # Update intervals for existing monitors if changed
            bookmark_map = {b["id"]: b for b in bookmarks}
            for bookmark_id in running_ids & active_ids:
                # Could implement interval update logic here if needed
                pass
                
        except Exception as e:
            print(f"📡 Error syncing monitors: {e}")
    
    def _start_monitor(self, bookmark: dict):
        """Start a monitoring task for a bookmark"""
        bookmark_id = bookmark["id"]
        if bookmark_id in self.check_tasks:
            return
        
        print(f"📡 Starting monitor: {bookmark['name']} ({bookmark['type']})")
        task = asyncio.create_task(self._monitor_loop(bookmark))
        self.check_tasks[bookmark_id] = task
    
    def _stop_monitor(self, bookmark_id: str):
        """Stop a monitoring task"""
        if bookmark_id in self.check_tasks:
            print(f"📡 Stopping monitor: {bookmark_id}")
            self.check_tasks[bookmark_id].cancel()
            del self.check_tasks[bookmark_id]
    
    async def _monitor_loop(self, bookmark: dict):
        """Main monitoring loop for a single bookmark"""
        bookmark_id = bookmark["id"]
        tenant_id = bookmark.get("tenant_id", "default")
        interval = bookmark.get("interval_seconds", 60)
        
        # Track previous status to detect changes (None = unknown start state)
        last_status = None
        
        while self.running:
            try:
                # Perform the check
                result = await self._perform_check(bookmark)
                
                # Check for status change
                if last_status is not None and result.status != last_status:
                    # Status changed!
                    if result.status == 0:
                        # Down
                        await self.db.notification_manager.send_notification(
                            event_type="bookmark_down",
                            title=f"Bookmark Down: {bookmark['name']}",
                            body=f"Bookmark '{bookmark['name']}' ({bookmark['target']}) is DOWN.\nError: {result.message}",
                            tenant_id=tenant_id
                        )
                    else:
                        # Up
                        await self.db.notification_manager.send_notification(
                            event_type="bookmark_up",
                            title=f"Bookmark Recovered: {bookmark['name']}",
                            body=f"Bookmark '{bookmark['name']}' is back ONLINE.\nLatency: {result.latency_ms}ms",
                            tenant_id=tenant_id
                        )
                
                last_status = result.status
                
                # Record the result
                self.db.record_bookmark_check(
                    bookmark_id=bookmark_id,
                    status=result.status,
                    latency_ms=result.latency_ms,
                    message=result.message
                )
                
                # Wait for next check
                await asyncio.sleep(interval)
                
                # Refresh bookmark config in case it changed
                updated = self.db.get_bookmark(tenant_id, bookmark_id)
                if updated:
                    bookmark = updated
                    interval = bookmark.get("interval_seconds", 60)
                    if not bookmark.get("active"):
                        break  # Stop if deactivated
                else:
                    break  # Stop if bookmark was deleted
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"📡 Error monitoring {bookmark.get('name', bookmark_id)}: {e}")
                await asyncio.sleep(interval)
    
    async def _perform_check(self, bookmark: dict) -> CheckResult:
        """Perform a health check based on bookmark type"""
        check_type = bookmark["type"]
        target = bookmark["target"]
        timeout = bookmark.get("timeout_seconds", 10)
        
        try:
            if check_type == "http":
                return await self._check_http(target, timeout)
            elif check_type == "icmp":
                return await self._check_icmp(target, timeout)
            elif check_type == "tcp-port":
                port = bookmark.get("port", 80)
                return await self._check_tcp(target, port, timeout)
            else:
                return CheckResult(0, 0, f"Unknown check type: {check_type}")
        except Exception as e:
            return CheckResult(0, 0, str(e))
    
    async def _check_http(self, url: str, timeout: int) -> CheckResult:
        """Perform HTTP health check"""
        # Ensure URL has scheme
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        
        start = time.monotonic()
        
        try:
            # Use shared session for connection pooling (much faster)
            if self._http_session is None or self._http_session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=10,
                    ttl_dns_cache=300,
                    ssl=False
                )
                self._http_session = aiohttp.ClientSession(connector=connector)
            
            async with self._http_session.get(
                url, 
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=False  # Don't verify SSL for monitoring
            ) as response:
                latency = int((time.monotonic() - start) * 1000)
                
                if 200 <= response.status < 300:
                    return CheckResult(1, latency, f"HTTP {response.status}")
                else:
                    return CheckResult(0, latency, f"HTTP {response.status}")
                        
        except asyncio.TimeoutError:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, "Timeout")
        except aiohttp.ClientError as e:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, str(e)[:100])
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, str(e)[:100])
    
    async def _check_icmp(self, host: str, timeout: int) -> CheckResult:
        """Perform ICMP ping check"""
        start = time.monotonic()
        
        # Strip URL scheme if present (user might enter http://host for ICMP)
        if host.startswith(("http://", "https://")):
            parsed = urlparse(host)
            host = parsed.hostname or parsed.path
        
        try:
            # Use system ping command (cross-platform)
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), host]
            else:
                cmd = ["ping", "-c", "1", "-W", str(timeout), host]
            
            # Run ping in executor to not block
            loop = asyncio.get_event_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 2
                )
            )
            
            latency = int((time.monotonic() - start) * 1000)
            
            if process.returncode == 0:
                # Try to extract latency from ping output
                output = process.stdout
                if "time=" in output:
                    try:
                        # Extract time=XXms or time=XX.X ms
                        time_part = output.split("time=")[1].split()[0]
                        ping_ms = float(time_part.replace("ms", "").replace(",", "."))
                        latency = int(ping_ms)
                    except:
                        pass
                return CheckResult(1, latency, "Ping OK")
            else:
                return CheckResult(0, latency, "Ping failed")
                
        except subprocess.TimeoutExpired:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, "Timeout")
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, str(e)[:100])
    
    async def _check_tcp(self, host: str, port: int, timeout: int) -> CheckResult:
        """Perform TCP port check"""
        start = time.monotonic()
        
        try:
            # Try to connect to the TCP port
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            
            latency = int((time.monotonic() - start) * 1000)
            writer.close()
            await writer.wait_closed()
            
            return CheckResult(1, latency, f"Port {port} open")
            
        except asyncio.TimeoutError:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, f"Port {port} timeout")
        except ConnectionRefusedError:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, f"Port {port} refused")
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            return CheckResult(0, latency, str(e)[:100])
    
    async def run_check_now(self, bookmark_id: str) -> Optional[CheckResult]:
        """Manually trigger a check for a bookmark (for testing)"""
        bookmark = self.db.get_bookmark(bookmark_id)
        if not bookmark:
            return None
        
        result = await self._perform_check(bookmark)
        
        # Record the result
        self.db.record_bookmark_check(
            bookmark_id=bookmark_id,
            status=result.status,
            latency_ms=result.latency_ms,
            message=result.message
        )
        
        return result


# Global monitor instance (will be initialized in main.py)
bookmark_monitor: Optional[BookmarkMonitor] = None


def get_monitor() -> Optional[BookmarkMonitor]:
    """Get the global bookmark monitor instance"""
    return bookmark_monitor


def init_monitor(db_manager) -> BookmarkMonitor:
    """Initialize the global bookmark monitor"""
    global bookmark_monitor
    bookmark_monitor = BookmarkMonitor(db_manager)
    return bookmark_monitor
