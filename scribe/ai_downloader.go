package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"time"
)

// RunnerDownloader handles downloading the llama-server binary
type RunnerDownloader struct {
	mu          sync.RWMutex
	downloading bool
	progress    float64
	error       string
}

// DownloadProgress tracks download status
type DownloadProgress struct {
	Downloading bool    `json:"downloading"`
	Progress    float64 `json:"progress"`
	Error       string  `json:"error,omitempty"`
}

// NewRunnerDownloader creates a new downloader
func NewRunnerDownloader() *RunnerDownloader {
	return &RunnerDownloader{}
}

// GetStatus returns the current download status
func (d *RunnerDownloader) GetStatus() DownloadProgress {
	d.mu.RLock()
	defer d.mu.RUnlock()
	return DownloadProgress{
		Downloading: d.downloading,
		Progress:    d.progress,
		Error:       d.error,
	}
}

// GitHubRelease represents a GitHub release
type GitHubRelease struct {
	TagName string `json:"tag_name"`
	Assets  []struct {
		Name               string `json:"name"`
		BrowserDownloadURL string `json:"browser_download_url"`
		Size               int64  `json:"size"`
	} `json:"assets"`
}

// GetLatestRunnerInfo gets the latest llama.cpp release info
func (d *RunnerDownloader) GetLatestRunnerInfo() (*GitHubRelease, error) {
	url := "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"

	resp, err := http.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch release info: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GitHub API returned %d", resp.StatusCode)
	}

	var release GitHubRelease
	if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
		return nil, fmt.Errorf("failed to decode release info: %w", err)
	}

	return &release, nil
}

// FindRunnerAsset finds the appropriate asset for the current OS/arch
func (d *RunnerDownloader) FindRunnerAsset(release *GitHubRelease) (string, string, int64, error) {
	// Map of OS/arch to expected asset name patterns
	patterns := map[string][]string{
		"windows/amd64": {"llama-b*-bin-win-avx2-x64.zip", "llama-b*-bin-win-x64.zip", "cudart-llama-bin-win-cu"},
		"windows/arm64": {"llama-b*-bin-win-arm64.zip"},
		"linux/amd64":   {"llama-b*-bin-ubuntu-x64.zip", "llama-b*-bin-linux-x64.zip"},
		"linux/arm64":   {"llama-b*-bin-linux-arm64.zip"},
		"darwin/arm64":  {"llama-b*-bin-macos-arm64.zip"},
		"darwin/amd64":  {"llama-b*-bin-macos-x64.zip"},
	}

	key := runtime.GOOS + "/" + runtime.GOARCH
	expectedPatterns, ok := patterns[key]
	if !ok {
		return "", "", 0, fmt.Errorf("unsupported platform: %s", key)
	}

	// Find matching asset (prefer AVX2 on Windows for performance)
	for _, pattern := range expectedPatterns {
		for _, asset := range release.Assets {
			if matchesPattern(asset.Name, pattern) {
				return asset.Name, asset.BrowserDownloadURL, asset.Size, nil
			}
		}
	}

	return "", "", 0, fmt.Errorf("no suitable binary found for %s in release %s", key, release.TagName)
}

// matchesPattern does simple glob matching
func matchesPattern(name, pattern string) bool {
	// Very simple pattern matching - just check if key parts are present
	// Pattern like "llama-b*-bin-win-avx2-x64.zip"
	parts := splitPattern(pattern)
	for _, part := range parts {
		if part != "*" && !contains(name, part) {
			return false
		}
	}
	return true
}

func splitPattern(pattern string) []string {
	var parts []string
	current := ""
	for _, c := range pattern {
		if c == '*' {
			if current != "" {
				parts = append(parts, current)
				current = ""
			}
			parts = append(parts, "*")
		} else {
			current += string(c)
		}
	}
	if current != "" {
		parts = append(parts, current)
	}
	return parts
}

func contains(s, substr string) bool {
	return len(substr) == 0 || (len(s) >= len(substr) && (s == substr || containsSubstr(s, substr)))
}

func containsSubstr(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}

// Download downloads the runner binary to the specified directory
func (d *RunnerDownloader) Download(ctx context.Context, destDir string) (string, error) {
	d.mu.Lock()
	if d.downloading {
		d.mu.Unlock()
		return "", fmt.Errorf("download already in progress")
	}
	d.downloading = true
	d.progress = 0
	d.error = ""
	d.mu.Unlock()

	defer func() {
		d.mu.Lock()
		d.downloading = false
		d.mu.Unlock()
	}()

	// Get latest release info
	logInfo("Fetching latest llama.cpp release info...")
	release, err := d.GetLatestRunnerInfo()
	if err != nil {
		d.mu.Lock()
		d.error = err.Error()
		d.mu.Unlock()
		return "", err
	}

	assetName, downloadURL, size, err := d.FindRunnerAsset(release)
	if err != nil {
		d.mu.Lock()
		d.error = err.Error()
		d.mu.Unlock()
		return "", err
	}

	logInfo("Downloading %s (%d MB)...", assetName, size/(1024*1024))

	// Create destination directory
	if err := os.MkdirAll(destDir, 0755); err != nil {
		d.mu.Lock()
		d.error = err.Error()
		d.mu.Unlock()
		return "", fmt.Errorf("failed to create directory: %w", err)
	}

	// Download the file
	zipPath := filepath.Join(destDir, assetName)
	if err := d.downloadFile(ctx, downloadURL, zipPath, size); err != nil {
		d.mu.Lock()
		d.error = err.Error()
		d.mu.Unlock()
		return "", err
	}

	// Extract the binary
	runnerPath, err := d.extractRunner(zipPath, destDir)
	if err != nil {
		d.mu.Lock()
		d.error = err.Error()
		d.mu.Unlock()
		os.Remove(zipPath)
		return "", err
	}

	// Clean up zip file
	os.Remove(zipPath)

	d.mu.Lock()
	d.progress = 100
	d.mu.Unlock()

	logInfo("Runner downloaded successfully: %s", runnerPath)
	return runnerPath, nil
}

// downloadFile downloads a file with progress tracking
func (d *RunnerDownloader) downloadFile(ctx context.Context, url, destPath string, expectedSize int64) error {
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return err
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download failed with status %d", resp.StatusCode)
	}

	out, err := os.Create(destPath)
	if err != nil {
		return err
	}
	defer out.Close()

	var downloaded int64
	buf := make([]byte, 32*1024)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		n, err := resp.Body.Read(buf)
		if n > 0 {
			if _, writeErr := out.Write(buf[:n]); writeErr != nil {
				return writeErr
			}
			downloaded += int64(n)

			if expectedSize > 0 {
				d.mu.Lock()
				d.progress = float64(downloaded) / float64(expectedSize) * 90 // Reserve 10% for extraction
				d.mu.Unlock()
			}
		}

		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
	}

	return nil
}

// extractRunner extracts llama-server from the zip file
func (d *RunnerDownloader) extractRunner(zipPath, destDir string) (string, error) {
	// Use archive/zip to extract
	// For simplicity, we'll use the unzip command if available, or Go's archive/zip

	runnerName := GetRunnerBinaryName()
	runnerPath := filepath.Join(destDir, runnerName)

	// Try using system unzip first (more reliable for large files)
	if err := d.extractWithSystemUnzip(zipPath, destDir, runnerName); err != nil {
		// Fall back to Go's archive/zip
		if err := d.extractWithGoZip(zipPath, destDir, runnerName); err != nil {
			return "", fmt.Errorf("failed to extract runner: %w", err)
		}
	}

	// Make executable on Unix
	if runtime.GOOS != "windows" {
		os.Chmod(runnerPath, 0755)
	}

	// Verify the binary exists
	if _, err := os.Stat(runnerPath); os.IsNotExist(err) {
		return "", fmt.Errorf("runner binary not found after extraction")
	}

	return runnerPath, nil
}

// extractWithSystemUnzip uses the system unzip command
func (d *RunnerDownloader) extractWithSystemUnzip(zipPath, destDir, targetFile string) error {
	var cmd string
	var args []string

	if runtime.GOOS == "windows" {
		// Use PowerShell's Expand-Archive
		cmd = "powershell"
		args = []string{
			"-NoProfile",
			"-Command",
			fmt.Sprintf("Expand-Archive -Path '%s' -DestinationPath '%s' -Force", zipPath, destDir),
		}
	} else {
		cmd = "unzip"
		args = []string{"-o", "-j", zipPath, "*" + targetFile, "-d", destDir}
	}

	return runCommand(cmd, args...)
}

// extractWithGoZip uses Go's archive/zip package
func (d *RunnerDownloader) extractWithGoZip(zipPath, destDir, targetFile string) error {
	// Import archive/zip dynamically to avoid import if not needed
	// For now, return error to indicate system unzip should be used
	return fmt.Errorf("Go zip extraction not implemented - please ensure unzip or PowerShell is available")
}

// runCommand executes a command with a timeout
func runCommand(name string, args ...string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	cmd := exec.CommandContext(ctx, name, args...)
	return cmd.Run()
}
