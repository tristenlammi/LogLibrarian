package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// OfflineBuffer manages metrics storage during network outages
// Features:
// - In-memory ring buffer for recent metrics
// - SQLite persistence for crash recovery
// - Automatic replay on reconnect
// - Configurable size limits
type OfflineBuffer struct {
	// Configuration
	maxMemoryEntries int           // Max entries in memory
	maxDiskSizeMB    int           // Max SQLite file size
	bufferDuration   time.Duration // How long to keep data
	dataDir          string        // Directory for SQLite file

	// In-memory buffer (ring buffer style)
	memBuffer    []BufferedMetric
	memBufferMux sync.RWMutex
	memHead      int // Next write position
	memCount     int // Current count

	// SQLite persistence
	db          *sql.DB
	dbPath      string
	dbMux       sync.Mutex
	diskEnabled bool

	// Statistics
	stats BufferStats
}

// BufferedMetric wraps a metric with metadata
type BufferedMetric struct {
	ID        int64         `json:"id"`
	Timestamp time.Time     `json:"timestamp"`
	AgentID   string        `json:"agent_id"`
	Hostname  string        `json:"hostname"`
	Metrics   MetricPoint   `json:"metrics"`
	Processes []ProcessInfo `json:"processes,omitempty"`
	LoadAvg   float64       `json:"load_avg"`
	PublicIP  string        `json:"public_ip"`
	Persisted bool          `json:"-"` // Whether saved to disk
}

// BufferStats tracks buffer usage
type BufferStats struct {
	MemoryEntries   int
	DiskEntries     int
	TotalBuffered   int64
	TotalReplayed   int64
	DroppedOldest   int64
	DiskWriteErrors int64
	LastBufferTime  time.Time
	LastReplayTime  time.Time
	EstimatedSizeMB float64
}

// BufferConfig holds buffer configuration
type BufferConfig struct {
	MaxMemoryEntries int           // Max entries in memory (default: 1800 = 1 hour at 2s intervals)
	MaxDiskSizeMB    int           // Max disk usage in MB (default: 50)
	BufferDuration   time.Duration // How long to keep data (default: 1 hour)
	DataDir          string        // Directory for persistence (default: same as executable)
	DiskEnabled      bool          // Enable disk persistence (default: true)
}

// DefaultBufferConfig returns sensible defaults
func DefaultBufferConfig() BufferConfig {
	// Default data dir is next to executable
	execPath, _ := os.Executable()
	dataDir := filepath.Dir(execPath)

	return BufferConfig{
		MaxMemoryEntries: 1800, // 1 hour at 2s intervals
		MaxDiskSizeMB:    50,
		BufferDuration:   time.Hour,
		DataDir:          dataDir,
		DiskEnabled:      true,
	}
}

// NewOfflineBuffer creates a new offline buffer
func NewOfflineBuffer(cfg BufferConfig) (*OfflineBuffer, error) {
	buf := &OfflineBuffer{
		maxMemoryEntries: cfg.MaxMemoryEntries,
		maxDiskSizeMB:    cfg.MaxDiskSizeMB,
		bufferDuration:   cfg.BufferDuration,
		dataDir:          cfg.DataDir,
		memBuffer:        make([]BufferedMetric, cfg.MaxMemoryEntries),
		diskEnabled:      cfg.DiskEnabled,
	}

	// Initialize SQLite if enabled
	if cfg.DiskEnabled {
		if err := buf.initDB(); err != nil {
			log.Printf("⚠️ Disk buffer disabled: %v", err)
			buf.diskEnabled = false
		}
	}

	return buf, nil
}

// initDB initializes the SQLite database
func (b *OfflineBuffer) initDB() error {
	b.dbPath = filepath.Join(b.dataDir, "scribe_buffer.db")

	var err error
	b.db, err = sql.Open("sqlite3", b.dbPath+"?_journal_mode=WAL&_synchronous=NORMAL")
	if err != nil {
		return fmt.Errorf("failed to open database: %w", err)
	}

	// Create table
	_, err = b.db.Exec(`
		CREATE TABLE IF NOT EXISTS buffered_metrics (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			timestamp DATETIME NOT NULL,
			agent_id TEXT NOT NULL,
			hostname TEXT NOT NULL,
			payload TEXT NOT NULL,
			created_at DATETIME DEFAULT CURRENT_TIMESTAMP
		);
		CREATE INDEX IF NOT EXISTS idx_timestamp ON buffered_metrics(timestamp);
	`)
	if err != nil {
		return fmt.Errorf("failed to create table: %w", err)
	}

	log.Printf("✓ Disk buffer initialized: %s", b.dbPath)
	return nil
}

// Add adds a metric to the buffer (called when offline)
func (b *OfflineBuffer) Add(metric BufferedMetric) error {
	metric.Timestamp = time.Now()

	// Add to memory buffer (ring buffer)
	b.memBufferMux.Lock()
	if b.memCount < b.maxMemoryEntries {
		b.memBuffer[b.memCount] = metric
		b.memCount++
	} else {
		// Ring buffer full - overwrite oldest
		b.memBuffer[b.memHead] = metric
		b.memHead = (b.memHead + 1) % b.maxMemoryEntries
		b.stats.DroppedOldest++
	}
	b.stats.MemoryEntries = b.memCount
	b.stats.TotalBuffered++
	b.stats.LastBufferTime = time.Now()
	b.memBufferMux.Unlock()

	// Persist to disk if enabled
	if b.diskEnabled {
		if err := b.persistToDisk(metric); err != nil {
			b.stats.DiskWriteErrors++
			log.Printf("⚠️ Disk write error: %v", err)
		}
	}

	return nil
}

// persistToDisk saves a metric to SQLite
func (b *OfflineBuffer) persistToDisk(metric BufferedMetric) error {
	b.dbMux.Lock()
	defer b.dbMux.Unlock()

	if b.db == nil {
		return errors.New("database not initialized")
	}

	// Check disk size limit
	if err := b.checkDiskSize(); err != nil {
		return err
	}

	// Serialize payload
	payload, err := json.Marshal(metric)
	if err != nil {
		return fmt.Errorf("failed to marshal metric: %w", err)
	}

	_, err = b.db.Exec(
		"INSERT INTO buffered_metrics (timestamp, agent_id, hostname, payload) VALUES (?, ?, ?, ?)",
		metric.Timestamp, metric.AgentID, metric.Hostname, string(payload),
	)
	if err != nil {
		return fmt.Errorf("failed to insert: %w", err)
	}

	b.stats.DiskEntries++
	return nil
}

// checkDiskSize ensures we don't exceed disk limits
func (b *OfflineBuffer) checkDiskSize() error {
	info, err := os.Stat(b.dbPath)
	if err != nil {
		return nil // File doesn't exist yet
	}

	sizeMB := float64(info.Size()) / (1024 * 1024)
	b.stats.EstimatedSizeMB = sizeMB

	if sizeMB > float64(b.maxDiskSizeMB) {
		// Delete oldest 10% of entries
		_, err := b.db.Exec(`
			DELETE FROM buffered_metrics 
			WHERE id IN (
				SELECT id FROM buffered_metrics 
				ORDER BY timestamp ASC 
				LIMIT (SELECT COUNT(*) / 10 FROM buffered_metrics)
			)
		`)
		if err != nil {
			return fmt.Errorf("failed to prune old entries: %w", err)
		}
		log.Printf("📦 Pruned old buffer entries (was %.1f MB)", sizeMB)
	}

	return nil
}

// GetBufferedMetrics retrieves all buffered metrics for replay
// Returns metrics in chronological order (oldest first)
func (b *OfflineBuffer) GetBufferedMetrics() []BufferedMetric {
	var result []BufferedMetric

	// First, get from disk (oldest data)
	if b.diskEnabled && b.db != nil {
		diskMetrics := b.getFromDisk()
		result = append(result, diskMetrics...)
	}

	// Then, get from memory (more recent data)
	b.memBufferMux.RLock()
	if b.memCount > 0 {
		// Extract in chronological order from ring buffer
		for i := 0; i < b.memCount; i++ {
			idx := (b.memHead + i) % b.maxMemoryEntries
			if b.memCount < b.maxMemoryEntries {
				idx = i
			}
			result = append(result, b.memBuffer[idx])
		}
	}
	b.memBufferMux.RUnlock()

	return result
}

// getFromDisk retrieves metrics from SQLite
func (b *OfflineBuffer) getFromDisk() []BufferedMetric {
	b.dbMux.Lock()
	defer b.dbMux.Unlock()

	if b.db == nil {
		return nil
	}

	rows, err := b.db.Query(
		"SELECT id, timestamp, agent_id, hostname, payload FROM buffered_metrics ORDER BY timestamp ASC",
	)
	if err != nil {
		log.Printf("⚠️ Failed to read from disk: %v", err)
		return nil
	}
	defer rows.Close()

	var result []BufferedMetric
	for rows.Next() {
		var id int64
		var timestamp time.Time
		var agentID, hostname, payload string

		if err := rows.Scan(&id, &timestamp, &agentID, &hostname, &payload); err != nil {
			continue
		}

		var metric BufferedMetric
		if err := json.Unmarshal([]byte(payload), &metric); err != nil {
			continue
		}
		metric.ID = id
		metric.Persisted = true
		result = append(result, metric)
	}

	return result
}

// ClearReplayed clears metrics that have been successfully sent
func (b *OfflineBuffer) ClearReplayed(count int) {
	// Clear memory buffer
	b.memBufferMux.Lock()
	if count >= b.memCount {
		b.memCount = 0
		b.memHead = 0
	} else {
		// Partial clear - advance head
		b.memHead = (b.memHead + count) % b.maxMemoryEntries
		b.memCount -= count
	}
	b.stats.MemoryEntries = b.memCount
	b.stats.TotalReplayed += int64(count)
	b.stats.LastReplayTime = time.Now()
	b.memBufferMux.Unlock()

	// Clear disk buffer
	if b.diskEnabled && b.db != nil {
		b.clearDiskBuffer()
	}
}

// clearDiskBuffer removes all persisted metrics
func (b *OfflineBuffer) clearDiskBuffer() {
	b.dbMux.Lock()
	defer b.dbMux.Unlock()

	if b.db == nil {
		return
	}

	_, err := b.db.Exec("DELETE FROM buffered_metrics")
	if err != nil {
		log.Printf("⚠️ Failed to clear disk buffer: %v", err)
		return
	}

	b.stats.DiskEntries = 0
	log.Printf("✓ Cleared disk buffer")
}

// GetStats returns buffer statistics
func (b *OfflineBuffer) GetStats() BufferStats {
	b.memBufferMux.RLock()
	defer b.memBufferMux.RUnlock()
	return b.stats
}

// Count returns current buffer entry count
func (b *OfflineBuffer) Count() int {
	b.memBufferMux.RLock()
	defer b.memBufferMux.RUnlock()
	return b.memCount + b.stats.DiskEntries
}

// IsEmpty returns true if buffer has no entries
func (b *OfflineBuffer) IsEmpty() bool {
	return b.Count() == 0
}

// FlushToDisk saves all memory buffer to disk (for graceful shutdown)
func (b *OfflineBuffer) FlushToDisk() error {
	if !b.diskEnabled || b.db == nil {
		return errors.New("disk buffer not enabled")
	}

	b.memBufferMux.RLock()
	toFlush := make([]BufferedMetric, b.memCount)
	for i := 0; i < b.memCount; i++ {
		idx := (b.memHead + i) % b.maxMemoryEntries
		if b.memCount < b.maxMemoryEntries {
			idx = i
		}
		toFlush[i] = b.memBuffer[idx]
	}
	b.memBufferMux.RUnlock()

	flushed := 0
	for _, metric := range toFlush {
		if !metric.Persisted {
			if err := b.persistToDisk(metric); err != nil {
				log.Printf("⚠️ Failed to flush metric: %v", err)
			} else {
				flushed++
			}
		}
	}

	if flushed > 0 {
		log.Printf("📦 Flushed %d metrics to disk", flushed)
	}

	return nil
}

// LoadFromDisk loads persisted metrics on startup
func (b *OfflineBuffer) LoadFromDisk() int {
	if !b.diskEnabled || b.db == nil {
		return 0
	}

	b.dbMux.Lock()
	defer b.dbMux.Unlock()

	var count int
	err := b.db.QueryRow("SELECT COUNT(*) FROM buffered_metrics").Scan(&count)
	if err != nil {
		return 0
	}

	if count > 0 {
		log.Printf("📦 Found %d buffered metrics from previous session", count)
		b.stats.DiskEntries = count
	}

	return count
}

// Close closes the database connection
func (b *OfflineBuffer) Close() error {
	if b.db != nil {
		return b.db.Close()
	}
	return nil
}

// PruneOld removes metrics older than buffer duration
func (b *OfflineBuffer) PruneOld() {
	cutoff := time.Now().Add(-b.bufferDuration)

	// Prune memory buffer
	b.memBufferMux.Lock()
	pruned := 0
	newCount := 0
	for i := 0; i < b.memCount; i++ {
		idx := (b.memHead + i) % b.maxMemoryEntries
		if b.memCount < b.maxMemoryEntries {
			idx = i
		}
		if b.memBuffer[idx].Timestamp.After(cutoff) {
			if newCount != i {
				newIdx := (b.memHead + newCount) % b.maxMemoryEntries
				if b.memCount < b.maxMemoryEntries {
					newIdx = newCount
				}
				b.memBuffer[newIdx] = b.memBuffer[idx]
			}
			newCount++
		} else {
			pruned++
		}
	}
	b.memCount = newCount
	b.stats.MemoryEntries = b.memCount
	b.memBufferMux.Unlock()

	// Prune disk buffer
	if b.diskEnabled && b.db != nil {
		b.dbMux.Lock()
		result, err := b.db.Exec("DELETE FROM buffered_metrics WHERE timestamp < ?", cutoff)
		if err == nil {
			deleted, _ := result.RowsAffected()
			if deleted > 0 {
				pruned += int(deleted)
				log.Printf("📦 Pruned %d old metrics from disk", deleted)
			}
		}
		b.dbMux.Unlock()
	}

	if pruned > 0 {
		log.Printf("📦 Pruned %d old metrics (older than %v)", pruned, b.bufferDuration)
	}
}

// EstimateSizeMB returns estimated memory usage
func (b *OfflineBuffer) EstimateSizeMB() float64 {
	b.memBufferMux.RLock()
	defer b.memBufferMux.RUnlock()

	// Rough estimate: ~2KB per metric
	memSizeMB := float64(b.memCount) * 2.0 / 1024.0
	return memSizeMB + b.stats.EstimatedSizeMB
}

// SaveState saves buffer state for debugging
func (b *OfflineBuffer) SaveState(path string) error {
	state := struct {
		Stats       BufferStats `json:"stats"`
		MemoryCount int         `json:"memory_count"`
		DiskPath    string      `json:"disk_path"`
		DiskEnabled bool        `json:"disk_enabled"`
	}{
		Stats:       b.GetStats(),
		MemoryCount: b.memCount,
		DiskPath:    b.dbPath,
		DiskEnabled: b.diskEnabled,
	}

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(path, data, 0644)
}
