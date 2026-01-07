# LogLibrarian: Project Overview & Architecture

## 1. Core Concept
LogLibrarian is a distributed monitoring system. It consists of lightweight Agents that sit on servers/PCs, and a central Librarian (Server) that ingests data, visualizes it, and uses LLMs to explain error logs to the user.

## 2. The Stack

### A. The Agent ("Scribe")
**Language:** Go (Golang)

**Key Libraries:**
- `shirou/gopsutil`: For reading CPU, RAM, Disk, Network counters.
- `kardianos/service`: For self-installing as a background service (Systemd/Windows Service).
- `gorilla/websocket`: For real-time streaming (Planned).

**Behavior:**
- **Passive Mode (Default):** Collects metrics every 1s, buffers them, and HTTP POSTs a batch every 60s to save bandwidth.
- **Active Mode (Live):** When requested by Server, opens a WebSocket and streams metrics every 1s.

### B. The Backend ("The Library")
**Language:** Python 3.11+

**Framework:** FastAPI

**Database:** SQLite (dev) / PostgreSQL (prod).

**Vector DB:** Qdrant (for semantic search of error logs).

**API Structure:**
- `POST /ingest/heartbeat`: Receives bulk metrics.
- `POST /ingest/logs`: Receives raw text logs.
- `WS /ws/agent/{id}`: WebSocket endpoint for agents.
- `WS /ws/ui/{id}`: WebSocket endpoint for the Frontend dashboard.

### C. The Frontend ("The Dashboard")
**Framework:** Vue.js 3 (Composition API).

**Build Tool:** Vite.

**Styling:** Bootstrap 5 (Heavily customized CSS variables for "Dark Theme").

**Visualization:**
- **Chart.js:** For time-series data (CPU history).
- **Vue Flow:** For the Network Topology Map.

## 3. Data Strategy & Schema

### Metrics (Time Series)
We do not store every second of data forever.

- **Hot Storage:** 1-second resolution for 24 hours.
- **Warm Storage:** 1-minute resolution (Averages) for 30 days.
- **Cold Storage:** 1-hour resolution for 1 year.

### Processes (Snapshots)
We do not track every process.

- **The "Top 10" Rule:** The agent sorts processes by CPU usage and only sends the Top 10.
- **Frequency:** Every 30 seconds.

## 4. Current Feature Status

| Feature           | Status      | Notes                          |
|-------------------|-------------|--------------------------------|
| Agent Installer   | ✅ Done     | Works on Linux/Windows.        |
| Basic Metrics     | ✅ Done     | CPU, RAM, Disk, Network I/O.   |
| Dashboard UI      | ✅ Done     | Uptime Kuma clone style.       |
| Real-Time WS      | 🚧 Planned  | Next Priority.                 |
| Process List      | 🚧 Planned  | Needs "Time Machine" slider.   |
| Network Map       | 📝 Draft    | Vue Flow logic pending.        |
| AI Log Analysis   | 📝 Draft    | Qdrant integration pending.    |
