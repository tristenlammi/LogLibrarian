package main

import (
	"regexp"
	"strings"
)

// PII Redaction patterns (prefixed with 'pii' to avoid conflicts)
var (
	// IPv4 addresses: 192.168.1.1, 10.0.0.1, etc.
	piiIPv4Pattern = regexp.MustCompile(`\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b`)

	// IPv6 addresses (simplified pattern)
	piiIPv6Pattern = regexp.MustCompile(`\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b|\b(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b`)

	// Email addresses: user@domain.com
	piiEmailPattern = regexp.MustCompile(`\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b`)

	// OpenAI API keys: sk-... (typically 48+ chars)
	piiOpenAIKeyPattern = regexp.MustCompile(`\bsk-[A-Za-z0-9]{20,}\b`)

	// AWS Access Keys: AKIA...
	piiAWSAccessKeyPattern = regexp.MustCompile(`\bAKIA[0-9A-Z]{16}\b`)

	// AWS Secret Keys (40 char base64-ish)
	piiAWSSecretKeyPattern = regexp.MustCompile(`\b[A-Za-z0-9/+=]{40}\b`)

	// Generic API keys in key=value format
	// Matches: api_key=xxx, apiKey=xxx, API-KEY=xxx, token=xxx, secret=xxx
	piiKeyValuePattern = regexp.MustCompile(`(?i)\b(api[_-]?key|apikey|api[_-]?secret|access[_-]?token|auth[_-]?token|bearer[_-]?token|secret[_-]?key|private[_-]?key|client[_-]?secret|app[_-]?secret)\s*[=:]\s*['"]?([A-Za-z0-9_\-./+=]{8,})['"]?`)

	// Authorization headers: Bearer xxx, Basic xxx
	piiAuthHeaderPattern = regexp.MustCompile(`(?i)\b(Bearer|Basic)\s+[A-Za-z0-9_\-./+=]{10,}\b`)

	// JWT tokens (three base64 segments separated by dots)
	piiJWTPattern = regexp.MustCompile(`\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\b`)

	// Credit card numbers (basic pattern - 13-19 digits with optional separators)
	piiCreditCardPattern = regexp.MustCompile(`\b(?:\d{4}[- ]?){3}\d{1,7}\b`)

	// Social Security Numbers (US): 123-45-6789
	piiSSNPattern = regexp.MustCompile(`\b\d{3}-\d{2}-\d{4}\b`)

	// Phone numbers (various formats)
	piiPhonePattern = regexp.MustCompile(`\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b`)

	// GitHub/GitLab tokens: ghp_, gho_, ghu_, glpat-, etc.
	piiGitTokenPattern = regexp.MustCompile(`\b(ghp_|gho_|ghu_|ghs_|ghr_|glpat-)[A-Za-z0-9_]{20,}\b`)

	// Slack tokens: xoxb-, xoxp-, xoxa-, xoxr-
	piiSlackTokenPattern = regexp.MustCompile(`\bxox[bpars]-[A-Za-z0-9-]{10,}\b`)

	// Generic hex secrets (32+ hex chars, likely hashes/keys)
	piiHexSecretPattern = regexp.MustCompile(`\b[a-fA-F0-9]{32,}\b`)

	// UUID pattern (for context, may want to partially redact)
	piiUUIDPattern = regexp.MustCompile(`\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b`)

	// High-risk keywords that trigger full line removal (case-insensitive)
	highRiskKeywords = []string{
		"password",
		"passwd",
		"pwd",
		"secret",
		"private key",
		"private_key",
		"privatekey",
		"-----begin rsa",
		"-----begin openssh",
		"-----begin private",
		"-----begin ec private",
		"ssh-rsa",
		"ssh-ed25519",
		"encryption key",
		"master key",
		"root password",
		"admin password",
		"database password",
		"db_password",
		"mysql_pwd",
		"postgres_password",
	}
)

// SanitizeConfig allows customizing sanitization behavior
type SanitizeConfig struct {
	RedactIPs         bool
	RedactEmails      bool
	RedactAPIKeys     bool
	RedactCreditCards bool
	RedactSSN         bool
	RedactPhones      bool
	RedactJWT         bool
	RedactUUIDs       bool
	RemoveHighRisk    bool
	CustomPatterns    []*regexp.Regexp
	CustomKeywords    []string
}

// DefaultSanitizeConfig returns a config with all protections enabled
func DefaultSanitizeConfig() *SanitizeConfig {
	return &SanitizeConfig{
		RedactIPs:         true,
		RedactEmails:      true,
		RedactAPIKeys:     true,
		RedactCreditCards: true,
		RedactSSN:         true,
		RedactPhones:      false, // Often appears in legitimate logs
		RedactJWT:         true,
		RedactUUIDs:       false, // UUIDs are usually not sensitive
		RemoveHighRisk:    true,
	}
}

// CloudSanitizeConfig returns stricter config for cloud AI providers
func CloudSanitizeConfig() *SanitizeConfig {
	return &SanitizeConfig{
		RedactIPs:         true,
		RedactEmails:      true,
		RedactAPIKeys:     true,
		RedactCreditCards: true,
		RedactSSN:         true,
		RedactPhones:      true,
		RedactJWT:         true,
		RedactUUIDs:       true, // More paranoid for cloud
		RemoveHighRisk:    true,
	}
}

// SanitizeLogs removes or redacts sensitive information from log text
// This is the main entry point for PII redaction
func SanitizeLogs(input string) string {
	return SanitizeLogsWithConfig(input, DefaultSanitizeConfig())
}

// SanitizeLogsForCloud applies stricter redaction for cloud AI providers
func SanitizeLogsForCloud(input string) string {
	return SanitizeLogsWithConfig(input, CloudSanitizeConfig())
}

// SanitizeLogsWithConfig applies redaction based on the provided config
func SanitizeLogsWithConfig(input string, config *SanitizeConfig) string {
	if input == "" {
		return ""
	}

	// Process line by line for high-risk keyword filtering
	lines := strings.Split(input, "\n")
	var sanitizedLines []string

	for _, line := range lines {
		// Check for high-risk keywords (remove entire line)
		if config.RemoveHighRisk && containsHighRiskKeyword(line, config.CustomKeywords) {
			sanitizedLines = append(sanitizedLines, "[LINE_REDACTED: Contains sensitive keyword]")
			continue
		}

		// Apply pattern-based redactions
		sanitizedLine := sanitizeLine(line, config)
		sanitizedLines = append(sanitizedLines, sanitizedLine)
	}

	return strings.Join(sanitizedLines, "\n")
}

// containsHighRiskKeyword checks if line contains any high-risk keywords
func containsHighRiskKeyword(line string, customKeywords []string) bool {
	lowerLine := strings.ToLower(line)

	// Check built-in keywords
	for _, keyword := range highRiskKeywords {
		if strings.Contains(lowerLine, keyword) {
			return true
		}
	}

	// Check custom keywords
	for _, keyword := range customKeywords {
		if strings.Contains(lowerLine, strings.ToLower(keyword)) {
			return true
		}
	}

	return false
}

// sanitizeLine applies all redaction patterns to a single line
func sanitizeLine(line string, config *SanitizeConfig) string {
	result := line

	// API Keys (do this first as they're highest priority)
	if config.RedactAPIKeys {
		result = piiOpenAIKeyPattern.ReplaceAllString(result, "[OPENAI_KEY_REDACTED]")
		result = piiAWSAccessKeyPattern.ReplaceAllString(result, "[AWS_KEY_REDACTED]")
		result = piiAWSSecretKeyPattern.ReplaceAllString(result, "[AWS_SECRET_REDACTED]")
		result = piiGitTokenPattern.ReplaceAllString(result, "[GIT_TOKEN_REDACTED]")
		result = piiSlackTokenPattern.ReplaceAllString(result, "[SLACK_TOKEN_REDACTED]")
		result = piiAuthHeaderPattern.ReplaceAllString(result, "[AUTH_HEADER_REDACTED]")
		result = piiKeyValuePattern.ReplaceAllString(result, "$1=[KEY_REDACTED]")
	}

	// JWT Tokens
	if config.RedactJWT {
		result = piiJWTPattern.ReplaceAllString(result, "[JWT_REDACTED]")
	}

	// IP Addresses
	if config.RedactIPs {
		result = piiIPv4Pattern.ReplaceAllString(result, "[IP_REDACTED]")
		result = piiIPv6Pattern.ReplaceAllString(result, "[IPV6_REDACTED]")
	}

	// Email Addresses
	if config.RedactEmails {
		result = piiEmailPattern.ReplaceAllString(result, "[EMAIL_REDACTED]")
	}

	// Credit Cards
	if config.RedactCreditCards {
		result = piiCreditCardPattern.ReplaceAllString(result, "[CARD_REDACTED]")
	}

	// Social Security Numbers
	if config.RedactSSN {
		result = piiSSNPattern.ReplaceAllString(result, "[SSN_REDACTED]")
	}

	// Phone Numbers
	if config.RedactPhones {
		result = piiPhonePattern.ReplaceAllString(result, "[PHONE_REDACTED]")
	}

	// UUIDs (partial redaction - keep first segment for correlation)
	if config.RedactUUIDs {
		result = piiUUIDPattern.ReplaceAllStringFunc(result, func(uuid string) string {
			parts := strings.Split(uuid, "-")
			if len(parts) >= 1 {
				return parts[0] + "-[UUID_REDACTED]"
			}
			return "[UUID_REDACTED]"
		})
	}

	// Apply custom patterns
	for _, pattern := range config.CustomPatterns {
		result = pattern.ReplaceAllString(result, "[CUSTOM_REDACTED]")
	}

	return result
}

// SanitizeMultipleLines sanitizes an array of log lines efficiently
func SanitizeMultipleLines(lines []string, forCloud bool) []string {
	var config *SanitizeConfig
	if forCloud {
		config = CloudSanitizeConfig()
	} else {
		config = DefaultSanitizeConfig()
	}

	sanitized := make([]string, 0, len(lines))
	for _, line := range lines {
		sanitized = append(sanitized, SanitizeLogsWithConfig(line, config))
	}
	return sanitized
}

// QuickSanitize performs fast sanitization for real-time log streaming
// Only applies the most critical redactions for performance
func QuickSanitize(input string) string {
	if input == "" {
		return ""
	}

	// Quick high-risk check
	lowerInput := strings.ToLower(input)
	for _, keyword := range []string{"password", "secret", "private key", "-----begin"} {
		if strings.Contains(lowerInput, keyword) {
			return "[LINE_REDACTED: Contains sensitive keyword]"
		}
	}

	// Only critical redactions
	result := piiOpenAIKeyPattern.ReplaceAllString(input, "[API_KEY_REDACTED]")
	result = piiKeyValuePattern.ReplaceAllString(result, "$1=[KEY_REDACTED]")
	result = piiJWTPattern.ReplaceAllString(result, "[JWT_REDACTED]")

	return result
}

// IsSensitive checks if a string likely contains sensitive data
// Useful for pre-filtering before full sanitization
func IsSensitive(input string) bool {
	lowerInput := strings.ToLower(input)

	// Check high-risk keywords
	for _, keyword := range highRiskKeywords {
		if strings.Contains(lowerInput, keyword) {
			return true
		}
	}

	// Check patterns
	if piiOpenAIKeyPattern.MatchString(input) ||
		piiAWSAccessKeyPattern.MatchString(input) ||
		piiJWTPattern.MatchString(input) ||
		piiGitTokenPattern.MatchString(input) ||
		piiSSNPattern.MatchString(input) ||
		piiCreditCardPattern.MatchString(input) {
		return true
	}

	return false
}
