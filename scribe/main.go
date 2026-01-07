package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
	"github.com/hpcloud/tail"
	"github.com/kardianos/service"
)

const (
	defaultLogFilePath = "./test.log"
	defaultServerHost  = "127.0.0.1:8000"
	batchSize          = 50
	batchInterval      = 5 * time.Second

	// Metrics collection timing
	passiveCollectInterval = 2 * time.Second  // Collect every 2s in passive mode
	passiveSendInterval    = 60 * time.Second // Send buffer every 60s in passive mode
	activeTickerDur        = 1 * time.Second  // Active: 1s when UI watching (collect + send)
	activeMaxDuration      = 5 * time.Minute  // Max time allowed in active mode (failsafe)

	// Buffer limits (in-memory, for live streaming)
	maxBufferSize    = 150 // Max 5 minutes of data at 2s intervals (150 points)
	targetBufferSize = 30  // Target 30 points per send (1 minute at 2s intervals)
)

var (
	logFilePath          string
	serverHost           string
	currentServerAddress string // The address actually used for connection

	// Global configuration
	globalConfig     *Config
	globalConfigPath string // Path to config file for saving auth token
)

type BatchRequest struct {
	Logs []LogSchema `json:"logs"`
}

type Command struct {
	Command string                 `json:"command"`
	Params  map[string]interface{} `json:"params,omitempty"`
}

// ServerResponse handles various server responses including auth tokens
type ServerResponse struct {
	Command   string                 `json:"command,omitempty"`
	Params    map[string]interface{} `json:"params,omitempty"`
	AuthToken string                 `json:"auth_token,omitempty"`
	Error     string                 `json:"error,omitempty"`
	Message   string                 `json:"message,omitempty"`
}

var (
	buffer     []LogSchema
	bufferLock sync.Mutex
	shutdown   = make(chan struct{})
	wg         sync.WaitGroup
	logger     service.Logger

	// WebSocket connection
	wsConn      *websocket.Conn
	wsConnMutex sync.Mutex
	wsConnected bool

	// Ticker management for sending
	currentTicker    *time.Ticker
	tickerMutex      sync.Mutex
	currentTickerDur = passiveSendInterval
	tickerChanged    = make(chan time.Duration, 1)

	// Metrics buffer for passive mode
	metricsBufferMutex sync.Mutex
	metricsLocalBuffer []MetricPoint
	isActiveMode       bool
	activeModeMutex    sync.RWMutex
	activeStartTime    time.Time   // When active mode started (for timeout)
	activeTimeoutTimer *time.Timer // Timer for active mode timeout

	// Log collector instance
	logCollector *LogCollector

	// Channel to signal when agentID is ready (closed after first heartbeat registers)
	agentIDReady     = make(chan struct{})
	agentIDReadyOnce sync.Once

	// Resilience components
	offlineBuffer    *OfflineBuffer
	reconnectMgr     *ReconnectManager
	healthWriter     *HealthFileWriter
	gracefulShutdown *GracefulShutdown

	// Updater state
	updaterStarted bool
)

// initResilienceComponents initializes the offline buffer, reconnect manager, health writer, and graceful shutdown
func initResilienceComponents() {
	cfg := DefaultConfig()

	// Initialize offline buffer for metrics persistence
	if cfg.BufferEnabled {
		bufferCfg := cfg.GetBufferConfig()
		var err error
		offlineBuffer, err = NewOfflineBuffer(bufferCfg)
		if err != nil {
			log.Printf("⚠️ Failed to initialize offline buffer: %v", err)
		} else {
			stats := offlineBuffer.GetStats()
			log.Printf("📦 Offline buffer initialized (memory: %d entries, estimated: %.1f MB)",
				stats.MemoryEntries, stats.EstimatedSizeMB)
		}
	}

	// Initialize reconnect manager with exponential backoff
	reconnectCfg := cfg.GetReconnectConfig()
	reconnectMgr = NewReconnectManager(reconnectCfg)
	log.Printf("🔄 Reconnect manager initialized (initial: %v, max: %v)",
		reconnectCfg.InitialDelay, reconnectCfg.MaxDelay)

	// Initialize health file writer
	if cfg.HealthFileEnabled {
		healthWriter = NewHealthFileWriter(
			cfg.BufferDataDir,
			time.Duration(cfg.HealthFileIntervalSec)*time.Second,
		)
		log.Printf("💓 Health file writer initialized (interval: %ds)", cfg.HealthFileIntervalSec)
	}

	// Initialize graceful shutdown handler (pass the components)
	gracefulShutdown = NewGracefulShutdown(offlineBuffer, reconnectMgr, healthWriter)
}

// setupSignalHandlers sets up OS signal handlers for graceful shutdown
func setupSignalHandlers() {
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		log.Printf("📡 Received signal: %v", sig)
		close(shutdown)
	}()
}

// bufferPruneTask periodically prunes old entries from the offline buffer
func bufferPruneTask() {
	defer wg.Done()
	ticker := time.NewTicker(1 * time.Minute)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if offlineBuffer != nil {
				offlineBuffer.PruneOld()
			}
		case <-shutdown:
			return
		}
	}
}

// formatBytes formats bytes into human-readable string
func formatBytes(bytes int64) string {
	const unit = 1024
	if bytes < unit {
		return fmt.Sprintf("%d B", bytes)
	}
	div, exp := int64(unit), 0
	for n := bytes / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %cB", float64(bytes)/float64(div), "KMGTPE"[exp])
}

// getBufferCount returns the current offline buffer count for health status
func getBufferCount() int {
	if offlineBuffer != nil {
		return offlineBuffer.GetStats().MemoryEntries
	}
	return 0
}

// Program implements the service.Interface
type Program struct{}

func (p *Program) Start(s service.Service) error {
	// Start should not block. Do the actual work async.
	go p.run()
	return nil
}

func (p *Program) run() {
	log.Println("Starting Scribe agent...")
	log.Printf("Tailing log file: %s", logFilePath)
	log.Printf("WebSocket server: %s", serverHost)

	// Initialize resilience components
	initResilienceComponents()

	// Start background slow metrics collector (for 1-second active mode)
	StartSlowMetricsCollector()

	// Initialize system info first
	if err := GetSystemInfo(); err != nil {
		log.Printf("Warning: Could not get system info: %v", err)
	}

	// Load any buffered metrics from previous session
	if offlineBuffer != nil {
		count := offlineBuffer.LoadFromDisk()
		if count > 0 {
			log.Printf("📦 Loaded %d buffered metrics from previous session", count)
		}
	}

	// Start health file writer
	if healthWriter != nil {
		healthWriter.Start()
	}

	// Register agent with the server via HTTP (before WebSocket)
	if err := registerWithServer(); err != nil {
		log.Printf("⚠️ Registration error (will retry via WebSocket): %v", err)
	} else {
		log.Printf("✅ Agent registered successfully with ID: %s", agentID)
	}

	// Signal that agentID is ready (GetSystemInfo already called above)
	if agentID != "" {
		agentIDReadyOnce.Do(func() {
			close(agentIDReady)
		})
	}

	// Start WebSocket connection manager (handles metrics streaming)
	wg.Add(1)
	go func() {
		defer wg.Done()
		WebSocketManager()
	}()

	// Start the batch sender for logs
	wg.Add(1)
	go batchSender()

	// Start the file tailer
	wg.Add(1)
	go tailLogFile()

	// Start buffer pruning task (removes old metrics)
	wg.Add(1)
	go bufferPruneTask()

	// Start the system log collector (Module 3)
	// Waits for agentID to be ready via channel (no arbitrary sleep)
	go func() {
		// Wait for agentID to be set (up to 30 seconds)
		select {
		case <-agentIDReady:
			// agentID is ready, start the collector
		case <-time.After(30 * time.Second):
			log.Println("⚠️ Timeout waiting for agent ID, log collector not started")
			return
		case <-shutdown:
			return
		}

		if agentID != "" {
			// Get security log paths from config (empty slice if not set)
			var securityLogPaths []string
			if globalConfig != nil {
				securityLogPaths = globalConfig.SecurityLogPaths
			}
			logCollector = NewLogCollector(serverHost, agentID, securityLogPaths)
			logCollector.Start()
			log.Println("📋 Log collector started successfully")
		} else {
			log.Println("⚠️ Agent ID not set, log collector not started")
		}
	}()

	// Setup signal handlers for graceful shutdown
	setupSignalHandlers()

	// Wait for shutdown signal
	<-shutdown
	log.Println("Shutdown signal received...")

	// Perform graceful shutdown
	if gracefulShutdown != nil {
		gracefulShutdown.Shutdown()
	}

	// Stop log collector
	if logCollector != nil {
		logCollector.Stop()
	}

	// Close WebSocket connection
	wsConnMutex.Lock()
	if wsConn != nil {
		wsConn.Close()
	}
	wsConnMutex.Unlock()

	// Wait for goroutines to finish
	wg.Wait()

	// Final flush
	flushBuffer()
	log.Println("Scribe agent stopped.")
}

func (p *Program) Stop(s service.Service) error {
	// Stop should not block. Signal shutdown.
	close(shutdown)
	return nil
}

func main() {
	// Define command-line flags
	var (
		configPath = flag.String("config", "", "Path to configuration file")
		install    = flag.Bool("install", false, "Install the service")
		uninstall  = flag.Bool("uninstall", false, "Uninstall the service")
		start      = flag.Bool("start", false, "Start the service")
	)
	flag.Parse()

	// Load configuration
	var cfg *Config
	var err error

	if *configPath != "" {
		cfg, err = LoadConfig(*configPath)
		if err != nil {
			log.Fatalf("Failed to load config: %v", err)
		}
		globalConfigPath = *configPath
	} else {
		// Auto-detect config.json in working directory or executable directory
		possiblePaths := []string{
			"config.json",
			"./config.json",
		}
		// Also check next to executable
		if execPath, err := os.Executable(); err == nil {
			possiblePaths = append(possiblePaths, filepath.Join(filepath.Dir(execPath), "config.json"))
		}

		configFound := false
		for _, path := range possiblePaths {
			if _, err := os.Stat(path); err == nil {
				log.Printf("Auto-detected config file: %s", path)
				cfg, err = LoadConfig(path)
				if err != nil {
					log.Printf("Warning: Failed to load %s: %v", path, err)
					continue
				}
				globalConfigPath = path
				configFound = true
				break
			}
		}

		if !configFound {
			log.Println("No config.json found, using defaults")
			cfg = DefaultConfig()
			// Set default config path for saving auth token
			if execPath, err := os.Executable(); err == nil {
				globalConfigPath = filepath.Join(filepath.Dir(execPath), "config.json")
			} else {
				globalConfigPath = "config.json"
			}
		}
	}

	// Set global config reference
	globalConfig = cfg

	// Set global variables from config
	logFilePath = cfg.LogFile

	// Initialize system info BEFORE registration to get stable agent ID
	if err := GetSystemInfo(); err != nil {
		log.Printf("Warning: Could not get system info: %v", err)
	}

	// Determine prioritized server hosts
	prioritizedHosts := []string{}
	if len(cfg.ServerHosts) > 0 {
		prioritizedHosts = append(prioritizedHosts, cfg.ServerHosts...)
	}
	// Always add legacy serverHost if not already present
	if cfg.ServerHost != "" {
		found := false
		for _, h := range prioritizedHosts {
			if h == cfg.ServerHost {
				found = true
				break
			}
		}
		if !found {
			prioritizedHosts = append(prioritizedHosts, cfg.ServerHost)
		}
	}
	if len(prioritizedHosts) == 0 {
		prioritizedHosts = append(prioritizedHosts, defaultServerHost)
	}

	// Try to connect to each host in order, fallback if needed
	var connectErr error
	for _, h := range prioritizedHosts {
		log.Printf("Attempting to connect to server: %s", h)
		serverHost = h
		connectErr = registerWithServer()
		if connectErr == nil {
			log.Printf("Connected to server: %s", h)
			currentServerAddress = h
			// Set the agent's own local IP as the connection address (for display in dashboard)
			localIP := GetLocalIP()
			if localIP != "" {
				SetConnectionAddress(localIP)
				log.Printf("Agent local IP: %s", localIP)
			} else {
				SetConnectionAddress(h) // Fallback to server address if can't get local IP
			}
			break
		} else {
			log.Printf("Failed to connect to %s: %v", h, connectErr)
		}
	}
	if connectErr != nil {
		log.Fatalf("Could not connect to any server address: %v", connectErr)
	}

	log.Printf("Starting with config: server=%s, log=%s", serverHost, logFilePath)

	// Service configuration
	svcConfig := &service.Config{
		Name:        "LogLibrarianScribe",
		DisplayName: "LogLibrarian Scribe Agent",
		Description: "Lightweight log tailing agent that sends compressed logs to LogLibrarian",
	}

	prg := &Program{}
	s, err := service.New(prg, svcConfig)
	if err != nil {
		log.Fatal(err)
	}

	// Setup logger
	errs := make(chan error, 5)
	logger, err = s.Logger(errs)
	if err != nil {
		log.Fatal(err)
	}

	// Handle service control commands
	if *install {
		err := s.Install()
		if err != nil {
			log.Fatalf("Failed to install service: %v", err)
		}
		log.Println("Service installed successfully")
		return
	}

	if *uninstall {
		err := s.Uninstall()
		if err != nil {
			log.Fatalf("Failed to uninstall service: %v", err)
		}
		log.Println("Service uninstalled successfully")
		return
	}

	if *start {
		err := s.Start()
		if err != nil {
			log.Fatalf("Failed to start service: %v", err)
		}
		log.Println("Service started successfully")
		return
	}

	// Run the service
	err = s.Run()
	if err != nil {
		logger.Error(err)
	}
}

// tailLogFile tails the log file and processes each line
func tailLogFile() {
	defer wg.Done()

	// Configure tail
	config := tail.Config{
		Follow:    true,
		ReOpen:    true,
		MustExist: false,
		Poll:      true,
		Location:  &tail.SeekInfo{Offset: 0, Whence: 2}, // Start at end
	}

	// Open tail
	t, err := tail.TailFile(logFilePath, config)
	if err != nil {
		log.Fatalf("Failed to tail file: %v", err)
	}

	log.Printf("Successfully started tailing %s", logFilePath)

	// Process lines
	for {
		select {
		case line, ok := <-t.Lines:
			if !ok {
				return
			}
			if line.Err != nil {
				log.Printf("Error reading line: %v", line.Err)
				continue
			}

			// Compress the log line
			compressed := CompressLog(line.Text)

			// Add to buffer
			bufferLock.Lock()
			buffer = append(buffer, compressed)
			currentSize := len(buffer)
			bufferLock.Unlock()

			// Send if buffer is full
			if currentSize >= batchSize {
				sendBatch()
			}

		case <-shutdown:
			log.Println("Stopping log tailer...")
			t.Stop()
			return
		}
	}
}

// batchSender sends batches on a timer
func batchSender() {
	defer wg.Done()

	ticker := time.NewTicker(batchInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			sendBatch()
		case <-shutdown:
			return
		}
	}
}

// sendBatch sends the current buffer to the server
func sendBatch() {
	bufferLock.Lock()
	if len(buffer) == 0 {
		bufferLock.Unlock()
		return
	}

	// Copy buffer and reset
	toSend := make([]LogSchema, len(buffer))
	copy(toSend, buffer)
	buffer = buffer[:0]
	bufferLock.Unlock()

	// Send in background to avoid blocking
	go func(logs []LogSchema) {
		if err := sendLogsViaWebSocket(logs); err != nil {
			log.Printf("Failed to send batch: %v", err)
			// TODO: Implement retry logic or dead letter queue
		} else {
			log.Printf("Successfully sent batch of %d logs", len(logs))
		}
	}(toSend)
}

// flushBuffer sends any remaining logs in the buffer
func flushBuffer() {
	bufferLock.Lock()
	defer bufferLock.Unlock()

	if len(buffer) == 0 {
		return
	}

	log.Printf("Flushing %d remaining logs...", len(buffer))
	// Note: Logs are sent via WebSocket in real-time, so flush is minimal
	buffer = buffer[:0]
}

// WebSocketManager manages the WebSocket connection with auto-reconnect
func WebSocketManager() {
	for {
		select {
		case <-shutdown:
			log.Println("WebSocket manager shutting down...")
			return
		default:
			if err := connectAndStream(); err != nil {
				log.Printf("WebSocket connection error: %v", err)

				// Mark as disconnected
				wsConnMutex.Lock()
				wsConnected = false
				wsConnMutex.Unlock()

				// Update health status
				if healthWriter != nil {
					healthWriter.SetStatus(false, getBufferCount())
				}

				// Notify reconnect manager of disconnect
				if reconnectMgr != nil {
					reconnectMgr.OnDisconnect()
					delay := reconnectMgr.GetNextDelay()
					log.Printf("🔄 Reconnecting in %v...", delay)
					time.Sleep(delay)
				} else {
					// Fallback to fixed interval if reconnectMgr not initialized
					time.Sleep(5 * time.Second)
				}
			}
		}
	}
}

// connectAndStream establishes WebSocket connection and handles streaming
func connectAndStream() error {
	// Get WebSocket scheme based on SSL config
	wsScheme := "ws"
	if globalConfig != nil && globalConfig.SSLEnabled {
		wsScheme = "wss"
	}

	// Build WebSocket URL
	u := url.URL{
		Scheme: wsScheme,
		Host:   serverHost,
		Path:   fmt.Sprintf("/api/ws/agent/%s", agentID),
	}

	log.Printf("Connecting to WebSocket: %s", u.String())

	// Configure WebSocket dialer with TLS settings
	dialer := websocket.DefaultDialer
	if globalConfig != nil && globalConfig.SSLEnabled {
		dialer = &websocket.Dialer{
			TLSClientConfig: &tls.Config{
				InsecureSkipVerify: !globalConfig.SSLVerify,
			},
			HandshakeTimeout: 45 * time.Second,
		}
	}

	// Dial WebSocket
	conn, _, err := dialer.Dial(u.String(), nil)
	if err != nil {
		return fmt.Errorf("dial error: %w", err)
	}

	// Store connection
	wsConnMutex.Lock()
	wsConn = conn
	wsConnected = true
	wsConnMutex.Unlock()

	log.Println("✅ WebSocket connected successfully")

	// Reset reconnect manager (exponential backoff reset on success)
	if reconnectMgr != nil {
		reconnectMgr.Reset()
	}

	// Force system info to be sent on first heartbeat of new connection
	ResetSysInfoSentTime()

	// Reset to passive mode on new connection (server will send start_stream if UI is watching)
	setActiveMode(false)

	// Start background updater (checks for agent updates periodically) - only once
	if !updaterStarted {
		updaterStarted = true
		StartBackgroundUpdater(serverHost)
	}

	// Update health status
	if healthWriter != nil {
		healthWriter.SetStatus(true, getBufferCount())
	}

	// Initialize metrics collection
	if err := InitMetricsCollection(); err != nil {
		log.Printf("Failed to initialize metrics: %v", err)
	}

	// Replay buffered metrics from offline buffer
	if offlineBuffer != nil {
		go replayBufferedMetrics(conn)
	}

	// Start goroutines for sending and receiving
	done := make(chan struct{})
	errChan := make(chan error, 2)

	// Goroutine 1: Sender (metrics streaming with dynamic ticker)
	go metricsSender(conn, done, errChan)

	// Goroutine 2: Listener (commands from server)
	go messageListener(conn, done, errChan)

	// Wait for error or shutdown
	select {
	case err := <-errChan:
		close(done)
		conn.Close()
		return err
	case <-shutdown:
		close(done)
		conn.Close()
		return nil
	}
}

// setActiveMode sets the current mode (active vs passive)
func setActiveMode(active bool) {
	activeModeMutex.Lock()
	defer activeModeMutex.Unlock()

	// Cancel existing timeout timer if any
	if activeTimeoutTimer != nil {
		activeTimeoutTimer.Stop()
		activeTimeoutTimer = nil
	}

	isActiveMode = active

	if active {
		// Record when active mode started
		activeStartTime = time.Now()

		// Set timeout timer to auto-revert to passive mode
		activeTimeoutTimer = time.AfterFunc(activeMaxDuration, func() {
			log.Printf("⚠️ Active mode timeout after %v - forcing switch to passive mode", activeMaxDuration)
			setActiveMode(false)
			tickerChanged <- passiveSendInterval
		})
		log.Printf("Active mode started with %v timeout", activeMaxDuration)
	} else {
		activeStartTime = time.Time{}
	}
}

// getActiveMode returns the current mode
func getActiveMode() bool {
	activeModeMutex.RLock()
	defer activeModeMutex.RUnlock()
	return isActiveMode
}

// addToMetricsBuffer adds a metric point to the local buffer
func addToMetricsBuffer(metric MetricPoint) {
	metricsBufferMutex.Lock()
	defer metricsBufferMutex.Unlock()

	metricsLocalBuffer = append(metricsLocalBuffer, metric)

	// If buffer exceeds max size, drop oldest entries
	if len(metricsLocalBuffer) > maxBufferSize {
		// Keep only the most recent maxBufferSize entries
		excess := len(metricsLocalBuffer) - maxBufferSize
		metricsLocalBuffer = metricsLocalBuffer[excess:]
		log.Printf("Buffer overflow - dropped %d oldest metrics (keeping %d)", excess, maxBufferSize)
	}
}

// getAndClearMetricsBuffer returns all buffered metrics and clears the buffer
func getAndClearMetricsBuffer() []MetricPoint {
	metricsBufferMutex.Lock()
	defer metricsBufferMutex.Unlock()

	if len(metricsLocalBuffer) == 0 {
		return nil
	}

	// Copy buffer
	result := make([]MetricPoint, len(metricsLocalBuffer))
	copy(result, metricsLocalBuffer)

	// Clear buffer
	metricsLocalBuffer = metricsLocalBuffer[:0]

	return result
}

// getMetricsBufferCopy returns a copy without clearing (for retry scenarios)
func getMetricsBufferCopy() []MetricPoint {
	metricsBufferMutex.Lock()
	defer metricsBufferMutex.Unlock()

	if len(metricsLocalBuffer) == 0 {
		return nil
	}

	result := make([]MetricPoint, len(metricsLocalBuffer))
	copy(result, metricsLocalBuffer)
	return result
}

// clearMetricsBuffer clears the buffer (called after successful send)
func clearMetricsBuffer() {
	metricsBufferMutex.Lock()
	defer metricsBufferMutex.Unlock()
	metricsLocalBuffer = metricsLocalBuffer[:0]
}

// replayBufferedMetrics sends any offline-buffered metrics to the server on reconnect
func replayBufferedMetrics(conn *websocket.Conn) {
	if offlineBuffer == nil {
		return
	}

	metrics := offlineBuffer.GetBufferedMetrics()
	if len(metrics) == 0 {
		log.Println("📦 No buffered metrics to replay")
		return
	}

	log.Printf("📤 Replaying %d buffered metrics...", len(metrics))

	replayedCount := 0
	errorCount := 0

	for _, buffered := range metrics {
		// Create message payload matching server expectations
		payload := map[string]interface{}{
			"type":           "metric",
			"agent_id":       buffered.AgentID,
			"hostname":       buffered.Hostname,
			"cpu_percent":    buffered.Metrics.CPUPercent,
			"ram_percent":    buffered.Metrics.RAMPercent,
			"net_sent_bps":   buffered.Metrics.NetSentBps,
			"net_recv_bps":   buffered.Metrics.NetRecvBps,
			"disk_read_bps":  buffered.Metrics.DiskReadBps,
			"disk_write_bps": buffered.Metrics.DiskWriteBps,
			"timestamp":      buffered.Timestamp.Format(time.RFC3339),
			"historical":     true, // Flag for server to know this is replayed data
		}

		// Add optional fields
		if len(buffered.Processes) > 0 {
			payload["top_processes"] = buffered.Processes
		}
		if buffered.LoadAvg > 0 {
			payload["load_avg"] = buffered.LoadAvg
		}
		if len(buffered.Metrics.Disks) > 0 {
			payload["disks"] = buffered.Metrics.Disks
		}

		err := conn.WriteJSON(payload)
		if err != nil {
			log.Printf("⚠️ Failed to replay metric from %v: %v", buffered.Timestamp, err)
			errorCount++
			if errorCount > 10 {
				log.Printf("🛑 Too many replay errors, stopping replay")
				break
			}
			continue
		}

		replayedCount++

		// Small delay to avoid overwhelming the server
		time.Sleep(10 * time.Millisecond)
	}

	// Clear successfully replayed metrics
	if replayedCount > 0 {
		offlineBuffer.ClearReplayed(replayedCount)
	}

	stats := offlineBuffer.GetStats()
	log.Printf("✅ Replayed %d metrics (%d errors, %d remaining in buffer)",
		replayedCount, errorCount, stats.MemoryEntries)
}

// passiveMetricsCollector runs in background, collecting metrics every 2 seconds in passive mode
func passiveMetricsCollector(done chan struct{}) {
	ticker := time.NewTicker(passiveCollectInterval)
	defer ticker.Stop()

	log.Printf("Passive metrics collector started (collecting every %v)", passiveCollectInterval)

	for {
		select {
		case <-ticker.C:
			// Only collect if in passive mode
			if !getActiveMode() {
				metric, err := CollectMetrics()
				if err != nil {
					log.Printf("Failed to collect metric: %v", err)
					continue
				}

				// Add to local buffer for immediate sending
				addToMetricsBuffer(metric)

				// Also add to offline buffer when disconnected
				wsConnMutex.Lock()
				isConnected := wsConnected
				wsConnMutex.Unlock()

				if !isConnected && offlineBuffer != nil {
					bufferedMetric := BufferedMetric{
						Timestamp: time.Now(),
						AgentID:   agentID,
						Hostname:  hostname,
						Metrics:   metric,
						Processes: topProcesses,
						LoadAvg:   currentLoadAvg,
						PublicIP:  currentPublicIP,
					}
					offlineBuffer.Add(bufferedMetric)
				}
			}
		case <-done:
			log.Println("Passive metrics collector stopping")
			return
		}
	}
}

// metricsSender sends metrics on a dynamic ticker
func metricsSender(conn *websocket.Conn, done chan struct{}, errChan chan error) {
	// Start with passive send ticker (60s)
	sendTicker := time.NewTicker(currentTickerDur)
	defer sendTicker.Stop()

	// Start passive collector goroutine
	collectorDone := make(chan struct{})
	go passiveMetricsCollector(collectorDone)
	defer close(collectorDone)

	log.Printf("Metrics sender started with %v send interval", currentTickerDur)

	// Send initial metrics immediately (single point)
	if err := sendMetricsImmediate(conn); err != nil {
		log.Printf("Failed to send initial metrics: %v", err)
	}

	for {
		select {
		case <-sendTicker.C:
			if getActiveMode() {
				// Active mode: collect and send single metric immediately
				if err := sendMetricsImmediate(conn); err != nil {
					errChan <- fmt.Errorf("send error: %w", err)
					return
				}
			} else {
				// Passive mode: send buffered metrics
				if err := sendBufferedMetrics(conn); err != nil {
					log.Printf("Failed to send buffered metrics: %v", err)
					// Don't return error - keep buffer and retry next tick
				}
			}

		case newDuration := <-tickerChanged:
			// Switch ticker
			sendTicker.Stop()
			sendTicker = time.NewTicker(newDuration)
			tickerMutex.Lock()
			currentTickerDur = newDuration
			tickerMutex.Unlock()
			log.Printf("Send ticker switched to %v interval", newDuration)

			// If switching to active mode, send any buffered data first
			if newDuration == activeTickerDur {
				if buffered := getAndClearMetricsBuffer(); len(buffered) > 0 {
					log.Printf("Flushing %d buffered metrics before active mode", len(buffered))
					payload, _ := BuildHeartbeatPayload(buffered)
					if jsonData, err := json.Marshal(payload); err == nil {
						wsConnMutex.Lock()
						conn.WriteMessage(websocket.TextMessage, jsonData)
						wsConnMutex.Unlock()
					}
				}
			}

		case <-done:
			return
		}
	}
}

// sendMetricsImmediate collects and sends a single metric point immediately (for active mode)
func sendMetricsImmediate(conn *websocket.Conn) error {
	metric, err := CollectMetrics()
	if err != nil {
		return fmt.Errorf("failed to collect metrics: %w", err)
	}

	payload, err := BuildHeartbeatPayload([]MetricPoint{metric})
	if err != nil {
		return fmt.Errorf("failed to build payload: %w", err)
	}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	wsConnMutex.Lock()
	err = conn.WriteMessage(websocket.TextMessage, jsonData)
	wsConnMutex.Unlock()

	if err != nil {
		// Buffer the metric for later replay when connection is restored
		if offlineBuffer != nil {
			bufferedMetric := BufferedMetric{
				Timestamp: time.Now(),
				AgentID:   agentID,
				Hostname:  hostname,
				Metrics:   metric,
				Processes: topProcesses,
				LoadAvg:   currentLoadAvg,
				PublicIP:  currentPublicIP,
			}
			offlineBuffer.Add(bufferedMetric)
			log.Printf("📦 Metric buffered offline due to send error")
		}
		return fmt.Errorf("write error: %w", err)
	}

	log.Printf("Sent immediate metric via WebSocket")
	return nil
}

// sendBufferedMetrics sends all buffered metrics (for passive mode)
func sendBufferedMetrics(conn *websocket.Conn) error {
	buffered := getMetricsBufferCopy()
	if len(buffered) == 0 {
		// No buffered metrics - collect one now and send
		metric, err := CollectMetrics()
		if err != nil {
			return fmt.Errorf("failed to collect metrics: %w", err)
		}
		buffered = []MetricPoint{metric}
	}

	payload, err := BuildHeartbeatPayload(buffered)
	if err != nil {
		return fmt.Errorf("failed to build payload: %w", err)
	}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	wsConnMutex.Lock()
	err = conn.WriteMessage(websocket.TextMessage, jsonData)
	wsConnMutex.Unlock()

	if err != nil {
		// Store all buffered metrics in offline buffer for crash recovery
		if offlineBuffer != nil {
			for _, metric := range buffered {
				bufferedMetric := BufferedMetric{
					Timestamp: metric.Timestamp,
					AgentID:   agentID,
					Hostname:  hostname,
					Metrics:   metric,
					Processes: topProcesses,
					LoadAvg:   currentLoadAvg,
					PublicIP:  currentPublicIP,
				}
				offlineBuffer.Add(bufferedMetric)
			}
			log.Printf("📦 %d metrics buffered offline due to send error", len(buffered))
		}
		// Keep local buffer for retry
		return fmt.Errorf("write error: %w", err)
	}

	// Success - clear buffer
	clearMetricsBuffer()
	log.Printf("Sent %d buffered metrics via WebSocket", len(buffered))
	return nil
}

// messageListener listens for commands from the server
func messageListener(conn *websocket.Conn, done chan struct{}, errChan chan error) {
	for {
		select {
		case <-done:
			return
		default:
			_, message, err := conn.ReadMessage()
			if err != nil {
				if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
					log.Println("WebSocket closed normally")
				} else {
					errChan <- fmt.Errorf("read error: %w", err)
				}
				return
			}

			// Parse server response
			var resp ServerResponse
			if err := json.Unmarshal(message, &resp); err != nil {
				log.Printf("Failed to parse server message: %v", err)
				continue
			}

			// Handle auth token response from server
			if resp.AuthToken != "" {
				handleAuthToken(resp.AuthToken)
				continue
			}

			// Handle errors from server
			if resp.Error != "" {
				log.Printf("⚠️ Server error: %s - %s", resp.Error, resp.Message)
				if resp.Error == "auth_failed" {
					log.Println("Authentication failed - agent may need to be re-registered")
					// Clear invalid token and retry
					if globalConfig != nil {
						globalConfig.AuthToken = ""
						saveAuthToken("")
					}
				}
				continue
			}

			// Handle commands
			if resp.Command != "" {
				handleCommand(Command{Command: resp.Command, Params: resp.Params})
			}
		}
	}
}

// handleAuthToken processes a new auth token from the server
func handleAuthToken(token string) {
	log.Println("🔐 Received auth token from server - saving to config")

	if globalConfig != nil {
		globalConfig.AuthToken = token
		saveAuthToken(token)
	}
}

// saveAuthToken persists the auth token to the config file
func saveAuthToken(token string) {
	if globalConfigPath == "" {
		log.Println("⚠️ No config path set, cannot save auth token")
		return
	}

	if globalConfig == nil {
		log.Println("⚠️ No global config, cannot save auth token")
		return
	}

	// Update the config and save
	globalConfig.AuthToken = token
	if err := SaveConfig(globalConfigPath, globalConfig); err != nil {
		log.Printf("⚠️ Failed to save auth token to config: %v", err)
	} else {
		log.Printf("✅ Auth token saved to %s", globalConfigPath)
	}
}

// handleCommand processes server commands
func handleCommand(cmd Command) {
	switch cmd.Command {
	case "start_stream":
		log.Println("📡 Received start_stream command - switching to active mode (1s interval)")
		setActiveMode(true)
		tickerChanged <- activeTickerDur

	case "stop_stream":
		log.Println("📴 Received stop_stream command - switching to passive mode (60s interval)")
		setActiveMode(false)
		tickerChanged <- passiveSendInterval

	case "shutdown":
		log.Println("Received shutdown command - exiting agent")
		os.Exit(0)

	case "restart":
		log.Println("Received restart command - restarting agent")
		// Self-restart: launch a new instance then exit
		execPath, err := os.Executable()
		if err != nil {
			log.Printf("Failed to get executable path: %v", err)
			os.Exit(1)
		}

		// Get current working directory
		workDir, _ := os.Getwd()

		// Start new process
		cmd := exec.Command(execPath)
		cmd.Dir = workDir
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Start(); err != nil {
			log.Printf("Failed to restart: %v", err)
			os.Exit(1)
		}
		log.Printf("Started new instance (PID %d), exiting current process", cmd.Process.Pid)
		os.Exit(0)

	case "disable":
		log.Println("Received disable command - stopping data collection")
		// Stop sending metrics but keep connection alive
		tickerChanged <- 24 * time.Hour // Effectively disable

	// AI Commands
	case "ai_status":
		handleAIStatusCommand()

	case "ai_enable":
		handleAIEnableCommand(cmd.Params)

	case "ai_disable":
		handleAIDisableCommand()

	case "ai_download_model":
		handleAIDownloadModelCommand(cmd.Params)

	case "ai_download_runner":
		handleAIDownloadRunnerCommand()

	case "ai_generate":
		handleAIGenerateCommand(cmd.Params)

	default:
		log.Printf("Unknown command: %s", cmd.Command)
	}
}

// sendLogsViaWebSocket sends log batch via WebSocket connection
func sendLogsViaWebSocket(logs []LogSchema) error {
	wsConnMutex.Lock()
	conn := wsConn
	connected := wsConnected
	wsConnMutex.Unlock()

	if !connected || conn == nil {
		return fmt.Errorf("websocket not connected")
	}

	// Create batch request
	batch := BatchRequest{
		Logs: logs,
	}

	// Marshal to JSON
	jsonData, err := json.Marshal(batch)
	if err != nil {
		return fmt.Errorf("failed to marshal logs: %w", err)
	}

	// Send via WebSocket (thread-safe write)
	wsConnMutex.Lock()
	defer wsConnMutex.Unlock()

	if err := conn.WriteMessage(websocket.TextMessage, jsonData); err != nil {
		return fmt.Errorf("write error: %w", err)
	}

	return nil
}

// registerWithServer registers the agent with the server via HTTP
// This is called at startup before establishing WebSocket connection
func registerWithServer() error {
	// Build HTTP URL with proper scheme
	httpScheme := "http"
	if globalConfig != nil && globalConfig.SSLEnabled {
		httpScheme = "https"
	}
	registerURL := fmt.Sprintf("%s://%s/api/register", httpScheme, serverHost)

	// Get hostname for registration
	hostName, err := os.Hostname()
	if err != nil {
		hostName = "unknown"
	}

	// Get config for tenant settings (use globalConfig, not DefaultConfig)
	cfg := globalConfig

	// Build registration payload
	payload := map[string]interface{}{
		"agent_id": agentID,
		"hostname": hostName,
		"os":       runtime.GOOS,
	}
	if cfg.TenantID != "" {
		payload["tenant_id"] = cfg.TenantID
	}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal registration payload: %w", err)
	}

	// Make HTTP request with proper TLS settings
	client := cfg.GetHTTPClient(10 * time.Second)
	req, err := http.NewRequest("POST", registerURL, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create registration request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// Add API key header if configured
	if cfg.APIKey != "" {
		req.Header.Set("X-API-Key", cfg.APIKey)
	}

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("registration request failed: %w", err)
	}
	defer resp.Body.Close()

	// Parse response
	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("failed to decode registration response: %w", err)
	}

	// Check if server assigned a different agent_id (fallback scenario)
	if newID, ok := result["agent_id"].(string); ok && newID != "" && newID != agentID {
		log.Printf("Server assigned new agent_id: %s (was: %s)", newID, agentID)
		agentID = newID
	}

	log.Printf("Registration response: %v", result)
	return nil
}
