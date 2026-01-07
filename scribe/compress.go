package main

import (
	"crypto/sha256"
	"fmt"
	"regexp"
	"time"
)

// LogSchema represents the compressed log structure
type LogSchema struct {
	TemplateID   string    `json:"template_id"`
	TemplateText string    `json:"template_text"`
	Variables    []string  `json:"variables"`
	Timestamp    time.Time `json:"timestamp"`
}

var (
	// Timestamp patterns (ISO8601, syslog, common formats)
	timestampPatterns = []*regexp.Regexp{
		regexp.MustCompile(`\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?`),
		regexp.MustCompile(`\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}`),
		regexp.MustCompile(`\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}\s+[+-]\d{4}`),
	}

	// IPv4 pattern
	ipv4Pattern = regexp.MustCompile(`\b(?:\d{1,3}\.){3}\d{1,3}\b`)

	// Quoted string pattern
	quotedStringPattern = regexp.MustCompile(`"([^"]*)"`)

	// Number pattern (integers and floats, but not part of timestamps/IPs)
	numberPattern = regexp.MustCompile(`\b\d+(?:\.\d+)?\b`)
)

// CompressLog performs semantic compression on a raw log line
func CompressLog(rawLine string) LogSchema {
	var variables []string
	compressed := rawLine
	timestamp := time.Now()

	// 1. Extract and remove timestamps (must be first to avoid conflicts)
	for _, pattern := range timestampPatterns {
		if match := pattern.FindString(compressed); match != "" {
			// Parse timestamp
			parsedTime := parseTimestamp(match)
			if !parsedTime.IsZero() {
				timestamp = parsedTime
			}
			// Remove timestamp from line
			compressed = pattern.ReplaceAllString(compressed, "")
			break
		}
	}

	// 2. Extract IPv4 addresses and replace with <IP>
	ipMatches := ipv4Pattern.FindAllString(compressed, -1)
	for _, ip := range ipMatches {
		variables = append(variables, ip)
	}
	compressed = ipv4Pattern.ReplaceAllString(compressed, "<IP>")

	// 3. Extract quoted strings and replace with <STR>
	quotedMatches := quotedStringPattern.FindAllStringSubmatch(compressed, -1)
	for _, match := range quotedMatches {
		if len(match) > 1 {
			variables = append(variables, match[1])
		}
	}
	compressed = quotedStringPattern.ReplaceAllString(compressed, "<STR>")

	// 4. Extract numbers and replace with <NUM>
	numberMatches := numberPattern.FindAllString(compressed, -1)
	for _, num := range numberMatches {
		variables = append(variables, num)
	}
	compressed = numberPattern.ReplaceAllString(compressed, "<NUM>")

	// Clean up multiple spaces
	multiSpace := regexp.MustCompile(`\s+`)
	compressed = multiSpace.ReplaceAllString(compressed, " ")
	compressed = regexp.MustCompile(`^\s+|\s+$`).ReplaceAllString(compressed, "")

	// Generate template ID (SHA256 hash of template)
	templateID := generateTemplateID(compressed)

	return LogSchema{
		TemplateID:   templateID,
		TemplateText: compressed,
		Variables:    variables,
		Timestamp:    timestamp,
	}
}

// parseTimestamp attempts to parse various timestamp formats
func parseTimestamp(ts string) time.Time {
	formats := []string{
		time.RFC3339,
		time.RFC3339Nano,
		"2006-01-02 15:04:05",
		"2006-01-02T15:04:05",
		"Jan 2 15:04:05",
		"Jan _2 15:04:05",
		"02/Jan/2006:15:04:05 -0700",
	}

	for _, format := range formats {
		if t, err := time.Parse(format, ts); err == nil {
			// For syslog format without year, use current year
			if format == "Jan 2 15:04:05" || format == "Jan _2 15:04:05" {
				now := time.Now()
				t = t.AddDate(now.Year(), 0, 0)
			}
			return t
		}
	}

	return time.Time{}
}

// generateTemplateID creates a SHA256 hash of the template text
func generateTemplateID(template string) string {
	hash := sha256.Sum256([]byte(template))
	return fmt.Sprintf("%x", hash)
}
