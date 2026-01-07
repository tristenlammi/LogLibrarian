package main

import (
	"crypto/tls"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// Config holds all configuration for the agent
type Config struct {
	ServerHost       string   `json:"server_host"`   // Primary server address (legacy, for backward compatibility)
	LibrarianURL     string   `json:"librarian_url"` // Alternative name for server URL (from install scripts)
	ServerHosts      []string `json:"server_hosts"`  // Prioritized list of server addresses (LAN, DNS, etc.)
	AgentName        string   `json:"agent_name"`
	LogFile          string   `json:"log_file"`
	MetricsInterval  int      `json:"metrics_interval"`
	LogBatchSize     int      `json:"log_batch_size"`
	LogBatchInterval int      `json:"log_batch_interval"`
	SSLEnabled       bool     `json:"ssl_enabled"`
	SSLVerify        bool     `json:"ssl_verify"`
	AgentID          string   `json:"agent_id"`

	// Security log settings
	SecurityLogPaths []string `json:"security_log_paths"` // Paths to security log files (Linux only, e.g., /var/log/clamav/clamav.log)

	// Multi-tenant settings
	TenantID string `json:"tenant_id"` // Tenant identifier (optional, derived from API key)
	APIKey   string `json:"api_key"`   // API key for authentication (ll_xxx format)

	// Agent authentication token (issued by server, stored locally)
	AuthToken string `json:"auth_token"` // Authentication token for agent verification

	// Offline buffer settings
	BufferEnabled        bool   `json:"buffer_enabled"`          // Enable offline buffering (default: true)
	BufferMaxSizeMB      int    `json:"buffer_max_size_mb"`      // Max disk buffer size in MB (default: 50)
	BufferMaxDurationMin int    `json:"buffer_max_duration_min"` // Max buffer duration in minutes (default: 60)
	BufferDiskEnabled    bool   `json:"buffer_disk_enabled"`     // Enable disk persistence (default: true)
	BufferDataDir        string `json:"buffer_data_dir"`         // Directory for buffer files

	// Reconnection settings
	ReconnectInitialSec int `json:"reconnect_initial_sec"` // Initial reconnect delay (default: 5)
	ReconnectMaxSec     int `json:"reconnect_max_sec"`     // Max reconnect delay (default: 300)

	// Health file settings
	HealthFileEnabled     bool `json:"health_file_enabled"`      // Enable health file (default: true)
	HealthFileIntervalSec int  `json:"health_file_interval_sec"` // Health file update interval (default: 60)
}

// DefaultConfig returns a configuration with sensible defaults
func DefaultConfig() *Config {
	hostname, _ := os.Hostname()

	// Check environment variables first (don't set a default - let config file take precedence)
	serverHost := os.Getenv("SERVER_HOST")
	// Note: We don't set a default here - it's applied after config loading

	agentName := os.Getenv("AGENT_NAME")
	if agentName == "" {
		agentName = hostname
	}

	logFile := os.Getenv("LOG_FILE")
	if logFile == "" {
		logFile = "./test.log"
	}

	// Multi-tenant settings from env
	tenantID := os.Getenv("TENANT_ID")
	apiKey := os.Getenv("API_KEY")

	// Buffer settings from env
	bufferMaxMB := 50
	if v := os.Getenv("BUFFER_MAX_SIZE_MB"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			bufferMaxMB = n
		}
	}

	bufferDuration := 60
	if v := os.Getenv("BUFFER_MAX_DURATION_MIN"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			bufferDuration = n
		}
	}

	// Default data dir is next to executable
	bufferDataDir := os.Getenv("BUFFER_DATA_DIR")
	if bufferDataDir == "" {
		execPath, _ := os.Executable()
		bufferDataDir = filepath.Dir(execPath)
	}

	return &Config{
		ServerHost:       serverHost,
		ServerHosts:      []string{},
		AgentName:        agentName,
		LogFile:          logFile,
		MetricsInterval:  60,
		LogBatchSize:     50,
		LogBatchInterval: 5,
		SSLEnabled:       false,
		SSLVerify:        true,
		AgentID:          "",

		// Multi-tenant defaults
		TenantID: tenantID,
		APIKey:   apiKey,

		// Buffer defaults
		BufferEnabled:        true,
		BufferMaxSizeMB:      bufferMaxMB,
		BufferMaxDurationMin: bufferDuration,
		BufferDiskEnabled:    true,
		BufferDataDir:        bufferDataDir,

		// Reconnect defaults
		ReconnectInitialSec: 5,
		ReconnectMaxSec:     300, // 5 minutes

		// Health file defaults
		HealthFileEnabled:     true,
		HealthFileIntervalSec: 60,
	}
}

// GetBufferConfig returns buffer configuration from config
func (c *Config) GetBufferConfig() BufferConfig {
	return BufferConfig{
		MaxMemoryEntries: c.BufferMaxDurationMin * 30, // 2s intervals = 30 per minute
		MaxDiskSizeMB:    c.BufferMaxSizeMB,
		BufferDuration:   time.Duration(c.BufferMaxDurationMin) * time.Minute,
		DataDir:          c.BufferDataDir,
		DiskEnabled:      c.BufferDiskEnabled,
	}
}

// GetReconnectConfig returns reconnection configuration from config
func (c *Config) GetReconnectConfig() ReconnectConfig {
	return ReconnectConfig{
		InitialDelay: time.Duration(c.ReconnectInitialSec) * time.Second,
		MaxDelay:     time.Duration(c.ReconnectMaxSec) * time.Second,
		Multiplier:   2.0,
		JitterFactor: 0.1,
	}
}

// LoadConfig loads configuration from a JSON file
func LoadConfig(path string) (*Config, error) {
	cfg := DefaultConfig()

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	if err := json.Unmarshal(data, cfg); err != nil {
		return nil, err
	}

	// Support librarian_url as an alias for server_host (from install scripts)
	// librarian_url takes precedence if server_host is empty or default
	if cfg.LibrarianURL != "" {
		url := cfg.LibrarianURL
		// Strip http:// or https:// prefix
		if len(url) > 7 && url[:7] == "http://" {
			url = url[7:]
		} else if len(url) > 8 && url[:8] == "https://" {
			url = url[8:]
		}
		// Strip trailing slash
		if len(url) > 0 && url[len(url)-1] == '/' {
			url = url[:len(url)-1]
		}
		// librarian_url always takes precedence over server_host
		cfg.ServerHost = url
	}

	// Validate required fields - only use localhost as absolute last resort
	if cfg.ServerHost == "" {
		cfg.ServerHost = "127.0.0.1:8000"
	}
	if cfg.LogFile == "" {
		cfg.LogFile = "./test.log"
	}
	if cfg.MetricsInterval <= 0 {
		cfg.MetricsInterval = 60
	}
	if cfg.LogBatchSize <= 0 {
		cfg.LogBatchSize = 50
	}
	if cfg.LogBatchInterval <= 0 {
		cfg.LogBatchInterval = 5
	}

	return cfg, nil
}

// SaveConfig saves the configuration to a JSON file
func SaveConfig(path string, cfg *Config) error {
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(path, data, 0600)
}

// GetHTTPScheme returns "https" if SSL is enabled, otherwise "http"
func (c *Config) GetHTTPScheme() string {
	if c.SSLEnabled {
		return "https"
	}
	return "http"
}

// GetWSScheme returns "wss" if SSL is enabled, otherwise "ws"
func (c *Config) GetWSScheme() string {
	if c.SSLEnabled {
		return "wss"
	}
	return "ws"
}

// GetHTTPClient returns an HTTP client configured for TLS settings
func (c *Config) GetHTTPClient(timeout time.Duration) *http.Client {
	client := &http.Client{Timeout: timeout}

	if c.SSLEnabled && !c.SSLVerify {
		// Skip certificate verification (for self-signed certs)
		client.Transport = &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		}
	}

	return client
}

// GetTLSConfig returns TLS configuration based on settings
func (c *Config) GetTLSConfig() *tls.Config {
	if !c.SSLEnabled {
		return nil
	}
	return &tls.Config{
		InsecureSkipVerify: !c.SSLVerify,
	}
}
