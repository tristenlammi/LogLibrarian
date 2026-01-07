# LogLibrarian

**Self-hosted, AI-powered log analysis and troubleshooting platform**

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Scribe    │─────▶│  Librarian   │◀────▶│  Dashboard  │
│  (Go Agent) │      │ (Python API) │      │  (Vue.js)   │
└─────────────┘      └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │   Qdrant    │
                     │ (Vector DB) │
                     └─────────────┘
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
- Qdrant: http://localhost:6333

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

### 1. Qdrant (Vector Database)

```bash
docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage:z \
    qdrant/qdrant
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
- Server status cards
- Recent log activity
- Statistics overview

### 2. Chat with AI
Navigate to **"Librarian"** (🤖) in the sidebar to ask questions:
- "Show me recent errors"
- "What servers are having issues?"
- "Summarize today's activity"

### 3. Monitor Agents
Go to **"Agents"** (🖥️) to see connected Scribe instances.

### 4. Browse Logs
Use **"Logs"** (📝) to search and filter log templates.

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

- **Qdrant (Vector DB)**: Stores unique log templates as embeddings for semantic search
- **SQLite**: Stores individual log occurrences with timestamps and variables
- **AI Model**: Uses `all-MiniLM-L6-v2` for embeddings (local, no API keys needed)

## Tech Stack

| Component  | Technology |
|------------|------------|
| Agent      | Go 1.21+ |
| Backend    | Python 3.10, FastAPI |
| Frontend   | Vue.js 3, Vite, Bootstrap 5 |
| Vector DB  | Qdrant |
| Embeddings | Sentence Transformers |
| AI (TODO)  | Ollama (local LLM) |

## Troubleshooting

### Backend won't start
```bash
# Check Qdrant is running
curl http://localhost:6333/collections

# Check Python dependencies
pip install -r librarian/requirements.txt
```

### Dashboard shows "AI Not Connected Yet"
The Ollama integration is pending. The backend returns a placeholder response.

### Scribe agent can't connect
Ensure the backend is running and update `serverURL` in `scribe/main.go`.

### Port conflicts
Edit `docker-compose.yml` to change ports:
```yaml
ports:
  - "8001:8000"  # Change 8000 to 8001
```

## Production Deployment

### Environment Variables

Create `.env` files:

**librarian/.env:**
```
QDRANT_HOST=qdrant
QDRANT_PORT=6333
SQLITE_DB_PATH=/data/loglibrarian.db
```

**dashboard/.env:**
```
VITE_API_URL=https://your-backend.com
```

### Security Hardening

1. **Enable authentication** (add JWT to backend)
2. **Use HTTPS** (add nginx/traefik reverse proxy)
3. **Restrict CORS** (update `allow_origins` in `librarian/main.py`)
4. **Set resource limits** in docker-compose

## Development Roadmap

- [x] Scribe agent with semantic compression
- [x] Backend API with vector storage
- [x] Dashboard with Uptime Kuma theme
- [x] Real-time chat interface
- [ ] Ollama LLM integration
- [ ] WebSocket real-time updates
- [ ] Agent health monitoring
- [ ] Alert rules and notifications
- [ ] Multi-tenant support
- [ ] Grafana-style query builder

## License

MIT License - See LICENSE file for details

## Support

Create an issue on GitHub for bugs or feature requests.
