package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAIHTTPServer_Health(t *testing.T) {
	server := &AIHTTPServer{port: 12380}

	req := httptest.NewRequest("GET", "/api/ai/health", nil)
	w := httptest.NewRecorder()

	server.handleHealth(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Errorf("Failed to decode response: %v", err)
	}

	// Should have healthy, enabled, runner_ready fields
	if _, ok := result["healthy"]; !ok {
		t.Error("Response missing 'healthy' field")
	}
	if _, ok := result["enabled"]; !ok {
		t.Error("Response missing 'enabled' field")
	}
	if _, ok := result["runner_ready"]; !ok {
		t.Error("Response missing 'runner_ready' field")
	}
}

func TestAIHTTPServer_Status(t *testing.T) {
	server := &AIHTTPServer{port: 12380}

	req := httptest.NewRequest("GET", "/api/ai/status", nil)
	w := httptest.NewRecorder()

	server.handleStatus(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Errorf("Failed to decode response: %v", err)
	}

	// Should have status, models, config fields
	if _, ok := result["status"]; !ok {
		t.Error("Response missing 'status' field")
	}
	if _, ok := result["models"]; !ok {
		t.Error("Response missing 'models' field")
	}
	if _, ok := result["config"]; !ok {
		t.Error("Response missing 'config' field")
	}
}

func TestAIHTTPServer_Analyze_NoBody(t *testing.T) {
	server := &AIHTTPServer{port: 12380}

	req := httptest.NewRequest("POST", "/api/ai/analyze", nil)
	w := httptest.NewRecorder()

	server.handleAnalyze(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Errorf("Expected status 400, got %d", resp.StatusCode)
	}
}

func TestAIHTTPServer_Analyze_EmptyPrompt(t *testing.T) {
	server := &AIHTTPServer{port: 12380}

	body := strings.NewReader(`{"prompt": ""}`)
	req := httptest.NewRequest("POST", "/api/ai/analyze", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	server.handleAnalyze(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Errorf("Expected status 400, got %d", resp.StatusCode)
	}
}

func TestAIHTTPServer_Analyze_AINotEnabled(t *testing.T) {
	server := &AIHTTPServer{port: 12380}

	body := strings.NewReader(`{"prompt": "analyze this"}`)
	req := httptest.NewRequest("POST", "/api/ai/analyze", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	server.handleAnalyze(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	// Should return 503 when AI is not enabled
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("Expected status 503, got %d", resp.StatusCode)
	}

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Errorf("Failed to decode response: %v", err)
	}

	if result["error"] != "AI is not enabled" {
		t.Errorf("Expected 'AI is not enabled' error, got: %v", result["error"])
	}
}

func TestAIHTTPServer_StreamAnalysis_MethodNotAllowed(t *testing.T) {
	server := &AIHTTPServer{port: 12380}

	req := httptest.NewRequest("PUT", "/api/ai/stream-analysis", nil)
	w := httptest.NewRecorder()

	server.handleStreamAnalysis(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Errorf("Expected status 405, got %d", resp.StatusCode)
	}
}

func TestAIHTTPServer_StreamAnalysis_EmptyRequest(t *testing.T) {
	server := &AIHTTPServer{port: 12380}

	body := strings.NewReader(`{}`)
	req := httptest.NewRequest("POST", "/api/ai/stream-analysis", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	server.handleStreamAnalysis(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Errorf("Expected status 400, got %d", resp.StatusCode)
	}
}

func TestCORSMiddleware(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	wrapped := corsMiddleware(handler)

	// Test preflight request
	req := httptest.NewRequest("OPTIONS", "/api/ai/health", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	w := httptest.NewRecorder()

	wrapped.ServeHTTP(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200 for preflight, got %d", resp.StatusCode)
	}

	// Check CORS headers
	if cors := resp.Header.Get("Access-Control-Allow-Origin"); cors != "http://localhost:3000" {
		t.Errorf("Expected CORS origin header, got: %s", cors)
	}
	if methods := resp.Header.Get("Access-Control-Allow-Methods"); methods == "" {
		t.Error("Missing CORS methods header")
	}
}

func TestSSEEventFormat(t *testing.T) {
	w := httptest.NewRecorder()

	// httptest.ResponseRecorder implements http.Flusher
	flusher, ok := interface{}(w).(http.Flusher)
	if !ok {
		t.Fatal("ResponseRecorder should implement http.Flusher")
	}

	// Send a test event
	sendSSEEvent(w, flusher, "chunk", `{"content": "hello"}`)

	body, _ := io.ReadAll(w.Body)
	output := string(body)

	// Verify SSE format
	if !strings.Contains(output, "event: chunk\n") {
		t.Error("Missing event line")
	}
	if !strings.Contains(output, `data: {"content": "hello"}`) {
		t.Error("Missing data line")
	}
	if !strings.HasSuffix(output, "\n\n") {
		t.Error("Missing double newline at end")
	}
}

func TestStreamAnalysisRequest_Parse(t *testing.T) {
	tests := []struct {
		name    string
		json    string
		wantErr bool
	}{
		{
			name: "Valid request with prompt",
			json: `{"prompt": "analyze these logs"}`,
		},
		{
			name: "Valid request with logs",
			json: `{"logs": ["log1", "log2"], "prompt": "what happened?"}`,
		},
		{
			name: "Request with all fields",
			json: `{"prompt": "analyze", "logs": ["log1"], "max_tokens": 512, "temperature": 0.5, "sanitize": true}`,
		},
		{
			name:    "Invalid JSON",
			json:    `{invalid`,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var req StreamAnalysisRequest
			err := json.Unmarshal([]byte(tt.json), &req)

			if tt.wantErr && err == nil {
				t.Error("Expected error, got nil")
			}
			if !tt.wantErr && err != nil {
				t.Errorf("Unexpected error: %v", err)
			}
		})
	}
}
