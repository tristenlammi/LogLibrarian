from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends, Header, Response, Body
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import uvicorn
import json
import asyncio
import gzip
import os
import re
import secrets

from models import LogBatch, HeartbeatPayload, ReportProfileCreate, ReportProfileUpdate
from metrics_buffer import MetricsBuffer, init_metrics_buffer, get_metrics_buffer
from retention_manager import (
    RetentionManager, init_retention_manager, get_retention_manager,
    get_disk_space_info, check_disk_space_ok, MIN_FREE_SPACE_GB, MIN_FREE_SPACE_PERCENT
)
from redis_queue import RedisQueueManager, init_redis_queue, get_redis_queue
from connection_manager import (
    OptimizedConnectionManager, 
    init_connection_manager, 
    get_connection_manager,
    AsyncHandlerTimer,
    SLOW_HANDLER_THRESHOLD_MS
)
from ai_service import get_ai_service, reload_ai_service
from ai_reports import (
    get_report_scheduler, init_report_scheduler,
    DailyBriefingGenerator
)
from archivist import get_archivist, Archivist
from bookmark_monitor import (
    BookmarkMonitor, init_monitor, get_monitor
)

# Import AI chat router
from routers.ai_chat import router as ai_chat_router

# Database backend selection
# Set USE_POSTGRES=true and DATABASE_URL to switch to PostgreSQL/TimescaleDB
USE_POSTGRES = os.getenv("USE_POSTGRES", "false").lower() == "true"

if USE_POSTGRES:
    print("🐘 PostgreSQL mode enabled")
    from db_postgres import PostgresDatabaseManager, get_postgres_db
    # Create synchronous database manager instance
    db_manager = get_postgres_db()
else:
    print("📁 SQLite mode enabled")
    from db import db_manager

# Instance API key for scribe authentication (loaded from database after setup)
# All scribes must provide this key to connect
_instance_api_key: Optional[str] = None

def get_instance_api_key() -> Optional[str]:
    """Get the instance API key from cache or database"""
    global _instance_api_key
    if _instance_api_key is None:
        # Try to get from database
        if hasattr(db_manager, 'get_instance_api_key'):
            _instance_api_key = db_manager.get_instance_api_key()
        else:
            # Fallback: get from setup_config via get_setup_config
            config = db_manager.get_setup_config()
            _instance_api_key = config.get('instance_api_key')
    return _instance_api_key

def clear_instance_api_key_cache():
    """Clear the cached API key (call after regeneration)"""
    global _instance_api_key
    _instance_api_key = None

def validate_scribe_api_key(provided_key: Optional[str]) -> tuple[bool, str]:
    """Validate a scribe's API key against the instance key"""
    if not provided_key:
        return False, "no_api_key"
    
    instance_key = get_instance_api_key()
    if not instance_key:
        # No instance key set yet (setup not complete) - reject all
        return False, "instance_not_configured"
    
    if secrets.compare_digest(provided_key, instance_key):
        return True, "valid"
    
    return False, "invalid_api_key"

# Global metrics buffer (initialized on startup)
metrics_buffer: Optional[MetricsBuffer] = None

# Global retention manager (initialized on startup)
retention_manager: Optional[RetentionManager] = None

# Global Redis queue manager (initialized on startup, optional)
redis_queue: Optional[RedisQueueManager] = None

# Global optimized connection manager (initialized on startup)
connection_manager: Optional[OptimizedConnectionManager] = None

# Global AI report scheduler (initialized on startup)
report_scheduler = None

# Global bookmark monitor (initialized on startup)
bookmark_monitor: Optional[BookmarkMonitor] = None


app = FastAPI(
    title="LogLibrarian - The Librarian",
    description="Central log ingestion and AI-powered troubleshooting service",
    version="1.0.0"
)

# Include AI chat router
app.include_router(ai_chat_router)

# CORS middleware for frontend communication
# ALLOWED_ORIGINS can be a comma-separated list: "http://localhost:3000,https://example.com"
# Default to allowing all origins for development
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
if allowed_origins == ["*"]:
    # Allow all origins (development mode)
    # Note: Cannot use allow_credentials=True with allow_origins=["*"] per CORS spec
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Restricted origins (production mode) - credentials allowed with explicit origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in allowed_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Panic Switch: Check disk space before allowing data ingestion
# Protected endpoints that write data to disk
INGESTION_ENDPOINTS = {"/ingest", "/heartbeat", "/agents/", "/logs/reap"}
_panic_switch_triggered_at: Optional[str] = None  # Track when panic was first triggered


@app.middleware("http")
async def panic_switch_middleware(request: Request, call_next):
    """
    Panic Switch Middleware
    
    Rejects data ingestion requests when disk space is critically low.
    This prevents the system from completely filling the disk and crashing.
    
    Returns 507 Insufficient Storage when:
    - Free disk space < MIN_FREE_SPACE_GB (default: 1GB)
    - Free disk space < MIN_FREE_SPACE_PERCENT (default: 5%)
    """
    global _panic_switch_triggered_at
    
    # Check if this is an ingestion endpoint
    path = request.url.path
    is_ingestion = any(path.startswith(ep) or path == ep for ep in INGESTION_ENDPOINTS)
    
    if is_ingestion and request.method in ("POST", "PUT"):
        # Check disk space
        disk_ok, message = check_disk_space_ok(".")
        
        if not disk_ok:
            # Log critical alert (only once per incident)
            if _panic_switch_triggered_at is None:
                _panic_switch_triggered_at = datetime.now().isoformat()
                print(f"🚨 PANIC SWITCH ACTIVATED: {message}")
                print(f"🚨 Rejecting all data ingestion until disk space is freed!")
            
            # Return 507 Insufficient Storage
            return Response(
                content=json.dumps({
                    "error": "Insufficient Storage",
                    "detail": message,
                    "panic_switch": True,
                    "triggered_at": _panic_switch_triggered_at,
                    "min_free_space_gb": MIN_FREE_SPACE_GB,
                    "min_free_space_percent": MIN_FREE_SPACE_PERCENT
                }),
                status_code=507,
                media_type="application/json"
            )
        else:
            # Reset panic state if space is OK
            if _panic_switch_triggered_at is not None:
                print(f"✅ PANIC SWITCH DEACTIVATED: Disk space recovered. {message}")
                _panic_switch_triggered_at = None
    
    # Process request normally
    return await call_next(request)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


# ==================== AUTH MODELS ====================

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateAccountRequest(BaseModel):
    username: str
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;\'\/]', v):
            raise ValueError('Password must contain at least one special character')
        return v

class AddUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    role: str = None  # 'admin' or 'user'
    assigned_profile_id: str = None
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;\'\/]', v):
            raise ValueError('Password must contain at least one special character')
        return v
    
    @validator('role')
    def validate_role(cls, v):
        if v is not None and v not in ('admin', 'user'):
            raise ValueError('Role must be "admin" or "user"')
        return v

class UpdateUserRequest(BaseModel):
    role: str = None  # 'admin' or 'user'
    assigned_profile_id: str = None
    
    @validator('role')
    def validate_role(cls, v):
        if v is not None and v not in ('admin', 'user'):
            raise ValueError('Role must be "admin" or "user"')
        return v

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;\'\/]', v):
            raise ValueError('Password must contain at least one special character')
        return v

# Database-backed session management (sessions persist across restarts)
_session_expiry_days = 30

def create_session(user: dict) -> str:
    """Create a new session token for a user (stored in database)"""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(days=_session_expiry_days)
    
    # Store session in database
    db_manager.create_session(token, user, expires_at)
    return token

def get_session(token: str) -> Optional[dict]:
    """Get session data by token from database, returns None if expired or not found"""
    if not token:
        return None
    return db_manager.get_session(token)

def delete_session(token: str):
    """Delete a session from database"""
    if token:
        db_manager.delete_session(token)

def cleanup_expired_sessions():
    """Remove expired sessions from database"""
    deleted = db_manager.cleanup_expired_sessions()
    if deleted > 0:
        print(f"Cleaned up {deleted} expired sessions")

async def get_current_user(request: Request) -> Optional[dict]:
    """Dependency to get current user from session token"""
    # Check Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        session = get_session(token)
        if session:
            return session
    # Check cookie as fallback
    token = request.cookies.get("session_token")
    if token:
        return get_session(token)
    return None

async def require_auth(request: Request) -> dict:
    """Dependency that requires authentication"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def require_admin(request: Request) -> dict:
    """Dependency that requires admin authentication"""
    user = await require_auth(request)
    # Check both is_admin and role for compatibility
    if not (user.get("is_admin") or user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# Global flag to control background tasks
watchdog_running = False


async def heartbeat_watchdog():
    """
    Background task to monitor agent status and track uptime.
    
    Runs every 60 seconds to:
    1. Mark stale agents (no heartbeat > 2 min) as offline
    2. Increment uptime_seconds for all online agents
    3. Record heartbeats for historical uptime tracking
    """
    global watchdog_running, connection_manager
    print("🐕 Heartbeat watchdog started (2 minute timeout, 60s uptime accumulator)")
    
    uptime_log_counter = 0
    
    while watchdog_running:
        try:
            # Step A: Mark stale agents as offline
            # Uses efficient bulk update instead of individual checks
            offline_agents = db_manager.mark_stale_agents_offline(offline_threshold_seconds=120)
            if offline_agents:
                print(f"🐕 Marked {len(offline_agents)} agent(s) as offline: {offline_agents}")
            
            # Step B: Increment uptime for all online agents
            # This is the "accumulator" method - very efficient
            updated_count = db_manager.increment_online_agents_uptime(increment_seconds=60)
            
            # Step C: Record heartbeats for all online agents (for historical uptime)
            try:
                online_agents = [a["agent_id"] for a in db_manager.get_all_agents() if a.get("status") == "online"]
                if online_agents:
                    db_manager.record_bulk_heartbeats(online_agents, 'online')
            except Exception as hb_err:
                print(f"Heartbeat recording error: {hb_err}")
            
            # Log uptime updates every 5 minutes (every 5th iteration)
            uptime_log_counter += 1
            if updated_count > 0 and uptime_log_counter >= 5:
                print(f"📊 Incremented uptime for {updated_count} online agent(s)")
                uptime_log_counter = 0
                    
        except Exception as e:
            print(f"Watchdog error: {e}")
        
        # Wait 60 seconds before next check
        await asyncio.sleep(60)
    
    print("🐕 Heartbeat watchdog stopped")


async def log_reaper_task():
    """
    The Reaper: Daily background task to clean up old logs.
    Runs once every 24 hours at startup-relative time.
    """
    global watchdog_running
    print("🧹 Log Reaper started (runs every 24 hours)")
    
    # Initial delay: wait 5 minutes after startup before first run
    await asyncio.sleep(300)
    
    while watchdog_running:
        try:
            print("🧹 Log Reaper running daily cleanup...")
            result = db_manager.reap_old_logs()
            print(f"🧹 Log Reaper complete: {result['total_deleted']} logs deleted from {result['agents_processed']} agents")
            
            # Also clean up old heartbeats (keep 30 days)
            try:
                heartbeats_deleted = db_manager.cleanup_old_heartbeats(days_to_keep=30)
                if heartbeats_deleted > 0:
                    print(f"🧹 Cleaned up {heartbeats_deleted} old heartbeat records")
            except Exception as hb_err:
                print(f"Heartbeat cleanup error: {hb_err}")
            
            # Clean up expired sessions
            try:
                cleanup_expired_sessions()
            except Exception as sess_err:
                print(f"Session cleanup error: {sess_err}")
                
        except Exception as e:
            print(f"Log Reaper error: {e}")
        
        # Wait 24 hours before next run
        await asyncio.sleep(86400)  # 24 * 60 * 60
    
    print("🧹 Log Reaper stopped")


# ==================== Archivist Scheduler ====================
async def archivist_indexer_task():
    """
    Background task that runs the Archivist indexer every hour.
    Indexes new logs into Qdrant for semantic search.
    """
    print("📚 Archivist indexer task started")
    
    # Wait 30 seconds after startup before first run
    await asyncio.sleep(30)
    
    archivist = get_archivist(db_manager)
    
    while watchdog_running:
        try:
            # Run indexer for logs from the last hour
            stats = archivist.run_indexer(hours_back=1)
            
            if stats.get('error'):
                print(f"⚠️ Archivist indexer error: {stats['error']}")
            else:
                indexed = stats.get('logs_indexed', 0)
                if indexed > 0:
                    print(f"📚 Archivist indexed {indexed} logs into archive")
                    
        except Exception as e:
            print(f"⚠️ Archivist indexer exception: {e}")
        
        # Wait 1 hour before next run
        await asyncio.sleep(3600)


@app.on_event("startup")
async def startup_event():
    """Initialize databases on startup"""
    global watchdog_running, metrics_buffer, retention_manager, redis_queue, connection_manager
    print("Starting LogLibrarian backend...")
    
    # Initialize optimized connection manager
    connection_manager = init_connection_manager()
    print("✓ Connection manager initialized")
    
    # Initialize PostgreSQL if using that backend
    if USE_POSTGRES:
        try:
            db_manager.initialize()  # Now synchronous
            print("✓ PostgreSQL database initialized")
        except Exception as e:
            print(f"❌ PostgreSQL initialization failed: {e}")
            raise
    
    print("Database initialization complete")
    
    # Initialize metrics buffer for batch inserts
    metrics_buffer = init_metrics_buffer(
        db_insert_func=db_manager.bulk_insert_metrics,
        use_postgres=USE_POSTGRES
    )
    await metrics_buffer.start()
    
    # Initialize Redis queue (optional - falls back to direct writes if unavailable)
    redis_queue = init_redis_queue(
        metrics_buffer_callback=metrics_buffer.add_metrics if metrics_buffer else None,
        fallback_callback=metrics_buffer.add_metrics if metrics_buffer else None
    )
    redis_available = await redis_queue.initialize()
    if redis_available:
        await redis_queue.start()
        print("✓ Redis queue enabled for metrics buffering")
    else:
        print("ℹ️ Redis unavailable - using direct database writes")
    
    # Initialize retention manager for automatic cleanup
    retention_manager = init_retention_manager(
        db_manager=db_manager,
        use_postgres=USE_POSTGRES
    )
    await retention_manager.start()
    
    # Start heartbeat watchdog
    watchdog_running = True
    asyncio.create_task(heartbeat_watchdog())
    
    # Start log reaper (daily cleanup - legacy, retention_manager handles this now)
    asyncio.create_task(log_reaper_task())
    
    # Initialize AI service and report scheduler
    global report_scheduler
    try:
        ai_service = get_ai_service(db_manager)
        if ai_service:
            report_scheduler = await init_report_scheduler(db_manager, ai_service)
            print("✓ AI Report Scheduler initialized")
        else:
            print("ℹ️ AI service not initialized - scheduler skipped")
    except Exception as e:
        print(f"⚠️ AI scheduler initialization failed: {e}")
    
    # Initialize Archivist for long-term AI memory
    try:
        archivist = get_archivist(db_manager)
        if archivist._ensure_initialized():
            # Start the hourly indexer task
            asyncio.create_task(archivist_indexer_task())
            print("✓ Archivist initialized - long-term memory enabled")
        else:
            print("ℹ️ Archivist not available")
    except Exception as e:
        print(f"⚠️ Archivist initialization failed: {e}")
    
    # Initialize Bookmark Monitor for uptime checking
    global bookmark_monitor
    try:
        bookmark_monitor = init_monitor(db_manager)
        await bookmark_monitor.start()
        print("✓ Bookmark Monitor started")
    except Exception as e:
        print(f"⚠️ Bookmark Monitor initialization failed: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global watchdog_running, metrics_buffer, retention_manager, redis_queue, report_scheduler, bookmark_monitor
    watchdog_running = False
    
    # Stop Bookmark Monitor
    if bookmark_monitor:
        try:
            await bookmark_monitor.stop()
            print("✓ Bookmark Monitor stopped")
        except Exception as e:
            print(f"Error stopping Bookmark Monitor: {e}")
    
    # Stop AI report scheduler
    if report_scheduler:
        try:
            await report_scheduler.stop()
            print("✓ AI Report Scheduler stopped")
        except Exception as e:
            print(f"Error stopping AI scheduler: {e}")
    
    # Stop Redis queue first (so remaining messages go through fallback)
    if redis_queue:
        try:
            await redis_queue.stop()
            print("✓ Redis queue stopped")
        except Exception as e:
            print(f"Error stopping Redis queue: {e}")
    
    # Stop retention manager
    if retention_manager:
        try:
            await retention_manager.stop()
            print("✓ Retention manager stopped")
        except Exception as e:
            print(f"Error stopping retention manager: {e}")
    
    # Stop metrics buffer (flushes remaining data)
    if metrics_buffer:
        try:
            await metrics_buffer.stop()
            print("✓ Metrics buffer stopped and flushed")
        except Exception as e:
            print(f"Error stopping metrics buffer: {e}")
    
    # Close PostgreSQL connection pool if using that backend
    if USE_POSTGRES:
        try:
            db_manager.close()  # Now synchronous
            print("✓ PostgreSQL connection pool closed")
        except Exception as e:
            print(f"Error closing PostgreSQL pool: {e}")
    
    print("LogLibrarian backend shutting down...")


@app.get("/api/health")
async def health_check():
    """Health check endpoint with component status"""
    health_status = {
        "status": "ok",
        "database": "postgresql" if USE_POSTGRES else "sqlite",
        "components": {
            "database": "ok",
            "metrics_buffer": "ok" if metrics_buffer else "not_initialized",
            "retention_manager": "ok" if retention_manager else "not_initialized",
        }
    }
    
    # Add Redis status
    if redis_queue:
        try:
            redis_health = await redis_queue.get_health()
            health_status["components"]["redis"] = redis_health.get("status", "unknown")
            health_status["redis"] = redis_health
        except Exception as e:
            health_status["components"]["redis"] = "error"
            health_status["redis"] = {"status": "error", "error": str(e)}
    else:
        health_status["components"]["redis"] = "disabled"
        health_status["redis"] = {"status": "disabled", "enabled": False}
    
    # Overall status degraded if any component unhealthy
    if any(v in ["error", "unhealthy"] for v in health_status["components"].values()):
        health_status["status"] = "degraded"
    
    return health_status


# ==================== AUTH ENDPOINTS ====================

@app.get("/api/auth/status")
async def auth_status(request: Request):
    """Check authentication status and if setup is required"""
    user = await get_current_user(request)
    setup_required = db_manager.is_setup_required()
    
    return {
        "authenticated": user is not None,
        "setup_required": setup_required,
        "user": {
            "username": user["username"],
            "is_admin": user["is_admin"],
            "role": user.get("role", "admin" if user["is_admin"] else "user"),
            "assigned_profile_id": user.get("assigned_profile_id")
        } if user else None
    }

@app.post("/api/auth/login")
async def login(request: LoginRequest, response: Response):
    """Login with username and password"""
    # Check if setup is required (no users exist)
    if db_manager.is_setup_required():
        # No default credentials - user must complete setup wizard first
        raise HTTPException(
            status_code=403, 
            detail="Setup required. Please complete the setup wizard to create your admin account."
        )
    
    # Normal authentication
    user = db_manager.authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Create session
    token = create_session(user)
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=_session_expiry_days * 86400,
        samesite="lax"
    )
    
    return {
        "success": True,
        "token": token,
        "user": {
            "username": user["username"],
            "is_admin": user["is_admin"],
            "role": user.get("role", "admin" if user["is_admin"] else "user"),
            "assigned_profile_id": user.get("assigned_profile_id")
        }
    }

@app.post("/api/auth/setup")
async def setup_account(request: CreateAccountRequest, response: Response):
    """Create the first admin account (only works when no users exist)"""
    if not db_manager.is_setup_required():
        raise HTTPException(status_code=400, detail="Setup already completed")
    
    # Create admin user with admin role
    user_id = db_manager.create_user(request.username, request.password, is_admin=True, role='admin')
    if not user_id:
        raise HTTPException(status_code=400, detail="Failed to create account. Username may already exist.")
    
    # Get user and create session
    user = db_manager.get_user_by_id(user_id)
    token = create_session({
        "id": user_id,
        "username": request.username,
        "is_admin": True,
        "role": "admin",
        "assigned_profile_id": None
    })
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=_session_expiry_days * 86400,
        samesite="lax"
    )
    
    print(f"✅ Initial admin account created: {request.username}")
    
    return {
        "success": True,
        "token": token,
        "user": {
            "username": request.username,
            "is_admin": True,
            "role": "admin",
            "assigned_profile_id": None
        }
    }

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    """Logout and invalidate session"""
    # Get token from header or cookie
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("session_token")
    
    if token:
        delete_session(token)
    
    response.delete_cookie("session_token")
    return {"success": True}


# ==================== SETUP WIZARD ENDPOINTS ====================

class SetupWizardRequest(BaseModel):
    admin_username: str
    admin_password: str
    instance_name: str = "LogLibrarian"
    deployment_profile: str = "homelab"  # homelab, small_business, production
    default_retention_days: int = 30
    timezone: str = "UTC"
    instance_api_key: str  # Required API key for all scribes to connect
    server_address: str = ""  # External IP/hostname for scribe connections

@app.get("/api/setup/status")
async def get_setup_status():
    """
    Check if initial setup is required.
    Returns setup status.
    """
    setup_complete = db_manager.is_setup_complete()
    
    # If setup_complete check fails, fall back to user count
    if not setup_complete:
        setup_complete = not db_manager.is_setup_required()
    
    return {
        "setup_complete": setup_complete,
        "setup_required": not setup_complete
    }

@app.post("/api/setup/complete")
async def complete_setup_wizard(setup: SetupWizardRequest, response: Response):
    """
    Complete the initial setup wizard.
    Creates admin account and configures the instance.
    """
    # Check if setup already complete
    if db_manager.is_setup_complete() or not db_manager.is_setup_required():
        raise HTTPException(status_code=400, detail="Setup already completed")
    
    # Validate password strength
    if len(setup.admin_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    if len(setup.admin_username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    
    # Validate API key format
    if not setup.instance_api_key or len(setup.instance_api_key) < 32:
        raise HTTPException(status_code=400, detail="Instance API key must be at least 32 characters")
    
    # Complete the setup
    result = db_manager.complete_setup(
        admin_username=setup.admin_username,
        admin_password=setup.admin_password,
        instance_name=setup.instance_name,
        deployment_profile=setup.deployment_profile,
        default_retention_days=setup.default_retention_days,
        timezone=setup.timezone,
        instance_api_key=setup.instance_api_key,
        server_address=setup.server_address
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Setup failed"))
    
    # Create session for the new admin
    user = db_manager.authenticate_user(setup.admin_username, setup.admin_password)
    if user:
        token = create_session(user)
        
        # Set cookie
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            max_age=_session_expiry_days * 86400,
            samesite="lax"
        )
        
        result["token"] = token
        result["user"] = {
            "username": user["username"],
            "is_admin": user["is_admin"],
            "role": user.get("role", "admin")
        }
    
    print(f"✅ Setup wizard completed: instance='{setup.instance_name}', admin='{setup.admin_username}', profile='{setup.deployment_profile}'")
    
    return result

@app.get("/api/setup/config")
async def get_setup_config():
    """Get the current setup configuration (instance name, etc)"""
    config = db_manager.get_setup_config()
    return {
        "instance_name": config.get("instance_name", "LogLibrarian"),
        "deployment_profile": config.get("deployment_profile", "homelab"),
        "default_retention_days": int(config.get("default_retention_days", 30)),
        "timezone": config.get("timezone", "UTC"),
        "database_type": "postgresql" if USE_POSTGRES else "sqlite",
        "setup_timestamp": config.get("setup_timestamp")
    }


# ==================== INSTANCE API KEY MANAGEMENT ====================

@app.get("/api/settings/api-key")
async def get_api_key_info(user: dict = Depends(require_admin)):
    """Get the instance API key (admin only) - used for scribe installation"""
    config = db_manager.get_setup_config()
    api_key = config.get("instance_api_key", "")
    
    return {
        "api_key": api_key,
        "masked_key": f"{api_key[:8]}...{api_key[-4:]}" if api_key and len(api_key) > 12 else api_key,
        "key_length": len(api_key) if api_key else 0
    }

class RegenerateApiKeyRequest(BaseModel):
    new_api_key: str

@app.post("/api/settings/api-key/regenerate")
async def regenerate_api_key(request: RegenerateApiKeyRequest, user: dict = Depends(require_admin)):
    """
    Regenerate the instance API key (admin only).
    
    WARNING: This will disconnect all existing scribes until they are 
    reconfigured with the new API key.
    """
    if not request.new_api_key or len(request.new_api_key) < 32:
        raise HTTPException(status_code=400, detail="New API key must be at least 32 characters")
    
    # Regenerate the key
    if hasattr(db_manager, 'regenerate_instance_api_key'):
        success = db_manager.regenerate_instance_api_key(request.new_api_key)
    else:
        # Fallback for SQLite
        success = db_manager.set_setup_config('instance_api_key', request.new_api_key)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to regenerate API key")
    
    # Clear the cached key so it's reloaded on next use
    clear_instance_api_key_cache()
    
    print(f"🔑 Instance API key regenerated by {user['username']}")
    
    return {
        "success": True,
        "message": "API key regenerated. All scribes must be updated with the new key.",
        "masked_key": f"{request.new_api_key[:8]}...{request.new_api_key[-4:]}"
    }

@app.get("/api/settings/scribe-install-command")
async def get_scribe_install_command(user: dict = Depends(require_admin), request: Request = None):
    """Get the scribe installation command with pre-filled API key"""
    config = db_manager.get_setup_config()
    api_key = config.get("instance_api_key", "")
    server_address = config.get("server_address", "")
    
    # Determine the server URL - prefer configured server_address
    if server_address:
        # Use the configured server address
        if not server_address.startswith("http"):
            server_url = f"http://{server_address}"
        else:
            server_url = server_address
        # Ensure port is included
        if ":" not in server_url.split("//")[-1]:
            server_url = f"{server_url}:8000"
    elif request:
        # Fall back to request host
        scheme = "https" if request.url.scheme == "https" else "http"
        host = request.headers.get("host", "localhost:8000")
        server_url = f"{scheme}://{host}"
    else:
        server_url = "http://YOUR_SERVER:8000"
    
    # Generate install commands for different platforms
    linux_cmd = f'curl -sSL "{server_url}/api/install/scribe" | API_KEY="{api_key}" bash'
    windows_cmd = f'irm "{server_url}/api/install/scribe.ps1" | iex'  # PowerShell will need API key differently
    
    return {
        "server_url": server_url,
        "api_key": api_key,
        "install_commands": {
            "linux": linux_cmd,
            "windows": windows_cmd,
            "manual": {
                "config_field": "api_key",
                "config_value": api_key
            }
        }
    }


# ==================== USER MANAGEMENT ====================

@app.get("/api/auth/users")
async def list_users(user: dict = Depends(require_admin)):
    """List all users (admin only)"""
    users = db_manager.get_all_users()
    return {"users": users}

@app.post("/api/auth/users")
async def add_user(request: AddUserRequest, user: dict = Depends(require_admin)):
    """Add a new user (admin only)"""
    # Check if this is the first non-setup user - if so, make them admin by default
    existing_users = db_manager.get_all_users()
    is_first_real_user = len(existing_users) == 1  # Only the setup admin exists
    
    # Determine role - first real user becomes admin, otherwise use specified or default
    if is_first_real_user and request.role is None and not request.is_admin:
        # First user after setup becomes admin by default
        role = 'admin'
        is_admin = True
        print(f"🔑 First user after setup - automatically granting admin role")
    else:
        # Normal logic - if role specified use it, otherwise derive from is_admin
        role = request.role if request.role else ('admin' if request.is_admin else 'user')
        is_admin = request.is_admin or (role == 'admin')
    
    user_id = db_manager.create_user(
        request.username, 
        request.password, 
        is_admin=is_admin,
        role=role,
        assigned_profile_id=request.assigned_profile_id
    )
    if not user_id:
        raise HTTPException(status_code=400, detail="Failed to create user. Username may already exist.")
    
    print(f"✅ User created: {request.username} (role: {role}, profile: {request.assigned_profile_id})")
    
    return {
        "success": True,
        "user": {
            "id": user_id,
            "username": request.username,
            "is_admin": is_admin,
            "role": role,
            "assigned_profile_id": request.assigned_profile_id
        }
    }

@app.delete("/api/auth/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(require_admin)):
    """Delete a user (admin only, cannot delete yourself)"""
    if user_id == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    # Protect the first admin account (id=1) - it's undeletable
    if user_id == 1:
        raise HTTPException(status_code=400, detail="Cannot delete the primary admin account")
    
    # Check if this is the last admin
    target_user = db_manager.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    target_is_admin = target_user.get("is_admin") or target_user.get("role") == "admin"
    if target_is_admin:
        # Count admins
        all_users = db_manager.get_all_users()
        admin_count = sum(1 for u in all_users if u.get("is_admin") or u.get("role") == "admin")
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin account")
    
    success = db_manager.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete user")
    
    print(f"✅ User deleted: {target_user['username']}")
    
    return {"success": True}

@app.put("/api/auth/users/{user_id}")
async def update_user(user_id: int, request: UpdateUserRequest, current_user: dict = Depends(require_admin)):
    """Update a user's role and assigned profile (admin only)"""
    target_user = db_manager.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # If demoting from admin, check if this is the last admin
    if request.role == 'user' and target_user["role"] == 'admin':
        all_users = db_manager.get_all_users()
        admin_count = sum(1 for u in all_users if u["role"] == 'admin')
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last admin account")
    
    success = db_manager.update_user(
        user_id,
        role=request.role,
        assigned_profile_id=request.assigned_profile_id
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update user")
    
    # Get updated user
    updated_user = db_manager.get_user_by_id(user_id)
    
    print(f"✅ User updated: {target_user['username']} (role: {request.role}, profile: {request.assigned_profile_id})")
    
    return {
        "success": True,
        "user": {
            "id": updated_user["id"],
            "username": updated_user["username"],
            "is_admin": updated_user["is_admin"],
            "role": updated_user["role"],
            "assigned_profile_id": updated_user["assigned_profile_id"]
        }
    }

@app.post("/api/auth/change-password")
async def change_password(request: ChangePasswordRequest, current_user: dict = Depends(require_auth)):
    """Change current user's password"""
    user = db_manager.get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify current password
    if not db_manager.verify_password(request.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    # Update password
    success = db_manager.update_user_password(current_user["user_id"], request.new_password)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update password")
    
    return {"success": True}


@app.get("/api/stats/connections")
async def get_connection_stats():
    """
    Get comprehensive WebSocket connection statistics.
    
    Returns:
    - Summary: total connections, agents, clients, capacity usage
    - Limits: configured connection limits
    - Statistics: message counts, bytes transferred, slow handlers
    - IP distribution: connections per IP address
    - Agents: detailed per-agent connection info
    """
    if connection_manager:
        return {
            "status": "ok",
            **connection_manager.get_connection_stats()
        }
    return {
        "status": "error",
        "message": "Connection manager not initialized"
    }


@app.get("/api/redis/stats")
async def get_redis_stats():
    """Get Redis queue statistics for monitoring"""
    if redis_queue:
        return {
            "status": "ok",
            "enabled": redis_queue.is_enabled,
            "connected": redis_queue.is_connected,
            "stats": redis_queue.get_stats(),
            "health": await redis_queue.get_health()
        }
    return {
        "status": "ok",
        "enabled": False,
        "connected": False,
        "message": "Redis queue not initialized"
    }


@app.get("/api/metrics/buffer-stats")
async def get_buffer_stats():
    """Get metrics buffer statistics for monitoring"""
    if metrics_buffer:
        return {
            "status": "ok",
            "buffer": metrics_buffer.get_stats()
        }
    return {
        "status": "ok",
        "buffer": None,
        "message": "Metrics buffer not initialized"
    }


@app.post("/api/metrics/flush")
async def force_flush_metrics(user: dict = Depends(require_admin)):
    """Force flush the metrics buffer (admin endpoint)"""
    if metrics_buffer:
        buffer_size = metrics_buffer.buffer_size
        await metrics_buffer.flush(force=True)
        return {
            "status": "ok",
            "flushed_rows": buffer_size,
            "message": f"Forced flush of {buffer_size} buffered metrics"
        }
    return {
        "status": "ok",
        "flushed_rows": 0,
        "message": "No metrics buffer to flush"
    }


# ==================== RETENTION MANAGEMENT ====================

@app.get("/api/settings/retention")
async def get_retention_policy():
    """
    Get current data retention policy configuration.
    
    Returns retention periods for:
    - Raw metrics (48 hours)
    - 1-minute aggregates (7 days)
    - 15-minute aggregates (30 days)
    - 1-hour aggregates (365 days)
    """
    if retention_manager:
        return {
            "status": "ok",
            **retention_manager.get_retention_policy()
        }
    return {
        "status": "ok",
        "message": "Retention manager not initialized"
    }


@app.post("/api/retention/cleanup")
async def trigger_retention_cleanup(user: dict = Depends(require_admin)):
    """
    Manually trigger retention cleanup (admin endpoint).
    
    This runs the same cleanup that happens hourly:
    - Deletes data older than retention periods
    - Cleans continuous aggregates
    - Logs cleanup results
    """
    if retention_manager:
        try:
            result = await retention_manager.run_cleanup()
            return {
                "status": "ok",
                **result.to_dict()
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")
    return {
        "status": "error",
        "message": "Retention manager not initialized"
    }


@app.get("/api/storage/stats")
async def get_storage_stats():
    """
    Get storage statistics for monitoring.
    
    Returns:
    - Table sizes (PostgreSQL) or file size (SQLite)
    - Row counts
    - Chunk information (TimescaleDB)
    """
    if retention_manager:
        try:
            stats = await retention_manager.get_storage_stats()
            return {
                "status": "ok",
                **stats
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
    return {
        "status": "error",
        "message": "Retention manager not initialized"
    }


@app.get("/api/janitor/status")
async def get_janitor_status():
    """
    Get Janitor (retention manager) and Panic Switch status.
    
    Returns comprehensive status including:
    - Retention policies and last cleanup run
    - Size limits and current storage usage
    - Disk space information
    - Panic switch state
    """
    disk_info = get_disk_space_info(".")
    disk_ok, disk_message = check_disk_space_ok(".")
    
    response = {
        "janitor": {
            "status": "running" if retention_manager and retention_manager._running else "stopped",
            "last_run": retention_manager._last_run.to_dict() if retention_manager and retention_manager._last_run else None
        },
        "panic_switch": {
            "active": _panic_switch_triggered_at is not None,
            "triggered_at": _panic_switch_triggered_at,
            "disk_ok": disk_ok,
            "message": disk_message,
            "thresholds": {
                "min_free_space_gb": MIN_FREE_SPACE_GB,
                "min_free_space_percent": MIN_FREE_SPACE_PERCENT
            }
        },
        "disk": disk_info,
        "storage_limits": {
            "max_storage_gb": retention_manager.max_storage_gb if retention_manager else None,
            "size_cleanup_batch": retention_manager.size_cleanup_batch if retention_manager else None
        }
    }
    
    # Add storage stats if available
    if retention_manager:
        try:
            stats = await retention_manager.get_storage_stats()
            response["storage"] = stats
        except Exception as e:
            response["storage"] = {"error": str(e)}
    
    return response


@app.post("/api/janitor/run")
async def run_janitor_cleanup(user: dict = Depends(require_admin)):
    """
    Manually trigger a janitor cleanup run.
    
    Useful for testing or when you need immediate cleanup.
    """
    if not retention_manager:
        raise HTTPException(status_code=503, detail="Retention manager not initialized")
    
    try:
        print("🧹 Manual janitor cleanup triggered via API...")
        
        # Run time-based cleanup
        result = await retention_manager.run_cleanup()
        
        # Run size-based cleanup
        size_deleted = await retention_manager.cleanup_by_size()
        
        return {
            "status": "ok",
            "time_based_cleanup": result.to_dict(),
            "size_based_cleanup": {
                "rows_deleted": size_deleted
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


class JanitorSettingsUpdate(BaseModel):
    max_storage_gb: Optional[float] = None
    min_free_space_gb: Optional[float] = None
    retention_raw_logs_days: Optional[int] = None
    retention_metrics_days: Optional[int] = None  # Changed from hours to days
    retention_process_snapshots_days: Optional[int] = None
    # AI data retention
    retention_ai_briefings_days: Optional[int] = None
    retention_ai_chat_days: Optional[int] = None
    # Executive report storage
    max_exec_reports_per_profile: Optional[int] = None


@app.get("/api/janitor/settings")
async def get_janitor_settings():
    """Get janitor/storage configuration settings"""
    try:
        # Read stored value (in hours for backward compatibility) and convert to days
        metrics_hours = int(db_manager.get_system_setting("retention_metrics_hours", "48"))
        metrics_days = max(1, metrics_hours // 24)  # Convert hours to days, minimum 1
        
        settings = {
            "max_storage_gb": float(db_manager.get_system_setting("max_storage_gb", "10")),
            "min_free_space_gb": float(db_manager.get_system_setting("min_free_space_gb", "1")),
            "retention_raw_logs_days": int(db_manager.get_system_setting("retention_raw_logs_days", "7")),
            "retention_metrics_days": metrics_days,  # Return as days
            "retention_process_snapshots_days": int(db_manager.get_system_setting("retention_process_snapshots_days", "7")),
            # AI data retention
            "retention_ai_briefings_days": int(db_manager.get_system_setting("retention_ai_briefings_days", "90")),
            "retention_ai_chat_days": int(db_manager.get_system_setting("retention_ai_chat_days", "30")),
            # Executive report storage
            "max_exec_reports_per_profile": int(db_manager.get_system_setting("max_exec_reports_per_profile", "12")),
        }
        return {"status": "ok", "settings": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@app.put("/api/janitor/settings")
async def update_janitor_settings(settings: JanitorSettingsUpdate, user: dict = Depends(require_admin)):
    """Update janitor/storage configuration settings"""
    try:
        updated = []
        
        if settings.max_storage_gb is not None:
            if settings.max_storage_gb < 0.1:
                raise HTTPException(status_code=400, detail="max_storage_gb must be at least 0.1")
            db_manager.set_system_setting("max_storage_gb", str(settings.max_storage_gb))
            if retention_manager:
                retention_manager.max_storage_gb = settings.max_storage_gb
            updated.append("max_storage_gb")
        
        if settings.min_free_space_gb is not None:
            if settings.min_free_space_gb < 0.1:
                raise HTTPException(status_code=400, detail="min_free_space_gb must be at least 0.1")
            db_manager.set_system_setting("min_free_space_gb", str(settings.min_free_space_gb))
            # Update the global variable used by middleware
            global MIN_FREE_SPACE_GB
            from retention_manager import MIN_FREE_SPACE_GB as _
            import retention_manager as rm
            rm.MIN_FREE_SPACE_GB = settings.min_free_space_gb
            updated.append("min_free_space_gb")
        
        if settings.retention_raw_logs_days is not None:
            if settings.retention_raw_logs_days < 1:
                raise HTTPException(status_code=400, detail="retention_raw_logs_days must be at least 1")
            db_manager.set_system_setting("retention_raw_logs_days", str(settings.retention_raw_logs_days))
            if retention_manager:
                from datetime import timedelta
                retention_manager.retention_policies["raw_logs"] = timedelta(days=settings.retention_raw_logs_days)
            updated.append("retention_raw_logs_days")
        
        if settings.retention_metrics_days is not None:
            if settings.retention_metrics_days < 1:
                raise HTTPException(status_code=400, detail="retention_metrics_days must be at least 1")
            # Store as hours internally for backward compatibility
            metrics_hours = settings.retention_metrics_days * 24
            db_manager.set_system_setting("retention_metrics_hours", str(metrics_hours))
            if retention_manager:
                from datetime import timedelta
                retention_manager.retention_policies["metrics"] = timedelta(days=settings.retention_metrics_days)
            updated.append("retention_metrics_days")
        
        if settings.retention_process_snapshots_days is not None:
            if settings.retention_process_snapshots_days < 1:
                raise HTTPException(status_code=400, detail="retention_process_snapshots_days must be at least 1")
            db_manager.set_system_setting("retention_process_snapshots_days", str(settings.retention_process_snapshots_days))
            if retention_manager:
                from datetime import timedelta
                retention_manager.retention_policies["process_snapshots"] = timedelta(days=settings.retention_process_snapshots_days)
            updated.append("retention_process_snapshots_days")
        
        # AI data retention settings
        if settings.retention_ai_briefings_days is not None:
            if settings.retention_ai_briefings_days < 7:
                raise HTTPException(status_code=400, detail="retention_ai_briefings_days must be at least 7")
            db_manager.set_system_setting("retention_ai_briefings_days", str(settings.retention_ai_briefings_days))
            if retention_manager:
                from datetime import timedelta
                retention_manager.retention_policies["ai_briefings"] = timedelta(days=settings.retention_ai_briefings_days)
            updated.append("retention_ai_briefings_days")
        
        if settings.retention_ai_chat_days is not None:
            if settings.retention_ai_chat_days < 7:
                raise HTTPException(status_code=400, detail="retention_ai_chat_days must be at least 7")
            db_manager.set_system_setting("retention_ai_chat_days", str(settings.retention_ai_chat_days))
            if retention_manager:
                from datetime import timedelta
                retention_manager.retention_policies["ai_chat"] = timedelta(days=settings.retention_ai_chat_days)
            updated.append("retention_ai_chat_days")
        
        if settings.max_exec_reports_per_profile is not None:
            if settings.max_exec_reports_per_profile < 1 or settings.max_exec_reports_per_profile > 365:
                raise HTTPException(status_code=400, detail="max_exec_reports_per_profile must be between 1 and 365")
            db_manager.set_system_setting("max_exec_reports_per_profile", str(settings.max_exec_reports_per_profile))
            updated.append("max_exec_reports_per_profile")
        
        return {"status": "ok", "updated": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


# ==================== SYSTEM SETTINGS ====================

class SystemSettingsUpdate(BaseModel):
    public_app_url: Optional[str] = None


@app.get("/api/settings")
async def get_system_settings():
    """Get all system settings"""
    try:
        settings = db_manager.get_all_system_settings()
        return {"settings": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@app.put("/api/settings")
async def update_system_settings(settings: SystemSettingsUpdate, user: dict = Depends(require_admin)):
    """Update system settings"""
    try:
        if settings.public_app_url is not None:
            # Validate URL format if not empty
            if settings.public_app_url and not settings.public_app_url.startswith(('http://', 'https://')):
                raise HTTPException(status_code=400, detail="public_app_url must start with http:// or https://")
            
            # Remove trailing slash
            url = settings.public_app_url.rstrip('/') if settings.public_app_url else ""
            db_manager.set_system_setting("public_app_url", url)
        
        return {"status": "ok", "message": "Settings updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


@app.get("/api/settings/public-url")
async def get_public_url():
    """Get the public app URL for agent connections"""
    try:
        url = db_manager.get_public_app_url()
        return {"public_app_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AI SETTINGS & MODELS ====================

from model_downloader import get_model_downloader, get_available_models, AVAILABLE_MODELS
from gpu_detector import GPUDetector
from ai_installer import get_installer, InstallStatus

# Initialize model downloader
_model_downloader = None

def get_downloader():
    global _model_downloader
    if _model_downloader is None:
        _model_downloader = get_model_downloader(db_manager)
    return _model_downloader


# WebSocket connections for AI installation progress
_ai_install_connections: Dict[str, WebSocket] = {}


class AISettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    local_model_id: Optional[str] = None
    openai_key: Optional[str] = None
    briefing_time: Optional[str] = None
    report_style: Optional[str] = None
    feature_flags: Optional[dict] = None
    exec_summary_enabled: Optional[bool] = None
    exec_summary_schedule: Optional[str] = None
    exec_summary_day_of_week: Optional[str] = None
    exec_summary_day_of_month: Optional[int] = None
    exec_summary_period_days: Optional[str] = None


@app.get("/api/ai/settings")
async def get_ai_settings():
    """Get AI configuration settings"""
    try:
        settings = db_manager.get_ai_settings()
        # Mask the API key for security
        if settings.get("openai_key"):
            key = settings["openai_key"]
            if len(key) > 8:
                settings["openai_key"] = key[:4] + "..." + key[-4:]
        # Ensure enabled field exists
        if "enabled" not in settings:
            settings["enabled"] = False
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get AI settings: {str(e)}")


@app.get("/api/ai/status")
async def get_ai_status():
    """Get AI system status including runner and model state"""
    try:
        settings = db_manager.get_ai_settings()
        downloader = get_downloader()
        
        # Check runner status
        runner_ready = downloader.is_runner_ready() if hasattr(downloader, 'is_runner_ready') else False
        
        # Get active model status
        active_model = settings.get("local_model_id", "")
        model_loaded = False
        
        if active_model:
            model_status = downloader.get_download_status(active_model) if hasattr(downloader, 'get_download_status') else None
            model_loaded = downloader.is_model_downloaded(active_model) if hasattr(downloader, 'is_model_downloaded') else False
        
        return {
            "status": {
                "enabled": settings.get("enabled", False),
                "provider": settings.get("provider", "local"),
                "runner_ready": runner_ready,
                "running": model_loaded and runner_ready,
                "model_id": active_model,
                "model_loaded": model_loaded,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get AI status: {str(e)}")


@app.get("/api/ai/detect-gpu")
async def detect_gpu():
    """Detect available GPU acceleration options"""
    try:
        result = GPUDetector.detect()
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPU detection failed: {str(e)}")


@app.get("/api/ai/dependencies/status")
async def get_ai_dependencies_status():
    """Check if AI dependencies are installed and working"""
    try:
        installer = get_installer()
        installed = installer.check_installed()
        verified = False
        version = None
        
        if installed:
            success, msg = installer.verify_installation()
            verified = success
            if success and "llama-cpp-python" in msg:
                # Extract version from message
                import re
                match = re.search(r'llama-cpp-python (\S+)', msg)
                if match:
                    version = match.group(1)
        
        # Get backend from settings
        backend = db_manager.get_system_setting('ai_backend') or ''
        
        return {
            "installed": installed,
            "verified": verified,
            "version": version,
            "backend": backend
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check dependencies: {str(e)}")


class AIEnableRequest(BaseModel):
    enable: bool
    backend: Optional[str] = None  # cuda, rocm, sycl, or cpu


@app.post("/api/ai/enable")
async def enable_ai(request: AIEnableRequest, user: dict = Depends(require_admin)):
    """
    Enable or disable AI features.
    
    When enabling:
    - If dependencies not installed, starts installation with selected backend
    - Requires backend selection (cuda, rocm, sycl, cpu) if enabling for first time
    
    When disabling:
    - Unloads any loaded model
    - AI features become unavailable
    """
    try:
        if request.enable:
            # Check if dependencies are installed
            installer = get_installer()
            deps_installed = db_manager.get_system_setting('ai_dependencies_installed') == 'true'
            
            if not deps_installed:
                # Need to install dependencies first
                if not request.backend:
                    # Return available backends for user to choose
                    gpu_result = GPUDetector.detect()
                    return {
                        "status": "needs_backend",
                        "message": "Select a backend to install AI dependencies",
                        "gpu_detection": gpu_result.to_dict(),
                        "recommended": gpu_result.recommended
                    }
                
                # Validate backend
                if request.backend not in ['cuda', 'rocm', 'sycl', 'cpu']:
                    raise HTTPException(status_code=400, detail=f"Invalid backend: {request.backend}")
                
                # Store selected backend
                db_manager.set_system_setting('ai_backend', request.backend)
                
                # Start installation (this is synchronous for now, could be async with WebSocket)
                def progress_callback(progress):
                    # Could broadcast via WebSocket here
                    pass
                
                success, msg = installer.install(request.backend, progress_callback)
                
                if not success:
                    return {
                        "status": "error",
                        "message": f"Failed to install dependencies: {msg}"
                    }
                
                # Mark as installed
                db_manager.set_system_setting('ai_dependencies_installed', 'true')
            
            # Enable AI
            db_manager.set_system_setting('ai_enabled', 'true')
            
            return {
                "status": "ok",
                "message": "AI features enabled",
                "enabled": True
            }
        else:
            # Disable AI
            # First unload any model
            downloader = get_downloader()
            current_model = db_manager.get_system_setting('ai_current_model')
            if current_model:
                db_manager.set_system_setting('ai_model_loaded', 'false')
            
            db_manager.set_system_setting('ai_enabled', 'false')
            
            return {
                "status": "ok", 
                "message": "AI features disabled",
                "enabled": False
            }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update AI state: {str(e)}")


@app.get("/api/ai/librarian/status")
async def get_librarian_status():
    """
    Get Librarian AI feature status.
    Used by frontend to determine whether to show Librarian in navigation.
    """
    try:
        ai_enabled = db_manager.get_system_setting('ai_enabled') == 'true'
        deps_installed = db_manager.get_system_setting('ai_dependencies_installed') == 'true'
        current_model = db_manager.get_system_setting('ai_current_model') or ''
        model_loaded = db_manager.get_system_setting('ai_model_loaded') == 'true'
        backend = db_manager.get_system_setting('ai_backend') or ''
        
        return {
            "enabled": ai_enabled,
            "dependencies_installed": deps_installed,
            "backend": backend,
            "current_model": current_model,
            "model_loaded": model_loaded,
            "ready": ai_enabled and deps_installed and current_model and model_loaded
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get Librarian status: {str(e)}")


@app.put("/api/ai/settings")
async def update_ai_settings(settings: AISettingsUpdate, user: dict = Depends(require_admin)):
    """Update AI configuration settings"""
    try:
        # Validate provider
        if settings.provider and settings.provider not in ["local", "openai"]:
            raise HTTPException(status_code=400, detail="Invalid provider. Must be 'local' or 'openai'")
        
        # Validate model ID
        if settings.local_model_id and settings.local_model_id not in AVAILABLE_MODELS:
            raise HTTPException(status_code=400, detail=f"Invalid model ID: {settings.local_model_id}")
        
        # Get full API key if user is just updating other settings
        current_settings = db_manager.get_ai_settings()
        openai_key = settings.openai_key
        
        # If the key looks masked (contains ...), don't update it
        if openai_key and "..." in openai_key:
            openai_key = current_settings.get("openai_key", "")
        
        success = db_manager.update_ai_settings(
            enabled=settings.enabled,
            provider=settings.provider,
            local_model_id=settings.local_model_id,
            openai_key=openai_key,
            briefing_time=settings.briefing_time,
            report_style=settings.report_style,
            feature_flags=settings.feature_flags,
            exec_summary_enabled=settings.exec_summary_enabled,
            exec_summary_schedule=settings.exec_summary_schedule,
            exec_summary_day_of_week=settings.exec_summary_day_of_week,
            exec_summary_day_of_month=settings.exec_summary_day_of_month,
            exec_summary_period_days=settings.exec_summary_period_days
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save AI settings")
        
        return {"status": "ok", "message": "AI settings updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update AI settings: {str(e)}")


@app.get("/api/ai/models")
async def get_ai_models():
    """Get list of available AI models and their download status"""
    try:
        downloader = get_downloader()
        models = downloader.get_all_models_status()
        
        # Include runner status
        runner_ready = downloader.is_runner_ready() if hasattr(downloader, 'is_runner_ready') else False
        
        # Get settings to determine which model is active
        settings = db_manager.get_ai_settings()
        active_model = settings.get("local_model_id", "")
        
        return {
            "models": models,
            "runner_ready": runner_ready,
            "active_model": active_model,
            "status": "ready" if runner_ready else "not_ready"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get models: {str(e)}")


@app.post("/api/ai/models/{model_id}/download")
async def download_ai_model(model_id: str, user: dict = Depends(require_admin)):
    """Start downloading an AI model"""
    try:
        if model_id not in AVAILABLE_MODELS:
            raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
        
        downloader = get_downloader()
        
        # Check if already downloading
        status = downloader.get_download_status(model_id)
        if status and status.state == "downloading":
            return {"status": "already_downloading", "progress": status.progress}
        
        # Check if already downloaded
        if downloader.is_model_downloaded(model_id):
            return {"status": "already_downloaded"}
        
        # Start download in background
        async def download_task():
            await downloader.download_model(model_id)
        
        asyncio.create_task(download_task())
        
        return {"status": "started", "message": f"Download started for {model_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start download: {str(e)}")


@app.delete("/api/ai/models/{model_id}")
async def delete_ai_model(model_id: str, user: dict = Depends(require_admin)):
    """Delete a downloaded AI model"""
    try:
        if model_id not in AVAILABLE_MODELS:
            raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
        
        downloader = get_downloader()
        success = await downloader.delete_model(model_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete model")
        
        return {"status": "ok", "message": f"Model {model_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")


@app.get("/api/ai/models/{model_id}/status")
async def get_ai_model_status(model_id: str):
    """Get download status for a specific model"""
    try:
        if model_id not in AVAILABLE_MODELS:
            raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
        
        downloader = get_downloader()
        
        # Check download status
        status = downloader.get_download_status(model_id)
        is_downloaded = downloader.is_model_downloaded(model_id)
        
        result = {
            "model_id": model_id,
            "is_downloaded": is_downloaded,
            "download_status": None
        }
        
        if status:
            result["download_status"] = {
                "state": status.state,
                "progress": status.progress,
                "downloaded_mb": status.downloaded_bytes / (1024 * 1024),
                "total_mb": status.total_bytes / (1024 * 1024),
                "speed_mbps": status.speed_mbps,
                "error": status.error
            }
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get model status: {str(e)}")


@app.post("/api/ai/models/{model_id}/activate")
async def activate_ai_model(model_id: str, user: dict = Depends(require_admin)):
    """Activate/load a downloaded model for inference"""
    try:
        if model_id not in AVAILABLE_MODELS:
            raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
        
        downloader = get_downloader()
        
        # Check if model is downloaded
        if not downloader.is_model_downloaded(model_id):
            raise HTTPException(status_code=400, detail=f"Model {model_id} is not downloaded")
        
        # Update settings to use this model
        db_manager.update_ai_settings(local_model_id=model_id)
        
        # Store as system setting too for status display
        db_manager.set_system_setting('ai_current_model', model_id)
        
        # If runner is available, load the model
        if hasattr(downloader, 'load_model'):
            await downloader.load_model(model_id)
        
        return {"status": "ok", "message": f"Model {model_id} activated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to activate model: {str(e)}")


@app.post("/api/ai/models/unload")
async def unload_ai_model(user: dict = Depends(require_admin)):
    """Unload the currently loaded model"""
    try:
        downloader = get_downloader()
        
        # Unload if runner supports it
        if hasattr(downloader, 'unload_model'):
            await downloader.unload_model()
        
        # Clear from settings
        db_manager.update_ai_settings(local_model_id="")
        db_manager.set_system_setting('ai_current_model', '')
        
        return {"status": "ok", "message": "Model unloaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unload model: {str(e)}")


@app.post("/api/ai/models/cancel-download")
async def cancel_model_download(user: dict = Depends(require_admin)):
    """Cancel any ongoing model download"""
    try:
        downloader = get_downloader()
        
        if hasattr(downloader, 'cancel_download'):
            await downloader.cancel_download()
        
        return {"status": "ok", "message": "Download cancelled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel download: {str(e)}")


@app.post("/api/ai/test-openai")
async def test_openai_key(request: Request, user: dict = Depends(require_admin)):
    """Test OpenAI API key validity"""
    try:
        body = await request.json()
        api_key = body.get("api_key", "")
        
        if not api_key:
            # Use stored key if none provided
            settings = db_manager.get_ai_settings()
            api_key = settings.get("openai_key", "")
        
        if not api_key:
            raise HTTPException(status_code=400, detail="No API key provided")
        
        # Test the key with a simple request
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0
            )
            
            if response.status_code == 200:
                return {"status": "ok", "message": "API key is valid"}
            elif response.status_code == 401:
                return {"status": "error", "message": "Invalid API key"}
            else:
                return {"status": "error", "message": f"API error: {response.status_code}"}
    except httpx.TimeoutException:
        return {"status": "error", "message": "Connection timeout"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to test API key: {str(e)}")


@app.post("/api/ai/runner/download")
async def download_runner(user: dict = Depends(require_admin)):
    """Download the llama-server binary"""
    try:
        downloader = get_downloader()
        
        if hasattr(downloader, 'download_runner'):
            asyncio.create_task(downloader.download_runner())
            return {"status": "started", "message": "Runner download started"}
        else:
            return {"status": "error", "message": "Runner download not supported"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start runner download: {str(e)}")


@app.get("/api/ai/runner/status")
async def get_runner_status():
    """Get AI runner (llama-server) status including download progress"""
    try:
        downloader = get_downloader()
        
        if hasattr(downloader, 'get_runner_status'):
            return downloader.get_runner_status()
        else:
            return {"ready": False, "download_status": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get runner status: {str(e)}")


# ==================== AI REPORTS ====================

@app.get("/api/ai/reports")
async def get_ai_reports(
    report_type: str = None,
    limit: int = 50,
    unread_only: bool = False,
    agent_id: str = None
):
    """Get AI-generated reports"""
    try:
        reports = db_manager.get_ai_reports(
            report_type=report_type,
            limit=limit,
            unread_only=unread_only,
            agent_id=agent_id
        )
        return {"reports": reports}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get reports: {str(e)}")


@app.get("/api/ai/reports/unread-count")
async def get_unread_report_count():
    """Get count of unread AI reports by type"""
    try:
        counts = db_manager.get_unread_ai_report_count()
        return counts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get unread count: {str(e)}")


@app.get("/api/ai/reports/{report_id}")
async def get_ai_report(report_id: int):
    """Get a specific AI report"""
    try:
        report = db_manager.get_ai_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get report: {str(e)}")


@app.post("/api/ai/reports/{report_id}/read")
async def mark_report_read(report_id: int):
    """Mark an AI report as read"""
    try:
        success = db_manager.mark_ai_report_read(report_id)
        if not success:
            raise HTTPException(status_code=404, detail="Report not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark as read: {str(e)}")


@app.post("/api/ai/reports/mark-all-read")
async def mark_all_reports_read(report_type: str = None):
    """Mark all AI reports as read"""
    try:
        count = db_manager.mark_all_ai_reports_read(report_type)
        return {"status": "ok", "marked_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark as read: {str(e)}")


@app.delete("/api/ai/reports/{report_id}")
async def delete_ai_report(report_id: int, user: dict = Depends(require_admin)):
    """Delete an AI report"""
    try:
        success = db_manager.delete_ai_report(report_id)
        if not success:
            raise HTTPException(status_code=404, detail="Report not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete report: {str(e)}")


@app.post("/api/ai/reports/{report_id}/feedback")
async def set_report_feedback(report_id: int, request: Request):
    """Set feedback (thumbs up/down) for an AI report"""
    try:
        body = await request.json()
        feedback = body.get("feedback")  # 'up', 'down', or null to clear
        
        if feedback not in [None, 'up', 'down']:
            raise HTTPException(status_code=400, detail="Invalid feedback value")
        
        success = db_manager.set_ai_report_feedback(report_id, feedback)
        if not success:
            raise HTTPException(status_code=404, detail="Report not found")
        return {"status": "ok", "feedback": feedback}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set feedback: {str(e)}")


# ==================== AI MANUAL TRIGGERS ====================

@app.post("/api/ai/generate/briefing")
async def generate_briefing_now(user: dict = Depends(require_admin)):
    """
    Manually trigger the Daily Briefing report generation.
    Bypasses the schedule and runs immediately.
    """
    global report_scheduler
    
    try:
        # Check if AI is enabled
        settings = db_manager.get_ai_settings()
        if not settings.get("enabled", False):
            raise HTTPException(status_code=400, detail="AI assistant is disabled. Enable it in Settings.")
        
        provider = settings.get("provider", "local")
        
        # For OpenAI provider, check API key
        if provider == "openai":
            if not settings.get("openai_key"):
                raise HTTPException(status_code=503, detail="OpenAI API key not configured. Please add your API key in Settings.")
        else:
            # For local provider, check runner and model status
            downloader = get_downloader()
            if not downloader.is_runner_ready():
                raise HTTPException(status_code=503, detail="AI Engine not installed. Please install it in Settings.")
            
            active_model = settings.get("local_model_id", "")
            if not active_model or not downloader.is_model_downloaded(active_model):
                raise HTTPException(status_code=503, detail="AI model not downloaded. Please download a model in Settings.")
        
        # Ensure AI service is available
        ai_service = get_ai_service(db_manager)
        if not ai_service:
            raise HTTPException(status_code=503, detail="AI service not initialized")
        
        # Generate briefing directly (bypass scheduler for immediate execution)
        # skip_ready_check=True because we already validated model availability above
        generator = DailyBriefingGenerator(db_manager, ai_service)
        report_id = await generator.generate(skip_ready_check=True)
        
        if report_id:
            return {"status": "ok", "message": "Daily briefing generated", "report_id": report_id}
        else:
            return {"status": "skipped", "message": "No data available for briefing (no agents or briefing disabled)"}
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate briefing: {str(e)}")


@app.post("/api/ai/generate/executive-summary")
async def generate_executive_summary_now(
    days: int = 30,
    profile_id: str = None,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """
    Generate and save an Executive Summary report.
    This creates a STATIC snapshot in the ai_reports table that will not change when viewed later.
    Optionally scope to a specific report profile.
    """
    try:
        # Fetch the full executive summary data by calling the GET endpoint logic
        # This ensures the stored report matches what would be displayed
        exec_summary_response = await get_executive_summary(
            days=days,
            profile_id=profile_id,
            x_tenant_id=x_tenant_id
        )
        
        if not exec_summary_response.get("success"):
            return {"status": "error", "message": "Failed to generate executive summary data"}
        
        summary_data = exec_summary_response.get("data", {})
        
        # Extract key values for the report title and markdown content
        profile_name = summary_data.get("profile_name", "All Services")
        global_uptime = summary_data.get("global_uptime_percent") or 100.0
        sla_target = summary_data.get("sla_target", 99.9)
        sla_status = summary_data.get("sla_status", "UNKNOWN")
        sla_passed = sla_status == "PASSED"
        incident_count = summary_data.get("incident_count", 0)
        monitors_count = summary_data.get("monitors_count", 0)
        scribes_count = summary_data.get("scribes_count", 0)
        total_checks = summary_data.get("theoretical_checks", 0)
        logs_analyzed = summary_data.get("logs_analyzed", 0)
        period = summary_data.get("period", {})
        start_str = period.get("start", "")
        end_str = period.get("end", "")
        
        # Parse dates for display
        try:
            from datetime import datetime
            start_date = datetime.fromisoformat(start_str.replace('Z', '').split('+')[0])
            end_date = datetime.fromisoformat(end_str.replace('Z', '').split('+')[0])
            period_display = f"{start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}"
        except:
            period_display = f"{start_str} - {end_str}"
        
        # Build report content (markdown summary)
        report_title = f"{profile_name} - {days} Day Report"
        report_content = f"""# Executive Summary Report

**Profile:** {profile_name}
**Period:** {period_display} ({days} days)

## Key Metrics

- **Global Availability:** {global_uptime:.2f}%
- **SLA Status:** {'✓ PASSED' if sla_passed else '✕ FAILED'} (Target: {sla_target}%)
- **Service Interruptions:** {incident_count}
- **Services Monitored:** {monitors_count}
- **Scribes Reporting:** {scribes_count}
- **Logs Analyzed:** {logs_analyzed:,}

## Summary

{'All systems maintained excellent availability during this period.' if global_uptime >= 99.9 else 'Some services experienced availability issues during this period. Review the service details for more information.'}

---
*Generated by LogLibrarian on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}*
"""
        
        # Store the FULL summary data in metadata - this makes the report STATIC
        # When viewing a historical report, we use this stored data, not live calculations
        metadata = {
            "period_days": days,
            "profile_id": profile_id,
            "profile_name": profile_name,
            # Store the complete snapshot for static viewing
            "snapshot": summary_data
        }
        
        report_id = db_manager.create_ai_report(
            report_type="executive_summary",
            title=report_title,
            content=report_content,
            metadata=metadata
        )
        
        if report_id > 0:
            return {"status": "ok", "message": "Executive summary generated", "report_id": report_id}
        else:
            return {"status": "error", "message": "Failed to save report"}
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate executive summary: {str(e)}")


# ==================== AI SYSTEM CONTEXT ====================

@app.get("/api/ai/system-context")
async def get_system_context():
    """
    Get current system status for AI chat context injection.
    Returns a summary of agents, alerts, and system health.
    """
    try:
        agents = db_manager.get_all_agents()
        
        online_count = sum(1 for a in agents if a.get("status") == "online")
        offline_count = len(agents) - online_count
        
        # Get active alerts count
        alerts = db_manager.get_active_alerts()
        alert_count = len(alerts) if alerts else 0
        
        # Get recent error count
        error_count = 0
        try:
            logs = db_manager.get_raw_logs(severity="error", limit=100)
            error_count = len(logs) if logs else 0
        except:
            pass
        
        context = {
            "total_agents": len(agents),
            "online_agents": online_count,
            "offline_agents": offline_count,
            "active_alerts": alert_count,
            "recent_errors": error_count,
            "agents": [
                {
                    "hostname": a.get("hostname", "Unknown"),
                    "status": a.get("status", "offline"),
                    "os": a.get("os", "unknown")
                }
                for a in agents[:10]  # Limit to first 10 for context size
            ],
            "summary": f"{online_count} agent{'s' if online_count != 1 else ''} online, {offline_count} offline, {alert_count} active alert{'s' if alert_count != 1 else ''}"
        }
        
        return context
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system context: {str(e)}")


# ==================== Archivist API (Long-term Memory) ====================

@app.get("/api/ai/archivist/stats")
async def get_archivist_stats():
    """Get statistics about the Archivist archive collection"""
    try:
        archivist = get_archivist(db_manager)
        stats = archivist.get_archive_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get archivist stats: {str(e)}")


@app.post("/api/ai/archivist/index")
async def trigger_archivist_index(request: Request, user: dict = Depends(require_admin)):
    """Manually trigger the Archivist indexer to archive recent logs"""
    try:
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        hours_back = body.get("hours_back", 1)
        
        archivist = get_archivist(db_manager)
        stats = archivist.run_indexer(hours_back=hours_back)
        
        return {
            "status": "ok",
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run indexer: {str(e)}")


class ArchiveSearchRequest(BaseModel):
    query: str
    limit: int = 10
    server_name: Optional[str] = None
    log_level: Optional[str] = None
    time_range_hours: Optional[int] = None


@app.post("/api/ai/archivist/search")
async def search_archives(request: ArchiveSearchRequest):
    """
    Semantic search over archived logs.
    
    Returns the most relevant log entries matching the natural language query.
    """
    try:
        archivist = get_archivist(db_manager)
        
        entries = archivist.search_archives(
            query=request.query,
            limit=request.limit,
            server_name=request.server_name,
            log_level=request.log_level,
            time_range_hours=request.time_range_hours
        )
        
        # Convert to serializable format
        results = []
        for entry in entries:
            results.append({
                "id": entry.id,
                "text": entry.text,
                "server_name": entry.server_name,
                "timestamp": entry.timestamp,
                "log_level": entry.log_level,
                "source": entry.source,
                "score": entry.score
            })
        
        return {
            "query": request.query,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# ==================== INSTALL SCRIPT (Single-User Mode) ====================

@app.get("/api/install-script")
async def get_install_script(request: Request):
    """
    Get the pre-configured install commands for deploying agents.
    This is a zero-configuration endpoint - it automatically uses the default API key.
    """
    try:
        # Get the default API key
        api_key = db_manager.get_default_api_key()
        if not api_key:
            raise HTTPException(status_code=500, detail="Default API key not found. Please restart the server.")
        
        # Get the effective server URL
        server_url = get_effective_server_url(request)
        
        # Build the install commands
        # Fetch all prioritized addresses for agent config - respecting fallback_order setting
        from utils import get_lan_ips
        
        fallback_order = db_manager.get_system_setting("fallback_order", "lan_first")
        custom_url = db_manager.get_system_setting("custom_url", "").strip()
        selected_lan_ip = db_manager.get_system_setting("selected_lan_ip", "").strip()
        public_url = db_manager.get_public_app_url().strip()
        
        # Build LAN hosts list
        lan_hosts = []
        if selected_lan_ip:
            lan_hosts.append(f"http://{selected_lan_ip}:8000")
        else:
            for ip in get_lan_ips():
                lan_hosts.append(f"http://{ip}:8000")
        
        # Build DNS/public hosts list
        dns_hosts = []
        if public_url:
            dns_hosts.append(public_url)
        if custom_url and custom_url not in dns_hosts:
            dns_hosts.append(custom_url)
        
        # Apply fallback order setting
        if fallback_order == "lan_first":
            prioritized_hosts = lan_hosts + dns_hosts
        else:
            prioritized_hosts = dns_hosts + lan_hosts
        
        # Remove duplicates, preserve order
        seen = set()
        prioritized_hosts = [x for x in prioritized_hosts if not (x in seen or seen.add(x))]

        # Use the first as the main server_url for legacy
        main_url = prioritized_hosts[0] if prioritized_hosts else server_url
        # Pass all prioritized hosts as JSON for config
        hosts_json = json.dumps(prioritized_hosts)

        linux_cmd = f'curl -sSL "{main_url}/api/scripts/install-linux?api_key={api_key}" | sudo bash'
        windows_cmd = f'iwr -useb "{main_url}/api/scripts/install-windows?api_key={api_key}" | iex'
        
        return {
            "status": "ok",
            "server_url": server_url,
            "api_key": api_key,
            "commands": {
                "linux": linux_cmd,
                "windows": windows_cmd
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate install script: {str(e)}")


@app.get("/api/download/scribe-windows-configured")
async def download_configured_windows_agent(request: Request):
    """
    Download a pre-configured Windows Scribe agent package (ZIP).
    The package includes the scribe.exe and a config.json with API key and server URL pre-filled.
    """
    import zipfile
    import io
    import json
    from utils import get_lan_ips
    
    try:
        # Get the default API key
        api_key = db_manager.get_default_api_key()
        if not api_key:
            raise HTTPException(status_code=500, detail="Default API key not found. Please restart the server.")
        
        # Get the effective server URL
        server_url = get_effective_server_url(request)
        
        # Build prioritized hosts list based on settings
        fallback_order = db_manager.get_system_setting("fallback_order", "lan_first")
        custom_url = db_manager.get_system_setting("custom_url", "").strip()
        selected_lan_ip = db_manager.get_system_setting("selected_lan_ip", "").strip()
        
        prioritized_hosts = []
        lan_hosts = []
        if selected_lan_ip:
            lan_hosts.append(f"http://{selected_lan_ip}:8000")
        else:
            for ip in get_lan_ips():
                lan_hosts.append(f"http://{ip}:8000")
        
        dns_hosts = []
        public_url = db_manager.get_public_app_url().strip()
        if public_url:
            dns_hosts.append(public_url)
        if custom_url and custom_url not in dns_hosts:
            dns_hosts.append(custom_url)
        
        if fallback_order == "lan_first":
            prioritized_hosts = lan_hosts + dns_hosts
        else:
            prioritized_hosts = dns_hosts + lan_hosts
        
        # Use the first as the main server_url for legacy
        main_url = prioritized_hosts[0] if prioritized_hosts else server_url
        
        # Create the config.json content
        config = {
            "server_host": main_url.replace("http://", "").replace("https://", ""),
            "server_hosts": [h.replace("http://", "").replace("https://", "") for h in prioritized_hosts],
            "agent_name": "",
            "log_file": "",
            "metrics_interval": 10,
            "log_batch_size": 50,
            "log_batch_interval": 5,
            "ssl_enabled": main_url.startswith("https://"),
            "ssl_verify": True,
            "agent_id": "",
            "api_key": api_key,
            "buffer_enabled": True,
            "buffer_max_size_mb": 50,
            "buffer_max_duration_min": 60,
            "buffer_disk_enabled": True,
            "buffer_data_dir": "",
            "reconnect_initial_sec": 5,
            "reconnect_max_sec": 300,
            "health_file_enabled": True,
            "health_file_interval_sec": 60
        }
        
        # Check if the scribe binary exists
        scribe_path = "/app/scribe-bin/scribe.exe"
        
        if not os.path.exists(scribe_path):
            # Fallback: provide just the config as a download with instructions
            config_json = json.dumps(config, indent=2)
            return Response(
                content=config_json,
                media_type="application/json",
                headers={
                    "Content-Disposition": "attachment; filename=config.json"
                }
            )
        
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add the scribe executable
            zf.write(scribe_path, "scribe.exe")
            
            # Add the config.json
            config_json = json.dumps(config, indent=2)
            zf.writestr("config.json", config_json)
            
            # Add a README
            readme = f"""LogLibrarian Scribe Agent - Pre-Configured Package
================================================

This package contains:
- scribe.exe: The Scribe agent for collecting metrics and logs
- config.json: Pre-configured with your API key and server URL

Server: {server_url}
API Key: {api_key[:20]}...

INSTALLATION
------------
1. Extract this ZIP to a folder (e.g., C:\\Scribe)
2. Open PowerShell as Administrator
3. Navigate to the folder: cd C:\\Scribe
4. Run the agent: .\\scribe.exe

The agent will automatically:
- Connect to your LogLibrarian server
- Start collecting system metrics
- Register itself in the dashboard

For service installation (run on startup):
    .\\scribe.exe install
    .\\scribe.exe start

For more options:
    .\\scribe.exe --help

"""
            zf.writestr("README.txt", readme)
        
        zip_buffer.seek(0)
        
        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=scribe-windows-configured.zip"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create package: {str(e)}")


@app.get("/api/download/scribe-config")
async def download_scribe_config(request: Request):
    """
    Download just the config.json file for manual agent setup.
    """
    import json
    from utils import get_lan_ips
    
    try:
        # Get the default API key
        api_key = db_manager.get_default_api_key()
        if not api_key:
            raise HTTPException(status_code=500, detail="Default API key not found. Please restart the server.")
        
        # Get the effective server URL
        server_url = get_effective_server_url(request)
        
        # Build prioritized hosts list based on settings
        fallback_order = db_manager.get_system_setting("fallback_order", "lan_first")
        custom_url = db_manager.get_system_setting("custom_url", "").strip()
        selected_lan_ip = db_manager.get_system_setting("selected_lan_ip", "").strip()
        
        prioritized_hosts = []
        lan_hosts = []
        if selected_lan_ip:
            lan_hosts.append(f"http://{selected_lan_ip}:8000")
        else:
            for ip in get_lan_ips():
                lan_hosts.append(f"http://{ip}:8000")
        
        dns_hosts = []
        public_url = db_manager.get_public_app_url().strip()
        if public_url:
            dns_hosts.append(public_url)
        if custom_url and custom_url not in dns_hosts:
            dns_hosts.append(custom_url)
        
        if fallback_order == "lan_first":
            prioritized_hosts = lan_hosts + dns_hosts
        else:
            prioritized_hosts = dns_hosts + lan_hosts
        
        # Use the first as the main server_url for legacy
        main_url = prioritized_hosts[0] if prioritized_hosts else server_url
        
        # Create the config.json content
        config = {
            "server_host": main_url.replace("http://", "").replace("https://", ""),
            "server_hosts": [h.replace("http://", "").replace("https://", "") for h in prioritized_hosts],
            "agent_name": "",
            "log_file": "",
            "metrics_interval": 10,
            "log_batch_size": 50,
            "log_batch_interval": 5,
            "ssl_enabled": main_url.startswith("https://"),
            "ssl_verify": True,
            "agent_id": "",
            "api_key": api_key,
            "buffer_enabled": True,
            "buffer_max_size_mb": 50,
            "buffer_max_duration_min": 60,
            "buffer_disk_enabled": True,
            "buffer_data_dir": "",
            "reconnect_initial_sec": 5,
            "reconnect_max_sec": 300,
            "health_file_enabled": True,
            "health_file_interval_sec": 60
        }
        
        config_json = json.dumps(config, indent=2)
        
        return Response(
            content=config_json,
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=config.json"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate config: {str(e)}")


def validate_api_key_simple(api_key: str) -> bool:
    """Simple API key validation for single-user mode"""
    if not api_key:
        return False
    return db_manager.validate_api_key(api_key)


# ==================== AGENT REGISTRATION ====================

class RegisterPayload(BaseModel):
    agent_id: Optional[str] = None
    hostname: str
    public_ip: Optional[str] = ""
    os: Optional[str] = ""


@app.post("/api/register")
async def register_agent(
    payload: RegisterPayload, 
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None)
):
    """
    Register a new agent or update existing agent.
    Validates API key for authentication.
    """
    try:
        # Validate API key
        api_key = x_api_key
        if not api_key and authorization and authorization.startswith("Bearer "):
            api_key = authorization[7:]
        
        if api_key and not validate_api_key_simple(api_key):
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        # Generate agent_id if not provided or invalid
        agent_id = payload.agent_id
        if not agent_id or len(agent_id) < 3:
            # Fallback: use hostname + timestamp
            import time
            agent_id = f"{payload.hostname}-{int(time.time())}"
            print(f"⚠️ Generated fallback agent_id: {agent_id}")
        
        # Get public IP from request if not provided
        public_ip = payload.public_ip
        if not public_ip:
            # Try to get from X-Forwarded-For header (if behind proxy)
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                public_ip = forwarded.split(",")[0].strip()
            else:
                public_ip = request.client.host if request.client else ""
        
        # Upsert agent
        db_manager.upsert_agent(
            agent_id=agent_id,
            hostname=payload.hostname,
            status="online",
            last_seen=None,  # Will use current time
            public_ip=public_ip,
            os=payload.os or ""
        )
        
        # Get log settings for this agent
        log_settings = db_manager.get_log_settings(agent_id)
        
        return {
            "status": "registered",
            "agent_id": agent_id,
            "log_settings": log_settings,
            "message": f"Agent {payload.hostname} registered successfully"
        }
        
    except Exception as e:
        print(f"❌ Registration error: {str(e)}")
        # Even on error, try to return a usable response
        return {
            "status": "registered_with_errors",
            "agent_id": payload.agent_id or payload.hostname,
            "error": str(e),
            "message": "Agent registered with errors - some features may be limited"
        }


def get_effective_server_url(request: Request) -> str:
    """
    Get the effective server URL for agent connections.
    Respects user's fallback_order setting (lan_first or dns_first).
    Never returns 127.0.0.1 - falls back to request origin if no valid IP found.
    """
    from utils import get_best_lan_ip
    
    # Get system settings
    custom_url = db_manager.get_system_setting("custom_url", "").strip()
    fallback_order = db_manager.get_system_setting("fallback_order", "lan_first")
    selected_lan_ip = db_manager.get_system_setting("selected_lan_ip", "").strip()
    public_url = db_manager.get_public_app_url().strip()

    # Helper to get LAN URL (returns None if no valid IP)
    def get_lan_url():
        ip = selected_lan_ip if selected_lan_ip else get_best_lan_ip()
        if ip and not ip.startswith("127."):
            return f"http://{ip}:8000"
        return None

    # Helper to get DNS/custom URL
    def get_dns_url():
        if public_url:
            return public_url
        if custom_url:
            return custom_url
        return None

    # Apply fallback order setting
    if fallback_order == "lan_first":
        # Try LAN IP first, then DNS/custom URL
        lan_url = get_lan_url()
        if lan_url:
            return lan_url
        dns_url = get_dns_url()
        if dns_url:
            return dns_url
    else:
        # Try DNS/custom URL first, then LAN IP
        dns_url = get_dns_url()
        if dns_url:
            return dns_url
        lan_url = get_lan_url()
        if lan_url:
            return lan_url

    # Ultimate fallback: use request origin (what the browser is using to reach us)
    origin = str(request.base_url).rstrip("/")
    return origin

# Endpoint to get all LAN IPs for UI selection
@app.get("/api/lan-ips")
async def get_lan_ips_endpoint():
    from utils import get_lan_ips
    return {"ips": get_lan_ips()}


# --- System Settings for Custom URL and Fallback Order ---
@app.get("/api/agent-connection-settings")
async def get_agent_connection_settings():
    return {
        "custom_url": db_manager.get_system_setting("custom_url", ""),
        "fallback_order": db_manager.get_system_setting("fallback_order", "lan_first"),
        "selected_lan_ip": db_manager.get_system_setting("selected_lan_ip", "")
    }

@app.put("/api/agent-connection-settings")
async def set_agent_connection_settings(
    custom_url: str = Body(""),
    fallback_order: str = Body("lan_first"),
    selected_lan_ip: str = Body(""),
    user: dict = Depends(require_admin)
):
    db_manager.set_system_setting("custom_url", custom_url)
    db_manager.set_system_setting("fallback_order", fallback_order)
    db_manager.set_system_setting("selected_lan_ip", selected_lan_ip)
    return {"status": "ok"}


# --- Binary Downloads Endpoint ---
@app.get("/api/downloads/{filename}")
async def download_binary(filename: str):
    """
    Serve scribe agent binaries for installation scripts.
    Binaries are expected in /app/scribe-bin/ (mounted from ./scribe/bin)
    """
    from fastapi.responses import FileResponse
    import re
    
    # Validate filename to prevent path traversal
    if not re.match(r'^scribe-(linux|windows)-(amd64|arm64|arm)(\.exe)?$', filename):
        raise HTTPException(status_code=404, detail="Binary not found")
    
    # Map requested filename to actual binary
    binary_dir = "/app/scribe-bin"
    
    # Check for exact match first
    binary_path = os.path.join(binary_dir, filename)
    if os.path.exists(binary_path):
        return FileResponse(
            binary_path,
            media_type="application/octet-stream",
            filename=filename
        )
    
    # Fallback: check for generic names (scribe.exe, scribe-linux, etc.)
    fallback_names = []
    if "windows" in filename:
        fallback_names = ["scribe.exe", "scribe-windows.exe"]
    elif "linux" in filename:
        fallback_names = ["scribe-linux", "scribe"]
    
    for fallback in fallback_names:
        fallback_path = os.path.join(binary_dir, fallback)
        if os.path.exists(fallback_path):
            return FileResponse(
                fallback_path,
                media_type="application/octet-stream",
                filename=filename
            )
    
    # List available files for debugging
    available = []
    if os.path.exists(binary_dir):
        available = os.listdir(binary_dir)
    
    raise HTTPException(
        status_code=404, 
        detail=f"Binary '{filename}' not found. Available: {available}"
    )


@app.get("/api/scripts/install-linux", response_class=PlainTextResponse)
async def get_linux_install_script(
    request: Request,
    api_key: Optional[str] = None
):
    """
    Returns a non-interactive Linux installation script.
    The script is pre-configured with the server URL and auth token.
    """
    # Get the effective server URL (public_app_url or request origin)
    server_url = get_effective_server_url(request)
    
    # If no api_key provided, get the instance API key from database
    if not api_key:
        config = db_manager.get_setup_config()
        api_key = config.get("instance_api_key", "")
    
    # Extract host:port from URL for server_host config
    from urllib.parse import urlparse
    parsed = urlparse(server_url)
    server_host = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
    
    # Determine if SSL should be enabled based on URL scheme
    ssl_enabled = "true" if parsed.scheme == "https" else "false"
    
    # API key line for config.json
    api_key_line = f'"api_key": "{api_key}",' if api_key else '"api_key": "",'
    
    script = f'''#!/bin/bash
# Scribe Agent - Linux Auto-Installer
# Pre-configured for: {server_url}
# Generated automatically - do not edit

set -e

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'
NC='\\033[0m'

echo -e "${{BLUE}}╔════════════════════════════════════════════════════════════════╗${{NC}}"
echo -e "${{BLUE}}║           📜 SCRIBE AGENT AUTO-INSTALLER (Linux)               ║${{NC}}"
echo -e "${{BLUE}}╚════════════════════════════════════════════════════════════════╝${{NC}}"
echo ""

# Configuration (pre-set from server)
SERVER_HOST="{server_host}"
SSL_ENABLED={ssl_enabled}
AGENT_NAME="${{AGENT_NAME:-$HOSTNAME}}"
AUTH_TOKEN="{api_key if api_key else ''}"

echo -e "${{GREEN}}Server:${{NC}} $SERVER_HOST"
echo -e "${{GREEN}}Agent Name:${{NC}} $AGENT_NAME"
echo ""

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo -e "${{YELLOW}}⚠️  Running without root. Using current user home directory.${{NC}}"
    INSTALL_DIR="$HOME/.scribe"
else
    INSTALL_DIR="/opt/scribe"
fi

# Stop existing scribe service if running (for upgrades)
if systemctl is-active --quiet scribe 2>/dev/null; then
    echo -e "${{YELLOW}}Stopping existing Scribe service for upgrade...${{NC}}"
    systemctl stop scribe
    RESTART_AFTER=true
else
    RESTART_AFTER=false
fi

echo -e "${{BLUE}}[1/4]${{NC}} Creating installation directory..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo -e "${{BLUE}}[2/4]${{NC}} Downloading Scribe agent..."
# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64) BINARY_ARCH="amd64" ;;
    aarch64) BINARY_ARCH="arm64" ;;
    armv7l) BINARY_ARCH="arm" ;;
    *) echo -e "${{RED}}Unsupported architecture: $ARCH${{NC}}"; exit 1 ;;
esac

# Download directly from this server
if ! curl -fsSL "{server_url}/api/downloads/scribe-linux-$BINARY_ARCH" -o scribe; then
    echo -e "${{RED}}Failed to download Scribe binary${{NC}}"
    echo -e "${{YELLOW}}Please download manually and place in $INSTALL_DIR${{NC}}"
    exit 1
fi

chmod +x scribe

echo -e "${{BLUE}}[3/4]${{NC}} Creating configuration..."
cat > config.json << EOF
{{
    "server_host": "$SERVER_HOST",
    {api_key_line}
    "ssl_enabled": $SSL_ENABLED,
    "metrics_interval": 60,
    "buffer_enabled": true,
    "buffer_max_size_mb": 50,
    "health_file_enabled": true
}}
EOF

echo -e "${{BLUE}}[4/4]${{NC}} Installing systemd service..."
if [ "$EUID" -eq 0 ]; then
    cat > /etc/systemd/system/scribe.service << EOF
[Unit]
Description=Scribe Monitoring Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/scribe -config $INSTALL_DIR/config.json
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable scribe
    systemctl start scribe
    
    echo ""
    echo -e "${{GREEN}}✅ Installation complete!${{NC}}"
    echo -e "${{GREEN}}Scribe is now running as a systemd service${{NC}}"
    echo ""
    echo "Commands:"
    echo "  Check status: systemctl status scribe"
    echo "  View logs:    journalctl -u scribe -f"
    echo "  Stop:         systemctl stop scribe"
    echo "  Start:        systemctl start scribe"
else
    echo ""
    echo -e "${{GREEN}}✅ Installation complete!${{NC}}"
    echo -e "${{YELLOW}}Note: Run as root to install as a system service${{NC}}"
    echo ""
    echo "To run manually:"
    echo "  cd $INSTALL_DIR && ./scribe"
fi

echo ""
echo -e "${{BLUE}}The agent should appear in your dashboard within 30 seconds${{NC}}"
'''
    return script


@app.get("/api/scripts/install-windows", response_class=PlainTextResponse)
async def get_windows_install_script(
    request: Request,
    api_key: Optional[str] = None
):
    """
    Returns a non-interactive Windows PowerShell installation script.
    The script is pre-configured with the server URL and auth token.
    """
    # Get the effective server URL (public_app_url or request origin)
    server_url = get_effective_server_url(request)
    
    # If no api_key provided, get the instance API key from database
    if not api_key:
        config = db_manager.get_setup_config()
        api_key = config.get("instance_api_key", "")
    
    # Extract host:port from URL for server_host config
    from urllib.parse import urlparse
    parsed = urlparse(server_url)
    server_host = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
    
    # Determine if SSL should be enabled based on URL scheme
    ssl_enabled = "true" if parsed.scheme == "https" else "false"
    
    script = f'''#Requires -RunAsAdministrator
# Scribe Agent - Windows Auto-Installer
# Pre-configured for: {server_url}
# Generated automatically - do not edit

$ErrorActionPreference = "Stop"

# Configuration (pre-set from server)
$ServerHost = "{server_host}"
$AuthToken = "{api_key if api_key else ''}"
$SSLEnabled = ${ssl_enabled}

# Set agent name (use env var if set, otherwise computer name)
if ($env:AGENT_NAME) {{
    $AgentName = $env:AGENT_NAME
}} else {{
    $AgentName = $env:COMPUTERNAME
}}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "          SCRIBE AGENT AUTO-INSTALLER (Windows)                " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Server: $ServerHost" -ForegroundColor Green
Write-Host "Agent Name: $AgentName" -ForegroundColor Green
Write-Host ""

# Installation directory
$InstallDir = "$env:ProgramData\\Scribe"
$ServiceName = "ScribeAgent"

# Stop existing service FIRST if running (required to replace binary)
$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ExistingService) {{
    Write-Host "[0/4] Stopping existing Scribe service for upgrade..." -ForegroundColor Yellow
    if ($ExistingService.Status -eq 'Running') {{
        Stop-Service -Name $ServiceName -Force
        Start-Sleep -Seconds 2
    }}
}}

Write-Host "[1/4] Creating installation directory..." -ForegroundColor Blue
if (!(Test-Path $InstallDir)) {{
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}}
Set-Location $InstallDir

Write-Host "[2/4] Downloading Scribe agent..." -ForegroundColor Blue
$BinaryUrl = "{server_url}/api/downloads/scribe-windows-amd64.exe"
$BinaryPath = Join-Path $InstallDir "scribe.exe"

try {{
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $BinaryUrl -OutFile $BinaryPath -UseBasicParsing
}} catch {{
    Write-Host "Failed to download Scribe binary: $_" -ForegroundColor Red
    Write-Host "Please download manually and place in $InstallDir" -ForegroundColor Yellow
    exit 1
}}

Write-Host "[3/4] Creating configuration..." -ForegroundColor Blue
$ConfigObj = @{{
    server_host = $ServerHost
    api_key = $AuthToken
    ssl_enabled = $SSLEnabled
    metrics_interval = 60
    buffer_enabled = $true
    buffer_max_size_mb = 50
    health_file_enabled = $true
}}
$Config = $ConfigObj | ConvertTo-Json

$ConfigPath = Join-Path $InstallDir "config.json"
# Use .NET to write without BOM (PowerShell's Out-File adds BOM which breaks Go JSON parser)
[System.IO.File]::WriteAllText($ConfigPath, $Config)

Write-Host "[4/4] Installing Windows service..." -ForegroundColor Blue

# Delete and recreate service (service was already stopped at step 0)
$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ExistingService) {{
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 2
}}

# Create new service using sc.exe
$ScribePath = "`"$BinaryPath`""
sc.exe create $ServiceName binPath= $ScribePath start= auto DisplayName= "Scribe Monitoring Agent" | Out-Null
sc.exe description $ServiceName "Scribe agent for LogLibrarian monitoring" | Out-Null
sc.exe failure $ServiceName reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null

# Start the service
Start-Service -Name $ServiceName

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host "Scribe is now running as a Windows service" -ForegroundColor Green
Write-Host ""
Write-Host "Commands:" -ForegroundColor Cyan
Write-Host "  Check status: Get-Service ScribeAgent"
Write-Host "  View logs:    Get-EventLog -LogName Application -Source ScribeAgent"
Write-Host "  Stop:         Stop-Service ScribeAgent"
Write-Host "  Start:        Start-Service ScribeAgent"
Write-Host ""
Write-Host "The agent should appear in your dashboard within 30 seconds" -ForegroundColor Blue
'''
    return script


@app.post("/api/ingest")
async def ingest_logs_endpoint(batch: LogBatch):
    """
    Ingest a batch of compressed logs from Scribe agents
    
    Stores templates in Qdrant (vector DB) and occurrences in SQLite
    """
    try:
        result = db_manager.ingest_logs(batch.logs)
        
        return {
            "status": "ingested",
            "count": result["total_occurrences"],
            "new_templates": result["new_templates"],
            "errors": result["errors"] if result["errors"] else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.post("/api/heartbeat")
async def heartbeat_endpoint(payload: HeartbeatPayload):
    """
    Receive heartbeat with buffered metrics from Scribe agents
    
    Updates agent status, adds metrics to buffer, and stores process snapshots.
    Metrics are batched for efficient database insertion.
    
    Authentication:
    - Scribe must provide the instance API key (set during setup)
    - Scribes without valid API key are rejected
    """
    try:
        # Validate instance API key
        provided_key = getattr(payload, 'auth_token', None) or getattr(payload, 'api_key', None)
        is_valid, auth_reason = validate_scribe_api_key(provided_key)
        
        if not is_valid:
            print(f"🔒 Authentication failed for agent {payload.agent_id}: {auth_reason}")
            raise HTTPException(
                status_code=401, 
                detail=f"Authentication failed: {auth_reason}. Check your API key configuration."
            )
        
        # Upsert agent information with public IP
        db_manager.upsert_agent(
            agent_id=payload.agent_id,
            hostname=payload.hostname,
            status=payload.status,
            last_seen=payload.last_seen_at,
            public_ip=payload.public_ip,
            connection_address=getattr(payload, 'connection_address', None)
        )
        
        # Prepare metrics data
        metrics_data = [
            {
                "timestamp": metric.timestamp,
                "cpu_percent": metric.cpu_percent,
                "ram_percent": metric.ram_percent,
                "net_sent_bps": metric.net_sent_bps,
                "net_recv_bps": metric.net_recv_bps,
                "disk_read_bps": metric.disk_read_bps,
                "disk_write_bps": metric.disk_write_bps,
                "ping_latency_ms": metric.ping_latency_ms,
                "cpu_temp": metric.cpu_temp,
                "cpu_name": getattr(metric, 'cpu_name', ''),
                "gpu_percent": getattr(metric, 'gpu_percent', 0.0),
                "gpu_temp": getattr(metric, 'gpu_temp', 0.0),
                "gpu_name": getattr(metric, 'gpu_name', ''),
                "is_vm": getattr(metric, 'is_vm', False),
                "disks": [disk.dict() for disk in metric.disks]
            }
            for metric in payload.metrics
        ]
        
        # Add metrics to buffer for batched insertion
        buffered_count = 0
        if metrics_buffer and metrics_data:
            buffered_count = await metrics_buffer.add_metrics(
                agent_id=payload.agent_id,
                metrics=metrics_data,
                load_avg=payload.load_avg
            )
        
        # Insert process snapshot if processes are provided
        if payload.processes:
            process_data = [proc.dict() for proc in payload.processes]
            db_manager.insert_process_snapshot(
                agent_id=payload.agent_id,
                timestamp=payload.last_seen_at,
                processes=process_data
            )
        
        # Update system info if provided (sent periodically by agent)
        if payload.system_info:
            db_manager.update_agent_system_info(
                agent_id=payload.agent_id,
                system_info=payload.system_info.dict()
            )
        
        response = {
            "status": "ok",
            "agent_id": payload.agent_id,
            "metrics_buffered": buffered_count,
            "processes_count": len(payload.processes),
            "message": f"Heartbeat received from {payload.hostname}"
        }
        
        return response
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Heartbeat processing failed: {str(e)}")


@app.get("/api/agents")
async def get_agents(request: Request):
    """
    Get all registered agents (filtered by user's role and profile).
    - Admin: sees all agents
    - User: sees only agents in their assigned profile's scope
    """
    try:
        # Check if user is authenticated
        current_user = await get_current_user(request)
        if current_user:
            # Use RBAC-filtered method
            agents = db_manager.get_agents_for_user(current_user)
        else:
            # Unauthenticated - return all (for backward compatibility with agents)
            agents = db_manager.get_all_agents()
        return {
            "agents": agents
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch agents: {str(e)}")


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str, user: dict = Depends(require_admin)):
    """Delete an agent and all its associated data"""
    try:
        # Send shutdown command to agent if connected
        if agent_id in connection_manager.agents:
            try:
                await connection_manager.agents[agent_id].send_json({"command": "shutdown"})
            except:
                pass
        
        # Delete from database
        db_manager.delete_agent(agent_id)
        
        # Disconnect from connection manager
        connection_manager.disconnect_agent(agent_id)
        
        return {"success": True, "message": f"Agent {agent_id} deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")


@app.post("/api/agents/{agent_id}/disable")
async def disable_agent(agent_id: str, user: dict = Depends(require_admin)):
    """Disable an agent (mark as offline, stop accepting data)"""
    try:
        db_manager.disable_agent(agent_id)
        
        # Send stop command to agent if connected
        if agent_id in connection_manager.agents:
            try:
                await connection_manager.agents[agent_id].send_json({"command": "disable"})
            except:
                pass
        
        return {"success": True, "message": f"Agent {agent_id} disabled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to disable agent: {str(e)}")


@app.post("/api/agents/{agent_id}/enable")
async def enable_agent(agent_id: str, user: dict = Depends(require_admin)):
    """Enable a previously disabled agent"""
    try:
        db_manager.enable_agent(agent_id)
        return {"success": True, "message": f"Agent {agent_id} enabled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enable agent: {str(e)}")


@app.post("/api/agents/{agent_id}/restart")
async def restart_agent(agent_id: str, user: dict = Depends(require_admin)):
    """Send restart command to an agent"""
    try:
        # Check if agent is connected
        if agent_id not in connection_manager.agents:
            raise HTTPException(status_code=404, detail="Agent not connected")
        
        # Send restart command to the agent
        await connection_manager.agents[agent_id].websocket.send_json({"command": "restart"})
        return {"success": True, "message": f"Restart command sent to agent {agent_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart agent: {str(e)}")


@app.get("/api/agents/{agent_id}/uptime")
async def get_agent_uptime(agent_id: str):
    """Get uptime statistics for an agent"""
    try:
        stats = db_manager.get_agent_uptime_stats(agent_id)
        if "error" in stats:
            raise HTTPException(status_code=404, detail=stats["error"])
        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get uptime: {str(e)}")


@app.get("/api/agents/{agent_id}/system-info")
async def get_agent_system_info(agent_id: str):
    """Get detailed system information for an agent (hardware, OS, etc.)"""
    try:
        system_info = db_manager.get_agent_system_info(agent_id)
        if system_info is None:
            return {"system_info": None, "message": "System info not yet received from agent"}
        return {"system_info": system_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system info: {str(e)}")


@app.put("/api/agents/{agent_id}/rename")
async def rename_agent(agent_id: str, data: dict, user: dict = Depends(require_admin)):
    """Rename an agent (set display name)"""
    try:
        display_name = data.get("display_name", "").strip()
        db_manager.update_agent_display_name(agent_id, display_name)
        return {"success": True, "message": f"Agent renamed to '{display_name}'" if display_name else "Agent name reset to hostname"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename agent: {str(e)}")


@app.put("/api/agents/{agent_id}/tags")
async def update_agent_tags(agent_id: str, data: dict, user: dict = Depends(require_admin)):
    """Update tags for an agent (comma-separated string)"""
    try:
        tags = data.get("tags", "").strip()
        db_manager.update_agent_tags(agent_id, tags)
        return {"success": True, "tags": tags, "message": f"Tags updated to '{tags}'" if tags else "Tags cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update agent tags: {str(e)}")


@app.put("/api/agents/{agent_id}/uptime-window")
async def update_agent_uptime_window(agent_id: str, data: dict, user: dict = Depends(require_admin)):
    """
    Update the availability window setting for an agent.
    
    Allowed values: 'daily', 'weekly', 'monthly', 'quarterly', 'yearly'
    """
    try:
        uptime_window = data.get("uptime_window", "monthly").strip().lower()
        valid_windows = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
        
        if uptime_window not in valid_windows:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid uptime_window: {uptime_window}. Must be one of {valid_windows}"
            )
        
        success = db_manager.update_agent_uptime_window(agent_id, uptime_window)
        if success:
            return {
                "success": True, 
                "uptime_window": uptime_window,
                "message": f"Availability window set to '{uptime_window}'"
            }
        else:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update uptime window: {str(e)}")


@app.get("/api/tags")
async def get_all_tags(x_tenant_id: str = Header(default="default")):
    """Get all unique tags from agents (scribes), bookmarks, and report profiles"""
    try:
        tags_set = set()
        
        # Get tags from agents
        agents = db_manager.get_all_agents()
        for agent in agents:
            agent_tags = agent.get("tags", "")
            if agent_tags:
                for tag in agent_tags.split(","):
                    tag = tag.strip()
                    if tag:
                        tags_set.add(tag)
        
        # Get tags from bookmarks
        bookmarks = db_manager.get_bookmarks(x_tenant_id)
        for bookmark in bookmarks:
            bookmark_tags = bookmark.get("tags", "")
            if bookmark_tags:
                for tag in bookmark_tags.split(","):
                    tag = tag.strip()
                    if tag:
                        tags_set.add(tag)
        
        # Get tags from report profiles
        try:
            profiles = db_manager.get_report_profiles(x_tenant_id)
            for profile in profiles:
                # monitor_scope_tags and scribe_scope_tags are stored as JSON arrays
                for field in ["monitor_scope_tags", "scribe_scope_tags"]:
                    profile_tags = profile.get(field, [])
                    if profile_tags:
                        if isinstance(profile_tags, str):
                            # Handle if stored as JSON string
                            import json
                            try:
                                profile_tags = json.loads(profile_tags)
                            except:
                                profile_tags = []
                        for tag in profile_tags:
                            if tag and isinstance(tag, str):
                                tags_set.add(tag.strip())
        except Exception as e:
            # Don't fail if report profiles can't be read
            print(f"Warning: Could not read report profile tags: {e}")
        
        # Return sorted list
        return {"success": True, "data": sorted(list(tags_set))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get tags: {str(e)}")


@app.delete("/api/tags/{tag_name}")
async def delete_tag(tag_name: str, x_tenant_id: str = Header(default="default"), user: dict = Depends(require_admin)):
    """Delete a tag from all agents, bookmarks, and report profiles"""
    try:
        tag_to_delete = tag_name.strip()
        if not tag_to_delete:
            raise HTTPException(status_code=400, detail="Tag name cannot be empty")
        
        removed_from_agents = 0
        removed_from_bookmarks = 0
        removed_from_profiles = 0
        
        # Remove tag from agents
        agents = db_manager.get_all_agents()
        for agent in agents:
            agent_tags = agent.get("tags", "")
            if agent_tags:
                tags_list = [t.strip() for t in agent_tags.split(",") if t.strip()]
                if tag_to_delete in tags_list:
                    tags_list.remove(tag_to_delete)
                    new_tags = ", ".join(tags_list)
                    db_manager.update_agent_tags(agent["agent_id"], new_tags)
                    removed_from_agents += 1
        
        # Remove tag from bookmarks
        bookmarks = db_manager.get_bookmarks(x_tenant_id)
        for bookmark in bookmarks:
            bookmark_tags = bookmark.get("tags", "")
            if bookmark_tags:
                tags_list = [t.strip() for t in bookmark_tags.split(",") if t.strip()]
                if tag_to_delete in tags_list:
                    tags_list.remove(tag_to_delete)
                    new_tags = ", ".join(tags_list)
                    db_manager.update_bookmark(
                        x_tenant_id,
                        bookmark["id"], 
                        tags=new_tags
                    )
                    removed_from_bookmarks += 1
        
        # Remove tag from report profiles
        try:
            import json
            profiles = db_manager.get_report_profiles(x_tenant_id)
            for profile in profiles:
                updated = False
                updates = {}
                
                for field in ["monitor_scope_tags", "scribe_scope_tags"]:
                    profile_tags = profile.get(field, [])
                    if profile_tags:
                        if isinstance(profile_tags, str):
                            try:
                                profile_tags = json.loads(profile_tags)
                            except:
                                profile_tags = []
                        if tag_to_delete in profile_tags:
                            profile_tags = [t for t in profile_tags if t != tag_to_delete]
                            updates[field] = profile_tags
                            updated = True
                
                if updated:
                    db_manager.update_report_profile(x_tenant_id, profile["id"], **updates)
                    removed_from_profiles += 1
        except Exception as e:
            print(f"Warning: Could not remove tag from report profiles: {e}")
        
        return {
            "success": True, 
            "message": f"Tag '{tag_to_delete}' deleted",
            "removed_from_agents": removed_from_agents,
            "removed_from_bookmarks": removed_from_bookmarks,
            "removed_from_profiles": removed_from_profiles
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete tag: {str(e)}")


@app.get("/api/agents/{agent_id}/metrics")
async def get_agent_metrics(
    agent_id: str, 
    limit: int = None,  # No default limit - return all data when time range specified
    start_time: str = None,
    end_time: str = None,
    downsample: str = None  # 'hour', 'day', or None for auto-resolution
):
    """
    Get metrics for a specific agent with automatic resolution selection.
    
    When a time range is provided without explicit downsampling,
    the best resolution is automatically selected:
    - <= 1 hour: Raw data (1-2 second resolution)
    - 1-24 hours: 1-minute averages
    - 1-7 days: 15-minute averages
    - > 7 days: Hourly averages
    
    Response includes 'resolution' field showing which data source was used.
    """
    try:
        # If no time range and no limit specified, default to last 100 points
        effective_limit = limit
        if not start_time and not end_time and limit is None:
            effective_limit = 100
            
        metrics = db_manager.get_agent_metrics(
            agent_id, 
            limit=effective_limit,
            start_time=start_time,
            end_time=end_time,
            downsample=downsample
        )
        
        # Get resolution info for PostgreSQL backend
        resolution = {"table": "metrics", "description": "Raw data", "auto_selected": False}
        query_stats = {}
        
        if USE_POSTGRES:
            try:
                resolution = db_manager.get_last_query_resolution()
                query_stats = db_manager.get_last_query_stats()
            except:
                pass
        
        return {
            "agent_id": agent_id,
            "metrics": metrics,
            "count": len(metrics),
            "resolution": resolution,
            "query_stats": query_stats if query_stats else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch metrics: {str(e)}")


@app.get("/api/agents/{agent_id}/metrics/smart")
async def get_agent_metrics_smart(
    agent_id: str,
    start_time: str = None,
    end_time: str = None,
    max_points: int = 500
):
    """
    Get metrics with automatic resolution selection based on time range.
    
    This endpoint automatically selects the appropriate data resolution:
    - <= 2 hours: Raw data (1-2 second resolution)
    - 2-24 hours: 1-minute averages
    - 1-7 days: 15-minute averages
    - > 7 days: Hourly averages
    
    Args:
        agent_id: Agent identifier
        start_time: ISO format start time (default: 1 hour ago)
        end_time: ISO format end time (default: now)
        max_points: Maximum data points to return (default: 500)
    
    Returns:
        Metrics with resolution info and min/max values for aggregates
    """
    try:
        # Only available for PostgreSQL backend
        if USE_POSTGRES:
            result = db_manager.get_agent_metrics_smart(  # Now synchronous
                agent_id=agent_id,
                start_time=start_time,
                end_time=end_time,
                max_points=max_points
            )
            return {"agent_id": agent_id, **result}
        else:
            # Fallback to regular query for SQLite
            metrics = db_manager.get_agent_metrics(
                agent_id,
                limit=max_points,
                start_time=start_time,
                end_time=end_time
            )
            return {
                "agent_id": agent_id,
                "metrics": metrics,
                "count": len(metrics),
                "resolution": {
                    "table": "metrics",
                    "description": "Raw data (SQLite does not support aggregates)"
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch metrics: {str(e)}")


@app.get("/api/agents/{agent_id}/processes")
async def get_agent_processes(
    agent_id: str, 
    start_time: str = None, 
    end_time: str = None
):
    """
    Get process snapshots for a specific agent.
    
    If start_time and end_time are provided, returns all snapshots within that range.
    Otherwise, returns only the latest snapshot.
    
    Time format: ISO 8601 (e.g., "2024-12-26T10:00:00")
    """
    try:
        # If time range is specified, return historical snapshots
        if start_time and end_time:
            from datetime import datetime
            
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(
                    status_code=400, 
                    detail="Invalid time format. Use ISO 8601 format (e.g., '2024-12-26T10:00:00')"
                )
            
            snapshots = db_manager.get_process_snapshots_range(agent_id, start_dt, end_dt)
            
            if not snapshots:
                raise HTTPException(
                    status_code=404, 
                    detail=f"No process data found for agent {agent_id} in specified time range"
                )
            
            return {
                "agent_id": agent_id,
                "start_time": start_time,
                "end_time": end_time,
                "count": len(snapshots),
                "snapshots": snapshots
            }
        
        # Default behavior: return latest snapshot
        else:
            snapshot = db_manager.get_latest_process_snapshot(agent_id)
            
            if not snapshot:
                raise HTTPException(status_code=404, detail=f"No process data found for agent {agent_id}")
            
            return {
                "agent_id": agent_id,
                "timestamp": snapshot["timestamp"],
                "processes": snapshot["processes"],
                "created_at": snapshot["created_at"]
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch processes: {str(e)}")


@app.get("/api/logs")
async def get_logs(
    agent_id: str = None,
    level: str = None,
    search: str = None,
    limit: int = 50,
    offset: int = 0
):
    """
    Get logs with filtering and pagination
    
    Query Parameters:
    - agent_id: Filter by agent ID (optional - for future use)
    - level: Filter by log level (error, warning, info, debug)
    - search: Full-text search on log message
    - limit: Maximum number of results (default: 50)
    - offset: Offset for pagination (default: 0)
    
    Returns paginated logs with metadata
    """
    try:
        # Validate limit
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 500")
        
        # Validate offset
        if offset < 0:
            raise HTTPException(status_code=400, detail="Offset must be non-negative")
        
        result = db_manager.query_logs(
            agent_id=agent_id,
            level=level,
            search=search,
            limit=limit,
            offset=offset
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


# =====================
# Alert Management APIs
# =====================

class AlertRulesUpdate(BaseModel):
    monitor_uptime: bool = True
    cpu_percent_threshold: Optional[float] = None
    ram_percent_threshold: Optional[float] = None
    disk_free_percent_threshold: Optional[float] = None
    cpu_temp_threshold: Optional[float] = None
    network_bandwidth_mbps_threshold: Optional[float] = None


@app.get("/api/agents/{agent_id}/alert-rules")
async def get_alert_rules(agent_id: str):
    """Get alert rules for a specific agent"""
    try:
        rules = db_manager.get_alert_rules(agent_id)
        return rules
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch alert rules: {str(e)}")


@app.put("/api/agents/{agent_id}/alert-rules")
async def update_alert_rules(agent_id: str, rules: AlertRulesUpdate, user: dict = Depends(require_admin)):
    """Update alert rules for a specific agent"""
    try:
        updated_rules = db_manager.update_alert_rules(agent_id, rules.dict())
        return updated_rules
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update alert rules: {str(e)}")


@app.get("/api/agents/{agent_id}/alerts")
async def get_agent_alerts(agent_id: str, include_resolved: bool = False):
    """Get alerts for a specific agent"""
    try:
        if include_resolved:
            alerts = db_manager.get_alert_history(agent_id, limit=100)
        else:
            alerts = db_manager.get_active_alerts(agent_id)
        return {"agent_id": agent_id, "alerts": alerts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch alerts: {str(e)}")


@app.get("/api/alerts")
async def get_all_alerts(include_resolved: bool = False):
    """Get all alerts across all agents"""
    try:
        if include_resolved:
            alerts = db_manager.get_alert_history(limit=200)
        else:
            alerts = db_manager.get_active_alerts()
        return {"alerts": alerts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch alerts: {str(e)}")


@app.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int, user: dict = Depends(require_admin)):
    """Manually resolve an alert"""
    try:
        success = db_manager.resolve_alert_by_id(alert_id)
        if not success:
            raise HTTPException(status_code=404, detail="Alert not found or already resolved")
        return {"success": True, "message": f"Alert {alert_id} resolved"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve alert: {str(e)}")


# ==============================
# Notification Channel APIs
# ==============================

class NotificationChannelCreate(BaseModel):
    name: str
    channel_type: str = "custom"  # discord, slack, email, telegram, pushover, custom
    url: str
    events: List[str] = ["all"]  # all, agent_offline, cpu_high, ram_high, disk_low, bookmark_down, etc.

class NotificationChannelUpdate(BaseModel):
    name: Optional[str] = None
    channel_type: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None
    enabled: Optional[bool] = None


@app.get("/api/notifications/channels")
async def get_notification_channels():
    """Get all notification channels"""
    try:
        channels = db_manager.get_notification_channels()
        return {"channels": channels}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch channels: {str(e)}")


@app.post("/api/notifications/channels")
async def create_notification_channel(channel: NotificationChannelCreate, user: dict = Depends(require_admin)):
    """Create a new notification channel"""
    try:
        created = db_manager.create_notification_channel(
            name=channel.name,
            channel_type=channel.channel_type,
            url=channel.url,
            events=channel.events
        )
        return created
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create channel: {str(e)}")


@app.get("/api/notifications/channels/{channel_id}")
async def get_notification_channel(channel_id: int):
    """Get a specific notification channel"""
    try:
        channel = db_manager.get_notification_channel_by_id(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        return channel
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch channel: {str(e)}")


@app.put("/api/notifications/channels/{channel_id}")
async def update_notification_channel(channel_id: int, updates: NotificationChannelUpdate, 
                                      user: dict = Depends(require_admin)):
    """Update a notification channel"""
    try:
        updated = db_manager.update_notification_channel(channel_id, updates.dict(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Channel not found")
        return updated
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update channel: {str(e)}")


@app.delete("/api/notifications/channels/{channel_id}")
async def delete_notification_channel(channel_id: int, user: dict = Depends(require_admin)):
    """Delete a notification channel"""
    try:
        success = db_manager.delete_notification_channel(channel_id)
        if not success:
            raise HTTPException(status_code=404, detail="Channel not found")
        return {"success": True, "message": "Channel deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete channel: {str(e)}")


@app.post("/api/notifications/channels/{channel_id}/test")
async def test_notification_channel(channel_id: int, user: dict = Depends(require_admin)):
    """Send a test notification to a channel"""
    try:
        channel = db_manager.get_notification_channel_by_id(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        # Use notification manager to send test
        from notification_manager import NotificationManager, APPRISE_AVAILABLE
        
        if not APPRISE_AVAILABLE:
            raise HTTPException(status_code=503, detail="Apprise not installed - notifications unavailable")
        
        import apprise
        ap = apprise.Apprise()
        ap.add(channel["url"])
        
        success = await ap.async_notify(
            title="LogLibrarian Test Notification",
            body=f"This is a test notification from LogLibrarian.\n\nChannel: {channel['name']}\nTime: {datetime.utcnow().isoformat()}Z"
        )
        
        # Record in history
        db_manager.add_notification_history(
            channel_id=channel_id,
            event_type="test",
            title="Test Notification",
            body="Test notification sent",
            status="sent" if success else "failed"
        )
        
        if success:
            return {"success": True, "message": "Test notification sent successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send test notification")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send test: {str(e)}")


@app.get("/api/notifications/history")
async def get_notification_history(limit: int = 100):
    """Get notification history"""
    try:
        history = db_manager.get_notification_history(limit=limit)
        return {"history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")


# ==============================
# Alert Rules V2 APIs (Global/Agent/Bookmark/Profile)
# ==============================

class AlertRuleCreate(BaseModel):
    name: str
    scope: str  # global, agent, bookmark, profile
    metric: str  # cpu, ram, disk, status, response_time, ssl_expiry
    operator: str  # gt, lt, eq, ne, contains, gte, lte
    threshold: str
    target_id: Optional[str] = None  # Required for agent/bookmark scope
    description: Optional[str] = None
    channels: List[int] = []  # Channel IDs
    cooldown_minutes: int = 5
    profile_id: Optional[str] = None  # Required for profile scope
    profile_agents: Optional[List[str]] = []  # Agent IDs for profile scope
    profile_bookmarks: Optional[List[str]] = []  # Bookmark IDs for profile scope

class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scope: Optional[str] = None
    target_id: Optional[str] = None
    metric: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[str] = None
    channels: Optional[List[int]] = None
    cooldown_minutes: Optional[int] = None
    enabled: Optional[bool] = None
    profile_id: Optional[str] = None
    profile_agents: Optional[List[str]] = None
    profile_bookmarks: Optional[List[str]] = None

class AlertRuleOverride(BaseModel):
    override_type: str  # disable, modify
    modified_threshold: Optional[str] = None
    modified_channels: Optional[List[int]] = None


@app.get("/api/alerts/rules")
async def get_alert_rules_v2(scope: Optional[str] = None):
    """Get all alert rules, optionally filtered by scope"""
    try:
        rules = db_manager.get_alert_rules_v2(scope=scope)
        return {"rules": rules}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch rules: {str(e)}")


@app.get("/api/alerts/rules/global")
async def get_global_rules():
    """Get all global alert rules"""
    try:
        rules = db_manager.get_global_alert_rules()
        return {"rules": rules}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch global rules: {str(e)}")


@app.post("/api/alerts/rules")
async def create_alert_rule_v2(rule: AlertRuleCreate, user: dict = Depends(require_admin)):
    """Create a new alert rule"""
    try:
        # Validate scope and target_id
        if rule.scope in ["agent", "bookmark"] and not rule.target_id:
            raise HTTPException(status_code=400, detail=f"target_id required for {rule.scope} scope")
        
        if rule.scope == "profile" and not rule.profile_id:
            raise HTTPException(status_code=400, detail="profile_id required for profile scope")
        
        created = db_manager.create_alert_rule_v2(
            name=rule.name,
            scope=rule.scope,
            metric=rule.metric,
            operator=rule.operator,
            threshold=rule.threshold,
            target_id=rule.target_id,
            description=rule.description,
            channels=rule.channels,
            cooldown_minutes=rule.cooldown_minutes,
            profile_id=rule.profile_id,
            profile_agents=rule.profile_agents,
            profile_bookmarks=rule.profile_bookmarks
        )
        return created
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create rule: {str(e)}")


@app.get("/api/alerts/rules/{rule_id}")
async def get_alert_rule_v2(rule_id: int):
    """Get a specific alert rule"""
    try:
        rules = db_manager.get_alert_rules_v2()
        rule = next((r for r in rules if r["id"] == rule_id), None)
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        return rule
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch rule: {str(e)}")


@app.put("/api/alerts/rules/{rule_id}")
async def update_alert_rule_v2(rule_id: int, updates: AlertRuleUpdate, user: dict = Depends(require_admin)):
    """Update an alert rule"""
    try:
        updated = db_manager.update_alert_rule_v2(rule_id, updates.dict(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Rule not found")
        return updated
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update rule: {str(e)}")


@app.delete("/api/alerts/rules/{rule_id}")
async def delete_alert_rule_v2(rule_id: int, user: dict = Depends(require_admin)):
    """Delete an alert rule"""
    try:
        success = db_manager.delete_alert_rule_v2(rule_id)
        if not success:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"success": True, "message": "Rule deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete rule: {str(e)}")


# Effective rules for targets (with overrides applied)
@app.get("/api/agents/{agent_id}/effective-rules")
async def get_agent_effective_rules(agent_id: str):
    """Get all effective alert rules for an agent (global + specific, with overrides)"""
    try:
        rules = db_manager.get_effective_rules_for_target("agent", agent_id)
        overrides = db_manager.get_rule_overrides_for_target("agent", agent_id)
        return {"agent_id": agent_id, "rules": rules, "overrides": overrides}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch effective rules: {str(e)}")


@app.get("/api/bookmarks/{bookmark_id}/effective-rules")
async def get_bookmark_effective_rules(bookmark_id: str):
    """Get all effective alert rules for a bookmark (global + specific, with overrides)"""
    try:
        rules = db_manager.get_effective_rules_for_target("bookmark", bookmark_id)
        overrides = db_manager.get_rule_overrides_for_target("bookmark", bookmark_id)
        return {"bookmark_id": bookmark_id, "rules": rules, "overrides": overrides}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch effective rules: {str(e)}")


# Rule overrides
@app.post("/api/agents/{agent_id}/rule-overrides/{rule_id}")
async def set_agent_rule_override(agent_id: str, rule_id: int, override: AlertRuleOverride, 
                                  user: dict = Depends(require_admin)):
    """Set an override for a global rule on this agent"""
    try:
        success = db_manager.set_rule_override(
            rule_id=rule_id,
            target_type="agent",
            target_id=agent_id,
            override_type=override.override_type,
            modified_threshold=override.modified_threshold,
            modified_channels=override.modified_channels
        )
        if success:
            return {"success": True, "message": "Override set"}
        raise HTTPException(status_code=500, detail="Failed to set override")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set override: {str(e)}")


@app.delete("/api/agents/{agent_id}/rule-overrides/{rule_id}")
async def remove_agent_rule_override(agent_id: str, rule_id: int, user: dict = Depends(require_admin)):
    """Remove an override for a global rule on this agent"""
    try:
        success = db_manager.remove_rule_override(rule_id, "agent", agent_id)
        if success:
            return {"success": True, "message": "Override removed"}
        raise HTTPException(status_code=404, detail="Override not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove override: {str(e)}")


@app.post("/api/bookmarks/{bookmark_id}/rule-overrides/{rule_id}")
async def set_bookmark_rule_override(bookmark_id: str, rule_id: int, override: AlertRuleOverride,
                                     user: dict = Depends(require_admin)):
    """Set an override for a global rule on this bookmark"""
    try:
        success = db_manager.set_rule_override(
            rule_id=rule_id,
            target_type="bookmark",
            target_id=bookmark_id,
            override_type=override.override_type,
            modified_threshold=override.modified_threshold,
            modified_channels=override.modified_channels
        )
        if success:
            return {"success": True, "message": "Override set"}
        raise HTTPException(status_code=500, detail="Failed to set override")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set override: {str(e)}")


@app.delete("/api/bookmarks/{bookmark_id}/rule-overrides/{rule_id}")
async def remove_bookmark_rule_override(bookmark_id: str, rule_id: int, user: dict = Depends(require_admin)):
    """Remove an override for a global rule on this bookmark"""
    try:
        success = db_manager.remove_rule_override(rule_id, "bookmark", bookmark_id)
        if success:
            return {"success": True, "message": "Override removed"}
        raise HTTPException(status_code=404, detail="Override not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove override: {str(e)}")


# =========================
# Log Settings & Raw Logs
# =========================

class LogSettingsUpdate(BaseModel):
    logging_enabled: bool = True
    log_level_threshold: str = "ERROR"
    log_retention_days: int = 7
    watch_docker_containers: bool = False
    watch_system_logs: bool = True
    watch_security_logs: bool = True
    troubleshooting_mode: bool = False


class RawLogEntry(BaseModel):
    timestamp: str
    severity: str
    source: str
    message: str
    metadata: Optional[dict] = None


class RawLogBatch(BaseModel):
    logs: List[RawLogEntry]


@app.get("/api/agents/{agent_id}/log-settings")
async def get_log_settings(agent_id: str):
    """Get log settings for a specific agent"""
    try:
        settings = db_manager.get_log_settings(agent_id)
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch log settings: {str(e)}")


@app.put("/api/agents/{agent_id}/log-settings")
async def update_log_settings(agent_id: str, settings: LogSettingsUpdate, user: dict = Depends(require_admin)):
    """Update log settings for a specific agent"""
    try:
        updated = db_manager.update_log_settings(agent_id, settings.dict())
        return updated
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update log settings: {str(e)}")


@app.post("/api/agents/{agent_id}/logs")
async def ingest_agent_logs(agent_id: str, request: Request):
    """
    Ingest raw logs from an agent.
    Accepts GZIP-compressed JSON payloads.
    """
    try:
        # Check for GZIP encoding
        content_encoding = request.headers.get("Content-Encoding", "")
        body = await request.body()
        
        if content_encoding == "gzip":
            try:
                body = gzip.decompress(body)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to decompress GZIP: {str(e)}")
        
        # Parse JSON
        try:
            data = json.loads(body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
        
        # Validate and extract logs
        logs_data = data.get("logs", [])
        if not logs_data:
            return {"success": True, "message": "No logs to ingest", "count": 0}
        
        print(f"[DEBUG] Ingesting {len(logs_data)} logs for agent {agent_id}")
        if logs_data:
            print(f"[DEBUG] Sample log: {logs_data[0]}")
        
        result = db_manager.ingest_raw_logs(agent_id, logs_data)
        print(f"[DEBUG] Ingest result: {result}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest logs: {str(e)}")


@app.get("/api/agents/{agent_id}/raw-logs")
async def get_agent_raw_logs(
    agent_id: str,
    severity: str = None,
    source: str = None,
    start_time: str = None,
    end_time: str = None,
    search: str = None,
    limit: int = 100,
    offset: int = 0
):
    """Get raw logs for a specific agent with filtering"""
    try:
        result = db_manager.get_raw_logs(
            agent_id=agent_id,
            severity=severity,
            source=source,
            start_time=start_time,
            end_time=end_time,
            search=search,
            limit=limit,
            offset=offset
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch raw logs: {str(e)}")


@app.get("/api/raw-logs")
async def get_all_raw_logs(
    agent_id: str = None,
    agent_ids: str = None,
    severity: str = None,
    source: str = None,
    start_time: str = None,
    end_time: str = None,
    search: str = None,
    limit: int = 100,
    offset: int = 0
):
    """Get raw logs across all agents with filtering. 
    Supports agent_ids as comma-separated list for multi-device filtering."""
    try:
        # Parse agent_ids if provided (comma-separated)
        agent_id_list = None
        if agent_ids:
            agent_id_list = [aid.strip() for aid in agent_ids.split(',') if aid.strip()]
        
        result = db_manager.get_raw_logs(
            agent_id=agent_id,
            agent_ids=agent_id_list,
            severity=severity,
            source=source,
            start_time=start_time,
            end_time=end_time,
            search=search,
            limit=limit,
            offset=offset
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch raw logs: {str(e)}")


@app.get("/api/agents/{agent_id}/log-stats")
async def get_agent_log_stats(agent_id: str):
    """Get log statistics for a specific agent"""
    try:
        stats = db_manager.get_log_stats(agent_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch log stats: {str(e)}")


@app.post("/api/logs/reap")
async def trigger_log_reaper():
    """Manually trigger the log reaper (cleanup old logs)"""
    try:
        result = db_manager.reap_old_logs()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run log reaper: {str(e)}")


@app.post("/api/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    """
    Ask a question about the logs using AI
    
    TODO: Connect to Ollama LLM for intelligent answers
    """
    # Placeholder response
    return AskResponse(answer="AI Not Connected Yet")


@app.websocket("/ws/agent/{agent_id}")
@app.websocket("/api/ws/agent/{agent_id}")
async def websocket_agent_endpoint(websocket: WebSocket, agent_id: str):
    """
    WebSocket endpoint for agents to stream real-time metrics
    
    Agents connect here and continuously send metrics data.
    Data is buffered for efficient DB insertion and broadcast to watching UI clients.
    
    Connection limits:
    - Per-IP limit prevents accidental DoS
    - Total connection limit ensures server stability
    - Graceful rejection with Retry-After header
    
    Authentication:
    - Token validated on first message
    - New/legacy agents receive token in response
    - Invalid tokens cause connection termination
    """
    import time as time_module
    
    # Check connection limits and accept/reject
    success, reason, retry_after = await connection_manager.connect_agent(agent_id, websocket)
    
    if not success:
        # Connection rejected - send error and close
        try:
            await websocket.accept()
            await websocket.send_json({
                "error": "connection_limit",
                "reason": reason,
                "retry_after_seconds": retry_after,
                "message": f"Connection limit exceeded. Retry after {retry_after} seconds."
            })
            await websocket.close(code=1013)  # Try Again Later
        except:
            pass
        return
    
    # Track if we've authenticated this connection
    ws_authenticated = False
    
    try:
        while True:
            # Receive data from agent
            handler_start = time_module.time()
            data = await websocket.receive_text()
            data_size = len(data.encode())
            
            # Record message for statistics
            connection_manager.record_message(agent_id, data_size)
            connection_manager.update_heartbeat(agent_id)
            
            try:
                message = json.loads(data)
                
                # Check if it's a heartbeat payload
                if "metrics" in message and "status" in message:
                    # Validate instance API key on first message
                    if not ws_authenticated:
                        provided_key = message.get('auth_token') or message.get('api_key')
                        is_valid, auth_reason = validate_scribe_api_key(provided_key)
                        
                        if not is_valid:
                            print(f"🔒 WebSocket auth failed for agent {agent_id}: {auth_reason}")
                            await websocket.send_json({
                                "error": "auth_failed",
                                "reason": auth_reason,
                                "message": "Invalid API key. Check your scribe configuration."
                            })
                            await websocket.close(code=4001)  # Custom close code for auth failure
                            return
                        
                        ws_authenticated = True
                        print(f"✅ WebSocket: Authenticated agent {agent_id}")
                    
                    # Debug: Check raw system_info before parsing
                    if "system_info" in message:
                        print(f"DEBUG: Raw system_info present in message: {type(message['system_info'])}, keys={list(message['system_info'].keys()) if message['system_info'] else 'None'}")
                    else:
                        print(f"DEBUG: No system_info key in raw message")
                    
                    # Parse into HeartbeatPayload
                    payload = HeartbeatPayload(**message)
                    
                    # Debug: log connection_address from payload
                    conn_addr = getattr(payload, 'connection_address', '')
                    if conn_addr:
                        print(f"Agent {payload.agent_id} connection_address: {conn_addr}")
                    
                    # Store in database using buffered insertion
                    try:
                        # Upsert agent information with public IP and connection address
                        db_manager.upsert_agent(
                            agent_id=payload.agent_id,
                            hostname=payload.hostname,
                            status=payload.status,
                            last_seen=payload.last_seen_at,
                            public_ip=payload.public_ip,
                            connection_address=getattr(payload, 'connection_address', '')
                        )
                        
                        # Prepare metrics data for buffered insertion
                        metrics_data = [
                            {
                                "timestamp": metric.timestamp.isoformat() if hasattr(metric.timestamp, 'isoformat') else str(metric.timestamp),
                                "cpu_percent": metric.cpu_percent,
                                "ram_percent": metric.ram_percent,
                                "net_sent_bps": metric.net_sent_bps,
                                "net_recv_bps": metric.net_recv_bps,
                                "disk_read_bps": metric.disk_read_bps,
                                "disk_write_bps": metric.disk_write_bps,
                                "ping_latency_ms": metric.ping_latency_ms,
                                "cpu_temp": metric.cpu_temp,
                                "cpu_name": metric.cpu_name,
                                "gpu_percent": metric.gpu_percent,
                                "gpu_temp": metric.gpu_temp,
                                "gpu_name": metric.gpu_name,
                                "is_vm": metric.is_vm,
                                "disks": [disk.dict() for disk in metric.disks]
                            }
                            for metric in payload.metrics
                        ]
                        
                        # Route metrics through Redis queue if available, else direct to buffer
                        if metrics_data:
                            if redis_queue and redis_queue.is_connected:
                                # Push to Redis stream for async processing
                                await redis_queue.publish_metrics(
                                    agent_id=payload.agent_id,
                                    metrics=metrics_data,
                                    load_avg=payload.load_avg
                                )
                            elif metrics_buffer:
                                # Direct to metrics buffer if Redis unavailable
                                await metrics_buffer.add_metrics(
                                    agent_id=payload.agent_id,
                                    metrics=metrics_data,
                                    load_avg=payload.load_avg
                                )
                        
                        # Insert process snapshot if processes are provided
                        if payload.processes:
                            process_data = [proc.dict() for proc in payload.processes]
                            db_manager.insert_process_snapshot(
                                agent_id=payload.agent_id,
                                timestamp=payload.last_seen_at,
                                processes=process_data
                            )
                        
                        # Update system info if provided (sent periodically by agent)
                        if payload.system_info:
                            print(f"DEBUG: Received system_info for {payload.agent_id}: OS={payload.system_info.os}, CPU={payload.system_info.cpu_model}")
                            # Convert system_info to dict and handle datetime serialization
                            system_info_dict = payload.system_info.dict()
                            # Convert datetime objects to ISO strings for JSON storage
                            if 'collected_at' in system_info_dict and system_info_dict['collected_at']:
                                system_info_dict['collected_at'] = system_info_dict['collected_at'].isoformat()
                            db_manager.update_agent_system_info(
                                agent_id=payload.agent_id,
                                system_info=system_info_dict
                            )
                        else:
                            print(f"DEBUG: No system_info in payload for {payload.agent_id}")
                        
                        # Evaluate metrics against alert rules (use latest metric)
                        if payload.metrics:
                            latest_metric = payload.metrics[-1]
                            try:
                                db_manager.evaluate_metrics(
                                    agent_id=payload.agent_id,
                                    metrics={
                                        "cpu_percent": latest_metric.cpu_percent,
                                        "ram_percent": latest_metric.ram_percent,
                                        "net_up": latest_metric.net_sent_bps,
                                        "net_down": latest_metric.net_recv_bps,
                                        "cpu_temp": latest_metric.cpu_temp,
                                        "disks": [disk.dict() for disk in latest_metric.disks]
                                    }
                                )
                            except Exception as alert_err:
                                print(f"Alert evaluation error: {alert_err}")
                    except Exception as e:
                        print(f"Error storing WebSocket data: {e}")
                    
                    # Broadcast latest metric to watching UI clients (flatten structure)
                    if payload.metrics:
                        latest_metric = payload.metrics[-1]  # Get most recent metric
                        ui_message = {
                            "timestamp": latest_metric.timestamp.isoformat(),
                            "cpu_percent": latest_metric.cpu_percent,
                            "ram_percent": latest_metric.ram_percent,
                            "net_up": latest_metric.net_sent_bps,
                            "net_down": latest_metric.net_recv_bps,
                            "disk_read": latest_metric.disk_read_bps,
                            "disk_write": latest_metric.disk_write_bps,
                            "ping": latest_metric.ping_latency_ms,
                            "cpu_temp": latest_metric.cpu_temp,
                            "cpu_name": latest_metric.cpu_name,
                            "gpu_percent": latest_metric.gpu_percent,
                            "gpu_temp": latest_metric.gpu_temp,
                            "gpu_name": latest_metric.gpu_name,
                            "is_vm": latest_metric.is_vm,
                            "disks": [disk.dict() for disk in latest_metric.disks] if latest_metric.disks else [],
                            "load_avg": payload.load_avg,
                            "processes": [proc.dict() for proc in payload.processes] if payload.processes else []
                        }
                        await connection_manager.broadcast_to_clients(agent_id, ui_message)
                else:
                    print(f"Received non-heartbeat message from agent {agent_id}: {message}")
                
            except json.JSONDecodeError:
                print(f"Invalid JSON from agent {agent_id}")
            except Exception as e:
                print(f"Error processing agent data: {e}")
            
            # Log slow handlers
            handler_duration = (time_module.time() - handler_start) * 1000
            if handler_duration > SLOW_HANDLER_THRESHOLD_MS:
                connection_manager.record_slow_handler(agent_id, handler_duration, "agent_handler")
    
    except WebSocketDisconnect:
        connection_manager.disconnect_agent(agent_id)
    except Exception as e:
        print(f"WebSocket error for agent {agent_id}: {e}")
        connection_manager.disconnect_agent(agent_id)


@app.websocket("/api/ws/ui/{agent_id}")
async def websocket_ui_endpoint(websocket: WebSocket, agent_id: str):
    """
    WebSocket endpoint for UI clients to receive real-time agent data
    
    UI connects here when viewing agent details.
    Sends start_stream command to agent on connect.
    Sends stop_stream command to agent on disconnect.
    
    Connection limits applied same as agent connections.
    """
    # Check connection limits and accept/reject
    success, reason, retry_after = await connection_manager.connect_client(agent_id, websocket)
    
    if not success:
        try:
            await websocket.accept()
            await websocket.send_json({
                "error": "connection_limit",
                "reason": reason,
                "retry_after_seconds": retry_after,
                "message": f"Connection limit exceeded. Retry after {retry_after} seconds."
            })
            await websocket.close(code=1013)
        except:
            pass
        return
    
    try:
        while True:
            # Keep connection alive and handle any incoming messages
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                
                # Handle UI commands (e.g., refresh, change interval, etc.)
                if "command" in message:
                    command = message["command"]
                    print(f"UI command for agent {agent_id}: {command}")
                    
                    # Forward commands to agent if needed
                    if agent_id in connection_manager.agents:
                        await connection_manager.agents[agent_id].websocket.send_json(message)
            
            except json.JSONDecodeError:
                print(f"Invalid JSON from UI client for agent {agent_id}")
    
    except WebSocketDisconnect:
        connection_manager.disconnect_client(agent_id, websocket)
    except Exception as e:
        print(f"WebSocket error for UI client watching {agent_id}: {e}")
        connection_manager.disconnect_client(agent_id, websocket)


@app.get("/api/ws/status/{agent_id}")
async def get_websocket_status(agent_id: str):
    """Get WebSocket connection status for an agent"""
    status = connection_manager.get_agent_status(agent_id)
    return {
        "agent_id": agent_id,
        "agent_connected": status["agent_connected"],
        "clients_watching": status["clients_watching"]
    }


# =============================================================================
# BOOKMARK / UPTIME MONITORING ENDPOINTS
# =============================================================================

class MonitorGroupCreate(BaseModel):
    name: str
    weight: int = 0

class MonitorGroupUpdate(BaseModel):
    name: Optional[str] = None
    weight: Optional[int] = None

class BookmarkCreate(BaseModel):
    group_id: Optional[str] = None
    name: str
    type: str  # "http", "icmp", "tcp-port"
    target: str  # URL or IP address
    port: Optional[int] = None  # For tcp-port type
    interval_seconds: int = 60
    timeout_seconds: int = 30
    max_retries: int = 1
    retry_interval: int = 30
    resend_notification: int = 0
    upside_down: bool = False
    method: str = "GET"
    active: bool = True
    tags: Optional[str] = None
    description: Optional[str] = None

class BookmarkUpdate(BaseModel):
    group_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    target: Optional[str] = None
    port: Optional[int] = None
    interval_seconds: Optional[int] = None
    timeout_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    retry_interval: Optional[int] = None
    resend_notification: Optional[int] = None
    upside_down: Optional[bool] = None
    method: Optional[str] = None
    active: Optional[bool] = None
    tags: Optional[str] = None
    description: Optional[str] = None


@app.get("/api/bookmarks/tree")
async def get_bookmarks_tree(
    request: Request,
    x_tenant_id: str = Header(default="default")
):
    """
    Get all bookmarks organized by groups with current status.
    Returns a tree structure: groups -> bookmarks -> latest check
    Filtered by user's role and profile.
    """
    try:
        # Check if user is authenticated and filter accordingly
        current_user = await get_current_user(request)
        if current_user:
            tree = db_manager.get_bookmarks_tree_for_user(current_user)
        else:
            # Unauthenticated - use tenant-based filtering (backward compatibility)
            tree = db_manager.get_bookmarks_tree(x_tenant_id)
        return {"success": True, "data": tree}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookmarks/groups")
async def get_monitor_groups(x_tenant_id: str = Header(default="default")):
    """Get all monitor groups"""
    try:
        groups = db_manager.get_monitor_groups(x_tenant_id)
        return {"success": True, "data": groups}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bookmarks/groups")
async def create_monitor_group(
    group: MonitorGroupCreate,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Create a new monitor group"""
    try:
        new_group = db_manager.create_monitor_group(x_tenant_id, group.name, group.weight)
        return {"success": True, "id": new_group["id"], "group": new_group}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/bookmarks/groups/{group_id}")
async def update_monitor_group(
    group_id: int,
    group: MonitorGroupUpdate,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Update a monitor group"""
    try:
        updates = {k: v for k, v in group.dict().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        db_manager.update_monitor_group(x_tenant_id, group_id, **updates)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/bookmarks/groups/{group_id}")
async def delete_monitor_group(
    group_id: str,
    delete_monitors: bool = False,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Delete a monitor group. If delete_monitors is true, delete all monitors in the group.
    Otherwise, monitors are moved to ungrouped."""
    try:
        db_manager.delete_monitor_group(x_tenant_id, group_id, delete_monitors=delete_monitors)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookmarks")
async def get_bookmarks(
    request: Request,
    group_id: Optional[str] = None,
    x_tenant_id: str = Header(default="default")
):
    """Get all bookmarks (filtered by user's role and profile).
    - Admin: sees all bookmarks
    - User: sees only bookmarks in their assigned profile's scope
    """
    try:
        # Check if user is authenticated
        current_user = await get_current_user(request)
        if current_user:
            # Use RBAC-filtered method
            bookmarks = db_manager.get_bookmarks_for_user(current_user)
            # Apply group filter if specified
            if group_id:
                bookmarks = [b for b in bookmarks if b.get("group_id") == group_id]
        else:
            # Unauthenticated - use tenant-based filtering (backward compatibility)
            bookmarks = db_manager.get_bookmarks(x_tenant_id, group_id)
        return {"success": True, "data": bookmarks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bookmarks/{bookmark_id}")
async def get_bookmark(
    bookmark_id: str,
    limit: int = 60,
    x_tenant_id: str = Header(default="default")
):
    """Get a bookmark with its recent check history"""
    try:
        bookmark = db_manager.get_bookmark_with_checks(x_tenant_id, bookmark_id, limit)
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        return {"success": True, "data": bookmark}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bookmarks")
async def create_bookmark(
    request: Request,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Create a new bookmark"""
    try:
        # Parse raw body for debugging
        raw_body = await request.json()
        print(f"📥 Create bookmark request: {raw_body}")
        
        # Manually validate with Pydantic
        try:
            bookmark = BookmarkCreate(**raw_body)
        except Exception as validation_error:
            print(f"❌ Validation error: {validation_error}")
            raise HTTPException(status_code=422, detail=str(validation_error))
        
        # Validate type
        if bookmark.type not in ("http", "icmp", "tcp-port"):
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'http', 'icmp', or 'tcp-port'")
        
        # Validate tcp-port requires port
        if bookmark.type == "tcp-port" and not bookmark.port:
            raise HTTPException(status_code=400, detail="Port is required for tcp-port type")
        
        new_bookmark = db_manager.create_bookmark(
            tenant_id=x_tenant_id,
            group_id=bookmark.group_id,
            name=bookmark.name,
            type=bookmark.type,
            target=bookmark.target,
            port=bookmark.port,
            interval_seconds=bookmark.interval_seconds,
            timeout_seconds=bookmark.timeout_seconds,
            max_retries=bookmark.max_retries,
            retry_interval=bookmark.retry_interval,
            resend_notification=bookmark.resend_notification,
            upside_down=bookmark.upside_down,
            active=bookmark.active,
            tags=bookmark.tags,
            description=bookmark.description
        )
        
        # Notify monitor to pick up the new bookmark
        if bookmark_monitor and bookmark.active:
            await bookmark_monitor.sync_bookmarks()
        
        return {"success": True, "id": new_bookmark["id"], "bookmark": new_bookmark}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/bookmarks/{bookmark_id}")
async def update_bookmark(
    bookmark_id: str,
    request: Request,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Update a bookmark"""
    try:
        # Get raw JSON to see what was actually sent
        raw_json = await request.json()
        print(f"📝 Update bookmark {bookmark_id}: {raw_json}")
        
        # Only include fields that were explicitly sent
        updates = {}
        allowed_fields = ['group_id', 'name', 'type', 'target', 'port', 'interval_seconds', 
                          'timeout_seconds', 'max_retries', 'retry_interval', 'resend_notification',
                          'upside_down', 'method', 'active', 'tags', 'description']
        
        for field in allowed_fields:
            if field in raw_json:
                updates[field] = raw_json[field]
        
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Validate type if provided
        if "type" in updates and updates["type"] not in ("http", "icmp", "tcp-port"):
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'http', 'icmp', or 'tcp-port'")
        
        db_manager.update_bookmark(x_tenant_id, bookmark_id, **updates)
        
        # Notify monitor to sync changes
        if bookmark_monitor:
            await bookmark_monitor.sync_bookmarks()
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/bookmarks/{bookmark_id}")
async def delete_bookmark(
    bookmark_id: str,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Delete a bookmark and its check history"""
    try:
        db_manager.delete_bookmark(x_tenant_id, bookmark_id)
        
        # Notify monitor to remove the bookmark
        if bookmark_monitor:
            await bookmark_monitor.sync_bookmarks()
        
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bookmarks/{bookmark_id}/check")
async def trigger_bookmark_check(
    bookmark_id: str,
    x_tenant_id: str = Header(default="default")
):
    """Manually trigger an immediate health check for a bookmark"""
    try:
        # Get the bookmark
        bookmark = db_manager.get_bookmark_with_checks(x_tenant_id, bookmark_id, limit=1)
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        
        # Perform the check using the monitor
        if not bookmark_monitor:
            raise HTTPException(status_code=503, detail="Bookmark monitor not initialized")
        
        result = await bookmark_monitor.perform_check(bookmark)
        
        # Record the result
        db_manager.record_bookmark_check(
            bookmark_id=bookmark_id,
            status=result.status,
            latency_ms=result.latency_ms,
            message=result.message
        )
        
        return {
            "success": True,
            "result": {
                "status": result.status,
                "latency_ms": result.latency_ms,
                "message": result.message
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookmarks/{bookmark_id}/history")
async def get_bookmark_history(
    bookmark_id: str,
    hours: int = 24,
    x_tenant_id: str = Header(default="default")
):
    """Get check history for a bookmark within time range"""
    try:
        checks = db_manager.get_bookmark_checks_range(x_tenant_id, bookmark_id, hours)
        
        # Calculate uptime percentage
        if checks:
            up_count = sum(1 for c in checks if c["status"] == 1)
            uptime_percent = round((up_count / len(checks)) * 100, 2)
            avg_latency = round(sum(c["latency_ms"] for c in checks if c["status"] == 1) / max(up_count, 1), 2)
        else:
            uptime_percent = None
            avg_latency = None
        
        return {
            "success": True,
            "data": {
                "checks": checks,
                "total_checks": len(checks),
                "uptime_percent": uptime_percent,
                "avg_latency_ms": avg_latency
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookmarks/status/summary")
async def get_bookmarks_summary(x_tenant_id: str = Header(default="default")):
    """Get a summary of all bookmarks status"""
    try:
        bookmarks = db_manager.get_bookmarks(x_tenant_id)
        
        total = len(bookmarks)
        up = 0
        down = 0
        unknown = 0
        
        for b in bookmarks:
            if not b.get("active"):
                continue
            latest = b.get("latest_check")
            if latest is None:
                unknown += 1
            elif latest.get("status") == 1:
                up += 1
            else:
                down += 1
        
        return {
            "success": True,
            "data": {
                "total": total,
                "up": up,
                "down": down,
                "unknown": unknown
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== REPORT PROFILES API ====================

@app.get("/api/report-profiles")
async def get_report_profiles(x_tenant_id: str = Header(default="default")):
    """Get all report profiles for the tenant"""
    try:
        profiles = db_manager.get_report_profiles(x_tenant_id)
        return {"success": True, "data": profiles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report-profiles/{profile_id}")
async def get_report_profile(
    profile_id: str,
    x_tenant_id: str = Header(default="default")
):
    """Get a specific report profile by ID"""
    try:
        profile = db_manager.get_report_profile(x_tenant_id, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Report profile not found")
        return {"success": True, "data": profile}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/report-profiles")
async def create_report_profile(
    profile: ReportProfileCreate,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Create a new report profile"""
    try:
        new_profile = db_manager.create_report_profile(
            tenant_id=x_tenant_id,
            name=profile.name,
            description=profile.description,
            frequency=profile.frequency.value if profile.frequency else "MONTHLY",
            sla_target=profile.sla_target if profile.sla_target is not None else 99.9,
            schedule_hour=profile.schedule_hour if profile.schedule_hour is not None else 7,
            recipient_emails=profile.recipient_emails,
            monitor_scope_tags=profile.monitor_scope_tags,
            monitor_scope_ids=profile.monitor_scope_ids,
            scribe_scope_tags=profile.scribe_scope_tags,
            scribe_scope_ids=profile.scribe_scope_ids
        )
        return {"success": True, "id": new_profile["id"], "data": new_profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/report-profiles/{profile_id}")
async def update_report_profile(
    profile_id: str,
    profile: ReportProfileUpdate,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Update a report profile"""
    try:
        # Build update dict from provided fields only
        updates = {}
        if profile.name is not None:
            updates["name"] = profile.name
        if profile.description is not None:
            updates["description"] = profile.description
        if profile.frequency is not None:
            updates["frequency"] = profile.frequency.value
        if profile.sla_target is not None:
            updates["sla_target"] = profile.sla_target
        if profile.schedule_hour is not None:
            updates["schedule_hour"] = profile.schedule_hour
        if profile.recipient_emails is not None:
            updates["recipient_emails"] = profile.recipient_emails
        if profile.monitor_scope_tags is not None:
            updates["monitor_scope_tags"] = profile.monitor_scope_tags
        if profile.monitor_scope_ids is not None:
            updates["monitor_scope_ids"] = profile.monitor_scope_ids
        if profile.scribe_scope_tags is not None:
            updates["scribe_scope_tags"] = profile.scribe_scope_tags
        if profile.scribe_scope_ids is not None:
            updates["scribe_scope_ids"] = profile.scribe_scope_ids
        
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        updated_profile = db_manager.update_report_profile(x_tenant_id, profile_id, **updates)
        if not updated_profile:
            raise HTTPException(status_code=404, detail="Report profile not found")
        
        return {"success": True, "data": updated_profile}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/report-profiles/{profile_id}")
async def delete_report_profile(
    profile_id: str,
    x_tenant_id: str = Header(default="default"),
    user: dict = Depends(require_admin)
):
    """Delete a report profile and all its stored reports"""
    try:
        deleted = db_manager.delete_report_profile(x_tenant_id, profile_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Report profile not found")
        return {"success": True, "message": "Profile and all stored reports deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report-profiles/{profile_id}/reports")
async def get_profile_stored_reports(
    profile_id: str,
    x_tenant_id: str = Header(default="default")
):
    """Get all stored reports for a profile from file storage"""
    try:
        # Verify profile belongs to tenant
        profile = db_manager.get_report_profile(x_tenant_id, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Report profile not found")
        
        reports = db_manager.get_profile_reports(profile_id)
        return {"success": True, "reports": reports, "count": len(reports)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report-profiles/{profile_id}/reports/{report_id}/pdf")
async def get_profile_report_pdf(
    profile_id: str,
    report_id: str,
    x_tenant_id: str = Header(default="default")
):
    """Download PDF for a specific report"""
    try:
        # Verify profile belongs to tenant
        profile = db_manager.get_report_profile(x_tenant_id, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Report profile not found")
        
        pdf_content = db_manager.get_profile_report_pdf(profile_id, report_id)
        if not pdf_content:
            raise HTTPException(status_code=404, detail="PDF not found for this report")
        
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={profile['name']}_{report_id}.pdf"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/trigger-profile-reports")
async def trigger_profile_reports(user: dict = Depends(require_admin)):
    """Manually trigger scheduled profile reports (for testing/admin)"""
    try:
        if report_scheduler:
            await report_scheduler.trigger_profile_reports_now()
            return {"success": True, "message": "Profile report generation triggered"}
        else:
            return {"success": False, "message": "Report scheduler not initialized"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/report-profiles/{profile_id}/generate-stats")
async def generate_stat_report(
    profile_id: str,
    days: int = 30,
    user: dict = Depends(require_admin),
    x_tenant_id: str = Header(default="default")
):
    """
    Generate a Stat Report for a profile.
    
    This creates a stats-based report showing:
    - Bookmark uptime percentages
    - Average response times
    - Incident counts
    - Scribe uptime percentages
    - Log volume and severity breakdown
    """
    try:
        from datetime import timedelta, timezone
        
        # Get profile
        profile = db_manager.get_report_profile(x_tenant_id, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Report profile not found")
        
        # Calculate date range (timezone-aware for PostgreSQL compatibility)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        sla_target = profile.get("sla_target", 99.9)
        
        # Get scoped bookmarks
        all_bookmarks = db_manager.get_bookmarks(x_tenant_id)
        active_bookmarks = [b for b in all_bookmarks if b.get("active", True)]
        
        scope_ids = profile.get("monitor_scope_ids") or []
        scope_tags = profile.get("monitor_scope_tags") or []
        
        if scope_ids or scope_tags:
            filtered_bookmarks = []
            for b in active_bookmarks:
                if b.get("id") in scope_ids:
                    filtered_bookmarks.append(b)
                    continue
                bookmark_tags = b.get("tags") or []
                if isinstance(bookmark_tags, str):
                    bookmark_tags = [t.strip() for t in bookmark_tags.split(",") if t.strip()]
                if any(t in scope_tags for t in bookmark_tags):
                    filtered_bookmarks.append(b)
            active_bookmarks = filtered_bookmarks if filtered_bookmarks else active_bookmarks
        
        # Get scoped scribes
        all_agents = db_manager.get_all_agents()
        scribe_scope_ids = profile.get("scribe_scope_ids") or []
        scribe_scope_tags = profile.get("scribe_scope_tags") or []
        
        if scribe_scope_ids or scribe_scope_tags:
            filtered_scribes = []
            for agent in all_agents:
                agent_id = agent.get("agent_id")
                if agent_id in scribe_scope_ids:
                    filtered_scribes.append(agent)
                    continue
                agent_tags = agent.get("tags") or []
                if isinstance(agent_tags, str):
                    agent_tags = [t.strip() for t in agent_tags.split(",") if t.strip()]
                if any(t in scribe_scope_tags for t in agent_tags):
                    filtered_scribes.append(agent)
            active_scribes = filtered_scribes if filtered_scribes else all_agents
        else:
            active_scribes = all_agents
        
        # Calculate bookmark stats
        monitors_summary = []
        total_uptime_sum = 0
        total_monitors_with_data = 0
        total_incidents = 0
        
        for bookmark in active_bookmarks:
            bookmark_id = bookmark["id"]
            uptime_data = db_manager.calculate_bookmark_uptime(bookmark_id, start_date, end_date)
            
            type_display = {
                "http": "Web Service",
                "icmp": "Network Connectivity", 
                "tcp-port": "Service Port"
            }.get(bookmark.get("type", "http"), "Service")
            
            current_status = bookmark.get("last_status")
            status_display = "Service Available" if current_status == 1 else (
                "Service Unavailable" if current_status == 0 else "Pending"
            )
            
            uptime_pct = uptime_data.get("uptime_percentage")
            if uptime_pct is not None:
                total_uptime_sum += uptime_pct
                total_monitors_with_data += 1
            
            total_incidents += uptime_data.get("incidents", 0)
            
            monitors_summary.append({
                "name": bookmark["name"],
                "type": type_display,
                "uptime_percent": uptime_pct,
                "avg_response_ms": uptime_data.get("avg_response_ms"),
                "incidents": uptime_data.get("incidents", 0),
                "checks_count": uptime_data.get("total_checks", 0),
                "current_status": status_display,
                "health": uptime_data.get("status", "no_data")
            })
        
        # Calculate scribe stats with log counts
        scribes_summary = []
        
        # Get log counts per agent for the period
        agent_log_counts = {}
        try:
            log_counts_result = db_manager.pool.fetchall("""
                SELECT agent_id, COUNT(*) as log_count
                FROM raw_logs
                WHERE created_at >= %s AND created_at <= %s
                GROUP BY agent_id
            """, (start_date, end_date))
            for row in log_counts_result:
                agent_log_counts[row['agent_id']] = int(row['log_count'])
        except Exception as e:
            print(f"[DEBUG] Error getting per-agent log counts: {e}")
        
        for agent in active_scribes:
            agent_id = agent.get("agent_id")
            display_name = agent.get("display_name") or agent.get("hostname") or agent_id
            
            # Get OS - try dedicated column first, fallback to system_info JSON
            agent_os = agent.get("os", "")
            if not agent_os and agent.get("system_info"):
                system_info = agent.get("system_info")
                if isinstance(system_info, dict):
                    agent_os = system_info.get("os", "")
            if not agent_os:
                agent_os = "Unknown"
            
            try:
                uptime_data = db_manager.calculate_agent_uptime(
                    agent_id=agent_id,
                    start_date=start_date,
                    end_date=end_date,
                    heartbeat_ttl_seconds=120
                )
                uptime_pct = uptime_data.get("uptime_percentage")
            except Exception as e:
                print(f"[DEBUG] Error calculating uptime for {agent_id}: {e}")
                uptime_pct = None
            
            # Determine health status based on online status and uptime
            current_status = agent.get("status", "unknown")
            if current_status == "offline":
                health_status = "offline"
            elif uptime_pct is not None and uptime_pct >= 99:
                health_status = "healthy"
            elif uptime_pct is not None:
                health_status = "unhealthy"
            else:
                health_status = "unknown"
            
            # Include scribe uptime in global calculation
            if uptime_pct is not None:
                total_uptime_sum += uptime_pct
                total_monitors_with_data += 1
            
            scribes_summary.append({
                "name": display_name,
                "agent_id": agent_id,
                "status": current_status,
                "health": health_status,
                "os": agent_os,
                "log_count": agent_log_counts.get(agent_id, 0),
                "uptime_percent": round(uptime_pct, 1) if uptime_pct is not None else None
            })
        
        # Calculate overall uptime
        global_uptime = round(total_uptime_sum / total_monitors_with_data, 2) if total_monitors_with_data > 0 else None
        sla_status = "MEETING" if global_uptime and global_uptime >= sla_target else (
            "AT_RISK" if global_uptime and global_uptime >= sla_target - 1 else "BELOW"
        ) if global_uptime else "NO_DATA"
        
        # Get log statistics (if using postgres with raw_logs table)
        # Filter by scoped scribes if there are any
        scoped_agent_ids = [a.get('agent_id') for a in active_scribes if a.get('agent_id')]
        
        log_stats = {
            "total_logs": 0,
            "critical_events": 0,
            "error_events": 0,
            "warning_events": 0,
            "info_events": 0
        }
        try:
            print(f"[DEBUG] Log query date range: {start_date} to {end_date}")
            print(f"[DEBUG] Scoped agent_ids: {scoped_agent_ids}")
            
            if scoped_agent_ids:
                # Query logs only for scoped scribes
                placeholders = ','.join(['%s'] * len(scoped_agent_ids))
                log_counts = db_manager.pool.fetchone(f"""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN severity IN ('critical', 'crit', 'emerg', 'emergency', 'alert', 'CRITICAL') THEN 1 ELSE 0 END) as critical,
                        SUM(CASE WHEN severity IN ('error', 'err', 'ERROR') THEN 1 ELSE 0 END) as errors,
                        SUM(CASE WHEN severity IN ('warning', 'warn', 'WARNING') THEN 1 ELSE 0 END) as warnings,
                        SUM(CASE WHEN severity IN ('info', 'information', 'INFO', 'notice', 'NOTICE', 'debug', 'DEBUG') THEN 1 ELSE 0 END) as infos
                    FROM raw_logs
                    WHERE created_at >= %s AND created_at <= %s
                    AND agent_id IN ({placeholders})
                """, (start_date, end_date, *scoped_agent_ids))
            else:
                # No scribe scope - count all logs
                log_counts = db_manager.pool.fetchone("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN severity IN ('critical', 'crit', 'emerg', 'emergency', 'alert', 'CRITICAL') THEN 1 ELSE 0 END) as critical,
                        SUM(CASE WHEN severity IN ('error', 'err', 'ERROR') THEN 1 ELSE 0 END) as errors,
                        SUM(CASE WHEN severity IN ('warning', 'warn', 'WARNING') THEN 1 ELSE 0 END) as warnings,
                        SUM(CASE WHEN severity IN ('info', 'information', 'INFO', 'notice', 'NOTICE', 'debug', 'DEBUG') THEN 1 ELSE 0 END) as infos
                    FROM raw_logs
                    WHERE created_at >= %s AND created_at <= %s
                """, (start_date, end_date))
                
            print(f"[DEBUG] Log counts result: {log_counts}")
            if log_counts:
                log_stats["total_logs"] = int(log_counts['total'] or 0)
                log_stats["critical_events"] = int(log_counts['critical'] or 0)
                log_stats["error_events"] = int(log_counts['errors'] or 0)
                log_stats["warning_events"] = int(log_counts['warnings'] or 0)
                log_stats["info_events"] = int(log_counts['infos'] or 0)
            print(f"[DEBUG] Final log_stats: {log_stats}")
        except Exception as e:
            print(f"[DEBUG] Error getting log stats: {e}")
        
        # Build report data
        report_data = {
            "profile_id": profile_id,
            "profile_name": profile.get("name", "Unknown"),
            "report_type": "stat_report",
            "generated_at": datetime.utcnow().isoformat(),
            "period": {
                "days": days,
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "summary": {
                "global_uptime_percent": global_uptime,
                "sla_target": sla_target,
                "sla_status": sla_status,
                "total_monitors": len(monitors_summary),
                "total_scribes": len(scribes_summary),
                "total_incidents": total_incidents
            },
            "monitors": monitors_summary,
            "scribes": scribes_summary,
            "logs": log_stats
        }
        
        # Store the report in ai_reports table with profile_id in metadata
        report_id = db_manager.save_ai_report(
            report_type="stat_report",
            title=f"Stat Report - {profile.get('name', 'Unknown')} - {datetime.utcnow().strftime('%Y-%m-%d')}",
            content=json.dumps(report_data, indent=2),
            metadata={"profile_id": profile_id, "report_data": report_data}
        )
        
        return {
            "success": True,
            "report_id": report_id,
            "data": report_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/executive-summary")
async def get_executive_summary(
    days: int = 30,
    sla_target: float = 99.9,
    profile_id: str = None,
    x_tenant_id: str = Header(default="default")
):
    """
    Generate an Executive Summary report for business stakeholders.
    Focuses on high-level availability metrics and proof of value.
    Optionally scope to a specific report profile.
    """
    try:
        from datetime import timedelta
        import sqlite3
        
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        total_minutes = days * 24 * 60
        
        # Get profile if specified
        profile = None
        profile_name = "All Services"
        if profile_id:
            profile = db_manager.get_report_profile(x_tenant_id, profile_id)
            if profile:
                profile_name = profile.get("name", "Custom Profile")
                # Use profile's SLA target if set
                if profile.get("sla_target") is not None:
                    sla_target = profile.get("sla_target")
                print(f"[DEBUG] Exec summary GET - profile: {profile_name}, sla_target: {sla_target}, scope_tags: {profile.get('monitor_scope_tags')}, scope_ids: {profile.get('monitor_scope_ids')}")
        
        # Get all active bookmarks
        bookmarks = db_manager.get_bookmarks(x_tenant_id)
        active_bookmarks = [b for b in bookmarks if b.get("active", True)]
        print(f"[DEBUG] Exec summary GET - total bookmarks: {len(bookmarks)}, active: {len(active_bookmarks)}")
        for b in active_bookmarks[:5]:
            print(f"[DEBUG]   Bookmark: {b.get('name')}, tags: {b.get('tags')}")
        
        # Filter by profile scope if specified
        if profile:
            scope_ids = profile.get("monitor_scope_ids") or []
            scope_tags = profile.get("monitor_scope_tags") or []
            
            if scope_ids or scope_tags:
                filtered_bookmarks = []
                for b in active_bookmarks:
                    # Check if bookmark ID is in scope
                    if b.get("id") in scope_ids:
                        filtered_bookmarks.append(b)
                        print(f"[DEBUG]   Matched by ID: {b.get('name')}")
                        continue
                    # Check if any bookmark tag matches scope tags
                    bookmark_tags = b.get("tags") or []
                    if isinstance(bookmark_tags, str):
                        bookmark_tags = [t.strip() for t in bookmark_tags.split(",") if t.strip()]
                    if any(t in scope_tags for t in bookmark_tags):
                        filtered_bookmarks.append(b)
                        print(f"[DEBUG]   Matched by tag: {b.get('name')} has {bookmark_tags}")
                
                print(f"[DEBUG] Exec summary GET - filtered: {len(filtered_bookmarks)} bookmarks")
                active_bookmarks = filtered_bookmarks if filtered_bookmarks else active_bookmarks
        
        # Get and filter scribes (agents) based on profile scope
        all_agents = db_manager.get_all_agents()
        active_scribes = []
        
        if profile:
            scribe_scope_ids = profile.get("scribe_scope_ids") or []
            scribe_scope_tags = profile.get("scribe_scope_tags") or []
            
            print(f"[DEBUG] Exec summary GET - scribe_scope_tags: {scribe_scope_tags}, scribe_scope_ids: {scribe_scope_ids}")
            
            if scribe_scope_ids or scribe_scope_tags:
                for agent in all_agents:
                    agent_id = agent.get("agent_id")
                    # Check if agent ID is in scope
                    if agent_id in scribe_scope_ids:
                        active_scribes.append(agent)
                        print(f"[DEBUG]   Scribe matched by ID: {agent.get('display_name') or agent.get('hostname')}")
                        continue
                    # Check if any agent tag matches scope tags
                    agent_tags = agent.get("tags") or []
                    if isinstance(agent_tags, str):
                        agent_tags = [t.strip() for t in agent_tags.split(",") if t.strip()]
                    if any(t in scribe_scope_tags for t in agent_tags):
                        active_scribes.append(agent)
                        print(f"[DEBUG]   Scribe matched by tag: {agent.get('display_name') or agent.get('hostname')} has {agent_tags}")
            else:
                # No scope specified, include all agents
                active_scribes = all_agents
            
            print(f"[DEBUG] Exec summary GET - filtered: {len(active_scribes)} scribes")
        else:
            # No profile, include all agents
            active_scribes = all_agents
        
        # Query critical events per agent from raw_logs
        scribe_critical_events = {}
        try:
            conn_logs = sqlite3.connect("./loglibrarian.db")
            conn_logs.row_factory = sqlite3.Row
            cursor_logs = conn_logs.cursor()
            
            # Get critical event counts per agent for the time period
            cursor_logs.execute("""
                SELECT agent_id, COUNT(*) as count 
                FROM raw_logs
                WHERE created_at >= ?
                AND severity IN ('critical', 'crit', 'emerg', 'emergency', 'alert', 'CRITICAL', 'CRIT', 'EMERG', 'EMERGENCY', 'ALERT')
                GROUP BY agent_id
            """, (start_date.isoformat(),))
            for row in cursor_logs.fetchall():
                scribe_critical_events[row["agent_id"]] = row["count"]
            
            conn_logs.close()
        except Exception as e:
            print(f"[DEBUG] Error querying scribe critical events: {e}")
        
        # Build scribes summary with historical uptime
        scribes_summary = []
        for agent in active_scribes:
            agent_id = agent.get("agent_id")
            display_name = agent.get("display_name") or agent.get("hostname") or agent_id
            status = agent.get("status", "unknown")
            last_seen = agent.get("last_seen")
            
            # Calculate historical uptime based on heartbeat records (Smart Start logic)
            try:
                uptime_data = db_manager.calculate_agent_uptime(
                    agent_id=agent_id,
                    start_date=start_date,
                    end_date=end_date,
                    heartbeat_ttl_seconds=120  # 2x the 60s heartbeat interval
                )
                uptime_pct = uptime_data.get("uptime_percentage")
                uptime_status = uptime_data.get("status", "unknown")
                
                # Handle N/A case (agent didn't exist during period)
                if uptime_pct is None:
                    uptime_pct = None  # Will display as "N/A" in frontend
                    uptime_status = "not_applicable"
            except Exception as e:
                print(f"[DEBUG] Error calculating uptime for {agent_id}: {e}")
                # Fallback to live status-based uptime
                uptime_pct = 100.0 if status == "online" else 0.0
                uptime_status = "fallback"
            
            # Determine health status
            health = "Online" if status == "online" else "Offline"
            
            scribes_summary.append({
                "name": display_name,
                "agent_id": agent_id,
                "status": status,
                "health": health,
                "last_seen": last_seen,
                "os": agent.get("os", "Unknown"),
                "hostname": agent.get("hostname", "Unknown"),
                "uptime_percent": round(uptime_pct, 1) if uptime_pct is not None else None,
                "uptime_status": uptime_status,
                "critical_events": scribe_critical_events.get(agent_id, 0)
            })
        
        print(f"[DEBUG] Exec summary GET - scribes_summary count: {len(scribes_summary)}")
        
        if not active_bookmarks and not active_scribes:
            return {
                "success": True,
                "data": {
                    "profile_id": profile_id,
                    "profile_name": profile_name,
                    "period": {"days": days, "start": start_date.isoformat(), "end": end_date.isoformat()},
                    "global_uptime_percent": None,
                    "sla_target": sla_target,
                    "sla_status": "NO_DATA",
                    "monitors_count": 0,
                    "scribes_count": 0,
                    "theoretical_checks": 0,
                    "logs_analyzed": 0,
                    "incident_count": 0,
                    "perfect_health": True,
                    "uptime_segments": [],
                    "monitors_summary": [],
                    "scribes_summary": [],
                    "strategic_recommendations": [],
                    "log_analysis": None
                }
            }
        
        # Calculate uptime metrics from bookmark checks
        conn = sqlite3.connect("./loglibrarian.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        total_checks = 0
        total_up_checks = 0
        incident_count = 0
        monitors_summary = []
        uptime_segments = []
        
        # Track downtime durations for MTTR calculation
        downtime_durations = []  # List of downtime durations in seconds
        
        # Check if bookmark_checks table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='bookmark_checks'
        """)
        table_exists = cursor.fetchone() is not None
        
        try:
            if table_exists:
                for bookmark in active_bookmarks:
                    bookmark_id = bookmark["id"]
                    bookmark_created = bookmark.get("created_at")
                    
                    # Parse bookmark creation date
                    bookmark_start = start_date
                    if bookmark_created:
                        try:
                            if 'T' in str(bookmark_created):
                                bc_dt = datetime.fromisoformat(str(bookmark_created).replace('Z', '').split('+')[0])
                            else:
                                bc_dt = datetime.strptime(str(bookmark_created)[:19], '%Y-%m-%d %H:%M:%S')
                            # If bookmark was created after start_date, use creation date
                            if bc_dt > start_date:
                                bookmark_start = bc_dt
                        except:
                            pass
                    
                    # Get all checks in the period (strictly within date range)
                    cursor.execute("""
                        SELECT status, created_at, latency_ms, message
                        FROM bookmark_checks 
                        WHERE bookmark_id = ? AND created_at >= ? AND created_at <= ?
                        ORDER BY created_at ASC
                    """, (bookmark_id, bookmark_start.isoformat(), end_date.isoformat()))
                    
                    checks = cursor.fetchall()
                    
                    if not checks:
                        # No check data yet - new monitors start at 100% uptime
                        # A new deployment with no data is considered "up"
                        type_display = {
                            "http": "Web Service",
                            "icmp": "Network Connectivity", 
                            "tcp-port": "Service Port"
                        }.get(bookmark.get("type", "http"), "Service")
                        
                        current_status = bookmark.get("last_status")
                        if current_status == 1:
                            status_display = "Service Available"
                        elif current_status == 0:
                            status_display = "Service Unavailable"
                        else:
                            status_display = "Pending Verification"
                        
                        check_interval = bookmark.get("check_interval", 60)  # default 60 seconds
                        
                        # New monitors start at 100% - if there's no failure data, assume success
                        monitors_summary.append({
                            "name": bookmark["name"],
                            "type": type_display,
                            "uptime_percent": 100.0,  # New deployments start at 100%
                            "avg_response_ms": 0,
                            "incidents": 0,
                            "checks_count": 0,
                            "check_interval_seconds": check_interval,
                            "current_status": status_display,
                            "health": "Healthy",  # New = assumed healthy
                            "latency_history": []
                        })
                        continue
                    
                    monitor_total = len(checks)
                    monitor_up = sum(1 for c in checks if c["status"] == 1)
                    monitor_uptime = (monitor_up / monitor_total * 100) if monitor_total > 0 else 0
                    avg_latency = sum(c["latency_ms"] or 0 for c in checks if c["status"] == 1) / max(monitor_up, 1)
                    
                    total_checks += monitor_total
                    total_up_checks += monitor_up
                    
                    # Count incidents (transitions to down) and track downtime durations for MTTR
                    prev_status = 1
                    monitor_incidents = 0
                    incident_start_time = None
                    for check in checks:
                        check_time_str = check["created_at"]
                        try:
                            if 'T' in str(check_time_str):
                                check_time = datetime.fromisoformat(str(check_time_str).replace('Z', '').split('+')[0])
                            else:
                                check_time = datetime.strptime(str(check_time_str)[:19], '%Y-%m-%d %H:%M:%S')
                        except:
                            check_time = None
                        
                        if check["status"] == 0 and prev_status == 1:
                            # Transition to down - start incident
                            monitor_incidents += 1
                            incident_start_time = check_time
                        elif check["status"] == 1 and prev_status == 0 and incident_start_time and check_time:
                            # Transition back to up - end incident, record duration
                            duration = (check_time - incident_start_time).total_seconds()
                            if duration > 0:
                                downtime_durations.append(duration)
                            incident_start_time = None
                        prev_status = check["status"]
                    
                    incident_count += monitor_incidents
                    
                    # Build latency history for sparkline (daily averages)
                    latency_history = []
                    for day_offset in range(days):
                        day_start = start_date + timedelta(days=day_offset)
                        day_end = day_start + timedelta(days=1)
                        day_checks = [c for c in checks if day_start.isoformat() <= c["created_at"] < day_end.isoformat()]
                        if day_checks:
                            day_latencies = [c["latency_ms"] for c in day_checks if c["status"] == 1 and c["latency_ms"]]
                            if day_latencies:
                                latency_history.append(round(sum(day_latencies) / len(day_latencies), 1))
                            else:
                                latency_history.append(None)  # No successful checks
                        else:
                            latency_history.append(None)  # No checks this day
                    
                    # Executive-friendly type names
                    type_display = {
                        "http": "Web Service",
                        "icmp": "Network Connectivity", 
                        "tcp-port": "Service Port"
                    }.get(bookmark.get("type", "http"), "Service")
                    
                    # Executive-friendly status
                    current_status = bookmark.get("last_status")
                    if current_status == 1:
                        status_display = "Service Available"
                    elif current_status == 0:
                        status_display = "Service Unavailable"
                    else:
                        status_display = "Pending Verification"
                    
                    check_interval = bookmark.get("check_interval", 60)  # default 60 seconds
                    monitors_summary.append({
                        "name": bookmark["name"],
                        "type": type_display,
                        "uptime_percent": round(monitor_uptime, 2),
                        "avg_response_ms": round(avg_latency, 1),
                        "incidents": monitor_incidents,
                        "checks_count": monitor_total,
                        "check_interval_seconds": check_interval,
                        "current_status": status_display,
                        "health": "Healthy" if monitor_uptime >= sla_target else "Needs Attention",
                        "latency_history": latency_history
                    })
            else:
                # No check history yet - build report from current bookmark status
                for bookmark in active_bookmarks:
                    type_display = {
                        "http": "Web Service",
                        "icmp": "Network Connectivity", 
                        "tcp-port": "Service Port"
                    }.get(bookmark.get("type", "http"), "Service")
                    
                    current_status = bookmark.get("last_status")
                    if current_status == 1:
                        status_display = "Service Available"
                    elif current_status == 0:
                        status_display = "Service Unavailable"
                    else:
                        status_display = "Pending Verification"
                    
                    check_interval = bookmark.get("check_interval", 60)  # default 60 seconds
                    monitors_summary.append({
                        "name": bookmark["name"],
                        "type": type_display,
                        "uptime_percent": 100.0 if current_status == 1 else (0 if current_status == 0 else None),
                        "avg_response_ms": 0,
                        "incidents": 0,
                        "checks_count": 0,
                        "check_interval_seconds": check_interval,
                        "current_status": status_display,
                        "health": "Healthy" if current_status == 1 else "Pending",
                        "latency_history": []  # No history yet
                    })
            
            # Build uptime segments for visualization (daily buckets)
            if table_exists:
                for day_offset in range(days):
                    day_start = start_date + timedelta(days=day_offset)
                    day_end = day_start + timedelta(days=1)
                    
                    cursor.execute("""
                        SELECT COUNT(*) as total, SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as up_count
                        FROM bookmark_checks
                        WHERE created_at >= ? AND created_at < ?
                    """, (day_start.isoformat(), day_end.isoformat()))
                    
                    row = cursor.fetchone()
                    if row and row["total"] > 0:
                        day_uptime = (row["up_count"] / row["total"]) * 100
                        uptime_segments.append({
                            "date": day_start.strftime("%Y-%m-%d"),
                            "uptime_percent": round(day_uptime, 1),
                            "status": "up" if day_uptime >= 99 else ("degraded" if day_uptime >= 90 else "down")
                        })
                    else:
                        uptime_segments.append({
                            "date": day_start.strftime("%Y-%m-%d"),
                            "uptime_percent": 100,
                            "status": "no_data"
                        })
            else:
                # No history - generate placeholder segments
                for day_offset in range(days):
                    day_start = start_date + timedelta(days=day_offset)
                    uptime_segments.append({
                        "date": day_start.strftime("%Y-%m-%d"),
                        "uptime_percent": 100,
                        "status": "no_data"
                    })
            
            # Count total log entries (Logs Analyzed) and gather log analysis data
            logs_analyzed = 0
            log_analysis = {
                "total_volume_bytes": 0,
                "total_volume_display": "0 KB",
                "top_sources": [],
                "critical_events": 0,
                "error_events": 0,
                "warning_events": 0
            }
            
            try:
                # Total log count
                cursor.execute("""
                    SELECT COUNT(*) as count FROM raw_logs
                    WHERE created_at >= ?
                """, (start_date.isoformat(),))
                log_count_row = cursor.fetchone()
                logs_analyzed = log_count_row["count"] if log_count_row else 0
                
                # Estimate total volume (assuming ~500 bytes per log entry average)
                estimated_bytes = logs_analyzed * 500
                if estimated_bytes >= 1e9:
                    log_analysis["total_volume_display"] = f"{estimated_bytes / 1e9:.1f} GB"
                elif estimated_bytes >= 1e6:
                    log_analysis["total_volume_display"] = f"{estimated_bytes / 1e6:.1f} MB"
                elif estimated_bytes >= 1e3:
                    log_analysis["total_volume_display"] = f"{estimated_bytes / 1e3:.1f} KB"
                else:
                    log_analysis["total_volume_display"] = f"{estimated_bytes} bytes"
                log_analysis["total_volume_bytes"] = estimated_bytes
                
                # Top log sources (by agent/source)
                cursor.execute("""
                    SELECT source, COUNT(*) as count 
                    FROM raw_logs
                    WHERE created_at >= ?
                    GROUP BY source
                    ORDER BY count DESC
                    LIMIT 5
                """, (start_date.isoformat(),))
                top_sources = cursor.fetchall()
                log_analysis["top_sources"] = [
                    {"name": row["source"] or "Unknown", "count": row["count"]} 
                    for row in top_sources
                ]
                
                # Severity breakdown
                cursor.execute("""
                    SELECT severity, COUNT(*) as count 
                    FROM raw_logs
                    WHERE created_at >= ?
                    GROUP BY severity
                """, (start_date.isoformat(),))
                for row in cursor.fetchall():
                    sev = (row["severity"] or "").lower()
                    if sev in ("critical", "crit", "emerg", "emergency", "alert"):
                        log_analysis["critical_events"] += row["count"]
                    elif sev in ("error", "err"):
                        log_analysis["error_events"] += row["count"]
                    elif sev in ("warning", "warn"):
                        log_analysis["warning_events"] += row["count"]
            except:
                pass
            
        finally:
            conn.close()
        
        # Calculate theoretical checks: (monitors) * (minutes in period) / (avg check interval in minutes)
        # Use the average check interval from all monitors, default to 1 minute
        total_check_intervals = sum(m.get("check_interval_seconds", 60) for m in monitors_summary)
        avg_check_interval_seconds = total_check_intervals / len(monitors_summary) if monitors_summary else 60
        avg_check_interval_minutes = avg_check_interval_seconds / 60
        theoretical_checks = int(len(active_bookmarks) * total_minutes / avg_check_interval_minutes) if avg_check_interval_minutes > 0 else 0
        
        # Calculate global uptime - COMBINED from both Bookmarks AND Scribes
        # This provides a true "Global Availability" score across all monitored assets
        all_uptime_values = []
        
        # Add bookmark uptime values (exclude N/A)
        for monitor in monitors_summary:
            uptime = monitor.get("uptime_percent")
            if uptime is not None:
                all_uptime_values.append(uptime)
        
        # Add scribe uptime values (exclude N/A - None values)
        for scribe in scribes_summary:
            uptime = scribe.get("uptime_percent")
            if uptime is not None:
                all_uptime_values.append(uptime)
        
        # Calculate global uptime as average of ALL valid uptime values
        if all_uptime_values:
            global_uptime = sum(all_uptime_values) / len(all_uptime_values)
        elif total_checks > 0:
            # Fallback to bookmark-only calculation if no individual uptimes available
            global_uptime = (total_up_checks / total_checks * 100)
        else:
            global_uptime = 100.0
        
        # Cap at 100%
        global_uptime = min(global_uptime, 100.0)
        
        # Determine SLA status
        sla_status = "PASSED" if global_uptime >= sla_target else "FAILED"
        perfect_health = incident_count == 0
        
        # Calculate MTTR (Mean Time To Recovery)
        mttr_seconds = None
        mttr_display = None
        if downtime_durations:
            mttr_seconds = sum(downtime_durations) / len(downtime_durations)
            if mttr_seconds >= 3600:
                hours = int(mttr_seconds // 3600)
                mins = int((mttr_seconds % 3600) // 60)
                mttr_display = f"{hours}h {mins}m"
            elif mttr_seconds >= 60:
                mins = int(mttr_seconds // 60)
                secs = int(mttr_seconds % 60)
                mttr_display = f"{mins}m {secs}s"
            else:
                mttr_display = f"{int(mttr_seconds)}s"
        
        # Find Lowest Performer (Primary Drag)
        lowest_performer = None
        all_assets_with_uptime = []
        
        # Collect all monitors with uptime
        for m in monitors_summary:
            if m.get("uptime_percent") is not None:
                all_assets_with_uptime.append({
                    "name": m["name"],
                    "type": "bookmark",
                    "uptime_percent": m["uptime_percent"]
                })
        
        # Collect all scribes with uptime
        for s in scribes_summary:
            if s.get("uptime_percent") is not None:
                all_assets_with_uptime.append({
                    "name": s["name"],
                    "type": "scribe",
                    "uptime_percent": s["uptime_percent"]
                })
        
        if all_assets_with_uptime:
            lowest = min(all_assets_with_uptime, key=lambda x: x["uptime_percent"])
            lowest_performer = {
                "name": lowest["name"],
                "type": lowest["type"],
                "uptime_percent": lowest["uptime_percent"]
            }
        
        # Calculate Trend (Delta vs previous period)
        trend = None
        try:
            # Previous period is the same number of days immediately before start_date
            prev_end_date = start_date
            prev_start_date = prev_end_date - timedelta(days=days)
            
            # Get previous period uptime for bookmarks
            prev_uptime_values = []
            conn_prev = sqlite3.connect("./loglibrarian.db")
            conn_prev.row_factory = sqlite3.Row
            cursor_prev = conn_prev.cursor()
            
            if table_exists:
                for bookmark in active_bookmarks:
                    bookmark_id = bookmark["id"]
                    cursor_prev.execute("""
                        SELECT status FROM bookmark_checks 
                        WHERE bookmark_id = ? AND created_at >= ? AND created_at < ?
                    """, (bookmark_id, prev_start_date.isoformat(), prev_end_date.isoformat()))
                    prev_checks = cursor_prev.fetchall()
                    if prev_checks:
                        prev_up = sum(1 for c in prev_checks if c["status"] == 1)
                        prev_uptime = (prev_up / len(prev_checks)) * 100
                        prev_uptime_values.append(prev_uptime)
            
            # Get previous period uptime for scribes
            for scribe in scribes_summary:
                agent_id = scribe.get("agent_id")
                if agent_id:
                    try:
                        prev_uptime_data = db_manager.calculate_agent_uptime(
                            agent_id=agent_id,
                            start_date=prev_start_date,
                            end_date=prev_end_date,
                            heartbeat_ttl_seconds=120
                        )
                        prev_uptime_pct = prev_uptime_data.get("uptime_percentage")
                        if prev_uptime_pct is not None:
                            prev_uptime_values.append(prev_uptime_pct)
                    except:
                        pass
            
            conn_prev.close()
            
            if prev_uptime_values:
                prev_global_uptime = sum(prev_uptime_values) / len(prev_uptime_values)
                trend = round(global_uptime - prev_global_uptime, 2)
        except Exception as e:
            print(f"[DEBUG] Error calculating trend: {e}")
        
        # Strategic recommendations
        strategic_recommendations = []
        
        # Check for monitors with poor performance
        for monitor in monitors_summary:
            if monitor["uptime_percent"] < 95:
                strategic_recommendations.append({
                    "type": "warning",
                    "category": "Availability",
                    "message": f"'{monitor['name']}' has {monitor['uptime_percent']}% uptime - review recommended"
                })
            if monitor["avg_response_ms"] > 2000:
                strategic_recommendations.append({
                    "type": "info",
                    "category": "Performance",
                    "message": f"'{monitor['name']}' average response time is {monitor['avg_response_ms']}ms - optimization may improve user experience"
                })
        
        # Check for high incident count
        if incident_count > 10:
            strategic_recommendations.append({
                "type": "warning",
                "category": "Stability",
                "message": f"{incident_count} service interruptions detected - infrastructure review recommended"
            })
        
        # If everything is perfect
        if not strategic_recommendations and perfect_health and global_uptime >= 99.9:
            strategic_recommendations.append({
                "type": "success",
                "category": "Status",
                "message": "All systems operating at optimal performance levels"
            })
        
        return {
            "success": True,
            "data": {
                "period": {
                    "days": days,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "generated_at": datetime.utcnow().isoformat()
                },
                "global_uptime_percent": round(global_uptime, 3),
                "trend": trend,
                "sla_target": sla_target,
                "sla_status": sla_status,
                "sla_margin": round(global_uptime - sla_target, 3),
                "lowest_performer": lowest_performer,
                "mttr_seconds": mttr_seconds,
                "mttr_display": mttr_display,
                "monitors_count": len(active_bookmarks),
                "scribes_count": len(scribes_summary),
                "total_checks": total_checks,
                "theoretical_checks": theoretical_checks,
                "logs_analyzed": logs_analyzed,
                "incident_count": incident_count,
                "perfect_health": perfect_health,
                "uptime_segments": uptime_segments,
                "monitors_summary": sorted(monitors_summary, key=lambda x: x["uptime_percent"] if x["uptime_percent"] is not None else 0),
                "scribes_summary": scribes_summary,
                "strategic_recommendations": strategic_recommendations,
                "log_analysis": log_analysis,
                "profile_id": profile_id,
                "profile_name": profile_name,
                # Executive-friendly summary text
                "executive_summary": {
                    "headline": f"{'Excellent' if global_uptime >= 99.9 else 'Good' if global_uptime >= 99 else 'Needs Attention'} System Health",
                    "uptime_text": f"{round(global_uptime, 2)}% availability over {days} days",
                    "sla_text": f"SLA Target {'Achieved' if sla_status == 'PASSED' else 'Not Met'} ({sla_target}%)",
                    "activity_text": f"{logs_analyzed:,} log entries analyzed by LogLibrarian",
                    "incident_text": "Perfect operational record" if perfect_health else f"{incident_count} incident{'s' if incident_count != 1 else ''} detected and logged"
                }
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def password_reset_cli():
    """CLI tool for resetting password from within the Docker container"""
    import sys
    import getpass
    
    print("\n" + "="*50)
    print("  LogLibrarian Password Reset")
    print("="*50 + "\n")
    
    # Get all users
    users = db_manager.get_all_users()
    
    if not users:
        print("No users found. The default credentials are: admin / admin")
        print("Login with these credentials to create your account.\n")
        return
    
    # Show existing users
    print("Existing users:")
    for i, user in enumerate(users, 1):
        admin_tag = " (admin)" if user["is_admin"] else ""
        print(f"  {i}. {user['username']}{admin_tag}")
    
    print()
    
    # Select user
    while True:
        try:
            choice = input("Enter user number to reset password (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                print("Cancelled.\n")
                return
            idx = int(choice) - 1
            if 0 <= idx < len(users):
                selected_user = users[idx]
                break
            print("Invalid selection. Try again.")
        except ValueError:
            print("Please enter a number.")
    
    print(f"\nResetting password for: {selected_user['username']}")
    
    # Get new password
    while True:
        password1 = getpass.getpass("Enter new password: ")
        
        # Validate password
        if len(password1) < 8:
            print("❌ Password must be at least 8 characters")
            continue
        if not re.search(r'\d', password1):
            print("❌ Password must contain at least one number")
            continue
        if not re.search(r'[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;\'\/]', password1):
            print("❌ Password must contain at least one special character")
            continue
        
        password2 = getpass.getpass("Confirm new password: ")
        
        if password1 != password2:
            print("❌ Passwords do not match. Try again.\n")
            continue
        
        break
    
    # Update password
    success = db_manager.update_user_password(selected_user["id"], password1)
    
    if success:
        print(f"\n✅ Password reset successfully for {selected_user['username']}")
    else:
        print("\n❌ Failed to reset password")
    
    print()


if __name__ == "__main__":
    import sys
    
    # Check for CLI commands
    if len(sys.argv) > 1:
        command = " ".join(sys.argv[1:]).lower()
        if command in ["password reset", "reset password", "password-reset"]:
            password_reset_cli()
            sys.exit(0)
        else:
            print(f"Unknown command: {command}")
            print("Available commands:")
            print("  password reset - Reset a user's password")
            sys.exit(1)
    
    # Normal server startup
    uvicorn.run(app, host="0.0.0.0", port=8000)
