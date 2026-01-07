"""
Multi-Tenant Support for MSP Deployments

This module provides tenant isolation for the LogLibrarian platform:
- Tenant model and management
- API key association with tenants
- Middleware for automatic tenant filtering
- Super-admin role support

Each tenant gets isolated access to:
- Their own agents
- Their own metrics and logs
- Their own alerts and settings
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from fastapi import HTTPException, Header, Request, Depends


# =============================================================================
# MODELS
# =============================================================================

class TenantRole(str, Enum):
    """User roles within the system"""
    TENANT_USER = "tenant_user"       # Regular tenant user
    TENANT_ADMIN = "tenant_admin"     # Tenant administrator
    SUPER_ADMIN = "super_admin"       # Can see all tenants


class TenantStatus(str, Enum):
    """Tenant account status"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"


class TenantCreate(BaseModel):
    """Request model for creating a tenant"""
    name: str = Field(..., min_length=2, max_length=100, description="Tenant name")
    contact_email: str = Field(..., description="Primary contact email")
    max_agents: int = Field(default=10, ge=1, le=10000, description="Maximum allowed agents")
    status: TenantStatus = Field(default=TenantStatus.ACTIVE)


class TenantUpdate(BaseModel):
    """Request model for updating a tenant"""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    contact_email: Optional[str] = None
    max_agents: Optional[int] = Field(None, ge=1, le=10000)
    status: Optional[TenantStatus] = None


class Tenant(BaseModel):
    """Full tenant model"""
    id: str
    name: str
    contact_email: str
    max_agents: int
    status: TenantStatus
    created_at: datetime
    updated_at: datetime


class TenantStats(BaseModel):
    """Tenant statistics"""
    tenant_id: str
    tenant_name: str
    agent_count: int
    online_agent_count: int
    total_metrics: int
    total_logs: int
    disk_usage_mb: float
    last_activity: Optional[datetime]


class APIKeyCreate(BaseModel):
    """Request model for creating an API key"""
    name: str = Field(..., min_length=2, max_length=100, description="Key name/description")
    role: TenantRole = Field(default=TenantRole.TENANT_USER)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365, description="Days until expiration")


class APIKey(BaseModel):
    """API key model (without sensitive key_hash)"""
    id: str
    tenant_id: str
    name: str
    role: TenantRole
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    is_active: bool


class APIKeyWithSecret(APIKey):
    """API key response with the secret (only shown once at creation)"""
    api_key: str  # The actual key - only shown once


class TenantContext(BaseModel):
    """Context injected into requests after authentication"""
    tenant_id: str
    tenant_name: str
    role: TenantRole
    api_key_id: str
    is_super_admin: bool = False
    
    def can_see_tenant(self, target_tenant_id: str) -> bool:
        """Check if this context can access a specific tenant's data"""
        return self.is_super_admin or self.tenant_id == target_tenant_id


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

class TenantDatabaseMixin:
    """
    Mixin class that adds tenant-related database operations.
    Can be mixed into both SQLite and PostgreSQL database managers.
    """
    
    # -------------------------------------------------------------------------
    # Tenant CRUD
    # -------------------------------------------------------------------------
    
    def create_tenant(self, tenant: TenantCreate) -> Tenant:
        """Create a new tenant"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        cursor = conn.cursor()
        
        tenant_id = f"tenant_{secrets.token_hex(8)}"
        now = datetime.utcnow()
        
        try:
            cursor.execute("""
                INSERT INTO tenants (id, name, contact_email, max_agents, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (tenant_id, tenant.name, tenant.contact_email, tenant.max_agents, 
                  tenant.status.value, now, now))
            conn.commit()
            
            return Tenant(
                id=tenant_id,
                name=tenant.name,
                contact_email=tenant.contact_email,
                max_agents=tenant.max_agents,
                status=tenant.status,
                created_at=now,
                updated_at=now
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Tenant creation failed: {e}")
        finally:
            conn.close()
    
    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get a tenant by ID"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
            
        return Tenant(
            id=row["id"],
            name=row["name"],
            contact_email=row["contact_email"],
            max_agents=row["max_agents"],
            status=TenantStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
    
    def list_tenants(self, include_suspended: bool = False) -> List[Tenant]:
        """List all tenants"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if include_suspended:
            cursor.execute("SELECT * FROM tenants ORDER BY name")
        else:
            cursor.execute("SELECT * FROM tenants WHERE status != 'suspended' ORDER BY name")
        
        rows = cursor.fetchall()
        conn.close()
        
        return [Tenant(
            id=row["id"],
            name=row["name"],
            contact_email=row["contact_email"],
            max_agents=row["max_agents"],
            status=TenantStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        ) for row in rows]
    
    def update_tenant(self, tenant_id: str, update: TenantUpdate) -> Optional[Tenant]:
        """Update a tenant"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if update.name is not None:
            updates.append("name = ?")
            params.append(update.name)
        if update.contact_email is not None:
            updates.append("contact_email = ?")
            params.append(update.contact_email)
        if update.max_agents is not None:
            updates.append("max_agents = ?")
            params.append(update.max_agents)
        if update.status is not None:
            updates.append("status = ?")
            params.append(update.status.value)
        
        if not updates:
            conn.close()
            return self.get_tenant(tenant_id)
        
        updates.append("updated_at = ?")
        params.append(datetime.utcnow())
        params.append(tenant_id)
        
        cursor.execute(f"""
            UPDATE tenants SET {', '.join(updates)} WHERE id = ?
        """, params)
        conn.commit()
        conn.close()
        
        return self.get_tenant(tenant_id)
    
    def delete_tenant(self, tenant_id: str) -> bool:
        """Delete a tenant (soft delete by setting status to suspended)"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE tenants SET status = 'suspended', updated_at = ? WHERE id = ?
        """, (datetime.utcnow(), tenant_id))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    def get_tenant_stats(self, tenant_id: str) -> Optional[TenantStats]:
        """Get statistics for a tenant"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get tenant info
        cursor.execute("SELECT name FROM tenants WHERE id = ?", (tenant_id,))
        tenant_row = cursor.fetchone()
        if not tenant_row:
            conn.close()
            return None
        
        # Get agent counts
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) as online
            FROM agents WHERE tenant_id = ?
        """, (tenant_id,))
        agent_row = cursor.fetchone()
        
        # Get metrics count
        cursor.execute("""
            SELECT COUNT(*) as count FROM metrics 
            WHERE agent_id IN (SELECT agent_id FROM agents WHERE tenant_id = ?)
        """, (tenant_id,))
        metrics_row = cursor.fetchone()
        
        # Get logs count
        cursor.execute("""
            SELECT COUNT(*) as count FROM raw_logs 
            WHERE agent_id IN (SELECT agent_id FROM agents WHERE tenant_id = ?)
        """, (tenant_id,))
        logs_row = cursor.fetchone()
        
        # Get last activity
        cursor.execute("""
            SELECT MAX(last_seen) as last_activity FROM agents WHERE tenant_id = ?
        """, (tenant_id,))
        activity_row = cursor.fetchone()
        
        conn.close()
        
        last_activity = None
        if activity_row and activity_row["last_activity"]:
            last_activity = datetime.fromisoformat(activity_row["last_activity"])
        
        return TenantStats(
            tenant_id=tenant_id,
            tenant_name=tenant_row["name"],
            agent_count=agent_row["total"] or 0,
            online_agent_count=agent_row["online"] or 0,
            total_metrics=metrics_row["count"] or 0,
            total_logs=logs_row["count"] or 0,
            disk_usage_mb=0.0,  # TODO: Calculate actual disk usage
            last_activity=last_activity
        )
    
    # -------------------------------------------------------------------------
    # API Key Management
    # -------------------------------------------------------------------------
    
    def create_api_key(self, tenant_id: str, key_data: APIKeyCreate) -> APIKeyWithSecret:
        """Create a new API key for a tenant"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        cursor = conn.cursor()
        
        key_id = f"key_{secrets.token_hex(8)}"
        api_key = f"ll_{secrets.token_urlsafe(32)}"  # ll_ prefix for LogLibrarian
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        now = datetime.utcnow()
        
        expires_at = None
        if key_data.expires_in_days:
            expires_at = now + timedelta(days=key_data.expires_in_days)
        
        try:
            cursor.execute("""
                INSERT INTO api_keys (id, tenant_id, name, key_hash, role, created_at, expires_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (key_id, tenant_id, key_data.name, key_hash, key_data.role.value, now, expires_at))
            conn.commit()
            
            return APIKeyWithSecret(
                id=key_id,
                tenant_id=tenant_id,
                name=key_data.name,
                role=key_data.role,
                created_at=now,
                expires_at=expires_at,
                last_used_at=None,
                is_active=True,
                api_key=api_key
            )
        finally:
            conn.close()
    
    def validate_api_key(self, api_key: str) -> Optional[TenantContext]:
        """Validate an API key and return tenant context"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        cursor.execute("""
            SELECT k.id, k.tenant_id, k.role, k.expires_at, k.is_active,
                   t.name as tenant_name, t.status as tenant_status
            FROM api_keys k
            JOIN tenants t ON k.tenant_id = t.id
            WHERE k.key_hash = ?
        """, (key_hash,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None
        
        # Check if key is active
        if not row["is_active"]:
            conn.close()
            return None
        
        # Check expiration
        if row["expires_at"]:
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at < datetime.utcnow():
                conn.close()
                return None
        
        # Check tenant status
        if row["tenant_status"] == "suspended":
            conn.close()
            return None
        
        # Update last used
        cursor.execute("""
            UPDATE api_keys SET last_used_at = ? WHERE id = ?
        """, (datetime.utcnow(), row["id"]))
        conn.commit()
        conn.close()
        
        role = TenantRole(row["role"])
        return TenantContext(
            tenant_id=row["tenant_id"],
            tenant_name=row["tenant_name"],
            role=role,
            api_key_id=row["id"],
            is_super_admin=(role == TenantRole.SUPER_ADMIN)
        )
    
    def list_api_keys(self, tenant_id: str) -> List[APIKey]:
        """List API keys for a tenant"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, tenant_id, name, role, created_at, expires_at, last_used_at, is_active
            FROM api_keys WHERE tenant_id = ? ORDER BY created_at DESC
        """, (tenant_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [APIKey(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            role=TenantRole(row["role"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
            is_active=bool(row["is_active"])
        ) for row in rows]
    
    def revoke_api_key(self, key_id: str, tenant_id: str) -> bool:
        """Revoke an API key"""
        import sqlite3
        conn = sqlite3.connect(self._get_db_path())
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE api_keys SET is_active = 0 WHERE id = ? AND tenant_id = ?
        """, (key_id, tenant_id))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    # -------------------------------------------------------------------------
    # Schema Initialization
    # -------------------------------------------------------------------------
    
    def _init_tenant_schema_sqlite(self, cursor):
        """Initialize tenant-related tables for SQLite"""
        
        # Create tenants table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                contact_email TEXT NOT NULL,
                max_agents INTEGER DEFAULT 10,
                status TEXT DEFAULT 'active',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create api_keys table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                role TEXT DEFAULT 'tenant_user',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                last_used_at DATETIME,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)
        """)
        
        # Add tenant_id to agents if not exists
        cursor.execute("PRAGMA table_info(agents)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'tenant_id' not in columns:
            cursor.execute("ALTER TABLE agents ADD COLUMN tenant_id TEXT DEFAULT NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agents_tenant ON agents(tenant_id)")
        
        # Add tenant_id to metrics if not exists (for future direct queries)
        cursor.execute("PRAGMA table_info(metrics)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'tenant_id' not in columns:
            cursor.execute("ALTER TABLE metrics ADD COLUMN tenant_id TEXT DEFAULT NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_tenant ON metrics(tenant_id, timestamp)")
        
        # Create default super-admin tenant if none exists
        cursor.execute("SELECT COUNT(*) FROM tenants")
        if cursor.fetchone()[0] == 0:
            print("Creating default super-admin tenant...")
            default_tenant_id = "tenant_default"
            now = datetime.utcnow()
            cursor.execute("""
                INSERT INTO tenants (id, name, contact_email, max_agents, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (default_tenant_id, "Default", "admin@localhost", 1000, "active", now, now))
            
            # Create a default super-admin API key
            api_key = f"ll_{secrets.token_urlsafe(32)}"
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            key_id = f"key_{secrets.token_hex(8)}"
            cursor.execute("""
                INSERT INTO api_keys (id, tenant_id, name, key_hash, role, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (key_id, default_tenant_id, "Default Super Admin", key_hash, 
                  TenantRole.SUPER_ADMIN.value, now))
            
            print(f"✓ Default tenant created")
            print(f"🔑 Default Super Admin API Key (save this, shown only once):")
            print(f"   {api_key}")
    
    def _get_db_path(self) -> str:
        """Get the SQLite database path"""
        return getattr(self, 'db_path', './loglibrarian.db')


# =============================================================================
# MIDDLEWARE & DEPENDENCIES
# =============================================================================

# Global reference to database manager (set during app startup)
_tenant_db = None


def set_tenant_db(db_manager):
    """Set the database manager for tenant operations"""
    global _tenant_db
    _tenant_db = db_manager


def get_tenant_db():
    """Get the database manager for tenant operations"""
    if _tenant_db is None:
        raise RuntimeError("Tenant database not initialized")
    return _tenant_db


# Optional tenant context for requests
_request_tenant_context: Dict[int, Optional[TenantContext]] = {}


async def get_optional_tenant(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None)
) -> Optional[TenantContext]:
    """
    Extract tenant context from API key if provided.
    Returns None if no key provided (for backward compatibility).
    """
    api_key = None
    
    # Check X-API-Key header first
    if x_api_key:
        api_key = x_api_key
    # Fall back to Authorization header (Bearer token)
    elif authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:]
    
    if not api_key:
        return None
    
    db = get_tenant_db()
    context = db.validate_api_key(api_key)
    
    if not context:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    
    return context


async def require_tenant(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None)
) -> TenantContext:
    """
    Require valid tenant authentication.
    Raises 401 if no valid API key provided.
    """
    context = await get_optional_tenant(x_api_key, authorization)
    
    if not context:
        raise HTTPException(
            status_code=401, 
            detail="API key required. Provide X-API-Key header or Authorization: Bearer <key>"
        )
    
    return context


async def require_super_admin(
    context: TenantContext = Depends(require_tenant)
) -> TenantContext:
    """Require super-admin role"""
    if not context.is_super_admin:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return context


async def require_tenant_admin(
    context: TenantContext = Depends(require_tenant)
) -> TenantContext:
    """Require tenant admin or super admin role"""
    if context.role not in [TenantRole.TENANT_ADMIN, TenantRole.SUPER_ADMIN]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return context


def apply_tenant_filter(query: str, params: list, tenant_context: Optional[TenantContext], 
                        table: str = "agents", tenant_col: str = "tenant_id") -> tuple:
    """
    Apply tenant filtering to a SQL query.
    
    Args:
        query: The SQL query
        params: Query parameters list
        tenant_context: The tenant context (None for no filtering)
        table: Table name/alias to filter
        tenant_col: Column name for tenant_id
    
    Returns:
        Modified (query, params) tuple
    """
    if tenant_context is None or tenant_context.is_super_admin:
        return query, params
    
    # Add WHERE clause or AND condition
    if "WHERE" in query.upper():
        query = query + f" AND {table}.{tenant_col} = ?"
    else:
        query = query + f" WHERE {table}.{tenant_col} = ?"
    
    params.append(tenant_context.tenant_id)
    return query, params
