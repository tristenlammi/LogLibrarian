# Multi-Tenant Support Guide

LogLibrarian supports multi-tenant deployments for Managed Service Providers (MSPs) and organizations managing multiple separate environments.

## Overview

Multi-tenant architecture provides:
- **Tenant Isolation**: Each tenant's data is logically separated
- **API Key Authentication**: Secure tenant identification via API keys
- **Super Admin Access**: Administrative access across all tenants
- **Per-Tenant Quotas**: Resource limits per tenant (coming soon)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                               │
│                   (X-API-Key Header)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│   │   Tenant A   │  │   Tenant B   │  │   Tenant C   │         │
│   │              │  │              │  │              │         │
│   │ - Agents     │  │ - Agents     │  │ - Agents     │         │
│   │ - Logs       │  │ - Logs       │  │ - Logs       │         │
│   │ - Metrics    │  │ - Metrics    │  │ - Metrics    │         │
│   │ - API Keys   │  │ - API Keys   │  │ - API Keys   │         │
│   └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Setup

### 1. Initial Configuration

On first startup, LogLibrarian creates a default tenant with a super-admin API key:

```bash
# Start the backend
docker-compose up -d

# Check logs for the initial API key
docker logs loglibrarian-librarian-1 2>&1 | grep "Super Admin API Key"
```

**IMPORTANT**: Save this API key immediately - it's only shown once!

Example output:
```
==============================================
INITIAL SUPER ADMIN API KEY CREATED
Key: ll_abc123xyz...
SAVE THIS KEY - IT WILL NOT BE SHOWN AGAIN
==============================================
```

### 2. Configure Dashboard

1. Open the LogLibrarian Dashboard
2. Go to **Settings** page
3. Enter your API key in the **API Key Configuration** section
4. Click **Save API Key**

### 3. Create Tenants

Using the super-admin API key, create tenant organizations:

```bash
# Create a new tenant
curl -X POST http://localhost:8000/api/tenants \
  -H "X-API-Key: ll_your_super_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme"}'
```

Response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Acme Corp",
  "slug": "acme",
  "status": "active",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### 4. Generate API Keys for Tenants

```bash
# Create an API key for a tenant
curl -X POST http://localhost:8000/api/tenants/{tenant_id}/api-keys \
  -H "X-API-Key: ll_your_super_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Production Agents", "role": "admin"}'
```

Response:
```json
{
  "id": "key_550e8400",
  "name": "Production Agents",
  "key": "ll_newkey123...",
  "role": "admin",
  "created_at": "2024-01-15T10:35:00Z"
}
```

## Agent Configuration

Configure scribe agents to connect with tenant API keys:

### Environment Variables

```bash
# In agent config or environment
export LIBRARIAN_URL=https://logs.yourcompany.com
export API_KEY=ll_tenant_api_key
```

### Config File

```json
{
  "server_url": "https://logs.yourcompany.com",
  "api_key": "ll_tenant_api_key"
}
```

### systemd Service Override

```ini
# /etc/systemd/system/scribe.service.d/override.conf
[Service]
Environment="API_KEY=ll_tenant_api_key"
```

## API Reference

### Authentication

Include the API key in requests:

```bash
# Via header (recommended)
curl -H "X-API-Key: ll_your_key" http://localhost:8000/api/agents

# Via Bearer token
curl -H "Authorization: Bearer ll_your_key" http://localhost:8000/api/agents
```

### Tenant Management (Super Admin Only)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tenants` | GET | List all tenants |
| `/api/tenants` | POST | Create new tenant |
| `/api/tenants/{id}` | GET | Get tenant details |
| `/api/tenants/{id}` | PUT | Update tenant |
| `/api/tenants/{id}/stats` | GET | Get tenant statistics |

### API Key Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tenants/{id}/api-keys` | GET | List tenant's API keys |
| `/api/tenants/{id}/api-keys` | POST | Create new API key |
| `/api/tenants/{id}/api-keys/{key_id}` | DELETE | Revoke API key |

### Current Tenant

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tenant/me` | GET | Get current tenant from API key |

## Roles

### Super Admin
- Full access to all tenants
- Can create/delete tenants
- Can manage all API keys
- Sees all agents and data

### Admin (per tenant)
- Full access within their tenant
- Can create API keys for their tenant
- Can manage agents and settings

### Agent (per tenant)
- Read/write logs and metrics
- Cannot manage other agents or settings

### Viewer (per tenant)
- Read-only access to logs and metrics

## Data Isolation

### Automatic Filtering

When using an API key, all queries are automatically filtered:

```sql
-- Regular user query
SELECT * FROM agents WHERE tenant_id = 'current_tenant_id'

-- Super admin sees all
SELECT * FROM agents
```

### Tables with Tenant Isolation

- `agents` - Log collection agents
- `metrics` - Agent metrics data
- `logs` - Log entries (when using LogLibrarian storage)
- `api_keys` - Tenant API keys

## Best Practices

### 1. Key Rotation

Rotate API keys periodically:

```bash
# Create new key
curl -X POST /api/tenants/{id}/api-keys -d '{"name": "Production Q2 2024"}'

# Update agents with new key

# Revoke old key
curl -X DELETE /api/tenants/{id}/api-keys/{old_key_id}
```

### 2. Least Privilege

- Use `agent` role for scribe agents
- Use `viewer` role for dashboards
- Reserve `admin` for management tasks

### 3. Key Security

- Store keys in secret managers (Vault, AWS Secrets Manager)
- Use environment variables, not config files
- Audit key usage regularly

### 4. Tenant Naming

- Use descriptive names: "Acme Corp - Production"
- Use slugs for URLs: "acme-prod"
- Document tenant purpose

## Troubleshooting

### Invalid API Key

```
{"detail": "Invalid API key"}
```

- Verify key format starts with `ll_`
- Check key hasn't been revoked
- Confirm key is for the correct environment

### Tenant Not Found

```
{"detail": "Tenant not found or inactive"}
```

- Verify tenant status is "active"
- Check tenant ID is correct
- Super admin may have suspended tenant

### Permission Denied

```
{"detail": "Super admin access required"}
```

- Only super-admin keys can manage tenants
- Regular tenant keys can only access their own data

### Agent Registration Failed

If agents fail to register with a tenant:

1. Check API key is valid: `curl -H "X-API-Key: ll_key" /api/tenant/me`
2. Verify network connectivity to LogLibrarian server
3. Check agent logs for detailed error messages

## Migration from Single-Tenant

If upgrading from a single-tenant deployment:

1. **Backup Data**: Export existing data before migration
2. **Create Default Tenant**: System creates one automatically
3. **Migrate Agents**: Existing agents belong to default tenant
4. **Generate API Keys**: Create keys for the default tenant
5. **Update Agents**: Configure agents with new API keys

## Future Enhancements

- [ ] Tenant quotas (max agents, log retention)
- [ ] Tenant billing integration
- [ ] Cross-tenant log aggregation (super admin)
- [ ] Tenant-specific alerting
- [ ] SSO integration per tenant
