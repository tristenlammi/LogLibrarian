package main

import (
	"fmt"
	"log"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// ReconnectConfig holds reconnection settings
type ReconnectConfig struct {
	InitialDelay time.Duration // First retry delay (default: 5s)
	MaxDelay     time.Duration // Maximum delay (default: 5 minutes)
	Multiplier   float64       // Backoff multiplier (default: 2.0)
	JitterFactor float64       // Random jitter 0-1 (default: 0.1)
}

// DefaultReconnectConfig returns sensible defaults
func DefaultReconnectConfig() ReconnectConfig {
	return ReconnectConfig{
		InitialDelay: 5 * time.Second,
		MaxDelay:     5 * time.Minute,
		Multiplier:   2.0,
		JitterFactor: 0.1,
	}
}

// ReconnectManager handles WebSocket reconnection with exponential backoff
type ReconnectManager struct {
	config      ReconnectConfig
	attempt     int
	lastAttempt time.Time
	mu          sync.Mutex
	isConnected bool

	// Statistics
	totalAttempts      int64
	successfulConnects int64
	failedConnects     int64
	totalDowntime      time.Duration
	lastDisconnect     time.Time
}

// NewReconnectManager creates a new reconnection manager
func NewReconnectManager(cfg ReconnectConfig) *ReconnectManager {
	return &ReconnectManager{
		config: cfg,
	}
}

// GetNextDelay calculates the next retry delay with exponential backoff and jitter
func (r *ReconnectManager) GetNextDelay() time.Duration {
	r.mu.Lock()
	defer r.mu.Unlock()

	// Calculate base delay with exponential backoff
	delay := float64(r.config.InitialDelay) * math.Pow(r.config.Multiplier, float64(r.attempt))

	// Cap at max delay
	if delay > float64(r.config.MaxDelay) {
		delay = float64(r.config.MaxDelay)
	}

	// Add jitter (±jitterFactor%)
	if r.config.JitterFactor > 0 {
		jitter := delay * r.config.JitterFactor * (2*rand.Float64() - 1)
		delay += jitter
	}

	r.attempt++
	r.totalAttempts++
	r.lastAttempt = time.Now()

	return time.Duration(delay)
}

// Reset resets the backoff state (call after successful connection)
func (r *ReconnectManager) Reset() {
	r.mu.Lock()
	defer r.mu.Unlock()

	if !r.isConnected && !r.lastDisconnect.IsZero() {
		r.totalDowntime += time.Since(r.lastDisconnect)
	}

	r.attempt = 0
	r.isConnected = true
	r.successfulConnects++
	log.Printf("✓ Connection established (attempt %d)", r.totalAttempts)
}

// OnDisconnect records a disconnection
func (r *ReconnectManager) OnDisconnect() {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.isConnected = false
	r.lastDisconnect = time.Now()
	r.failedConnects++
}

// GetStats returns reconnection statistics
func (r *ReconnectManager) GetStats() map[string]interface{} {
	r.mu.Lock()
	defer r.mu.Unlock()

	return map[string]interface{}{
		"current_attempt":     r.attempt,
		"total_attempts":      r.totalAttempts,
		"successful_connects": r.successfulConnects,
		"failed_connects":     r.failedConnects,
		"total_downtime":      r.totalDowntime.String(),
		"is_connected":        r.isConnected,
	}
}

// IsConnected returns current connection state
func (r *ReconnectManager) IsConnected() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.isConnected
}

// HealthFileWriter manages the local health file for external monitoring
type HealthFileWriter struct {
	filePath string
	interval time.Duration
	stopCh   chan struct{}
	wg       sync.WaitGroup
	mu       sync.Mutex
	running  bool

	// Additional health info
	lastWrite   time.Time
	writeCount  int64
	writeErrors int64
	isOnline    bool
	bufferCount int
}

// NewHealthFileWriter creates a health file writer
func NewHealthFileWriter(dataDir string, interval time.Duration) *HealthFileWriter {
	if interval == 0 {
		interval = time.Minute
	}

	// Health file path
	filePath := filepath.Join(dataDir, "scribe_health.json")

	return &HealthFileWriter{
		filePath: filePath,
		interval: interval,
		stopCh:   make(chan struct{}),
	}
}

// Start begins writing health file
func (h *HealthFileWriter) Start() {
	h.mu.Lock()
	if h.running {
		h.mu.Unlock()
		return
	}
	h.running = true
	h.mu.Unlock()

	h.wg.Add(1)
	go h.writeLoop()

	log.Printf("✓ Health file writer started: %s (every %v)", h.filePath, h.interval)
}

// Stop stops the health file writer
func (h *HealthFileWriter) Stop() {
	h.mu.Lock()
	if !h.running {
		h.mu.Unlock()
		return
	}
	h.running = false
	h.mu.Unlock()

	close(h.stopCh)
	h.wg.Wait()

	// Final write
	h.writeHealth()
	log.Printf("✓ Health file writer stopped")
}

// writeLoop periodically writes health file
func (h *HealthFileWriter) writeLoop() {
	defer h.wg.Done()

	// Initial write
	h.writeHealth()

	ticker := time.NewTicker(h.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			h.writeHealth()
		case <-h.stopCh:
			return
		}
	}
}

// SetStatus updates connection status
func (h *HealthFileWriter) SetStatus(online bool, bufferCount int) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.isOnline = online
	h.bufferCount = bufferCount
}

// writeHealth writes the health file
func (h *HealthFileWriter) writeHealth() {
	h.mu.Lock()
	isOnline := h.isOnline
	bufferCount := h.bufferCount
	h.mu.Unlock()

	status := "online"
	if !isOnline {
		status = "offline"
	}

	health := struct {
		Timestamp   string `json:"timestamp"`
		Status      string `json:"status"`
		AgentID     string `json:"agent_id"`
		Hostname    string `json:"hostname"`
		BufferCount int    `json:"buffer_count"`
		Uptime      string `json:"uptime"`
		PID         int    `json:"pid"`
	}{
		Timestamp:   time.Now().UTC().Format(time.RFC3339),
		Status:      status,
		AgentID:     agentID,
		Hostname:    hostname,
		BufferCount: bufferCount,
		Uptime:      time.Since(startTime).Round(time.Second).String(),
		PID:         os.Getpid(),
	}

	data := fmt.Sprintf(`{
  "timestamp": "%s",
  "status": "%s",
  "agent_id": "%s",
  "hostname": "%s",
  "buffer_count": %d,
  "uptime": "%s",
  "pid": %d
}`,
		health.Timestamp,
		health.Status,
		health.AgentID,
		health.Hostname,
		health.BufferCount,
		health.Uptime,
		health.PID,
	)

	err := os.WriteFile(h.filePath, []byte(data), 0644)

	h.mu.Lock()
	if err != nil {
		h.writeErrors++
		if h.writeErrors <= 3 {
			log.Printf("⚠️ Failed to write health file: %v", err)
		}
	} else {
		h.lastWrite = time.Now()
		h.writeCount++
	}
	h.mu.Unlock()
}

// GetFilePath returns the health file path
func (h *HealthFileWriter) GetFilePath() string {
	return h.filePath
}

// Global start time for uptime calculation
var startTime = time.Now()

// GracefulShutdown handles agent shutdown with buffer flush
type GracefulShutdown struct {
	buffer       *OfflineBuffer
	reconnect    *ReconnectManager
	healthWriter *HealthFileWriter
	mu           sync.Mutex
	shuttingDown bool
}

// NewGracefulShutdown creates a shutdown handler
func NewGracefulShutdown(buffer *OfflineBuffer, reconnect *ReconnectManager, health *HealthFileWriter) *GracefulShutdown {
	return &GracefulShutdown{
		buffer:       buffer,
		reconnect:    reconnect,
		healthWriter: health,
	}
}

// Shutdown performs graceful shutdown
func (g *GracefulShutdown) Shutdown() error {
	g.mu.Lock()
	if g.shuttingDown {
		g.mu.Unlock()
		return nil
	}
	g.shuttingDown = true
	g.mu.Unlock()

	log.Println("🛑 Starting graceful shutdown...")

	// 1. Stop health writer
	if g.healthWriter != nil {
		g.healthWriter.Stop()
	}

	// 2. Flush buffer to disk
	if g.buffer != nil {
		log.Println("📦 Flushing buffer to disk...")
		if err := g.buffer.FlushToDisk(); err != nil {
			log.Printf("⚠️ Buffer flush error: %v", err)
		}

		stats := g.buffer.GetStats()
		log.Printf("📦 Buffer stats at shutdown: memory=%d, disk=%d, total_buffered=%d",
			stats.MemoryEntries, stats.DiskEntries, stats.TotalBuffered)

		// Save state file
		statePath := filepath.Join(filepath.Dir(g.buffer.dbPath), "scribe_state.json")
		if err := g.buffer.SaveState(statePath); err != nil {
			log.Printf("⚠️ Failed to save state: %v", err)
		}

		// Close database
		if err := g.buffer.Close(); err != nil {
			log.Printf("⚠️ Failed to close buffer DB: %v", err)
		}
	}

	// 3. Log reconnect stats
	if g.reconnect != nil {
		stats := g.reconnect.GetStats()
		log.Printf("📊 Reconnect stats: attempts=%v, success=%v, failed=%v, downtime=%v",
			stats["total_attempts"],
			stats["successful_connects"],
			stats["failed_connects"],
			stats["total_downtime"],
		)
	}

	log.Println("✓ Graceful shutdown complete")
	return nil
}

// IsShuttingDown returns whether shutdown is in progress
func (g *GracefulShutdown) IsShuttingDown() bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.shuttingDown
}
