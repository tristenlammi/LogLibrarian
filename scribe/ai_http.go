package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"
)

// AIHTTPServer provides HTTP endpoints for AI features including SSE streaming
type AIHTTPServer struct {
	mu      sync.RWMutex
	server  *http.Server
	port    int
	running bool
}

// Global AI HTTP server instance
var globalAIHTTPServer *AIHTTPServer
var aiHTTPServerOnce sync.Once

// GetAIHTTPServer returns the singleton HTTP server
func GetAIHTTPServer() *AIHTTPServer {
	aiHTTPServerOnce.Do(func() {
		globalAIHTTPServer = &AIHTTPServer{
			port: 12380, // Default port for AI HTTP API
		}
	})
	return globalAIHTTPServer
}

// StreamAnalysisRequest represents an analysis request
type StreamAnalysisRequest struct {
	Prompt      string   `json:"prompt"`
	Logs        []string `json:"logs,omitempty"`
	MaxTokens   int      `json:"max_tokens,omitempty"`
	Temperature float64  `json:"temperature,omitempty"`
	Sanitize    bool     `json:"sanitize,omitempty"` // Apply PII redaction
}

// SSEEvent represents a Server-Sent Event
type SSEEvent struct {
	Event string `json:"event,omitempty"`
	Data  string `json:"data"`
}

// Start begins the HTTP server
func (s *AIHTTPServer) Start() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.running {
		return nil
	}

	mux := http.NewServeMux()

	// SSE streaming endpoint
	mux.HandleFunc("/api/ai/stream-analysis", s.handleStreamAnalysis)

	// Non-streaming analysis endpoint (fallback)
	mux.HandleFunc("/api/ai/analyze", s.handleAnalyze)

	// Health check
	mux.HandleFunc("/api/ai/health", s.handleHealth)

	// AI status
	mux.HandleFunc("/api/ai/status", s.handleStatus)

	// CORS middleware wrapper
	handler := corsMiddleware(mux)

	s.server = &http.Server{
		Addr:         fmt.Sprintf(":%d", s.port),
		Handler:      handler,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 5 * time.Minute, // Long timeout for streaming
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		log.Printf("AI HTTP server starting on port %d", s.port)
		if err := s.server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("AI HTTP server error: %v", err)
		}
	}()

	s.running = true
	return nil
}

// Stop shuts down the HTTP server
func (s *AIHTTPServer) Stop() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if !s.running || s.server == nil {
		return nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := s.server.Shutdown(ctx)
	s.running = false
	log.Printf("AI HTTP server stopped")
	return err
}

// corsMiddleware adds CORS headers for browser access
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Allow requests from dashboard
		origin := r.Header.Get("Origin")
		if origin == "" {
			origin = "*"
		}

		w.Header().Set("Access-Control-Allow-Origin", origin)
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept")
		w.Header().Set("Access-Control-Allow-Credentials", "true")

		// Handle preflight
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		next.ServeHTTP(w, r)
	})
}

// handleStreamAnalysis implements SSE streaming for AI responses
func (s *AIHTTPServer) handleStreamAnalysis(w http.ResponseWriter, r *http.Request) {
	// Only allow GET (SSE standard) or POST (for larger payloads)
	if r.Method != "GET" && r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse request
	var req StreamAnalysisRequest

	if r.Method == "POST" {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
			return
		}
	} else {
		// GET - read from query params
		req.Prompt = r.URL.Query().Get("prompt")
		if r.URL.Query().Get("sanitize") == "true" {
			req.Sanitize = true
		}
	}

	if req.Prompt == "" && len(req.Logs) == 0 {
		http.Error(w, "prompt or logs required", http.StatusBadRequest)
		return
	}

	// Set SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // Disable nginx buffering

	// Get flusher for streaming
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming not supported", http.StatusInternalServerError)
		return
	}

	// Build prompt with logs context if provided
	fullPrompt := req.Prompt
	if len(req.Logs) > 0 {
		// Optionally sanitize logs before sending to AI
		logs := req.Logs
		if req.Sanitize {
			logs = SanitizeMultipleLines(logs, false)
		}

		logsContext := strings.Join(logs, "\n")
		fullPrompt = fmt.Sprintf(`Analyze the following log entries and provide insights:

%s

User request: %s

Provide a clear, actionable analysis.`, logsContext, req.Prompt)
	}

	// Get AI manager
	manager := GetAIManager()
	if !manager.IsEnabled() {
		// Send error event
		sendSSEEvent(w, flusher, "error", `{"error": "AI is not enabled"}`)
		return
	}

	// Send start event
	sendSSEEvent(w, flusher, "start", `{"status": "starting"}`)

	// Create completion request
	completionReq := CompletionRequest{
		Prompt:      fullPrompt,
		MaxTokens:   req.MaxTokens,
		Temperature: req.Temperature,
		Stream:      true,
	}

	if completionReq.MaxTokens == 0 {
		completionReq.MaxTokens = 1024
	}
	if completionReq.Temperature == 0 {
		completionReq.Temperature = 0.7
	}

	// Create context with timeout
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
	defer cancel()

	// Track total response
	var totalResponse strings.Builder
	tokenCount := 0

	// Stream the response
	err := manager.StreamGenerate(ctx, completionReq, func(chunk StreamChunk) error {
		// Check if client disconnected
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		tokenCount++
		totalResponse.WriteString(chunk.Content)

		// Send chunk as SSE event
		chunkData, _ := json.Marshal(map[string]interface{}{
			"content": chunk.Content,
			"done":    chunk.Stop,
			"tokens":  tokenCount,
		})

		sendSSEEvent(w, flusher, "chunk", string(chunkData))

		return nil
	})

	if err != nil {
		log.Printf("Stream generation error: %v", err)
		errorData, _ := json.Marshal(map[string]string{
			"error": err.Error(),
		})
		sendSSEEvent(w, flusher, "error", string(errorData))
	}

	// Send completion event
	completeData, _ := json.Marshal(map[string]interface{}{
		"status":       "complete",
		"total_tokens": tokenCount,
		"full_content": totalResponse.String(),
	})
	sendSSEEvent(w, flusher, "complete", string(completeData))

	// Send done event (SSE standard)
	sendSSEEvent(w, flusher, "done", "[DONE]")
}

// sendSSEEvent sends a single SSE event
func sendSSEEvent(w http.ResponseWriter, flusher http.Flusher, event, data string) {
	if event != "" {
		fmt.Fprintf(w, "event: %s\n", event)
	}
	fmt.Fprintf(w, "data: %s\n\n", data)
	flusher.Flush()
}

// handleAnalyze provides non-streaming analysis (fallback)
func (s *AIHTTPServer) handleAnalyze(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req StreamAnalysisRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	if req.Prompt == "" && len(req.Logs) == 0 {
		http.Error(w, "prompt or logs required", http.StatusBadRequest)
		return
	}

	// Build prompt
	fullPrompt := req.Prompt
	if len(req.Logs) > 0 {
		logs := req.Logs
		if req.Sanitize {
			logs = SanitizeMultipleLines(logs, false)
		}

		logsContext := strings.Join(logs, "\n")
		fullPrompt = fmt.Sprintf(`Analyze the following log entries:

%s

User request: %s`, logsContext, req.Prompt)
	}

	manager := GetAIManager()
	if !manager.IsEnabled() {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(map[string]string{
			"error": "AI is not enabled",
		})
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
	defer cancel()

	completionReq := CompletionRequest{
		Prompt:      fullPrompt,
		MaxTokens:   req.MaxTokens,
		Temperature: req.Temperature,
	}

	if completionReq.MaxTokens == 0 {
		completionReq.MaxTokens = 1024
	}
	if completionReq.Temperature == 0 {
		completionReq.Temperature = 0.7
	}

	response, err := manager.Generate(ctx, completionReq)
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{
			"error": err.Error(),
		})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"content":          response.Content,
		"tokens_predicted": response.TokensPredicted,
		"tokens_evaluated": response.TokensEvaluated,
	})
}

// handleHealth returns AI service health
func (s *AIHTTPServer) handleHealth(w http.ResponseWriter, r *http.Request) {
	manager := GetAIManager()
	status := manager.GetStatus()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"healthy":      status.Running,
		"enabled":      status.Enabled,
		"model":        status.ModelID,
		"runner_ready": status.RunnerReady,
	})
}

// handleStatus returns full AI status
func (s *AIHTTPServer) handleStatus(w http.ResponseWriter, r *http.Request) {
	manager := GetAIManager()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": manager.GetStatus(),
		"models": manager.GetModels(),
		"config": manager.GetConfig(),
	})
}

// GetPort returns the server port
func (s *AIHTTPServer) GetPort() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.port
}

// SetPort sets the server port (must be called before Start)
func (s *AIHTTPServer) SetPort(port int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.running {
		s.port = port
	}
}

// IsRunning returns whether the server is running
func (s *AIHTTPServer) IsRunning() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.running
}
