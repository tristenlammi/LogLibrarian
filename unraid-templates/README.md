# Unraid Installation Guide

LogLibrarian can be installed on Unraid in two ways:

## Option 1: Docker Compose (Recommended)

This is the easiest method as LogLibrarian has multiple dependent services.

### Prerequisites
1. Install the **Docker Compose Manager** plugin from Community Applications

### Steps
1. Go to **Docker** → **Compose**
2. Click **Add New Stack**
3. Name it `loglibrarian`
4. Paste the contents of `docker-compose.yml` from this repo
5. Modify the `SECRET_KEY` environment variable (generate a random string)
6. Click **Save Changes** then **Compose Up**

The services will start:
- **TimescaleDB** (PostgreSQL with time-series extensions)
- **Redis** (caching and message queue)
- **LogLibrarian Backend** (API server)
- **LogLibrarian Dashboard** (Web UI)

Access the dashboard at `http://YOUR_UNRAID_IP:3000`

---

## Option 2: Individual Container Templates

If you prefer Unraid's native Docker management:

### Step 1: Install Dependencies

From Community Applications, install:
- **TimescaleDB** (or PostgreSQL)
- **Redis**

### Step 2: Add Template Repository

1. Go to **Docker** → **Template Repositories**
2. Add: `https://github.com/tristenlammi/LogLibrarian`
3. Click **Save**

### Step 3: Install Containers

1. Go to **Docker** → **Add Container**
2. Select **LogLibrarian** template
3. Configure the database URLs to point to your installed services
4. Repeat for **LogLibrarian-Dashboard**

---

## Network Configuration

All containers should be on the same Docker network to communicate:

```bash
# Create a custom network
docker network create loglibrarian

# Then add --network=loglibrarian to each container
```

Or use Unraid's built-in `br0` network with static IPs.

---

## Environment Variables

### Backend (Required)
| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | TimescaleDB connection | `postgresql://postgres:password@timescaledb:5432/loglibrarian` |
| `REDIS_URL` | Redis connection | `redis://redis:6379` |
| `SECRET_KEY` | JWT signing key | Random 32+ character string |
| `USE_POSTGRES` | Enable PostgreSQL mode | `true` |

### Backend (Optional)
| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity | `INFO` |

### Dashboard
| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_API_URL` | Backend API URL | `http://unraid-ip:8000` |

---

## Data Persistence

Map these volumes for data persistence:

| Container | Path | Purpose |
|-----------|------|---------|
| Backend | `/data` | Local data |
| TimescaleDB | `/var/lib/postgresql/data` | Database files |
| Redis | `/data` | Cache persistence |

Recommended location: `/mnt/user/appdata/loglibrarian/`

---

## Ports

| Service | Port | Purpose |
|---------|------|---------|
| Dashboard | 3000 | Web UI |
| Backend | 8000 | API & WebSocket |
| TimescaleDB | 5432 | Database (internal only) |
| Redis | 6379 | Cache (internal only) |

Only expose 3000 (dashboard) and 8000 (backend) externally.
