# 🚀 Quick Start Guide - WebSocket Real-Time Streaming

## Prerequisites
- **Backend:** Python 3.11+, FastAPI, websockets
- **Agent:** Go 1.21+, gorilla/websocket v1.5.1
- **Frontend:** Node.js 18+, Vue 3, Chart.js

---

## 🏃 Startup Sequence

### 1. Start Backend (Librarian)
```bash
cd librarian
source venv/bin/activate  # If using venv
uvicorn main:app --reload
```

**Expected output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

**Test it:**
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy"}
```

---

### 2. Start Agent (Scribe)
```bash
cd scribe
go run .
```

**Expected output:**
```
2024/01/15 10:30:45 Metrics collection initialized
2024/01/15 10:30:45 Starting WebSocket connection to ws://localhost:8000/ws/agent/<uuid>
2024/01/15 10:30:45 WebSocket connected successfully
2024/01/15 10:30:45 Message listener started
2024/01/15 10:30:45 Metrics sender started (60s interval)
```

**Verify registration:**
```bash
curl http://localhost:8000/agents | jq
# Should show your agent with hostname, agent_id, etc.
```

---

### 3. Start Frontend (Dashboard)

#### Option A: Development Server
```bash
cd dashboard
npm install  # First time only
npm run dev
```

**Expected output:**
```
VITE v5.x.x  ready in XXX ms

➜  Local:   http://localhost:5173/
➜  Network: use --host to expose
```

#### Option B: Build for Production
```bash
cd dashboard
npm run build
npm run preview
```

---

## 🧪 Testing the WebSocket Connection

### Automated Test
```bash
./test-websocket.sh
```

### Manual Browser Test
1. Open http://localhost:5173
2. Open browser DevTools (F12) → Console
3. Run:
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/ui/<AGENT_ID>')
ws.onopen = () => console.log('Connected!')
ws.onmessage = (e) => console.log('Metrics:', JSON.parse(e.data))
ws.onclose = () => console.log('Disconnected')
```

Replace `<AGENT_ID>` with actual ID from:
```bash
curl http://localhost:8000/agents | jq -r '.[0].agent_id'
```

---

## 🎭 Demo Walkthrough

### Step 1: View Agent List
- Dashboard shows all connected agents in cards
- Each card displays: hostname, last_seen, uptime

### Step 2: Select an Agent
- Click on any agent card
- Dashboard fetches last 500 historical metrics
- WebSocket opens: `ws://localhost:8000/ws/ui/{agent_id}`
- Backend sends `start_stream` command to agent
- Agent switches to 1-second interval

### Step 3: Watch the Magic ✨
- **LIVE badge appears** (green with blinking dot)
- **Charts update in real-time** (every second)
- **CPU/RAM values refresh** instantly
- **Process table updates** (every 10 seconds)

### Step 4: Close Detail View
- Click "Close" button
- WebSocket disconnects
- Backend sends `stop_stream` to agent
- Agent returns to 60-second interval
- LIVE badge disappears

---

## 🔍 Debugging

### Check Backend Logs
```bash
# Backend should show:
INFO:     WebSocket connected: /ws/agent/<id>
INFO:     Agent registered: <hostname>
INFO:     WebSocket connected: /ws/ui/<id>
INFO:     Sent command to agent <id>: start_stream
```

### Check Agent Logs
```bash
# Agent should show:
WebSocket connected successfully
Received command: start_stream
Switching to fast mode: 1s interval
Sending heartbeat... (repeats every 1s)
```

### Check Browser Console
```javascript
// Should see:
WebSocket connected for agent: <id>
// And continuous metric objects
```

### Common Issues

#### Agent won't connect
- ✅ Check backend is running: `curl http://localhost:8000/health`
- ✅ Check Go dependencies: `cd scribe && go mod tidy`
- ✅ Verify WebSocket URL in agent config

#### UI won't show LIVE badge
- ✅ Check `wsConnected` ref in Vue DevTools
- ✅ Open browser console for WebSocket errors
- ✅ Verify agent ID is correct

#### Charts not updating
- ✅ Check `metricsData.value` is growing in Vue DevTools
- ✅ Verify WebSocket `onmessage` is firing
- ✅ Check for JSON parsing errors

---

## 📊 Performance Metrics

### Expected Behavior
- **Passive mode:** Agent sends every 60s (no UI watching)
- **Active mode:** Agent sends every 1s (UI connected)
- **Chart buffer:** Last 500 data points (~8 minutes at 1s interval)
- **WebSocket overhead:** ~200-500 bytes per message

### Monitoring
```bash
# Watch agent CPU usage
ps aux | grep scribe

# Watch backend connections
ss -tln | grep 8000

# Watch network traffic
sudo tcpdump -i lo port 8000 -vv
```

---

## 🎨 UI Features

### LIVE Badge
- **Color:** Green (Bootstrap `bg-success`)
- **Animation:** Pulsing glow + blinking dot
- **Duration:** 1.5s cycle
- **Visibility:** Only when `wsConnected === true`

### Chart Updates
- **Library:** Chart.js 4.x
- **Animation:** Disabled (for performance)
- **Update method:** Reactive `chartData` computed property
- **Buffer:** Auto-trims to 500 points

### Real-Time Stats
- **CPU Average:** Computed from all metrics in buffer
- **RAM Average:** Computed from all metrics in buffer
- **Load Average:** Latest value from most recent metric
- **Data Points:** Total count in buffer

---

## 🛠️ Configuration

### Backend (librarian/main.py)
```python
# No config needed - auto-detects connections
```

### Agent (scribe/main.go)
```go
// Adjust intervals
const (
    PassiveInterval = 60 * time.Second  // No UI watching
    ActiveInterval = 1 * time.Second    // UI connected
)
```

### Frontend (dashboard/.env)
```bash
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

---

## 🚢 Deployment Checklist

- [ ] Backend: Environment variables for production
- [ ] Agent: Systemd service for auto-restart
- [ ] Frontend: Build and serve static files
- [ ] WebSocket: Use WSS (secure) in production
- [ ] Firewall: Open port 8000 (or use reverse proxy)
- [ ] CORS: Configure allowed origins
- [ ] Authentication: Add JWT tokens to WebSocket

---

## 📚 Additional Resources

- [WebSocket Implementation Docs](./WEBSOCKET_IMPLEMENTATION.md)
- [Architecture Diagram](./WEBSOCKET_IMPLEMENTATION.md#architecture)
- [Message Flow](./WEBSOCKET_IMPLEMENTATION.md#message-flow)

---

**Ready to go!** 🎉 All three layers are fully integrated and operational.
