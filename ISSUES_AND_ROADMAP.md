# LogLibrarian - Issues & Production Readiness Roadmap

> **Last Audit Date:** January 7, 2026  
> **Status:** Pre-Production - Requires Remediation Before Public Release

---

## Executive Summary

LogLibrarian is a self-hosted log analysis platform with a Go-based agent (Scribe), Python FastAPI backend, and Vue.js dashboard. A comprehensive security and code quality audit has identified **67 issues** across various categories that should be addressed before production deployment.

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Security/Auth | 3 | 5 | 6 | 2 |
| Backend Code Quality | 2 | 4 | 6 | 3 |
| Frontend | 1 | 3 | 5 | 4 |
| Scribe Agent | 3 | 5 | 8 | 6 |
| Database | 2 | 5 | 7 | 3 |
| Deployment/Docker | 2 | 3 | 4 | 2 |
| Project Structure | 2 | 2 | 4 | 2 |
| **Total** | **15** | **27** | **40** | **22** |

---

## 🔴 Critical Issues (Must Fix Before Production)

### Authentication & Security

#### 1. ~~Weak Password Hashing (SHA-256)~~ ✅ FIXED
- **Location:** `librarian/db.py`, `librarian/db_postgres.py`
- **Issue:** ~~Using SHA-256 for password hashing. SHA-256 is fast, allowing brute-force attacks at millions of attempts per second.~~
- **Status:** ✅ FIXED Jan 7 - Both SQLite and PostgreSQL now use bcrypt with automatic salt generation. Legacy SHA-256 hashes are supported during migration.

#### 2. ~~Timing Attack in API Key Comparison~~ ✅ FIXED
- **Location:** `librarian/main.py:87`
- **Issue:** ~~Using `==` for API key comparison enables timing attacks.~~
- **Status:** ✅ FIXED Jan 7 - Now uses `secrets.compare_digest()` for constant-time comparison.

#### 3. ~~Default Credentials Accepted~~ ✅ FIXED
- **Location:** `librarian/main.py:666-669`
- **Issue:** ~~`admin/admin` credentials work when setup incomplete. Attackers can access uninitialized instances.~~
- **Status:** ✅ FIXED Jan 7 - No default credentials accepted. Login is blocked until setup wizard is completed.

### Scribe Agent Security

#### 4. No Signature Verification on Updates
- **Location:** `scribe/updater.go`, `librarian/routers/agent_updates.py`
- **Issue:** ~~Binary updates downloaded and executed without cryptographic signature verification.~~
- **Status:** ✅ FIXED Jan 7 - SHA-256 checksum verification implemented. Server calculates checksum of binaries, agent verifies before applying updates.

#### 5. Unencrypted Communication
- **Location:** `scribe/main.go`, `scribe/updater.go`, `scribe/logcollector.go`, `scribe/config.go`
- **Issue:** ~~WebSocket uses `ws://` and HTTP uses `http://` - all data in plaintext.~~
- **Status:** ✅ FIXED Jan 7 - Agent now supports TLS. Set `ssl_enabled: true` in config.json for wss:// and https://. Set `ssl_verify: false` for self-signed certs. Defaults to SSL enabled.

#### 6. Command Injection Risk in PowerShell
- **Location:** `scribe/logcollector.go`, `scribe/securitylogs.go`
- **Issue:** String interpolation in shell commands could allow injection.
- **Fix:** Use parameterized commands or strict input validation.

### Database

#### 7. Foreign Keys Not Enforced (SQLite)
- **Location:** `librarian/db.py`
- **Issue:** SQLite foreign keys declared but never enforced (`PRAGMA foreign_keys` not set).
- **Fix:** Add `PRAGMA foreign_keys = ON;` to connection setup.

#### 8. No Foreign Keys in PostgreSQL Schema
- **Location:** `librarian/db_postgres.py`
- **Issue:** Tables reference `agent_id` but no FK constraints exist. Orphan records possible.
- **Fix:** Add `FOREIGN KEY` constraints with `ON DELETE CASCADE`.

### Deployment

#### 9. Containers Running as Root
- **Location:** All Dockerfiles
- **Issue:** ~~No `USER` directive - containers run as root, increasing attack surface.~~
- **Status:** ✅ FIXED Jan 7 - Added non-root users (`librarian`, `scribe`) to Dockerfiles. Dashboard uses nginx which already runs workers as non-root.

#### 10. Hardcoded Database Passwords
- **Location:** `docker-compose.yml`
- **Issue:** `POSTGRES_PASSWORD: postgres` hardcoded in compose files.
- **Fix:** Use environment variables or Docker secrets.

### Project Structure

#### 11. Missing LICENSE File
- **Location:** Project root
- **Issue:** README mentions MIT license but no LICENSE file exists.
- **Fix:** Create LICENSE file with full MIT license text.

#### 12. No Test Coverage
- **Location:** `librarian/`, `dashboard/`
- **Issue:** Zero unit tests for Python backend and Vue frontend.
- **Fix:** Add pytest for Python, Vitest for Vue, achieve 70%+ coverage.

---

## 🟠 High Priority Issues

### Authentication & Authorization

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 13 | No brute force protection on login | `main.py:659` | Add rate limiting, account lockout |
| 14 | Session tokens stored in plaintext | `db_postgres.py:3131` | Hash tokens before storage |
| 15 | Missing CSRF protection | `main.py` | Add CSRF tokens for state-changing requests |
| 16 | 30-day session expiry too long | `main.py:278` | Reduce to 24h, add refresh tokens |
| 17 | CORS allows all origins with credentials | `main.py:118-125` | Never combine `*` with `allow_credentials=True` |

### Backend Code Quality

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 18 | Bare `except:` clauses (20+ instances) | Multiple files | Use specific exception types |
| 19 | API keys logged to console | `main.py`, `db.py` | Remove secret printing |
| 20 | SQL injection patterns | `db.py`, `db_postgres.py`, `tenants.py` | Use parameterized queries |
| 21 | Resource leaks - unclosed connections | `db.py` | Use context managers consistently |

### Frontend

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 22 | 20+ console.log statements | Multiple Vue files | Remove debug statements |
| 23 | Hardcoded localhost URLs | `api.js`, `ai.js` | Use environment variables |
| 24 | No DOMPurify for v-html | `ChatView.vue` | Install and use DOMPurify |

### Scribe Agent

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 25 | Credentials stored in plaintext | `config.go` | Use OS secure storage |
| 26 | Path traversal in log paths | `securitylogs.go` | Validate against allowlist |
| 27 | AI HTTP server without auth | `ai_http.go` | Add bearer token auth |
| 28 | No input validation on server commands | `main.go` | Implement command signing |
| 29 | Downloaded files not verified | `updater.go`, `ai_downloader.go` | Verify checksums |

### Database

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 30 | N+1 query in get_all_agents | `db_postgres.py` | Batch uptime calculations |
| 31 | Uptime reset on server restart | `db.py` | Remove destructive startup query |
| 32 | Missing indexes | Multiple tables | Add idx_agents_enabled, idx_alert_triggered_at |
| 33 | No transaction boundaries | `db_postgres.py` | Wrap multi-table ops in transactions |
| 34 | Unbounded queries | Multiple methods | Add LIMIT to all queries |

### Deployment

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 35 | Redis/Qdrant without authentication | `docker-compose.yml` | Add --requirepass, enable auth |
| 36 | Internal ports exposed | `docker-compose.yml` | Remove 5432, 6379, 6333 port mappings |
| 37 | Missing .env.example | Project root | Create template with all variables |

---

## 🟡 Medium Priority Issues

### Security

| # | Issue | Location |
|---|-------|----------|
| 38 | No secure flag on cookies | `main.py` |
| 39 | Secret key fallback allows startup | `main.py` |
| 40 | Unprotected AI chat endpoints | `routers/ai_chat.py` |
| 41 | Agent update endpoint no auth | `routers/agent_updates.py` |
| 42 | Password policy inconsistent (6 vs 8 chars) | `main.py`, `models.py` |
| 43 | API key stored both plain and hashed | `db.py` |

### Backend

| # | Issue | Location |
|---|-------|----------|
| 44 | Type hints inconsistent | Multiple files |
| 45 | Placeholder endpoints | `main.py` (/api/ask) |
| 46 | Debug print statements | `db_postgres.py` |
| 47 | Information disclosure in errors | `agent_updates.py` |
| 48 | Race condition in global state | `main.py` |
| 49 | Missing input validation | `agent_updates.py`, models |

### Frontend

| # | Issue | Location |
|---|-------|----------|
| 50 | Missing ARIA labels | Multiple components |
| 51 | SettingsView.vue 5000+ lines | `SettingsView.vue` |
| 52 | Event listeners not in onMounted | `api.js`, `SettingsView.vue` |
| 53 | No virtual scrolling for logs | `LogsView.vue` |
| 54 | Missing loading/error states | Multiple components |

### Scribe Agent

| # | Issue | Location |
|---|-------|----------|
| 55 | Goroutine tracking incomplete | `main.go` |
| 56 | Race condition in buffer | `main.go` |
| 57 | SQLite buffer not encrypted | `buffer.go` |
| 58 | Hardcoded port ranges | `ai_runner.go` |
| 59 | Missing timeouts on external calls | `sysinfo.go` |
| 60 | Incomplete PII patterns | `sanitize.go` |
| 61 | No rate limiting on registration | `main.go` |
| 62 | Unbounded output buffer | `ai_runner.go` |

### Database

| # | Issue | Location |
|---|-------|----------|
| 63 | Timezone handling inconsistent | `db.py`, `db_postgres.py` |
| 64 | Connection pool missing timeouts | `db_connection_pool.py` |
| 65 | Schema drift SQLite vs PostgreSQL | Both DB files |
| 66 | No migration version tracking | `db.py` |
| 67 | Missing NOT NULL constraints | Schema definitions |

### Deployment

| # | Issue | Location |
|---|-------|----------|
| 68 | Unpinned Docker image tags | `docker-compose.yml` |
| 69 | Missing resource limits | `docker-compose.yml` |
| 70 | Missing health checks | `dashboard`, `qdrant` |
| 71 | Source mounts in production compose | `docker-compose.yml` |

### Project

| # | Issue | Location |
|---|-------|----------|
| 72 | No CI/CD configuration | Project root |
| 73 | Missing CONTRIBUTING.md | Project root |
| 74 | Dependencies ~2 years old | `requirements.txt`, `package.json` |
| 75 | Sensitive files in git | `*.db`, `config.json`, model files |

---

## 🟢 Low Priority Issues

| # | Issue | Location |
|---|-------|----------|
| 76 | Unused JWT implementation | `auth_manager.py` |
| 77 | Dead code - placeholder endpoints | `main.py` |
| 78 | Token stored in two places | `auth.js` |
| 79 | IPv6 pattern simplified | `sanitize.go` |
| 80 | Log messages may leak paths | `logging.go` |
| 81 | Color-only status indicators | Dashboard CSS |

---

## Remediation Roadmap

### Phase 1: Security Critical (Week 1)
- [x] Replace SHA-256 with bcrypt for passwords ✅
- [x] Fix timing attack in API key comparison ✅
- [x] Remove default admin/admin credentials ✅
- [ ] Add non-root users to Dockerfiles
- [ ] Remove hardcoded passwords from compose files
- [ ] Create LICENSE file

### Phase 2: Security High (Week 2)
- [ ] Add rate limiting to login endpoint
- [ ] Hash session tokens before storage
- [ ] Fix CORS configuration
- [ ] Add TLS support to Scribe agent
- [ ] Implement update signature verification
- [ ] Add Redis/Qdrant authentication

### Phase 3: Code Quality (Week 3)
- [ ] Replace bare except clauses
- [ ] Remove console.log/print debug statements
- [ ] Fix SQL injection patterns
- [ ] Add transaction boundaries to multi-table operations
- [ ] Add missing database indexes
- [ ] Fix N+1 query patterns

### Phase 4: Testing & CI (Week 4)
- [ ] Set up pytest with initial test suite
- [ ] Set up Vitest for Vue components
- [ ] Create GitHub Actions CI pipeline
- [ ] Add security scanning (Dependabot, CodeQL)
- [ ] Create .env.example files
- [ ] Add CONTRIBUTING.md

### Phase 5: Polish (Ongoing)
- [ ] Split large Vue components
- [ ] Add ARIA labels for accessibility
- [ ] Update dependencies
- [ ] Add comprehensive API documentation
- [ ] Performance optimization

---

## Files Requiring Most Attention

| File | Issues | Priority |
|------|--------|----------|
| `librarian/main.py` | 12 | 🔴 Critical |
| `librarian/db.py` | 9 | 🔴 Critical |
| `librarian/db_postgres.py` | 11 | 🔴 Critical |
| `scribe/main.go` | 8 | 🔴 Critical |
| `scribe/updater.go` | 4 | 🔴 Critical |
| `docker-compose.yml` | 7 | 🟠 High |
| `dashboard/src/components/SettingsView.vue` | 5 | 🟠 High |
| `scribe/ai_http.go` | 3 | 🟠 High |

---

## Quick Wins (Can Fix Today)

1. **Create LICENSE file** - 5 minutes
2. **Create root .gitignore** - 10 minutes
3. **Remove console.log statements** - 30 minutes
4. **Fix timing attack** - 5 minutes (one line change)
5. **Create .env.example** - 15 minutes
6. **Add USER to Dockerfiles** - 15 minutes
7. **Remove hardcoded passwords** - 10 minutes

---

## Notes for Contributors

When addressing these issues:

1. **Security fixes** should be tested thoroughly and may need coordinated deployment
2. **Database schema changes** require migration scripts for existing deployments
3. **Breaking API changes** should be versioned (v2 endpoints)
4. **Frontend changes** should maintain backward compatibility with existing sessions

---

## Verification Commands

```bash
# Check for Python security issues
pip install pip-audit && pip-audit -r librarian/requirements.txt

# Check for Node.js security issues
cd dashboard && npm audit

# Check for Go security issues
cd scribe && govulncheck ./...

# Scan Docker images
docker scan loglibrarian-librarian:latest
```

---

*This document should be updated as issues are resolved. Mark completed items with ✅ and add completion date.*
