package main

import (
	"strings"
	"testing"
)

func TestSanitizeLogs_IPv4(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"Connection from 192.168.1.1 established", "Connection from [IP_REDACTED] established"},
		{"Server IP: 10.0.0.1, Client IP: 172.16.0.1", "Server IP: [IP_REDACTED], Client IP: [IP_REDACTED]"},
		{"Localhost 127.0.0.1 is fine", "Localhost [IP_REDACTED] is fine"},
		{"Invalid IP 999.999.999.999 should not match", "Invalid IP 999.999.999.999 should not match"},
	}

	for _, tt := range tests {
		result := SanitizeLogs(tt.input)
		if result != tt.expected {
			t.Errorf("IPv4 test failed:\nInput:    %s\nExpected: %s\nGot:      %s", tt.input, tt.expected, result)
		}
	}
}

func TestSanitizeLogs_Email(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"Contact user@example.com for support", "Contact [EMAIL_REDACTED] for support"},
		{"From: admin@company.org To: support@company.org", "From: [EMAIL_REDACTED] To: [EMAIL_REDACTED]"},
		{"Email john.doe+tag@sub.domain.co.uk works", "Email [EMAIL_REDACTED] works"},
	}

	for _, tt := range tests {
		result := SanitizeLogs(tt.input)
		if result != tt.expected {
			t.Errorf("Email test failed:\nInput:    %s\nExpected: %s\nGot:      %s", tt.input, tt.expected, result)
		}
	}
}

func TestSanitizeLogs_APIKeys(t *testing.T) {
	tests := []struct {
		input       string
		shouldMatch bool
		redactType  string
	}{
		{"Using key sk-1234567890abcdefghijklmnopqrstuvwxyz1234567890", true, "OPENAI_KEY"},
		{"AWS key AKIAIOSFODNN7EXAMPLE found", true, "AWS_KEY"},
		{"api_key=abc123def456ghi789", true, "KEY_REDACTED"},
		{"Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", true, "AUTH_HEADER"},
		{"Token=mySecretToken123456", true, "KEY_REDACTED"},
		{"GitHub token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", true, "GIT_TOKEN"},
	}

	for _, tt := range tests {
		result := SanitizeLogs(tt.input)
		if tt.shouldMatch && !strings.Contains(result, "REDACTED") {
			t.Errorf("API Key test failed - expected redaction:\nInput: %s\nGot:   %s", tt.input, result)
		}
	}
}

func TestSanitizeLogs_HighRiskKeywords(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"User password is admin123", "[LINE_REDACTED: Contains sensitive keyword]"},
		{"Setting db_password in config", "[LINE_REDACTED: Contains sensitive keyword]"},
		{"Found secret key in environment", "[LINE_REDACTED: Contains sensitive keyword]"},
		{"-----BEGIN RSA PRIVATE KEY-----", "[LINE_REDACTED: Contains sensitive keyword]"},
		{"-----BEGIN OPENSSH PRIVATE KEY-----", "[LINE_REDACTED: Contains sensitive keyword]"},
		{"This is a normal log line", "This is a normal log line"},
	}

	for _, tt := range tests {
		result := SanitizeLogs(tt.input)
		if result != tt.expected {
			t.Errorf("High-risk keyword test failed:\nInput:    %s\nExpected: %s\nGot:      %s", tt.input, tt.expected, result)
		}
	}
}

func TestSanitizeLogs_JWT(t *testing.T) {
	jwt := "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
	input := "Token: " + jwt
	result := SanitizeLogs(input)

	if !strings.Contains(result, "[JWT_REDACTED]") {
		t.Errorf("JWT test failed:\nInput: %s\nGot:   %s", input, result)
	}
}

func TestSanitizeLogs_CreditCard(t *testing.T) {
	tests := []struct {
		input       string
		shouldMatch bool
	}{
		{"Card number 4111-1111-1111-1111", true},
		{"CC: 4111 1111 1111 1111", true},
		{"Number 4111111111111111", true},
	}

	for _, tt := range tests {
		result := SanitizeLogs(tt.input)
		if tt.shouldMatch && !strings.Contains(result, "[CARD_REDACTED]") {
			t.Errorf("Credit card test failed:\nInput: %s\nGot:   %s", tt.input, result)
		}
	}
}

func TestSanitizeLogs_SSN(t *testing.T) {
	input := "SSN: 123-45-6789"
	result := SanitizeLogs(input)

	if !strings.Contains(result, "[SSN_REDACTED]") {
		t.Errorf("SSN test failed:\nInput: %s\nGot:   %s", input, result)
	}
}

func TestSanitizeLogs_MultiLine(t *testing.T) {
	input := `Connection from 192.168.1.1
User email: test@example.com
Normal log line
Password: secret123
API call completed`

	result := SanitizeLogs(input)
	lines := strings.Split(result, "\n")

	// Line 1: IP should be redacted
	if !strings.Contains(lines[0], "[IP_REDACTED]") {
		t.Errorf("Line 1 should have IP redacted: %s", lines[0])
	}

	// Line 2: Email should be redacted
	if !strings.Contains(lines[1], "[EMAIL_REDACTED]") {
		t.Errorf("Line 2 should have email redacted: %s", lines[1])
	}

	// Line 3: Should be unchanged
	if lines[2] != "Normal log line" {
		t.Errorf("Line 3 should be unchanged: %s", lines[2])
	}

	// Line 4: Should be fully redacted (contains password)
	if !strings.Contains(lines[3], "[LINE_REDACTED") {
		t.Errorf("Line 4 should be fully redacted: %s", lines[3])
	}

	// Line 5: Should be unchanged
	if lines[4] != "API call completed" {
		t.Errorf("Line 5 should be unchanged: %s", lines[4])
	}
}

func TestSanitizeLogsForCloud(t *testing.T) {
	// Cloud config should be more aggressive
	input := "User ID: 550e8400-e29b-41d4-a716-446655440000 phone: 555-123-4567"
	result := SanitizeLogsForCloud(input)

	// Should redact both UUID and phone for cloud
	if !strings.Contains(result, "UUID_REDACTED") {
		t.Errorf("Cloud sanitize should redact UUID: %s", result)
	}
	if !strings.Contains(result, "PHONE_REDACTED") {
		t.Errorf("Cloud sanitize should redact phone: %s", result)
	}
}

func TestQuickSanitize(t *testing.T) {
	tests := []struct {
		input        string
		shouldRedact bool
	}{
		{"Normal log message", false},
		{"Password: admin123", true},
		{"api_key=sk-1234567890abcdefghijklmnop", true},
	}

	for _, tt := range tests {
		result := QuickSanitize(tt.input)
		hasRedaction := strings.Contains(result, "REDACTED")
		if tt.shouldRedact && !hasRedaction {
			t.Errorf("QuickSanitize should redact:\nInput: %s\nGot:   %s", tt.input, result)
		}
		if !tt.shouldRedact && hasRedaction {
			t.Errorf("QuickSanitize should not redact:\nInput: %s\nGot:   %s", tt.input, result)
		}
	}
}

func TestIsSensitive(t *testing.T) {
	tests := []struct {
		input    string
		expected bool
	}{
		{"Normal log message", false},
		{"User password is secret", true},
		{"API key sk-1234567890abcdefghijklmnopqrstuvwxyz1234", true},
		{"SSN: 123-45-6789", true},
		{"Just a regular log", false},
	}

	for _, tt := range tests {
		result := IsSensitive(tt.input)
		if result != tt.expected {
			t.Errorf("IsSensitive(%q) = %v, expected %v", tt.input, result, tt.expected)
		}
	}
}

func TestCustomConfig(t *testing.T) {
	config := &SanitizeConfig{
		RedactIPs:      true,
		RedactEmails:   false, // Disable email redaction
		RedactAPIKeys:  true,
		RemoveHighRisk: false, // Disable high-risk filtering
	}

	input := "Email test@example.com from 192.168.1.1 with password=secret"
	result := SanitizeLogsWithConfig(input, config)

	// Email should NOT be redacted
	if strings.Contains(result, "[EMAIL_REDACTED]") {
		t.Errorf("Email should not be redacted with custom config: %s", result)
	}

	// IP should be redacted
	if !strings.Contains(result, "[IP_REDACTED]") {
		t.Errorf("IP should be redacted: %s", result)
	}

	// High-risk line should NOT be removed (disabled)
	if strings.Contains(result, "[LINE_REDACTED") {
		t.Errorf("Line should not be removed with high-risk disabled: %s", result)
	}
}

// Benchmark tests
func BenchmarkSanitizeLogs(b *testing.B) {
	input := `2024-01-15 10:30:45 Connection from 192.168.1.100
User admin@company.com logged in
API call with token=abc123xyz789 completed
Database connection established to 10.0.0.5
Request processed successfully`

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		SanitizeLogs(input)
	}
}

func BenchmarkQuickSanitize(b *testing.B) {
	input := "2024-01-15 10:30:45 Normal log line with some data"

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		QuickSanitize(input)
	}
}
