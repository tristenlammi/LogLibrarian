package main

import (
	"bufio"
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"
)

// LogEntry represents a single log entry to be sent to the backend
type LogEntry struct {
	Timestamp string                 `json:"timestamp"`
	Severity  string                 `json:"severity"`
	Source    string                 `json:"source"`
	Message   string                 `json:"message"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
}

// LogSettings represents the agent's log collection configuration
type LogSettings struct {
	LoggingEnabled        bool   `json:"logging_enabled"`
	LogLevelThreshold     string `json:"log_level_threshold"`
	LogRetentionDays      int    `json:"log_retention_days"`
	WatchDockerContainers bool   `json:"watch_docker_containers"`
	WatchSystemLogs       bool   `json:"watch_system_logs"`
	WatchSecurityLogs     bool   `json:"watch_security_logs"`
	TroubleshootingMode   bool   `json:"troubleshooting_mode"`
}

// LogCollector manages log collection, filtering, and transmission
type LogCollector struct {
	settings      LogSettings
	settingsMutex sync.RWMutex

	// Buffer management
	buffer      []LogEntry
	bufferMutex sync.Mutex
	bufferSize  int
	maxBuffer   int
	flushTicker *time.Ticker

	// Rate limiting for urgent flushes
	urgentFlushCount int
	urgentFlushMutex sync.Mutex
	urgentFlushReset *time.Ticker
	urgentDisabled   bool

	// Control
	ctx        context.Context
	cancel     context.CancelFunc
	wg         sync.WaitGroup
	serverHost string
	agentID    string

	// Security log collection
	securityLogPaths []string // Paths to security log files (Linux only)
}

// Severity levels for filtering
var severityLevels = map[string]int{
	"DEBUG":    0,
	"INFO":     1,
	"WARN":     2,
	"WARNING":  2,
	"ERROR":    3,
	"CRITICAL": 4,
	"FATAL":    4,
}

// NewLogCollector creates a new log collector
func NewLogCollector(serverHost, agentID string, securityLogPaths []string) *LogCollector {
	ctx, cancel := context.WithCancel(context.Background())

	lc := &LogCollector{
		settings: LogSettings{
			LoggingEnabled:        true,
			LogLevelThreshold:     "ERROR",
			LogRetentionDays:      7,
			WatchDockerContainers: false,
			WatchSystemLogs:       true,
			WatchSecurityLogs:     true,
			TroubleshootingMode:   false,
		},
		buffer:           make([]LogEntry, 0, 100),
		maxBuffer:        50,
		ctx:              ctx,
		cancel:           cancel,
		serverHost:       serverHost,
		agentID:          agentID,
		securityLogPaths: securityLogPaths,
	}

	return lc
}

// Start begins log collection
func (lc *LogCollector) Start() {
	log.Println("📋 Log Collector starting...")

	// Fetch settings from server
	lc.fetchSettings()

	// Start standard flush timer (60 seconds)
	lc.flushTicker = time.NewTicker(60 * time.Second)

	// Start urgent flush rate limiter reset (every minute)
	lc.urgentFlushReset = time.NewTicker(1 * time.Minute)

	// Start background workers
	lc.wg.Add(1)
	go lc.flushLoop()

	lc.wg.Add(1)
	go lc.rateLimitResetLoop()

	// Start platform-specific collectors
	if runtime.GOOS == "windows" {
		lc.wg.Add(1)
		go lc.collectWindowsEventLogs()
	} else {
		// Linux/Mac
		if lc.settings.WatchSystemLogs {
			lc.wg.Add(1)
			go lc.collectSyslog()
		}
		if lc.settings.WatchSecurityLogs {
			lc.wg.Add(1)
			go lc.collectAuthLog()
		}
	}

	// Docker container log collection
	if lc.settings.WatchDockerContainers {
		lc.wg.Add(1)
		go lc.collectDockerLogs()
	}

	// Security log collection (Windows Defender / Linux security logs)
	if lc.settings.WatchSecurityLogs {
		securityCollector := NewSecurityLogCollector(lc, lc.securityLogPaths)
		lc.wg.Add(1)
		go securityCollector.StreamSecurityLogs()
	}

	// Periodic settings refresh
	lc.wg.Add(1)
	go lc.settingsRefreshLoop()

	log.Println("📋 Log Collector started")
}

// Stop halts log collection
func (lc *LogCollector) Stop() {
	log.Println("📋 Log Collector stopping...")
	lc.cancel()

	if lc.flushTicker != nil {
		lc.flushTicker.Stop()
	}
	if lc.urgentFlushReset != nil {
		lc.urgentFlushReset.Stop()
	}

	// Final flush
	lc.flush(false)

	lc.wg.Wait()
	log.Println("📋 Log Collector stopped")
}

// isScribeLog checks if a log message is from scribe itself (to avoid self-reporting)
func (lc *LogCollector) isScribeLog(message string) bool {
	// Common scribe log patterns to filter out
	scribePatterns := []string{
		"scribe[",                // Linux syslog format: "hostname scribe[pid]:"
		"scribe:",                // Simple format
		"scribe-agent",           // Service name
		"Log settings loaded:",   // Scribe settings message
		"WebSocket connection",   // Scribe connection messages
		"Connected to librarian", // Scribe connection success
		"Reconnecting to",        // Scribe reconnect messages
		"Starting log collector", // Scribe startup
		"📋",                      // Scribe emoji markers
		"🔌",                      // Scribe connection emoji
		"✅",                      // Scribe success emoji
	}

	msgLower := strings.ToLower(message)
	for _, pattern := range scribePatterns {
		if strings.Contains(msgLower, strings.ToLower(pattern)) {
			return true
		}
	}
	return false
}

// AddLog adds a log entry to the buffer with filtering
func (lc *LogCollector) AddLog(entry LogEntry) {
	lc.settingsMutex.RLock()
	settings := lc.settings
	lc.settingsMutex.RUnlock()

	// Check if logging is enabled
	if !settings.LoggingEnabled {
		return
	}

	// Skip scribe's own logs to avoid self-reporting
	if lc.isScribeLog(entry.Message) {
		return
	}

	// Apply severity filter (Gatekeeper)
	entrySeverity := strings.ToUpper(entry.Severity)
	entryLevel := severityLevels[entrySeverity]
	thresholdLevel := severityLevels[strings.ToUpper(settings.LogLevelThreshold)]

	// In troubleshooting mode, accept all levels
	if !settings.TroubleshootingMode && entryLevel < thresholdLevel {
		return // Drop log - below threshold
	}

	// Add to buffer
	lc.bufferMutex.Lock()
	lc.buffer = append(lc.buffer, entry)
	bufferLen := len(lc.buffer)
	isUrgent := entrySeverity == "ERROR" || entrySeverity == "CRITICAL" || entrySeverity == "FATAL"
	lc.bufferMutex.Unlock()

	// Check flush conditions
	if bufferLen >= lc.maxBuffer {
		// Buffer full - flush
		go lc.flush(false)
	} else if isUrgent {
		// Urgent log (ERROR/CRITICAL) - immediate flush
		go lc.urgentFlush()
	}
}

// urgentFlush handles immediate flush for error logs with rate limiting
func (lc *LogCollector) urgentFlush() {
	lc.urgentFlushMutex.Lock()

	// Check rate limit (>10/min disables urgent flushing)
	if lc.urgentDisabled {
		lc.urgentFlushMutex.Unlock()
		return
	}

	lc.urgentFlushCount++
	if lc.urgentFlushCount > 10 {
		log.Println("⚠️ Rate limit: Urgent flushes disabled (>10/min)")
		lc.urgentDisabled = true
		lc.urgentFlushMutex.Unlock()
		return
	}
	lc.urgentFlushMutex.Unlock()

	lc.flush(true)
}

// flush sends buffered logs to the server
func (lc *LogCollector) flush(urgent bool) {
	lc.bufferMutex.Lock()
	if len(lc.buffer) == 0 {
		lc.bufferMutex.Unlock()
		return
	}

	// Copy and clear buffer
	toSend := make([]LogEntry, len(lc.buffer))
	copy(toSend, lc.buffer)
	lc.buffer = lc.buffer[:0]
	lc.bufferMutex.Unlock()

	// Send with retry and exponential backoff
	maxRetries := 3
	baseDelay := 2 * time.Second

	var lastErr error
	for attempt := 0; attempt < maxRetries; attempt++ {
		if err := lc.sendLogs(toSend); err != nil {
			lastErr = err
			if attempt < maxRetries-1 {
				delay := baseDelay * time.Duration(1<<attempt) // Exponential backoff: 2s, 4s, 8s
				log.Printf("⚠️ Failed to send logs (attempt %d/%d): %v, retrying in %v", attempt+1, maxRetries, err, delay)

				select {
				case <-time.After(delay):
					continue
				case <-lc.ctx.Done():
					// Context cancelled, re-add logs to buffer and exit
					lc.bufferMutex.Lock()
					if len(lc.buffer) < lc.maxBuffer*2 {
						lc.buffer = append(toSend, lc.buffer...)
					}
					lc.bufferMutex.Unlock()
					return
				}
			}
		} else {
			// Success
			if urgent {
				log.Printf("🚨 Urgent flush: sent %d logs", len(toSend))
			} else {
				log.Printf("📤 Sent %d logs", len(toSend))
			}
			return
		}
	}

	// All retries failed
	log.Printf("❌ Failed to send logs after %d attempts: %v", maxRetries, lastErr)
	// Re-add to buffer on failure (limited to prevent memory issues)
	lc.bufferMutex.Lock()
	if len(lc.buffer) < lc.maxBuffer*2 {
		lc.buffer = append(toSend, lc.buffer...)
		log.Printf("📋 Re-buffered %d logs for later retry", len(toSend))
	} else {
		log.Printf("⚠️ Buffer full, discarding %d logs", len(toSend))
	}
	lc.bufferMutex.Unlock()
}

// sendLogs sends logs to the backend with GZIP compression
func (lc *LogCollector) sendLogs(logs []LogEntry) error {
	payload := struct {
		Logs []LogEntry `json:"logs"`
	}{Logs: logs}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal error: %w", err)
	}

	// GZIP compress
	var buf bytes.Buffer
	gzWriter := gzip.NewWriter(&buf)
	if _, err := gzWriter.Write(jsonData); err != nil {
		return fmt.Errorf("gzip write error: %w", err)
	}
	if err := gzWriter.Close(); err != nil {
		return fmt.Errorf("gzip close error: %w", err)
	}

	// Send HTTP POST with proper scheme
	httpScheme := "http"
	if globalConfig != nil && globalConfig.SSLEnabled {
		httpScheme = "https"
	}
	url := fmt.Sprintf("%s://%s/api/agents/%s/logs", httpScheme, lc.serverHost, lc.agentID)
	req, err := http.NewRequestWithContext(lc.ctx, "POST", url, &buf)
	if err != nil {
		return fmt.Errorf("request error: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Content-Encoding", "gzip")

	client := globalConfig.GetHTTPClient(30 * time.Second)
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("http error: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("server error %d: %s", resp.StatusCode, string(body))
	}

	return nil
}

// flushLoop handles periodic flushing
func (lc *LogCollector) flushLoop() {
	defer lc.wg.Done()

	for {
		select {
		case <-lc.flushTicker.C:
			lc.flush(false)
		case <-lc.ctx.Done():
			return
		}
	}
}

// rateLimitResetLoop resets the urgent flush counter every minute
func (lc *LogCollector) rateLimitResetLoop() {
	defer lc.wg.Done()

	for {
		select {
		case <-lc.urgentFlushReset.C:
			lc.urgentFlushMutex.Lock()
			if lc.urgentDisabled && lc.urgentFlushCount > 10 {
				log.Println("✅ Rate limit reset: Urgent flushes re-enabled")
			}
			lc.urgentFlushCount = 0
			lc.urgentDisabled = false
			lc.urgentFlushMutex.Unlock()
		case <-lc.ctx.Done():
			return
		}
	}
}

// fetchSettings retrieves log settings from the server
func (lc *LogCollector) fetchSettings() {
	httpScheme := "http"
	if globalConfig != nil && globalConfig.SSLEnabled {
		httpScheme = "https"
	}
	url := fmt.Sprintf("%s://%s/api/agents/%s/log-settings", httpScheme, lc.serverHost, lc.agentID)

	client := globalConfig.GetHTTPClient(10 * time.Second)
	resp, err := client.Get(url)
	if err != nil {
		log.Printf("⚠️ Failed to fetch log settings: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		log.Printf("⚠️ Log settings fetch returned %d", resp.StatusCode)
		return
	}

	var settings LogSettings
	if err := json.NewDecoder(resp.Body).Decode(&settings); err != nil {
		log.Printf("⚠️ Failed to decode log settings: %v", err)
		return
	}

	lc.settingsMutex.Lock()
	lc.settings = settings
	lc.settingsMutex.Unlock()

	log.Printf("📋 Log settings loaded: enabled=%v, level=%s, docker=%v",
		settings.LoggingEnabled, settings.LogLevelThreshold, settings.WatchDockerContainers)
}

// settingsRefreshLoop periodically refreshes settings
func (lc *LogCollector) settingsRefreshLoop() {
	defer lc.wg.Done()

	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			lc.fetchSettings()
		case <-lc.ctx.Done():
			return
		}
	}
}

// =====================================
// Platform-Specific Log Collectors
// =====================================

// collectWindowsEventLogs collects from Windows Event Log
func (lc *LogCollector) collectWindowsEventLogs() {
	defer lc.wg.Done()
	log.Println("📋 Starting Windows Event Log collector")

	// Poll every 30 seconds for new events
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	// On first run, look back 24 hours to catch logs missed during downtime
	// This ensures we capture events even if the agent was offline
	lastCheck := time.Now().Add(-24 * time.Hour)

	// Do initial collection immediately
	lc.doWindowsLogCollection(&lastCheck)

	for {
		select {
		case <-ticker.C:
			lc.doWindowsLogCollection(&lastCheck)

		case <-lc.ctx.Done():
			return
		}
	}
}

// doWindowsLogCollection performs one collection cycle
func (lc *LogCollector) doWindowsLogCollection(lastCheck *time.Time) {
	lc.settingsMutex.RLock()
	watchSystem := lc.settings.WatchSystemLogs
	watchSecurity := lc.settings.WatchSecurityLogs
	lc.settingsMutex.RUnlock()

	now := time.Now()

	// Collect System log (errors)
	if watchSystem {
		lc.collectWindowsLog("System", *lastCheck)
	}

	// Collect Application log (errors)
	if watchSystem {
		lc.collectWindowsLog("Application", *lastCheck)
	}

	// Collect Security log (audit failures)
	if watchSecurity {
		lc.collectWindowsSecurityLog(*lastCheck)
	}

	*lastCheck = now
}

// getWindowsLogLevels returns the Windows Event Log levels to query based on settings
func (lc *LogCollector) getWindowsLogLevels() string {
	lc.settingsMutex.RLock()
	threshold := lc.settings.LogLevelThreshold
	troubleshooting := lc.settings.TroubleshootingMode
	lc.settingsMutex.RUnlock()

	// Windows Event Log levels:
	// 1 = Critical
	// 2 = Error
	// 3 = Warning
	// 4 = Informational
	// 5 = Verbose

	if troubleshooting || strings.ToUpper(threshold) == "INFO" {
		return "1,2,3,4" // Critical, Error, Warning, Info
	} else if strings.ToUpper(threshold) == "WARN" || strings.ToUpper(threshold) == "WARNING" {
		return "1,2,3" // Critical, Error, Warning
	}
	return "1,2" // Critical, Error (default)
}

// collectWindowsLog collects from a specific Windows Event Log channel
func (lc *LogCollector) collectWindowsLog(logName string, since time.Time) {
	// Get dynamic log levels based on settings
	levels := lc.getWindowsLogLevels()
	// Format time for wevtutil XML query
	sinceStr := since.UTC().Format("2006-01-02T15:04:05.000Z")

	// Build XPath query for wevtutil
	// Level values: 1=Critical, 2=Error, 3=Warning, 4=Info
	levelParts := strings.Split(levels, ",")
	var levelConditions []string
	for _, l := range levelParts {
		levelConditions = append(levelConditions, fmt.Sprintf("Level=%s", strings.TrimSpace(l)))
	}
	levelXPath := strings.Join(levelConditions, " or ")

	// XPath query
	xpath := fmt.Sprintf("*[System[(%s) and TimeCreated[@SystemTime>='%s']]]", levelXPath, sinceStr)

	// Use renderedxml format to get the human-readable message text
	cmd := exec.CommandContext(lc.ctx, "wevtutil", "qe", logName, "/q:"+xpath, "/c:100", "/f:renderedxml")
	output, err := cmd.Output()
	if err != nil {
		// No events or error - this is normal
		return
	}

	lc.parseWevtutilXML(output, logName)
}

// collectWindowsSecurityLog collects security audit failures
func (lc *LogCollector) collectWindowsSecurityLog(since time.Time) {
	sinceStr := since.UTC().Format("2006-01-02T15:04:05.000Z")

	// Security log - audit failures using wevtutil
	// Keywords 0x10000000000000 = Audit Failure
	xpath := fmt.Sprintf("*[System[band(Keywords,0x10000000000000) and TimeCreated[@SystemTime>='%s']]]", sinceStr)

	// Use renderedxml format to get the human-readable message text
	cmd := exec.CommandContext(lc.ctx, "wevtutil", "qe", "Security", "/q:"+xpath, "/c:100", "/f:renderedxml")
	output, err := cmd.Output()
	if err != nil {
		return
	}

	lc.parseWevtutilXML(output, "Security")
}

// parseWevtutilXML parses wevtutil XML output
func (lc *LogCollector) parseWevtutilXML(data []byte, source string) {
	if len(data) == 0 {
		return
	}

	// wevtutil returns individual <Event> elements, not wrapped in a root
	// We need to wrap them to parse as valid XML
	xmlData := "<Events>" + string(data) + "</Events>"

	type EventData struct {
		Name  string `xml:"Name,attr"`
		Value string `xml:",chardata"`
	}

	type RenderingInfo struct {
		Level   string `xml:"Level"`
		Message string `xml:"Message"`
	}

	type Event struct {
		System struct {
			Provider struct {
				Name string `xml:"Name,attr"`
			} `xml:"Provider"`
			TimeCreated struct {
				SystemTime string `xml:"SystemTime,attr"`
			} `xml:"TimeCreated"`
			Level string `xml:"Level"`
		} `xml:"System"`
		EventData struct {
			Data []EventData `xml:"Data"`
		} `xml:"EventData"`
		RenderingInfo RenderingInfo `xml:"RenderingInfo"`
	}

	type Events struct {
		Events []Event `xml:"Event"`
	}

	var events Events
	decoder := xml.NewDecoder(strings.NewReader(xmlData))
	decoder.Strict = false
	if err := decoder.Decode(&events); err != nil {
		log.Printf("📋 Failed to parse XML from %s: %v", source, err)
		// Try to at least count events for debugging
		eventCount := strings.Count(string(data), "<Event ")
		log.Printf("📋 Raw data contained ~%d events", eventCount)
		return
	}

	if len(events.Events) > 0 {
		log.Printf("📋 Parsed %d events from %s", len(events.Events), source)
	}

	for _, event := range events.Events {
		// Determine severity from Level
		severity := "ERROR"
		switch event.System.Level {
		case "1":
			severity = "CRITICAL"
		case "2":
			severity = "ERROR"
		case "3":
			severity = "WARN"
		case "4":
			severity = "INFO"
		}

		// Get message from RenderingInfo if available, otherwise build from EventData
		message := event.RenderingInfo.Message
		if message == "" && len(event.EventData.Data) > 0 {
			var parts []string
			for _, d := range event.EventData.Data {
				if d.Value != "" {
					if d.Name != "" {
						parts = append(parts, fmt.Sprintf("%s=%s", d.Name, d.Value))
					} else {
						parts = append(parts, d.Value)
					}
				}
			}
			message = strings.Join(parts, ", ")
		}

		entry := LogEntry{
			Timestamp: event.System.TimeCreated.SystemTime,
			Severity:  severity,
			Source:    source,
			Message:   message,
			Metadata: map[string]interface{}{
				"provider": event.System.Provider.Name,
			},
		}
		lc.AddLog(entry)
	}
}

// parseWindowsEvents parses PowerShell JSON output (kept for compatibility)
func (lc *LogCollector) parseWindowsEvents(data []byte, source string) {
	if len(data) == 0 {
		return
	}

	// Try array first, then single object
	var events []struct {
		TimeCreated      string `json:"TimeCreated"`
		LevelDisplayName string `json:"LevelDisplayName"`
		ProviderName     string `json:"ProviderName"`
		Message          string `json:"Message"`
	}

	if err := json.Unmarshal(data, &events); err != nil {
		// Try single event
		var single struct {
			TimeCreated      string `json:"TimeCreated"`
			LevelDisplayName string `json:"LevelDisplayName"`
			ProviderName     string `json:"ProviderName"`
			Message          string `json:"Message"`
		}
		if err := json.Unmarshal(data, &single); err != nil {
			log.Printf("📋 Failed to parse single event: %v", err)
			return
		}
		events = append(events, single)
	}

	if len(events) > 0 {
		log.Printf("📋 Parsed %d events from %s", len(events), source)
	}

	for _, event := range events {
		severity := "ERROR"
		levelLower := strings.ToLower(event.LevelDisplayName)
		if strings.Contains(levelLower, "critical") {
			severity = "CRITICAL"
		} else if strings.Contains(levelLower, "error") {
			severity = "ERROR"
		} else if strings.Contains(levelLower, "warning") {
			severity = "WARN"
		} else if strings.Contains(levelLower, "information") || strings.Contains(levelLower, "info") {
			severity = "INFO"
		}

		entry := LogEntry{
			Timestamp: event.TimeCreated,
			Severity:  severity,
			Source:    source,
			Message:   event.Message,
			Metadata: map[string]interface{}{
				"provider": event.ProviderName,
			},
		}
		lc.AddLog(entry)
	}
}

// collectSyslog tails /var/log/syslog or /var/log/messages
func (lc *LogCollector) collectSyslog() {
	defer lc.wg.Done()
	log.Println("📋 Starting syslog collector")

	// Find the syslog file
	syslogPaths := []string{"/var/log/syslog", "/var/log/messages"}
	var syslogPath string

	for _, path := range syslogPaths {
		if _, err := os.Stat(path); err == nil {
			syslogPath = path
			break
		}
	}

	if syslogPath == "" {
		log.Println("⚠️ No syslog file found")
		return
	}

	lc.tailFile(syslogPath, "System")
}

// collectAuthLog tails /var/log/auth.log
func (lc *LogCollector) collectAuthLog() {
	defer lc.wg.Done()
	log.Println("📋 Starting auth.log collector")

	authPaths := []string{"/var/log/auth.log", "/var/log/secure"}
	var authPath string

	for _, path := range authPaths {
		if _, err := os.Stat(path); err == nil {
			authPath = path
			break
		}
	}

	if authPath == "" {
		log.Println("⚠️ No auth log file found")
		return
	}

	lc.tailFile(authPath, "Security")
}

// tailFile tails a log file and sends entries
func (lc *LogCollector) tailFile(path, source string) {
	// Use tail command to follow the file
	// -n 1000 reads the last 1000 lines on startup to catch logs missed during downtime
	// -F follows the file even if rotated
	cmd := exec.CommandContext(lc.ctx, "tail", "-F", "-n", "1000", path)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		log.Printf("❌ Failed to tail %s: %v", path, err)
		return
	}

	if err := cmd.Start(); err != nil {
		log.Printf("❌ Failed to start tail for %s: %v", path, err)
		return
	}

	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		select {
		case <-lc.ctx.Done():
			cmd.Process.Kill()
			return
		default:
		}

		line := scanner.Text()
		severity := lc.detectSeverity(line)

		entry := LogEntry{
			Timestamp: time.Now().Format(time.RFC3339),
			Severity:  severity,
			Source:    source,
			Message:   line,
		}
		lc.AddLog(entry)
	}
}

// collectDockerLogs collects stderr from Docker containers
func (lc *LogCollector) collectDockerLogs() {
	defer lc.wg.Done()
	log.Println("📋 Starting Docker log collector")

	// Check if Docker is available
	if _, err := exec.LookPath("docker"); err != nil {
		log.Println("⚠️ Docker not found, skipping container log collection")
		return
	}

	// Poll for running containers every 30 seconds
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	trackedContainers := make(map[string]context.CancelFunc)

	for {
		select {
		case <-ticker.C:
			lc.settingsMutex.RLock()
			enabled := lc.settings.WatchDockerContainers
			lc.settingsMutex.RUnlock()

			if !enabled {
				continue
			}

			// Get running containers
			cmd := exec.CommandContext(lc.ctx, "docker", "ps", "-q")
			output, err := cmd.Output()
			if err != nil {
				continue
			}

			containerIDs := strings.Fields(string(output))

			// Start log collection for new containers
			for _, cid := range containerIDs {
				if _, exists := trackedContainers[cid]; !exists {
					ctx, cancel := context.WithCancel(lc.ctx)
					trackedContainers[cid] = cancel
					go lc.tailDockerContainer(ctx, cid)
				}
			}

			// Stop collection for stopped containers
			for cid, cancel := range trackedContainers {
				found := false
				for _, id := range containerIDs {
					if id == cid {
						found = true
						break
					}
				}
				if !found {
					cancel()
					delete(trackedContainers, cid)
				}
			}

		case <-lc.ctx.Done():
			// Cleanup all container watchers
			for _, cancel := range trackedContainers {
				cancel()
			}
			return
		}
	}
}

// tailDockerContainer follows logs from a specific container
func (lc *LogCollector) tailDockerContainer(ctx context.Context, containerID string) {
	// Get container name
	nameCmd := exec.CommandContext(ctx, "docker", "inspect", "-f", "{{.Name}}", containerID)
	nameOut, _ := nameCmd.Output()
	containerName := strings.TrimSpace(strings.TrimPrefix(string(nameOut), "/"))
	if containerName == "" {
		containerName = containerID[:12]
	}

	log.Printf("📋 Tailing Docker container: %s", containerName)

	// Follow container logs (stderr only for errors)
	cmd := exec.CommandContext(ctx, "docker", "logs", "-f", "--since", "1s", containerID)
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return
	}

	if err := cmd.Start(); err != nil {
		return
	}

	scanner := bufio.NewScanner(stderr)
	for scanner.Scan() {
		select {
		case <-ctx.Done():
			cmd.Process.Kill()
			return
		default:
		}

		line := scanner.Text()
		severity := lc.detectSeverity(line)

		entry := LogEntry{
			Timestamp: time.Now().Format(time.RFC3339),
			Severity:  severity,
			Source:    "Docker",
			Message:   line,
			Metadata: map[string]interface{}{
				"container": containerName,
			},
		}
		lc.AddLog(entry)
	}
}

// detectSeverity attempts to detect log severity from message content
func (lc *LogCollector) detectSeverity(message string) string {
	upper := strings.ToUpper(message)

	if strings.Contains(upper, "CRITICAL") || strings.Contains(upper, "FATAL") ||
		strings.Contains(upper, "PANIC") || strings.Contains(upper, "EMERGENCY") {
		return "CRITICAL"
	}
	if strings.Contains(upper, "ERROR") || strings.Contains(upper, "ERR") ||
		strings.Contains(upper, "FAIL") {
		return "ERROR"
	}
	if strings.Contains(upper, "WARN") || strings.Contains(upper, "WARNING") {
		return "WARN"
	}
	if strings.Contains(upper, "DEBUG") {
		return "DEBUG"
	}

	return "INFO"
}
