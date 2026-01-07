# Agent Upgrade: Processes & Public IP

## Summary
Upgraded the Scribe agent to collect process information, public IP address, and system load average.

---

## New Data Structures

### ProcessInfo Struct
```go
type ProcessInfo struct {
    PID         int32   `json:"pid"`
    Name        string  `json:"name"`
    CPUPercent  float64 `json:"cpu_percent"`
    RAMPercent  float64 `json:"ram_percent"`
}
```

### Updated HeartbeatPayload
```go
type HeartbeatPayload struct {
    AgentID    string        `json:"agent_id"`
    Hostname   string        `json:"hostname"`
    Metrics    []MetricPoint `json:"metrics"`
    Status     string        `json:"status"`
    LastSeenAt time.Time     `json:"last_seen_at"`
    Processes  []ProcessInfo `json:"processes"`    // NEW
    PublicIP   string        `json:"public_ip"`    // NEW
    LoadAvg    float64       `json:"load_avg"`     // NEW
}
```

---

## New Functions

### 1. CollectTopProcesses()
**Purpose:** Scans all running processes, sorts by CPU usage, returns top 10

**Logic:**
```go
func CollectTopProcesses() ([]ProcessInfo, error)
```
- Iterates through all system processes
- Collects PID, Name, CPU%, RAM%
- Sorts by CPU usage (descending)
- Returns top 10 processes

**Performance:** Heavy operation, runs every 30 seconds in separate goroutine

### 2. FetchPublicIP()
**Purpose:** Queries external service to get public IP address

**Logic:**
```go
func FetchPublicIP() (string, error)
```
- Queries `https://api.ipify.org?format=text`
- 5-second timeout
- Returns IP as string

**Performance:** Network call, runs every 5 minutes in separate goroutine

### 3. CollectLoadAvg()
**Purpose:** Gets system load average (15-minute)

**Logic:**
```go
func CollectLoadAvg() (float64, error)
```
- Uses gopsutil `load.Avg()`
- Returns Load15 (15-minute load average)

**Performance:** Fast operation, collected every 30 seconds alongside processes

---

## Goroutine Architecture

### Main Metrics Loop (1 second intervals)
- Collects CPU, RAM, network, disk, temp, ping
- Buffers metrics for 10 seconds
- Sends heartbeat every 10 seconds

### Process Scanner (30 second intervals)
```go
go func() {
    processTicker := time.NewTicker(30 * time.Second)
    for {
        select {
        case <-processTicker.C:
            // Collect top 10 processes
            // Update load average
        case <-shutdown:
            return
        }
    }
}()
```

### Public IP Fetcher (5 minute intervals)
```go
go func() {
    ipTicker := time.NewTicker(5 * time.Minute)
    for {
        select {
        case <-ipTicker.C:
            // Fetch public IP
            // Detect IP changes
        case <-shutdown:
            return
        }
    }
}()
```

---

## Thread Safety

### Shared Variables (Protected by Mutex)
```go
var (
    topProcesses   []ProcessInfo
    currentPublicIP string
    currentLoadAvg  float64
    processMutex   sync.RWMutex
)
```

### Read Pattern (in SendHeartbeat)
```go
processMutex.RLock()
processes := topProcesses
publicIP := currentPublicIP
loadAvg := currentLoadAvg
processMutex.RUnlock()
```

### Write Pattern (in goroutines)
```go
processMutex.Lock()
topProcesses = newProcesses
processMutex.Unlock()
```

---

## Data Transmission

### Heartbeat Frequency
- Metrics: Every 10 seconds (buffered from 10x 1s samples)
- Processes: Latest top 10 (updated every 30s, sent every 10s)
- Public IP: Latest IP (updated every 5min, sent every 10s)
- Load Average: Latest 15min load (updated every 30s, sent every 10s)

**Note:** Processes, IP, and load average repeat across multiple heartbeats until updated.

---

## Example Heartbeat Payload

```json
{
  "agent_id": "myserver-1735200000",
  "hostname": "myserver",
  "status": "online",
  "last_seen_at": "2025-12-26T10:00:00Z",
  "public_ip": "203.0.113.42",
  "load_avg": 1.45,
  "processes": [
    {
      "pid": 1234,
      "name": "chrome",
      "cpu_percent": 45.2,
      "ram_percent": 8.5
    },
    {
      "pid": 5678,
      "name": "python",
      "cpu_percent": 23.1,
      "ram_percent": 12.3
    }
    // ... 8 more processes
  ],
  "metrics": [
    {
      "timestamp": "2025-12-26T10:00:00Z",
      "cpu_percent": 45.2,
      "ram_percent": 62.8,
      // ... other metrics
    }
    // ... 9 more metric points
  ]
}
```

---

## New Dependencies

Add these to `go.mod`:
```bash
go get github.com/shirou/gopsutil/v3/process
go get github.com/shirou/gopsutil/v3/load
go mod tidy
```

### New Imports
```go
import (
    "io"                                     // NEW
    "sort"                                   // NEW
    "sync"                                   // NEW
    "github.com/shirou/gopsutil/v3/load"     // NEW
    "github.com/shirou/gopsutil/v3/process"  // NEW
)
```

---

## Logging Output

### On Startup
```
Initial baseline metrics collected
Initial top processes collected
Initial public IP: 203.0.113.42
Initial load average (15min): 1.45
Initial heartbeat sent - agent is online
```

### During Operation
```
Updated top 10 processes (leader: chrome @ 45.2% CPU)
Public IP changed: 203.0.113.42 -> 203.0.113.50
Heartbeat sent: 10 metrics, status=online
```

---

## Performance Considerations

### CPU Impact
- Main metrics: ~1% CPU (1s intervals)
- Process scan: ~5% CPU spike (30s intervals)
- IP fetch: Negligible (5min intervals)

### Memory Impact
- Top 10 processes: ~2KB
- Metrics buffer (10 points): ~5KB
- Total: <10KB additional memory

### Network Impact
- Heartbeat: ~15KB every 10s (includes processes)
- IP fetch: ~1KB every 5min
- Total: ~1.5KB/s average

---

## Build Instructions

```bash
cd scribe
go get github.com/shirou/gopsutil/v3/process
go get github.com/shirou/gopsutil/v3/load
go mod tidy
go build
```

Or use the Makefile:
```bash
cd scribe
make deps
make build
```

---

## Next Steps

1. ✅ Agent updated with process tracking, public IP, and load average
2. ⏳ Backend needs to handle new HeartbeatPayload fields
3. ⏳ Database schema needs tables for processes and agent metadata
4. ⏳ Frontend needs to display processes, IP, and load average

---

## Files Modified

- `scribe/metrics.go` - Added ProcessInfo struct, new collection functions, goroutines for 30s/5min tasks
