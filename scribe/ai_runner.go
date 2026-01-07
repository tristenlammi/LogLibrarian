package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

// AIRunner manages the llama-server subprocess for local inference
type AIRunner struct {
	mu            sync.RWMutex
	process       *exec.Cmd
	port          int
	modelPath     string
	runnerPath    string
	client        *http.Client
	isRunning     bool
	ctx           context.Context
	cancel        context.CancelFunc
	startupChan   chan error
	outputBuffer  []string
	maxOutputSize int
}

// AIRunnerConfig holds configuration for the runner
type AIRunnerConfig struct {
	ModelPath      string `json:"model_path"`
	RunnerPath     string `json:"runner_path"`     // Path to llama-server binary
	ContextSize    int    `json:"context_size"`    // Default: 2048
	Threads        int    `json:"threads"`         // Default: auto-detect
	GPULayers      int    `json:"gpu_layers"`      // 0 = CPU only
	BatchSize      int    `json:"batch_size"`      // Default: 512
	FlashAttention bool   `json:"flash_attention"` // Enable if supported
}

// CompletionRequest matches llama-server /completion endpoint
type CompletionRequest struct {
	Prompt      string   `json:"prompt"`
	MaxTokens   int      `json:"n_predict,omitempty"`   // Max tokens to generate
	Temperature float64  `json:"temperature,omitempty"` // 0.0-2.0, default 0.8
	TopK        int      `json:"top_k,omitempty"`       // Default 40
	TopP        float64  `json:"top_p,omitempty"`       // Default 0.95
	Stop        []string `json:"stop,omitempty"`        // Stop sequences
	Stream      bool     `json:"stream,omitempty"`      // Enable streaming
}

// CompletionResponse from llama-server
type CompletionResponse struct {
	Content          string `json:"content"`
	Model            string `json:"model,omitempty"`
	Prompt           string `json:"prompt,omitempty"`
	Stop             bool   `json:"stop"`
	StoppedEOS       bool   `json:"stopped_eos,omitempty"`
	StoppedLimit     bool   `json:"stopped_limit,omitempty"`
	StoppedWord      string `json:"stopped_word,omitempty"`
	TokensEvaluated  int    `json:"tokens_evaluated,omitempty"`
	TokensPredicted  int    `json:"tokens_predicted,omitempty"`
	TruncatedPrompt  bool   `json:"truncated,omitempty"`
	GenerationTimeMS int64  `json:"generation_time_ms,omitempty"`
}

// StreamChunk for streaming responses
type StreamChunk struct {
	Content string `json:"content"`
	Stop    bool   `json:"stop"`
}

// HealthResponse from llama-server /health endpoint
type HealthResponse struct {
	Status      string `json:"status"`
	SlotsIdle   int    `json:"slots_idle,omitempty"`
	SlotsActive int    `json:"slots_processing,omitempty"`
}

// NewAIRunner creates a new runner instance
func NewAIRunner() *AIRunner {
	return &AIRunner{
		client: &http.Client{
			Timeout: 5 * time.Minute, // Long timeout for generation
		},
		maxOutputSize: 100,
		outputBuffer:  make([]string, 0, 100),
	}
}

// GetRunnerBinaryName returns the expected binary name for the current OS
func GetRunnerBinaryName() string {
	if runtime.GOOS == "windows" {
		return "llama-server.exe"
	}
	return "llama-server"
}

// GetRunnerDownloadURL returns the download URL for the runner binary
func GetRunnerDownloadURL() string {
	// Using llama.cpp releases - these provide pre-built binaries
	baseURL := "https://github.com/ggerganov/llama.cpp/releases/latest/download"

	switch runtime.GOOS {
	case "windows":
		if runtime.GOARCH == "amd64" {
			return baseURL + "/llama-server-win-x64.exe"
		}
		return baseURL + "/llama-server-win-arm64.exe"
	case "linux":
		if runtime.GOARCH == "amd64" {
			return baseURL + "/llama-server-ubuntu-x64"
		}
		return baseURL + "/llama-server-linux-arm64"
	case "darwin":
		return baseURL + "/llama-server-macos-arm64"
	default:
		return ""
	}
}

// findFreePort finds an available port in the range 12300-12400
func findFreePort() (int, error) {
	for port := 12300; port <= 12400; port++ {
		addr := fmt.Sprintf("127.0.0.1:%d", port)
		ln, err := net.Listen("tcp", addr)
		if err == nil {
			ln.Close()
			return port, nil
		}
	}
	return 0, fmt.Errorf("no free port found in range 12300-12400")
}

// Start launches the llama-server subprocess
func (r *AIRunner) Start(config AIRunnerConfig) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.isRunning {
		return fmt.Errorf("runner already running")
	}

	// Validate model path
	if _, err := os.Stat(config.ModelPath); os.IsNotExist(err) {
		return fmt.Errorf("model file not found: %s", config.ModelPath)
	}

	// Determine runner path
	var runnerPath string

	// If explicit runner path provided (e.g., from Docker env), use it
	if config.RunnerPath != "" {
		if _, err := os.Stat(config.RunnerPath); err == nil {
			runnerPath = config.RunnerPath
		}
	}

	// Fall back to searching in standard locations
	if runnerPath == "" {
		runnerName := GetRunnerBinaryName()
		possiblePaths := []string{
			filepath.Join(filepath.Dir(config.ModelPath), runnerName),
			filepath.Join(filepath.Dir(os.Args[0]), runnerName),
			runnerName, // PATH lookup
		}

		for _, p := range possiblePaths {
			if _, err := os.Stat(p); err == nil {
				runnerPath = p
				break
			}
			// Also try PATH lookup
			if p == runnerName {
				if path, err := exec.LookPath(runnerName); err == nil {
					runnerPath = path
					break
				}
			}
		}
	}

	if runnerPath == "" {
		return fmt.Errorf("llama-server binary not found. Please download from: %s", GetRunnerDownloadURL())
	}

	// Find a free port
	port, err := findFreePort()
	if err != nil {
		return err
	}

	// Set defaults
	if config.ContextSize == 0 {
		config.ContextSize = 2048
	}
	if config.Threads == 0 {
		config.Threads = runtime.NumCPU()
		// Don't use more than 8 threads by default
		if config.Threads > 8 {
			config.Threads = 8
		}
	}
	if config.BatchSize == 0 {
		config.BatchSize = 512
	}

	// Build command arguments
	args := []string{
		"--model", config.ModelPath,
		"--host", "127.0.0.1",
		"--port", fmt.Sprintf("%d", port),
		"--ctx-size", fmt.Sprintf("%d", config.ContextSize),
		"--threads", fmt.Sprintf("%d", config.Threads),
		"--batch-size", fmt.Sprintf("%d", config.BatchSize),
		"--log-disable", // Reduce noise
	}

	if config.GPULayers > 0 {
		args = append(args, "--n-gpu-layers", fmt.Sprintf("%d", config.GPULayers))
	}

	if config.FlashAttention {
		args = append(args, "--flash-attn")
	}

	// Create context for cancellation
	r.ctx, r.cancel = context.WithCancel(context.Background())

	// Create the command
	r.process = exec.CommandContext(r.ctx, runnerPath, args...)

	// Capture stdout/stderr
	stdout, err := r.process.StdoutPipe()
	if err != nil {
		return fmt.Errorf("failed to create stdout pipe: %w", err)
	}
	stderr, err := r.process.StderrPipe()
	if err != nil {
		return fmt.Errorf("failed to create stderr pipe: %w", err)
	}

	// Start the process
	if err := r.process.Start(); err != nil {
		return fmt.Errorf("failed to start llama-server: %w", err)
	}

	r.port = port
	r.modelPath = config.ModelPath
	r.runnerPath = runnerPath
	r.startupChan = make(chan error, 1)
	r.outputBuffer = make([]string, 0, r.maxOutputSize)

	// Read output in background
	go r.readOutput(stdout)
	go r.readOutput(stderr)

	// Wait for server to be ready
	go r.waitForReady()

	// Wait for startup with timeout
	select {
	case err := <-r.startupChan:
		if err != nil {
			r.Stop() // Cleanup on failure
			return err
		}
	case <-time.After(60 * time.Second):
		r.Stop()
		return fmt.Errorf("timeout waiting for llama-server to start")
	}

	r.isRunning = true
	logInfo("AI runner started on port %d with model %s", port, filepath.Base(config.ModelPath))
	return nil
}

// readOutput reads and buffers output from the subprocess
func (r *AIRunner) readOutput(reader io.Reader) {
	scanner := bufio.NewScanner(reader)
	for scanner.Scan() {
		line := scanner.Text()

		r.mu.Lock()
		if len(r.outputBuffer) >= r.maxOutputSize {
			r.outputBuffer = r.outputBuffer[1:]
		}
		r.outputBuffer = append(r.outputBuffer, line)
		r.mu.Unlock()

		// Log important messages
		if strings.Contains(line, "error") || strings.Contains(line, "Error") {
			logError("llama-server: %s", line)
		}
	}
}

// waitForReady polls the health endpoint until ready
func (r *AIRunner) waitForReady() {
	healthURL := fmt.Sprintf("http://127.0.0.1:%d/health", r.port)

	for i := 0; i < 120; i++ { // Try for 60 seconds (500ms intervals)
		select {
		case <-r.ctx.Done():
			r.startupChan <- fmt.Errorf("startup cancelled")
			return
		default:
		}

		resp, err := http.Get(healthURL)
		if err == nil {
			defer resp.Body.Close()

			if resp.StatusCode == http.StatusOK {
				var health HealthResponse
				if json.NewDecoder(resp.Body).Decode(&health) == nil {
					if health.Status == "ok" || health.Status == "ready" {
						r.startupChan <- nil
						return
					}
				}
			}
		}

		time.Sleep(500 * time.Millisecond)
	}

	r.startupChan <- fmt.Errorf("llama-server failed to become ready")
}

// Stop terminates the llama-server subprocess
func (r *AIRunner) Stop() error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if !r.isRunning && r.process == nil {
		return nil
	}

	// Cancel the context to signal shutdown
	if r.cancel != nil {
		r.cancel()
	}

	// Give it a moment to shutdown gracefully
	time.Sleep(100 * time.Millisecond)

	// Force kill if still running
	if r.process != nil && r.process.Process != nil {
		if runtime.GOOS == "windows" {
			// Windows needs explicit kill
			exec.Command("taskkill", "/F", "/PID", fmt.Sprintf("%d", r.process.Process.Pid)).Run()
		} else {
			r.process.Process.Kill()
		}
		r.process.Wait()
	}

	r.isRunning = false
	r.process = nil
	r.port = 0

	logInfo("AI runner stopped")
	return nil
}

// IsRunning returns whether the runner is active
func (r *AIRunner) IsRunning() bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.isRunning
}

// GetPort returns the current port
func (r *AIRunner) GetPort() int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.port
}

// GetOutput returns recent output from the subprocess
func (r *AIRunner) GetOutput() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]string, len(r.outputBuffer))
	copy(result, r.outputBuffer)
	return result
}

// Generate sends a completion request to llama-server
func (r *AIRunner) Generate(ctx context.Context, req CompletionRequest) (*CompletionResponse, error) {
	r.mu.RLock()
	if !r.isRunning {
		r.mu.RUnlock()
		return nil, fmt.Errorf("runner not running")
	}
	port := r.port
	r.mu.RUnlock()

	// Set defaults
	if req.MaxTokens == 0 {
		req.MaxTokens = 512
	}
	if req.Temperature == 0 {
		req.Temperature = 0.7
	}

	url := fmt.Sprintf("http://127.0.0.1:%d/completion", port)

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, strings.NewReader(string(body)))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := r.client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("server returned %d: %s", resp.StatusCode, string(bodyBytes))
	}

	var result CompletionResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &result, nil
}

// GenerateStream sends a streaming completion request
func (r *AIRunner) GenerateStream(ctx context.Context, req CompletionRequest, callback func(chunk StreamChunk) error) error {
	r.mu.RLock()
	if !r.isRunning {
		r.mu.RUnlock()
		return fmt.Errorf("runner not running")
	}
	port := r.port
	r.mu.RUnlock()

	req.Stream = true
	if req.MaxTokens == 0 {
		req.MaxTokens = 512
	}

	url := fmt.Sprintf("http://127.0.0.1:%d/completion", port)

	body, err := json.Marshal(req)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, strings.NewReader(string(body)))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	resp, err := r.client.Do(httpReq)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("server returned %d: %s", resp.StatusCode, string(bodyBytes))
	}

	// Parse SSE stream
	scanner := bufio.NewScanner(resp.Body)
	for scanner.Scan() {
		line := scanner.Text()

		// SSE format: "data: {...}"
		if !strings.HasPrefix(line, "data: ") {
			continue
		}

		data := strings.TrimPrefix(line, "data: ")
		if data == "[DONE]" {
			break
		}

		var chunk StreamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue // Skip malformed chunks
		}

		if err := callback(chunk); err != nil {
			return err
		}

		if chunk.Stop {
			break
		}
	}

	return scanner.Err()
}

// Health checks if the server is responsive
func (r *AIRunner) Health() (*HealthResponse, error) {
	r.mu.RLock()
	if !r.isRunning {
		r.mu.RUnlock()
		return nil, fmt.Errorf("runner not running")
	}
	port := r.port
	r.mu.RUnlock()

	url := fmt.Sprintf("http://127.0.0.1:%d/health", port)

	resp, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var health HealthResponse
	if err := json.NewDecoder(resp.Body).Decode(&health); err != nil {
		return nil, err
	}

	return &health, nil
}

// GetModelInfo returns information about the loaded model
func (r *AIRunner) GetModelInfo() map[string]interface{} {
	r.mu.RLock()
	defer r.mu.RUnlock()

	return map[string]interface{}{
		"running":     r.isRunning,
		"port":        r.port,
		"model_path":  r.modelPath,
		"runner_path": r.runnerPath,
	}
}
