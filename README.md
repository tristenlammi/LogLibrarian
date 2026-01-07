# LogLibrarian

**Self-hosted infrastructure monitoring platform for uptime tracking, metrics collection, and centralized log management**

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Scribe    │─────▶│  Librarian   │◀────▶│  Dashboard  │
│  (Go Agent) │ WS   │ (Python API) │      │  (Vue.js)   │
└─────────────┘      └──────────────┘      └─────────────┘
       │                    │
       │              ┌─────┴─────┐
       │              │           │
       ▼              ▼           ▼
   Metrics      ┌──────────┐  ┌───────┐
   & Logs       │TimescaleDB│  │ Redis │
                └──────────┘  └───────┘
```

## Quick Start (Docker)

### Prerequisites
- Docker & Docker Compose
- 4GB+ RAM recommended

### Start the Platform

```bash
# Clone or navigate to the project
cd LogLibrarian

# Start all services (use 'docker compose' without hyphen for modern Docker)
docker compose up -d

# Or if you have older docker-compose:
# docker-compose up -d

# Check status
docker compose ps
```

**Services will be available at:**
- Dashboard: http://localhost:3000
- Backend API: http://localhost:8000

### Stop the Platform

```bash
docker compose down
```

---

## Installing Agents

After starting the platform, install the Scribe monitoring agent on your target systems.

### Quick Install

**Linux:**
```bash
cd scribe
sudo ./install-linux.sh
```

**Windows (PowerShell as Administrator):**
```powershell
cd scribe
.\install-windows.ps1
```

The installation script will:
1. Build the agent binary
2. Install as a system service (systemd/Windows Service)
3. Configure connection to LogLibrarian backend
4. Start collecting metrics and logs

### Documentation

- **[Quick Start Guide](scribe/QUICKSTART.md)** - Fast installation for both platforms
- **[Comprehensive Installation Guide](AGENT_INSTALLATION.md)** - Detailed manual installation
- **[Deployment Checklist](DEPLOYMENT_CHECKLIST.md)** - Production deployment guide
- **[Docker Deployment](DOCKER_DEPLOYMENT.md)** - Run agents in containers

### Verify Installation

1. Check service status:
   ```bash
   # Linux
   sudo systemctl status scribe
   
   # Windows
   Get-Service Scribe
   ```

2. Open dashboard at http://localhost:3000
3. Verify your agent appears in the agents list
4. Check that metrics and logs are streaming

---

## Development Setup

### 1. Database Services

```bash
# Start TimescaleDB and Redis
docker compose up -d timescaledb redis
```

### 2. Librarian Backend (Python)

```bash
cd librarian

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py
```

**Backend will run on:** http://localhost:8000

**API Endpoints:**
- `GET /health` - Health check
- `POST /ingest` - Receive logs from Scribe agents
- `POST /ask` - Ask AI questions about logs

### 3. Dashboard (Vue.js)

```bash
cd dashboard

# Install dependencies
npm install

# Run dev server
npm run dev
```

**Dashboard will run on:** http://localhost:3000

### 4. Scribe Agent (Go)

The Scribe agent runs on your servers to collect logs.

#### Build for All Platforms

```bash
cd scribe

# Build for all platforms
make all

# Or use the build script
chmod +x build.sh
./build.sh
```

This creates:
- `bin/scribe.exe` (Windows)
- `bin/scribe-linux` (Linux)
- `bin/scribe-mac-intel` (macOS Intel)
- `bin/scribe-mac-arm` (macOS M1/M2)

#### Install as System Service

**Linux (systemd):**
```bash
sudo ./scribe-linux -install
sudo ./scribe-linux -start
```

**Windows:**
```cmd
scribe.exe -install
scribe.exe -start
```

**macOS:**
```bash
sudo ./scribe-mac-arm -install
sudo ./scribe-mac-arm -start
```

#### Uninstall Service

```bash
sudo ./scribe-linux -uninstall
```

#### Run Standalone (No Service)

```bash
./scribe-linux
```

**Configuration:**
- Edit `main.go` to change:
  - `logFilePath` - Path to log file (default: `./test.log`)
  - `serverURL` - Backend endpoint (default: `http://localhost:8000/ingest`)
  - `batchSize` - Logs per batch (default: 50)
  - `batchInterval` - Send interval (default: 5 seconds)

## Usage

### 1. View Dashboard
Open http://localhost:3000 to see:
- Server status cards with real-time metrics
- CPU, RAM, disk, and network usage
- Uptime tracking and alerts

### 2. Monitor Agents
Go to **"Agents"** to see all connected Scribe instances with:
- Live metrics streaming
- Historical data graphs
- System information

### 3. Browse Logs
Use **"Logs"** to search and filter collected logs by:
- Severity level
- Time range
- Agent/server

### 4. Configure Alerts
Set up alert rules to get notified when:
- Servers go offline
- CPU/RAM exceeds thresholds
- Disk space runs low

## How It Works

### Semantic Compression

The Scribe agent compresses logs before sending:

**Input:**
```
2025-12-25 10:00:00 [ERROR] Connection from 192.168.1.5 failed on port 80
```

**Output:**
```json
{
  "template_id": "a1b2c3d4...",
  "template_text": "[ERROR] Connection from <IP> failed on port <NUM>",
  "variables": ["192.168.1.5", "80"],
  "timestamp": "2025-12-25T10:00:00Z"
}
```

### Storage Strategy

- **TimescaleDB**: Time-series optimized PostgreSQL for metrics and logs
- **Redis**: Message queue for high-throughput metric ingestion
- **Automatic Compression**: TimescaleDB compresses older data automatically

## Tech Stack

| Component  | Technology |
|------------|------------|
| Agent      | Go 1.21+ |
| Backend    | Python 3.10, FastAPI |
| Frontend   | Vue.js 3, Vite, Bootstrap 5 |
| Database   | TimescaleDB (PostgreSQL) |
| Cache      | Redis |

## Troubleshooting

### Backend won't start
```bash
# Check database is running
docker compose ps

# Check logs
docker compose logs librarian
```

### Agent not appearing in dashboard
1. Check the agent service is running
2. Verify the backend URL in the agent's `config.json`
3. Check firewall allows port 8000

### Port conflicts
Edit `docker-compose.yml` to change ports:
```yaml
ports:
  - "8001:8000"  # Change 8000 to 8001
```

## Production Deployment

### Environment Variables

Create a `.env` file in the project root:

```bash
# Required - change in production!
SECRET_KEY=your-random-secret-key-here

# Optional - database password
POSTGRES_PASSWORD=your-secure-password
```

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Security Hardening

1. **Enable authentication** (add JWT to backend)
2. **Use HTTPS** (add nginx/traefik reverse proxy)
3. **Restrict CORS** (update `allow_origins` in `librarian/main.py`)
4. **Set resource limits** in docker-compose

## Features

- [x] Real-time metrics collection (CPU, RAM, disk, network)
- [x] WebSocket live updates
- [x] Uptime monitoring with historical tracking
- [x] Centralized log aggregation
- [x] Alert rules with webhook notifications
- [x] Multi-agent support
- [x] Docker deployment with pre-built images
- [x] TimescaleDB for efficient time-series storage
- [ ] Multi-tenant support
- [ ] Email notifications
- [ ] Grafana integration

## License

MIT License - See LICENSE file for details

## Support

Create an issue on GitHub for bugs or feature requests.
