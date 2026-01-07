package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// AIManager is the main interface for local AI functionality
// It coordinates model downloads, runner management, and inference
type AIManager struct {
	mu         sync.RWMutex
	runner     *AIRunner
	config     *AIManagerConfig
	enabled    bool
	modelID    string
	modelPath  string
	
	// Download tracking
	downloading    bool
	downloadTarget string
	downloadProg   float64
	downloadErr    string
}

// AIManagerConfig holds persistent configuration
type AIManagerConfig struct {
	ModelID       string  `json:"model_id"`
	ContextSize   int     `json:"context_size"`
	Threads       int     `json:"threads"`
	GPULayers     int     `json:"gpu_layers"`
	MaxTokens     int     `json:"max_tokens"`
	Temperature   float64 `json:"temperature"`
	AutoStart     bool    `json:"auto_start"`
}

// DefaultAIConfig returns sensible defaults
func DefaultAIConfig() *AIManagerConfig {
	return &AIManagerConfig{
		ContextSize: 2048,
		MaxTokens:   512,
		Temperature: 0.7,
		AutoStart:   false,
	}
}

// AIManagerStatus represents current state for API responses
type AIManagerStatus struct {
	Enabled        bool    `json:"enabled"`
	Running        bool    `json:"running"`
	ModelID        string  `json:"model_id,omitempty"`
	ModelPath      string  `json:"model_path,omitempty"`
	Port           int     `json:"port,omitempty"`
	Downloading    bool    `json:"downloading"`
	DownloadTarget string  `json:"download_target,omitempty"`
	DownloadProg   float64 `json:"download_progress"`
	Error          string  `json:"error,omitempty"`
	Health         string  `json:"health,omitempty"`
	RunnerReady    bool    `json:"runner_ready"`
}

// AIModel describes an available model
type AIModel struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Size        string `json:"size"`
	SizeBytes   int64  `json:"size_bytes"`
	Description string `json:"description"`
	URL         string `json:"url"`
	Filename    string `json:"filename"`
	Downloaded  bool   `json:"downloaded"`
}

// SupportedModels lists all models we can download
var SupportedModels = []AIModel{
	{
		ID:          "llama-3.2-1b",
		Name:        "Llama 3.2 1B",
		Size:        "750 MB",
		SizeBytes:   786432000,
		Description: "Compact and fast, ideal for simple analysis tasks",
		URL:         "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
		Filename:    "llama-3.2-1b-instruct-q4_k_m.gguf",
	},
	{
		ID:          "qwen-2.5-1.5b",
		Name:        "Qwen 2.5 1.5B",
		Size:        "1.1 GB",
		SizeBytes:   1181116006,
		Description: "Excellent reasoning and multilingual support",
		URL:         "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
		Filename:    "qwen2.5-1.5b-instruct-q4_k_m.gguf",
	},
	{
		ID:          "gemma-2-2b",
		Name:        "Gemma 2 2B",
		Size:        "1.5 GB",
		SizeBytes:   1610612736,
		Description: "Google's efficient model with excellent quality",
		URL:         "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
		Filename:    "gemma-2-2b-it-q4_k_m.gguf",
	},
}

// Global AI manager instance
var globalAIManager *AIManager
var aiManagerOnce sync.Once

// GetAIManager returns the singleton AI manager
func GetAIManager() *AIManager {
	aiManagerOnce.Do(func() {
		globalAIManager = &AIManager{
			runner: NewAIRunner(),
			config: DefaultAIConfig(),
		}
		globalAIManager.LoadConfig()
	})
	return globalAIManager
}

// GetModelsDir returns the directory for storing models and runner
func (m *AIManager) GetModelsDir() string {
	// Check environment variable first (set in Docker)
	if envDir := os.Getenv("AI_MODELS_DIR"); envDir != "" {
		return envDir
	}
	
	exePath, err := os.Executable()
	if err != nil {
		return filepath.Join(".", "ai-models")
	}
	return filepath.Join(filepath.Dir(exePath), "ai-models")
}

// GetRunnerPath returns the path to the llama-server binary
func (m *AIManager) GetRunnerPath() string {
	// Check environment variable first (set in Docker)
	if envPath := os.Getenv("AI_RUNNER_PATH"); envPath != "" {
		return envPath
	}
	
	// Fall back to models directory
	return filepath.Join(m.GetModelsDir(), GetRunnerBinaryName())
}

// GetConfigPath returns the path to the config file
func (m *AIManager) GetConfigPath() string {
	return filepath.Join(m.GetModelsDir(), "config.json")
}

// GetStatus returns the current status
func (m *AIManager) GetStatus() AIManagerStatus {
	m.mu.RLock()
	defer m.mu.RUnlock()

	status := AIManagerStatus{
		Enabled:        m.enabled,
		ModelID:        m.modelID,
		ModelPath:      m.modelPath,
		Downloading:    m.downloading,
		DownloadTarget: m.downloadTarget,
		DownloadProg:   m.downloadProg,
		Error:          m.downloadErr,
	}

	// Check runner status
	if m.runner != nil {
		status.Running = m.runner.IsRunning()
		status.Port = m.runner.GetPort()
		
		if status.Running {
			if health, err := m.runner.Health(); err == nil {
				status.Health = health.Status
			}
		}
	}

	// Check if runner binary exists (use GetRunnerPath for Docker/env support)
	runnerPath := m.GetRunnerPath()
	if _, err := os.Stat(runnerPath); err == nil {
		status.RunnerReady = true
	}

	return status
}

// GetModels returns all models with download status
func (m *AIManager) GetModels() []AIModel {
	modelsDir := m.GetModelsDir()
	models := make([]AIModel, len(SupportedModels))
	
	for i, model := range SupportedModels {
		models[i] = model
		modelPath := filepath.Join(modelsDir, model.Filename)
		if _, err := os.Stat(modelPath); err == nil {
			models[i].Downloaded = true
		}
	}
	
	return models
}

// FindModel finds a model by ID
func (m *AIManager) FindModel(modelID string) *AIModel {
	for _, model := range SupportedModels {
		if model.ID == modelID {
			return &model
		}
	}
	return nil
}

// DownloadModel downloads a model file
func (m *AIManager) DownloadModel(ctx context.Context, modelID string) error {
	model := m.FindModel(modelID)
	if model == nil {
		return fmt.Errorf("unknown model: %s", modelID)
	}

	m.mu.Lock()
	if m.downloading {
		m.mu.Unlock()
		return fmt.Errorf("download already in progress")
	}
	m.downloading = true
	m.downloadTarget = modelID
	m.downloadProg = 0
	m.downloadErr = ""
	m.mu.Unlock()

	defer func() {
		m.mu.Lock()
		m.downloading = false
		m.mu.Unlock()
	}()

	modelsDir := m.GetModelsDir()
	if err := os.MkdirAll(modelsDir, 0755); err != nil {
		m.mu.Lock()
		m.downloadErr = err.Error()
		m.mu.Unlock()
		return err
	}

	modelPath := filepath.Join(modelsDir, model.Filename)
	
	// Check if already exists
	if _, err := os.Stat(modelPath); err == nil {
		m.mu.Lock()
		m.downloadProg = 100
		m.mu.Unlock()
		return nil
	}

	logInfo("Starting download of model %s (%s)", modelID, model.Size)

	err := m.downloadFileWithProgress(ctx, model.URL, modelPath, model.SizeBytes)
	if err != nil {
		m.mu.Lock()
		m.downloadErr = err.Error()
		m.mu.Unlock()
		os.Remove(modelPath)
		return err
	}

	logInfo("Model %s downloaded successfully", modelID)
	return nil
}

// DownloadRunner downloads the llama-server binary
func (m *AIManager) DownloadRunner(ctx context.Context) error {
	m.mu.Lock()
	if m.downloading {
		m.mu.Unlock()
		return fmt.Errorf("download already in progress")
	}
	m.downloading = true
	m.downloadTarget = "llama-server"
	m.downloadProg = 0
	m.downloadErr = ""
	m.mu.Unlock()

	defer func() {
		m.mu.Lock()
		m.downloading = false
		m.mu.Unlock()
	}()

	modelsDir := m.GetModelsDir()
	if err := os.MkdirAll(modelsDir, 0755); err != nil {
		return err
	}

	runnerPath := filepath.Join(modelsDir, GetRunnerBinaryName())
	
	// Check if already exists
	if _, err := os.Stat(runnerPath); err == nil {
		logInfo("Runner already exists at %s", runnerPath)
		return nil
	}

	downloadURL := GetRunnerDownloadURL()
	if downloadURL == "" {
		err := fmt.Errorf("no pre-built binary available for this platform")
		m.mu.Lock()
		m.downloadErr = err.Error()
		m.mu.Unlock()
		return err
	}

	logInfo("Downloading llama-server from %s", downloadURL)

	// For direct executable downloads
	err := m.downloadFileWithProgress(ctx, downloadURL, runnerPath, 0)
	if err != nil {
		m.mu.Lock()
		m.downloadErr = err.Error()
		m.mu.Unlock()
		os.Remove(runnerPath)
		return err
	}

	// Make executable on Unix
	os.Chmod(runnerPath, 0755)

	logInfo("Runner downloaded successfully")
	return nil
}

// downloadFileWithProgress downloads a file with progress tracking
func (m *AIManager) downloadFileWithProgress(ctx context.Context, url, destPath string, expectedSize int64) error {
	tmpPath := destPath + ".download"
	
	out, err := os.Create(tmpPath)
	if err != nil {
		return fmt.Errorf("failed to create file: %w", err)
	}
	defer out.Close()

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "Scribe-Agent/1.0")

	client := &http.Client{Timeout: 30 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("download failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		os.Remove(tmpPath)
		return fmt.Errorf("download failed with status %d", resp.StatusCode)
	}

	totalSize := resp.ContentLength
	if totalSize <= 0 && expectedSize > 0 {
		totalSize = expectedSize
	}

	var downloaded int64
	buf := make([]byte, 64*1024) // 64KB buffer

	for {
		select {
		case <-ctx.Done():
			os.Remove(tmpPath)
			return ctx.Err()
		default:
		}

		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, writeErr := out.Write(buf[:n]); writeErr != nil {
				os.Remove(tmpPath)
				return writeErr
			}
			downloaded += int64(n)

			if totalSize > 0 {
				m.mu.Lock()
				m.downloadProg = float64(downloaded) / float64(totalSize) * 100
				m.mu.Unlock()
			}
		}

		if readErr != nil {
			if readErr == io.EOF {
				break
			}
			os.Remove(tmpPath)
			return readErr
		}
	}

	out.Close()

	// Rename to final path
	if err := os.Rename(tmpPath, destPath); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("failed to finalize download: %w", err)
	}

	m.mu.Lock()
	m.downloadProg = 100
	m.mu.Unlock()

	return nil
}

// Enable starts the AI runner with the specified model
func (m *AIManager) Enable(modelID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Stop if already running with different model
	if m.enabled && m.runner.IsRunning() {
		if m.modelID == modelID {
			return nil // Already running with same model
		}
		m.runner.Stop()
	}

	model := m.FindModel(modelID)
	if model == nil {
		return fmt.Errorf("unknown model: %s", modelID)
	}

	modelsDir := m.GetModelsDir()
	modelPath := filepath.Join(modelsDir, model.Filename)

	// Check model exists
	if _, err := os.Stat(modelPath); os.IsNotExist(err) {
		return fmt.Errorf("model %s not downloaded", modelID)
	}

	// Check runner exists (use GetRunnerPath for Docker/env support)
	runnerPath := m.GetRunnerPath()
	if _, err := os.Stat(runnerPath); os.IsNotExist(err) {
		return fmt.Errorf("llama-server not installed at %s - please download it first", runnerPath)
	}

	// Start the runner with explicit runner path
	config := AIRunnerConfig{
		ModelPath:   modelPath,
		RunnerPath:  runnerPath,
		ContextSize: m.config.ContextSize,
		Threads:     m.config.Threads,
		GPULayers:   m.config.GPULayers,
	}

	if err := m.runner.Start(config); err != nil {
		return fmt.Errorf("failed to start runner: %w", err)
	}

	m.modelID = modelID
	m.modelPath = modelPath
	m.enabled = true
	m.config.ModelID = modelID

	// Persist config
	m.saveConfigLocked()

	logInfo("AI enabled with model %s", modelID)
	return nil
}

// Disable stops the AI runner
func (m *AIManager) Disable() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if !m.enabled {
		return nil
	}

	if err := m.runner.Stop(); err != nil {
		return err
	}

	m.enabled = false
	logInfo("AI disabled")
	return nil
}

// IsEnabled returns whether AI is enabled and running
func (m *AIManager) IsEnabled() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.enabled && m.runner != nil && m.runner.IsRunning()
}

// Generate produces text using the loaded model (simple string prompt)
func (m *AIManager) Generate(ctx context.Context, req CompletionRequest) (*CompletionResponse, error) {
	m.mu.RLock()
	if !m.enabled || !m.runner.IsRunning() {
		m.mu.RUnlock()
		return nil, fmt.Errorf("AI not enabled")
	}
	config := m.config
	m.mu.RUnlock()

	// Apply defaults from config if not set
	if req.MaxTokens == 0 {
		req.MaxTokens = config.MaxTokens
	}
	if req.Temperature == 0 {
		req.Temperature = config.Temperature
	}
	if len(req.Stop) == 0 {
		req.Stop = []string{"<|endoftext|>", "<|im_end|>", "</s>", "<|eot_id|>"}
	}

	return m.runner.Generate(ctx, req)
}

// GenerateSimple produces text from a simple string prompt
func (m *AIManager) GenerateSimple(ctx context.Context, prompt string) (string, error) {
	resp, err := m.Generate(ctx, CompletionRequest{Prompt: prompt})
	if err != nil {
		return "", err
	}
	return resp.Content, nil
}

// StreamGenerate produces streaming text with CompletionRequest
func (m *AIManager) StreamGenerate(ctx context.Context, req CompletionRequest, callback func(StreamChunk) error) error {
	m.mu.RLock()
	if !m.enabled || !m.runner.IsRunning() {
		m.mu.RUnlock()
		return fmt.Errorf("AI not enabled")
	}
	config := m.config
	m.mu.RUnlock()

	// Apply defaults from config if not set
	if req.MaxTokens == 0 {
		req.MaxTokens = config.MaxTokens
	}
	if req.Temperature == 0 {
		req.Temperature = config.Temperature
	}
	if len(req.Stop) == 0 {
		req.Stop = []string{"<|endoftext|>", "<|im_end|>", "</s>", "<|eot_id|>"}
	}

	return m.runner.GenerateStream(ctx, req, callback)
}

// StreamGenerateSimple produces streaming text from a simple string prompt
func (m *AIManager) StreamGenerateSimple(ctx context.Context, prompt string, callback func(string) error) error {
	return m.StreamGenerate(ctx, CompletionRequest{Prompt: prompt}, func(chunk StreamChunk) error {
		return callback(chunk.Content)
	})
}

// UpdateConfig updates the AI configuration
func (m *AIManager) UpdateConfig(config *AIManagerConfig) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if config.ContextSize > 0 {
		m.config.ContextSize = config.ContextSize
	}
	if config.Threads >= 0 {
		m.config.Threads = config.Threads
	}
	if config.GPULayers >= 0 {
		m.config.GPULayers = config.GPULayers
	}
	if config.MaxTokens > 0 {
		m.config.MaxTokens = config.MaxTokens
	}
	if config.Temperature > 0 {
		m.config.Temperature = config.Temperature
	}
	m.config.AutoStart = config.AutoStart

	m.saveConfigLocked()
}

// GetConfig returns the current configuration
func (m *AIManager) GetConfig() *AIManagerConfig {
	m.mu.RLock()
	defer m.mu.RUnlock()
	
	config := *m.config
	return &config
}

// DeleteModel removes a downloaded model
func (m *AIManager) DeleteModel(modelID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.enabled && m.modelID == modelID {
		return fmt.Errorf("cannot delete model while in use")
	}

	model := m.FindModel(modelID)
	if model == nil {
		return fmt.Errorf("unknown model: %s", modelID)
	}

	modelPath := filepath.Join(m.GetModelsDir(), model.Filename)
	if err := os.Remove(modelPath); err != nil && !os.IsNotExist(err) {
		return err
	}

	logInfo("Model %s deleted", modelID)
	return nil
}

// SaveConfig persists configuration to disk
func (m *AIManager) SaveConfig() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.saveConfigLocked()
}

func (m *AIManager) saveConfigLocked() error {
	configPath := m.GetConfigPath()
	
	if err := os.MkdirAll(filepath.Dir(configPath), 0755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(m.config, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(configPath, data, 0644)
}

// LoadConfig loads configuration from disk
func (m *AIManager) LoadConfig() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	configPath := m.GetConfigPath()
	data, err := os.ReadFile(configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil // Use defaults
		}
		return err
	}

	return json.Unmarshal(data, m.config)
}

// AutoStartIfConfigured starts AI if auto_start is enabled
func (m *AIManager) AutoStartIfConfigured() {
	m.mu.RLock()
	autoStart := m.config.AutoStart
	modelID := m.config.ModelID
	m.mu.RUnlock()

	if autoStart && modelID != "" {
		logInfo("Auto-starting AI with model %s", modelID)
		if err := m.Enable(modelID); err != nil {
			logError("Failed to auto-start AI: %v", err)
		}
	}
}
