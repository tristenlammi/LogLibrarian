package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"
)

// Current Version
const Version = "0.1.0"

type UpdateCheckResponse struct {
	Available bool   `json:"available"`
	Version   string `json:"version"`
	URL       string `json:"url"`
	Checksum  string `json:"checksum"` // SHA-256 hex-encoded checksum
}

// StartBackgroundUpdater starts the periodic update check
func StartBackgroundUpdater(serverHost string) {
	go func() {
		// Initial check after 1 minute
		time.Sleep(1 * time.Minute)

		// Check every hour
		ticker := time.NewTicker(1 * time.Hour)
		for {
			checkForUpdates(serverHost)
			<-ticker.C
		}
	}()
}

func checkForUpdates(serverHost string) {
	log.Println("🔍 Checking for updates...")

	// Construct URL with proper scheme
	httpScheme := "http"
	if globalConfig != nil && globalConfig.SSLEnabled {
		httpScheme = "https"
	}
	baseURL := fmt.Sprintf("%s://%s", httpScheme, serverHost)

	checkURL := fmt.Sprintf("%s/api/agents/updates/check?current_version=%s&platform=%s&arch=%s",
		baseURL, Version, runtime.GOOS, runtime.GOARCH)

	client := globalConfig.GetHTTPClient(30 * time.Second)
	resp, err := client.Get(checkURL)
	if err != nil {
		log.Printf("⚠️ Update check failed: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		// likely 404 if endpoint doesn't exist yet, or other error
		return
	}

	var updateInfo UpdateCheckResponse
	if err := json.NewDecoder(resp.Body).Decode(&updateInfo); err != nil {
		log.Printf("⚠️ Failed to decode update info: %v", err)
		return
	}

	if updateInfo.Available {
		log.Printf("🚀 Update available: %s (Current: %s)", updateInfo.Version, Version)
		performUpdate(baseURL, updateInfo)
	} else {
		log.Println("✅ Agent is up to date")
	}
}

func performUpdate(baseURL string, info UpdateCheckResponse) {
	log.Printf("⬇️ Downloading update from %s...", info.URL)

	// 1. Download new binary
	downloadURL := fmt.Sprintf("%s%s", baseURL, info.URL)

	execPath, err := os.Executable()
	if err != nil {
		log.Printf("❌ Failed to get executable path: %v", err)
		return
	}

	execDir := filepath.Dir(execPath)
	newBinaryPath := filepath.Join(execDir, "scribe.new")

	if err := downloadFile(downloadURL, newBinaryPath); err != nil {
		log.Printf("❌ Download failed: %v", err)
		return
	}

	// 2. Verify checksum before applying update
	if info.Checksum != "" {
		log.Println("🔐 Verifying checksum...")
		if err := verifyChecksum(newBinaryPath, info.Checksum); err != nil {
			log.Printf("❌ Checksum verification failed: %v", err)
			os.Remove(newBinaryPath) // Clean up the bad download
			return
		}
		log.Println("✅ Checksum verified")
	} else {
		log.Println("⚠️ No checksum provided by server, skipping verification")
	}

	// Ensure executable permissions (Linux/Mac)
	if runtime.GOOS != "windows" {
		if err := os.Chmod(newBinaryPath, 0755); err != nil {
			log.Printf("❌ Failed to set permissions: %v", err)
			return
		}
	}

	log.Println("✅ Download complete. Applying update...")

	// 3. Swapping binaries
	// Windows cannot overwrite running executables, so we rename current to .old
	// Linux can overwrite, but renaming is safer

	oldBinaryPath := filepath.Join(execDir, "scribe.old")

	// Remove old .old file if exists
	os.Remove(oldBinaryPath)

	// Rename current -> .old
	if err := os.Rename(execPath, oldBinaryPath); err != nil {
		log.Printf("❌ Failed to rename current binary: %v", err)
		return
	}

	// Rename new -> current
	if err := os.Rename(newBinaryPath, execPath); err != nil {
		log.Printf("❌ Failed to move new binary into place: %v", err)

		// Rollback attempt
		os.Rename(oldBinaryPath, execPath)
		return
	}

	log.Printf("✅ Update installed. Restarting agent...")

	// 4. Restart
	restartAgent(execPath)
}

// verifyChecksum calculates SHA-256 of the file and compares with expected checksum
func verifyChecksum(filePath string, expectedChecksum string) error {
	f, err := os.Open(filePath)
	if err != nil {
		return fmt.Errorf("failed to open file: %w", err)
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return fmt.Errorf("failed to hash file: %w", err)
	}

	actualChecksum := hex.EncodeToString(h.Sum(nil))

	if actualChecksum != expectedChecksum {
		return fmt.Errorf("checksum mismatch: expected %s, got %s", expectedChecksum, actualChecksum)
	}

	return nil
}

func downloadFile(url string, filepath string) error {
	client := globalConfig.GetHTTPClient(5 * time.Minute) // Longer timeout for downloads
	resp, err := client.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("bad status: %s", resp.Status)
	}

	out, err := os.Create(filepath)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, resp.Body)
	return err
}

func restartAgent(execPath string) {
	cmd := exec.Command(execPath)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		log.Printf("❌ Failed to restart: %v", err)
		return
	}

	log.Printf("👋 Exiting current process. New PID: %d", cmd.Process.Pid)
	os.Exit(0)
}
