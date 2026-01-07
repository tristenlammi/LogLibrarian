package main

import (
	"fmt"
	"testing"
	"time"
)

func TestCompressLog(t *testing.T) {
	tests := []struct {
		name             string
		input            string
		expectedTemplate string
		expectedVars     []string
	}{
		{
			name:             "Basic error log with IP and port",
			input:            "2025-12-25 10:00:00 [ERROR] Connection from 192.168.1.5 failed on port 80",
			expectedTemplate: "[ERROR] Connection from <IP> failed on port <NUM>",
			expectedVars:     []string{"192.168.1.5", "80"},
		},
		{
			name:             "Log with quoted string",
			input:            `2025-12-25 10:15:30 [INFO] User "john_doe" logged in from 10.0.0.1`,
			expectedTemplate: "[INFO] User <STR> logged in from <IP>",
			expectedVars:     []string{"10.0.0.1", "john_doe"},
		},
		{
			name:             "Multiple IPs and numbers",
			input:            "2025-12-25T12:30:00Z Request from 192.168.1.100 to 10.20.30.40 took 250ms",
			expectedTemplate: "Request from <IP> to <IP> took <NUM>ms",
			expectedVars:     []string{"192.168.1.100", "10.20.30.40", "250"},
		},
		{
			name:             "Syslog format",
			input:            "Dec 25 10:00:00 webserver nginx: 404 error for 172.16.0.5",
			expectedTemplate: "webserver nginx: <NUM> error for <IP>",
			expectedVars:     []string{"172.16.0.5", "404"},
		},
		{
			name:             "Complex log with multiple elements",
			input:            `2025-12-25 14:22:15 [WARN] Database query "SELECT * FROM users" from 192.168.1.10 took 1500ms on port 5432`,
			expectedTemplate: "[WARN] Database query <STR> from <IP> took <NUM>ms on port <NUM>",
			expectedVars:     []string{"192.168.1.10", "SELECT * FROM users", "1500", "5432"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := CompressLog(tt.input)

			// Check template
			if result.TemplateText != tt.expectedTemplate {
				t.Errorf("Template mismatch:\nExpected: %s\nGot:      %s", tt.expectedTemplate, result.TemplateText)
			}

			// Check variables count
			if len(result.Variables) != len(tt.expectedVars) {
				t.Errorf("Variables count mismatch:\nExpected: %d (%v)\nGot:      %d (%v)",
					len(tt.expectedVars), tt.expectedVars,
					len(result.Variables), result.Variables)
			}

			// Check variables content
			for i, expectedVar := range tt.expectedVars {
				if i >= len(result.Variables) {
					break
				}
				if result.Variables[i] != expectedVar {
					t.Errorf("Variable[%d] mismatch:\nExpected: %s\nGot:      %s", i, expectedVar, result.Variables[i])
				}
			}

			// Check template ID exists
			if result.TemplateID == "" {
				t.Error("TemplateID should not be empty")
			}

			// Check timestamp is set
			if result.Timestamp.IsZero() {
				t.Error("Timestamp should not be zero")
			}

			// Print result for debugging
			fmt.Printf("\n[%s]\n", tt.name)
			fmt.Printf("  Template: %s\n", result.TemplateText)
			fmt.Printf("  Variables: %v\n", result.Variables)
			fmt.Printf("  TemplateID: %s\n", result.TemplateID[:16]+"...")
			fmt.Printf("  Timestamp: %s\n", result.Timestamp.Format(time.RFC3339))
		})
	}
}

func TestGenerateTemplateID(t *testing.T) {
	template1 := "[ERROR] Connection from <IP> failed on port <NUM>"
	template2 := "[ERROR] Connection from <IP> failed on port <NUM>"
	template3 := "[INFO] Connection from <IP> succeeded"

	id1 := generateTemplateID(template1)
	id2 := generateTemplateID(template2)
	id3 := generateTemplateID(template3)

	// Same templates should produce same ID
	if id1 != id2 {
		t.Error("Same templates should produce same TemplateID")
	}

	// Different templates should produce different IDs
	if id1 == id3 {
		t.Error("Different templates should produce different TemplateIDs")
	}

	// ID should be 64 characters (SHA256 hex)
	if len(id1) != 64 {
		t.Errorf("TemplateID should be 64 characters, got %d", len(id1))
	}
}
