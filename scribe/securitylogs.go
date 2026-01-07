package main

import (
	"bufio"
	"encoding/json"
	"log"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/hpcloud/tail"
)

// SecurityLogCollector handles security-specific log collection
// On Windows: subscribes to Windows Defender Event Log
// On Linux: tails multiple configured security log files (e.g., ClamAV, fail2ban)
type SecurityLogCollector struct {
	logCollector     *LogCollector
	securityLogPaths []string // Linux only - paths to security log files
}

// NewSecurityLogCollector creates a new security log collector
func NewSecurityLogCollector(lc *LogCollector, securityLogPaths []string) *SecurityLogCollector {
	return &SecurityLogCollector{
		logCollector:     lc,
		securityLogPaths: securityLogPaths,
	}
}

// StreamSecurityLogs starts the security log collection based on OS
func (slc *SecurityLogCollector) StreamSecurityLogs() {
	defer slc.logCollector.wg.Done()

	if runtime.GOOS == "windows" {
		slc.streamWindowsDefenderLogs()
	} else {
		slc.streamLinuxSecurityLogs()
	}
}

// streamWindowsDefenderLogs subscribes to Windows Defender Event Log
// Channel: Microsoft-Windows-Windows Defender/Operational
// Filters for Warning (Level 3) and Error (Level 2) events
func (slc *SecurityLogCollector) streamWindowsDefenderLogs() {
	log.Println("🛡️ Starting Windows Defender security log collector")

	// Poll every 30 seconds for new events
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	// On first run, look back 5 minutes to catch recent alerts
	lastCheck := time.Now().Add(-5 * time.Minute)

	// Do initial collection immediately
	slc.collectDefenderEvents(lastCheck)

	for {
		select {
		case <-ticker.C:
			now := time.Now()
			slc.collectDefenderEvents(lastCheck)
			lastCheck = now

		case <-slc.logCollector.ctx.Done():
			log.Println("🛡️ Windows Defender security log collector stopped")
			return
		}
	}
}

// collectDefenderEvents collects Windows Defender events since the given time
func (slc *SecurityLogCollector) collectDefenderEvents(since time.Time) {
	sinceStr := since.Format("2006-01-02T15:04:05")

	// Query Windows Defender Operational log for Warning (3) and Error (2) levels
	// Level 1 = Critical, 2 = Error, 3 = Warning
	cmd := exec.CommandContext(slc.logCollector.ctx, "powershell", "-NoProfile", "-Command", `
		$events = @()
		try {
			$events = Get-WinEvent -FilterHashtable @{
				LogName='Microsoft-Windows-Windows Defender/Operational'
				Level=2,3
				StartTime='`+sinceStr+`'
			} -MaxEvents 100 -ErrorAction SilentlyContinue
		} catch {}
		
		if ($events.Count -gt 0) {
			$events | Select-Object @{N='TimeCreated';E={$_.TimeCreated.ToString('o')}}, 
				@{N='Level';E={$_.LevelDisplayName}},
				@{N='Id';E={$_.Id}},
				@{N='Message';E={$_.Message}} | 
			ConvertTo-Json -Compress
		}
	`)

	output, err := cmd.Output()
	if err != nil {
		// No events or error - this is normal when no threats detected
		return
	}

	slc.parseDefenderEvents(output)
}

// parseDefenderEvents parses Windows Defender event JSON output
func (slc *SecurityLogCollector) parseDefenderEvents(data []byte) {
	if len(data) == 0 {
		return
	}

	// Try array first, then single object
	var events []struct {
		TimeCreated string `json:"TimeCreated"`
		Level       string `json:"Level"`
		Id          int    `json:"Id"`
		Message     string `json:"Message"`
	}

	if err := json.Unmarshal(data, &events); err != nil {
		// Try single event
		var single struct {
			TimeCreated string `json:"TimeCreated"`
			Level       string `json:"Level"`
			Id          int    `json:"Id"`
			Message     string `json:"Message"`
		}
		if err := json.Unmarshal(data, &single); err != nil {
			log.Printf("🛡️ Failed to parse Defender events: %v", err)
			return
		}
		events = append(events, single)
	}

	if len(events) > 0 {
		log.Printf("🛡️ Found %d Windows Defender security events", len(events))
	}

	for _, event := range events {
		// Determine threat type from event ID first
		threatType := slc.getDefenderThreatType(event.Id)

		// Threat detections should always be CRITICAL regardless of Windows event level
		var severity string
		if threatType == "threat_detected" || threatType == "malware_detected" || threatType == "suspicious_behavior" {
			severity = "CRITICAL"
		} else {
			severity = slc.defenderLevelToSeverity(event.Level)
		}

		entry := LogEntry{
			Timestamp: event.TimeCreated,
			Severity:  severity,
			Source:    "security", // Tag as security source
			Message:   event.Message,
			Metadata: map[string]interface{}{
				"provider":    "Windows Defender",
				"event_id":    event.Id,
				"threat_type": threatType,
			},
		}
		slc.logCollector.AddLog(entry)
	}
}

// defenderLevelToSeverity converts Windows event level to log severity
func (slc *SecurityLogCollector) defenderLevelToSeverity(level string) string {
	levelLower := strings.ToLower(level)
	switch {
	case strings.Contains(levelLower, "critical"):
		return "CRITICAL"
	case strings.Contains(levelLower, "error"):
		return "ERROR"
	case strings.Contains(levelLower, "warning"):
		return "WARN"
	default:
		return "WARN" // Default to WARN for security events
	}
}

// getDefenderThreatType returns a human-readable threat type based on event ID
func (slc *SecurityLogCollector) getDefenderThreatType(eventId int) string {
	// Common Windows Defender event IDs
	switch eventId {
	case 1006:
		return "malware_detected"
	case 1007:
		return "malware_action_taken"
	case 1008:
		return "malware_action_failed"
	case 1009:
		return "quarantine_restore"
	case 1010:
		return "quarantine_delete"
	case 1011:
		return "quarantine_delete_failed"
	case 1013:
		return "malware_history_delete"
	case 1015:
		return "suspicious_behavior"
	case 1116:
		return "threat_detected"
	case 1117:
		return "threat_action_taken"
	case 1118:
		return "threat_action_failed"
	case 1119:
		return "threat_action_critical_failed"
	case 2001:
		return "signature_update_failed"
	case 2003:
		return "engine_update_failed"
	case 2004:
		return "signature_revert"
	case 3002:
		return "realtime_protection_failed"
	case 5001:
		return "realtime_protection_disabled"
	case 5004:
		return "realtime_protection_config_changed"
	case 5007:
		return "antimalware_config_changed"
	case 5010:
		return "scan_disabled"
	case 5012:
		return "scan_paused"
	default:
		return "security_event"
	}
}

// streamLinuxSecurityLogs tails multiple configured security log files on Linux
func (slc *SecurityLogCollector) streamLinuxSecurityLogs() {
	// Check if any security_log_paths are configured
	if len(slc.securityLogPaths) == 0 {
		log.Println("🛡️ No security_log_paths configured, skipping Linux security log collection")
		log.Println("🛡️ To enable, set security_log_paths in config.json (e.g., [\"/var/log/clamav/clamav.log\"])")
		return
	}

	// Filter to only existing paths
	var validPaths []string
	for _, path := range slc.securityLogPaths {
		path = strings.TrimSpace(path)
		if path == "" {
			continue
		}
		if _, err := os.Stat(path); os.IsNotExist(err) {
			log.Printf("🛡️ Security log file not found (skipping): %s", path)
			continue
		}
		validPaths = append(validPaths, path)
	}

	if len(validPaths) == 0 {
		log.Println("🛡️ No valid security log files found")
		return
	}

	log.Printf("🛡️ Starting Linux security log collector for %d files", len(validPaths))

	// Use a WaitGroup to track all tailers
	var wg sync.WaitGroup

	// Start a tailer for each valid path
	for _, path := range validPaths {
		wg.Add(1)
		go func(logPath string) {
			defer wg.Done()
			slc.tailSecurityLogFile(logPath)
		}(path)
	}

	// Wait for all tailers to finish (they'll exit when context is cancelled)
	wg.Wait()
	log.Println("🛡️ Linux security log collector stopped")
}

// tailSecurityLogFile tails a single security log file
func (slc *SecurityLogCollector) tailSecurityLogFile(logPath string) {
	log.Printf("🛡️ Tailing security log: %s", logPath)

	// Use hpcloud/tail library for reliable file tailing
	t, err := tail.TailFile(logPath, tail.Config{
		Follow:    true,  // Follow the file as it grows
		ReOpen:    true,  // Reopen file if it's rotated
		MustExist: false, // Don't fail if file doesn't exist yet
		Poll:      true,  // Use polling (more compatible)
		Location: &tail.SeekInfo{ // Start from end of file
			Offset: 0,
			Whence: os.SEEK_END,
		},
	})

	if err != nil {
		log.Printf("🛡️ Failed to tail security log %s: %v", logPath, err)
		// Fallback to manual tail
		slc.tailSecurityLogManually(logPath)
		return
	}

	for {
		select {
		case line := <-t.Lines:
			if line == nil {
				continue
			}
			if line.Err != nil {
				log.Printf("🛡️ Error reading security log %s: %v", logPath, line.Err)
				continue
			}

			slc.processSecurityLogLine(line.Text, logPath)

		case <-slc.logCollector.ctx.Done():
			t.Stop()
			t.Cleanup()
			return
		}
	}
}

// tailSecurityLogManually uses exec tail as fallback
func (slc *SecurityLogCollector) tailSecurityLogManually(logPath string) {
	log.Printf("🛡️ Using fallback tail for: %s", logPath)

	cmd := exec.CommandContext(slc.logCollector.ctx, "tail", "-F", "-n", "0", logPath)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		log.Printf("🛡️ Failed to create pipe for security log %s: %v", logPath, err)
		return
	}

	if err := cmd.Start(); err != nil {
		log.Printf("🛡️ Failed to start tail for security log %s: %v", logPath, err)
		return
	}

	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		select {
		case <-slc.logCollector.ctx.Done():
			cmd.Process.Kill()
			return
		default:
		}

		slc.processSecurityLogLine(scanner.Text(), logPath)
	}

	if err := scanner.Err(); err != nil {
		log.Printf("🛡️ Scanner error for %s: %v", logPath, err)
	}
}

// processSecurityLogLine processes a single line from a Linux security log
func (slc *SecurityLogCollector) processSecurityLogLine(line string, logPath string) {
	if line == "" {
		return
	}

	// Detect severity from log content
	severity := slc.detectSecuritySeverity(line)

	// Detect threat type from log content
	threatType := slc.detectThreatType(line)

	// Build metadata based on detected content
	metadata := map[string]interface{}{
		"provider": detectSecurityProvider(logPath),
		"log_file": logPath,
	}

	if threatType != "" {
		metadata["threat_type"] = threatType
	}

	entry := LogEntry{
		Timestamp: time.Now().Format(time.RFC3339),
		Severity:  severity,
		Source:    "security", // Tag as security source
		Message:   line,
		Metadata:  metadata,
	}

	slc.logCollector.AddLog(entry)
}

// detectSecuritySeverity detects log severity from line content
func (slc *SecurityLogCollector) detectSecuritySeverity(line string) string {
	upper := strings.ToUpper(line)

	// Critical indicators
	if strings.Contains(upper, "FOUND") || // ClamAV virus found
		strings.Contains(upper, "INFECTED") ||
		strings.Contains(upper, "THREAT") ||
		strings.Contains(upper, "MALWARE") ||
		strings.Contains(upper, "TROJAN") ||
		strings.Contains(upper, "VIRUS") ||
		strings.Contains(upper, "RANSOMWARE") ||
		strings.Contains(upper, "ROOTKIT") {
		return "CRITICAL"
	}

	// Error indicators
	if strings.Contains(upper, "ERROR") ||
		strings.Contains(upper, "FAILED") ||
		strings.Contains(upper, "DENIED") {
		return "ERROR"
	}

	// Warning indicators
	if strings.Contains(upper, "WARN") ||
		strings.Contains(upper, "SUSPICIOUS") ||
		strings.Contains(upper, "BLOCKED") ||
		strings.Contains(upper, "QUARANTINE") {
		return "WARN"
	}

	return "INFO"
}

// detectThreatType detects the type of security threat from line content
func (slc *SecurityLogCollector) detectThreatType(line string) string {
	upper := strings.ToUpper(line)

	// ClamAV specific patterns
	if strings.Contains(upper, "FOUND") {
		return "malware_detected"
	}
	if strings.Contains(upper, "SCAN STARTED") {
		return "scan_started"
	}
	if strings.Contains(upper, "SCAN COMPLETED") || strings.Contains(upper, "SCAN FINISHED") {
		return "scan_completed"
	}

	// Generic patterns
	if strings.Contains(upper, "QUARANTINE") {
		return "quarantine_action"
	}
	if strings.Contains(upper, "UPDATE") {
		if strings.Contains(upper, "FAILED") {
			return "signature_update_failed"
		}
		return "signature_updated"
	}
	if strings.Contains(upper, "BLOCKED") {
		return "threat_blocked"
	}

	return ""
}

// detectSecurityProvider determines the security provider from the log path
func detectSecurityProvider(logPath string) string {
	pathLower := strings.ToLower(logPath)

	if strings.Contains(pathLower, "clamav") || strings.Contains(pathLower, "clam") {
		return "ClamAV"
	}
	if strings.Contains(pathLower, "sophos") {
		return "Sophos"
	}
	if strings.Contains(pathLower, "eset") {
		return "ESET"
	}
	if strings.Contains(pathLower, "comodo") {
		return "Comodo"
	}
	if strings.Contains(pathLower, "rkhunter") {
		return "rkhunter"
	}
	if strings.Contains(pathLower, "chkrootkit") {
		return "chkrootkit"
	}
	if strings.Contains(pathLower, "fail2ban") {
		return "fail2ban"
	}
	if strings.Contains(pathLower, "ossec") {
		return "OSSEC"
	}

	return "security_scanner"
}
