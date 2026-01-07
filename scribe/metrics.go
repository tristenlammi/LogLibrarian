package main

import (
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/host"
	"github.com/shirou/gopsutil/v3/load"
	"github.com/shirou/gopsutil/v3/mem"
	netstat "github.com/shirou/gopsutil/v3/net"
	"github.com/shirou/gopsutil/v3/process"
)

// DiskInfo represents individual disk/partition metrics
type DiskInfo struct {
	Mountpoint   string  `json:"mountpoint"`
	Device       string  `json:"device"`
	UsagePercent float64 `json:"usage_percent"`
	ReadBps      float64 `json:"read_bps"`
	WriteBps     float64 `json:"write_bps"`
	Temperature  float64 `json:"temperature,omitempty"`
}

// ProcessInfo represents a running process with resource usage
type ProcessInfo struct {
	PID        int32   `json:"pid"`
	Name       string  `json:"name"`
	CPUPercent float64 `json:"cpu_percent"`
	RAMPercent float64 `json:"ram_percent"`
}

// MetricPoint represents a comprehensive system metric snapshot
type MetricPoint struct {
	Timestamp     time.Time  `json:"timestamp"`
	CPUPercent    float64    `json:"cpu_percent"`
	RAMPercent    float64    `json:"ram_percent"`
	NetSentBps    float64    `json:"net_sent_bps"`
	NetRecvBps    float64    `json:"net_recv_bps"`
	DiskReadBps   float64    `json:"disk_read_bps"`
	DiskWriteBps  float64    `json:"disk_write_bps"`
	PingLatencyMs float64    `json:"ping_latency_ms"`
	CPUTemp       float64    `json:"cpu_temp,omitempty"`
	CPUName       string     `json:"cpu_name,omitempty"`
	GPUPercent    float64    `json:"gpu_percent,omitempty"`
	GPUTemp       float64    `json:"gpu_temp,omitempty"`
	GPUName       string     `json:"gpu_name,omitempty"`
	IsVM          bool       `json:"is_vm"`
	Disks         []DiskInfo `json:"disks"`
}

// HeartbeatPayload contains buffered metrics to send to server
type HeartbeatPayload struct {
	AgentID           string        `json:"agent_id"`
	Hostname          string        `json:"hostname"`
	Metrics           []MetricPoint `json:"metrics"`
	Status            string        `json:"status"`
	LastSeenAt        time.Time     `json:"last_seen_at"`
	Processes         []ProcessInfo `json:"processes"`
	PublicIP          string        `json:"public_ip"`
	LoadAvg           float64       `json:"load_avg"`
	ConnectionAddress string        `json:"connection_address"`
	SystemInfo        *SystemInfo   `json:"system_info,omitempty"`
	AuthToken         string        `json:"auth_token,omitempty"` // Authentication token for server verification
	Version           string        `json:"version"`              // Agent version
}

var (
	metricsBuffer            []MetricPoint
	agentID                  string
	hostname                 string
	currentConnectionAddress string

	// Previous counters for speed calculation
	prevNetStat      *netstat.IOCountersStat
	prevDiskStat     *disk.IOCountersStat
	prevDiskIOByName map[string]*disk.IOCountersStat // Per-disk I/O tracking
	prevTime         time.Time

	// Shared data for processes and public IP
	topProcesses    []ProcessInfo
	currentPublicIP string
	currentLoadAvg  float64
	processMutex    sync.RWMutex

	// VM detection cache
	isVMCached   bool
	isVMDetected bool

	// GPU detection cache - avoid repeated slow PowerShell queries
	gpuLoggedOnce   bool
	gpuCached       bool
	cachedGPUName   string
	cachedGPUVendor string // "nvidia", "amd", "intel", or ""

	// CPU name cache - only need to query once
	cpuNameCached bool
	cachedCPUName string

	// Temperature source cache - remember what's available
	tempSourceChecked   bool
	hasLibreHardwareMon bool
	hasOpenHardwareMon  bool

	// Startup retry for hardware monitors (check 3 times in first 3 minutes)
	startupTime            time.Time
	startupChecksRemaining int
	lastStartupCheck       time.Time

	// Background slow metrics collector
	slowMetricsMutex   sync.RWMutex
	slowMetricsRunning bool
	cachedCPUTemp      float64
	cachedGPUPercent   float64
	cachedGPUTemp      float64
	cachedGPUNameValue string
	cachedPingLatency  float64
)

// getCPUName returns the CPU model name (cached after first call)
func getCPUName() string {
	if cpuNameCached {
		return cachedCPUName
	}

	// On Windows, use LibreHardwareMonitor WMI (same source as temperature)
	if runtime.GOOS == "windows" {
		// Try LibreHardwareMonitor first
		cmd := exec.Command("powershell", "-NoProfile", "-Command",
			`Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Hardware 2>$null | Where-Object { $_.HardwareType -eq "Cpu" } | Select-Object -First 1 -ExpandProperty Name`)
		output, err := cmd.Output()
		if err == nil {
			name := strings.TrimSpace(string(output))
			if name != "" {
				cachedCPUName = name
				cpuNameCached = true
				return cachedCPUName
			}
		}

		// Fallback to OpenHardwareMonitor
		cmd = exec.Command("powershell", "-NoProfile", "-Command",
			`Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Hardware 2>$null | Where-Object { $_.HardwareType -eq "CPU" } | Select-Object -First 1 -ExpandProperty Name`)
		output, err = cmd.Output()
		if err == nil {
			name := strings.TrimSpace(string(output))
			if name != "" {
				cachedCPUName = name
				cpuNameCached = true
				return cachedCPUName
			}
		}
	}

	// Fallback to gopsutil for Linux/macOS
	cpuInfo, err := cpu.Info()
	if err == nil && len(cpuInfo) > 0 {
		cachedCPUName = cpuInfo[0].ModelName
	}
	cpuNameCached = true
	return cachedCPUName
}

// StartSlowMetricsCollector starts a background goroutine that continuously
// collects slow metrics (temperature, GPU, ping) so they don't block the main collector
func StartSlowMetricsCollector() {
	slowMetricsMutex.Lock()
	if slowMetricsRunning {
		slowMetricsMutex.Unlock()
		return
	}
	slowMetricsRunning = true
	slowMetricsMutex.Unlock()

	go func() {
		log.Println("🌡️ Background slow metrics collector started")
		ticker := time.NewTicker(2 * time.Second) // Refresh slow metrics every 2 seconds
		defer ticker.Stop()

		// Collect immediately on start
		collectSlowMetrics()

		for range ticker.C {
			collectSlowMetrics()
		}
	}()
}

// collectSlowMetrics gathers CPU temp, GPU metrics, and ping latency
func collectSlowMetrics() {
	isVM := detectVM()

	// Run all slow operations in parallel
	var wg sync.WaitGroup
	var cpuTemp, gpuPercent, gpuTemp, pingLatency float64
	var gpuName string

	wg.Add(3)

	// CPU Temperature
	go func() {
		defer wg.Done()
		cpuTemp = collectCPUTemperature(isVM)
	}()

	// GPU Metrics
	go func() {
		defer wg.Done()
		gpuPercent, gpuTemp, gpuName = collectGPUMetrics()
	}()

	// Ping Latency
	go func() {
		defer wg.Done()
		pingLatency = measurePingLatency("1.1.1.1", 1*time.Second)
	}()

	wg.Wait()

	// Update cached values
	slowMetricsMutex.Lock()
	cachedCPUTemp = cpuTemp
	cachedGPUPercent = gpuPercent
	cachedGPUTemp = gpuTemp
	cachedGPUNameValue = gpuName
	cachedPingLatency = pingLatency
	slowMetricsMutex.Unlock()
}

// getSlowMetrics returns the latest cached slow metrics
func getSlowMetrics() (cpuTemp, gpuPercent, gpuTemp, pingLatency float64, gpuName string) {
	slowMetricsMutex.RLock()
	defer slowMetricsMutex.RUnlock()
	return cachedCPUTemp, cachedGPUPercent, cachedGPUTemp, cachedPingLatency, cachedGPUNameValue
}

// CollectMetrics gathers comprehensive system metrics
// Fast metrics are collected synchronously, slow metrics use cached values from background collector
func CollectMetrics() (MetricPoint, error) {
	now := time.Now()

	metric := MetricPoint{
		Timestamp: now,
		Disks:     []DiskInfo{},
		IsVM:      detectVM(),
	}

	// 1. CPU Usage - use 0 duration for instant reading (we collect frequently)
	cpuPercents, err := cpu.Percent(0, false)
	if err == nil && len(cpuPercents) > 0 {
		metric.CPUPercent = cpuPercents[0]
	}

	// 2. RAM Usage
	memStats, err := mem.VirtualMemory()
	if err == nil {
		metric.RAMPercent = memStats.UsedPercent
	}

	// 3. Network Speed (requires differential)
	netStats, err := netstat.IOCounters(false)
	if err == nil && len(netStats) > 0 {
		currentNet := &netStats[0]

		if prevNetStat != nil && !prevTime.IsZero() {
			elapsed := now.Sub(prevTime).Seconds()
			if elapsed > 0 {
				metric.NetSentBps = float64(currentNet.BytesSent-prevNetStat.BytesSent) / elapsed
				metric.NetRecvBps = float64(currentNet.BytesRecv-prevNetStat.BytesRecv) / elapsed
			}
		}

		prevNetStat = currentNet
	}

	// 4. Disk I/O Speed - aggregate and per-disk
	diskIOStats, err := disk.IOCounters()
	if err == nil {
		// Initialize per-disk tracking if needed
		if prevDiskIOByName == nil {
			prevDiskIOByName = make(map[string]*disk.IOCountersStat)
		}

		// Aggregate all disks
		var totalRead, totalWrite uint64
		for _, stat := range diskIOStats {
			totalRead += stat.ReadBytes
			totalWrite += stat.WriteBytes
		}

		currentDisk := &disk.IOCountersStat{
			ReadBytes:  totalRead,
			WriteBytes: totalWrite,
		}

		if prevDiskStat != nil && !prevTime.IsZero() {
			elapsed := now.Sub(prevTime).Seconds()
			if elapsed > 0 {
				metric.DiskReadBps = float64(currentDisk.ReadBytes-prevDiskStat.ReadBytes) / elapsed
				metric.DiskWriteBps = float64(currentDisk.WriteBytes-prevDiskStat.WriteBytes) / elapsed
			}
		}

		prevDiskStat = currentDisk
	}

	// 5. Get slow metrics from background collector (instant - just reads cached values)
	cpuTemp, gpuPercent, gpuTemp, pingLatency, gpuName := getSlowMetrics()

	metric.CPUTemp = cpuTemp
	metric.CPUName = getCPUName()
	metric.GPUPercent = gpuPercent
	metric.GPUTemp = gpuTemp
	metric.GPUName = gpuName
	if gpuName != "" && !gpuLoggedOnce {
		log.Printf("GPU detected: %s", gpuName)
		gpuLoggedOnce = true
	}

	metric.PingLatencyMs = pingLatency

	// 6. Disk Usage per partition (with per-disk I/O)
	partitions, err := disk.Partitions(false)
	if err == nil {
		for _, partition := range partitions {
			// Skip pseudo filesystems and loop devices
			if shouldSkipFilesystem(partition.Fstype) {
				continue
			}
			if shouldSkipDevice(partition.Device) {
				continue
			}

			usage, err := disk.Usage(partition.Mountpoint)
			if err != nil {
				continue
			}

			diskInfo := DiskInfo{
				Mountpoint:   partition.Mountpoint,
				Device:       partition.Device,
				UsagePercent: usage.UsedPercent,
			}

			// Calculate per-disk I/O speed if available
			if diskIOStats != nil && prevDiskIOByName != nil && !prevTime.IsZero() {
				diskName := getDiskNameFromDevice(partition.Device)
				if currentIO, ok := diskIOStats[diskName]; ok {
					if prevIO, hasPrev := prevDiskIOByName[diskName]; hasPrev {
						elapsed := now.Sub(prevTime).Seconds()
						if elapsed > 0 {
							diskInfo.ReadBps = float64(currentIO.ReadBytes-prevIO.ReadBytes) / elapsed
							diskInfo.WriteBps = float64(currentIO.WriteBytes-prevIO.WriteBytes) / elapsed
						}
					}
				}
			}

			// Try to get disk temperature (may not work on all systems)
			// This is a best-effort approach
			diskInfo.Temperature = 0 // Default, temperature reading is complex

			metric.Disks = append(metric.Disks, diskInfo)
		}
	}

	// Update per-disk I/O tracking for next iteration
	if diskIOStats != nil {
		for name, stat := range diskIOStats {
			copyStat := stat
			prevDiskIOByName[name] = &copyStat
		}
	}

	// Update previous time for next differential calculation
	prevTime = now

	return metric, nil
}

// shouldSkipFilesystem checks if filesystem should be ignored
func shouldSkipFilesystem(fstype string) bool {
	skipTypes := []string{
		"squashfs",
		"tmpfs",
		"devtmpfs",
		"overlay",
		"overlay2",
		"aufs",
		"proc",
		"sysfs",
		"devfs",
		"iso9660",
		"fuse",
		"cgroup",
		"cgroup2",
	}

	fstypeLower := strings.ToLower(fstype)
	for _, skip := range skipTypes {
		if strings.Contains(fstypeLower, skip) {
			return true
		}
	}

	return false
}

// shouldSkipDevice checks if device should be ignored (loop devices, snap, etc.)
func shouldSkipDevice(device string) bool {
	deviceLower := strings.ToLower(device)
	skipPatterns := []string{
		"/dev/loop", // Linux loop devices (snap)
		"/dev/sr",   // CD/DVD drives
		"/dev/fd",   // Floppy drives
		"/dev/ram",  // RAM disks
		"\\\\?\\",   // Windows special paths
	}

	for _, skip := range skipPatterns {
		if strings.Contains(deviceLower, strings.ToLower(skip)) {
			return true
		}
	}

	return false
}

// getDiskNameFromDevice extracts the disk name from device path
// e.g., /dev/sda1 -> sda, C: -> C:
func getDiskNameFromDevice(device string) string {
	// Windows: return as-is (e.g., C:)
	if runtime.GOOS == "windows" {
		return device
	}

	// Linux: extract base name and remove partition number
	// /dev/sda1 -> sda, /dev/nvme0n1p1 -> nvme0n1
	if strings.HasPrefix(device, "/dev/") {
		name := strings.TrimPrefix(device, "/dev/")

		// Handle NVMe drives (nvme0n1p1 -> nvme0n1)
		if strings.HasPrefix(name, "nvme") {
			if idx := strings.LastIndex(name, "p"); idx > 0 {
				return name[:idx]
			}
		}

		// Handle regular drives (sda1 -> sda)
		re := regexp.MustCompile(`^([a-z]+)[0-9]*$`)
		if matches := re.FindStringSubmatch(name); len(matches) > 1 {
			return matches[1]
		}

		return name
	}

	return device
}

// detectVM checks if running inside a VM (cached)
func detectVM() bool {
	if isVMCached {
		return isVMDetected
	}

	isVMDetected = checkIfVM()
	isVMCached = true

	if isVMDetected {
		log.Println("🖥️ VM detected - some sensors may be unavailable")
	}

	return isVMDetected
}

// checkIfVM performs actual VM detection
// Distinguishes between being a VM HOST (has KVM installed) vs being a VM GUEST
func checkIfVM() bool {
	// Check virtualization info from host
	info, err := host.Info()
	if err == nil {
		virtRole := strings.ToLower(info.VirtualizationRole)
		virtSys := strings.ToLower(info.VirtualizationSystem)

		// IMPORTANT: "host" role means we're running VMs, not that we ARE a VM
		// Only "guest" role means we're inside a VM
		if virtRole == "guest" {
			log.Printf("VM detected via gopsutil: role=%s, system=%s", virtRole, virtSys)
			return true
		}

		// If role is "host" or empty, we're on bare metal (possibly running VMs)
		// Don't falsely flag as VM just because KVM modules are loaded
		if virtRole == "host" || virtRole == "" {
			// Not a VM - we're the hypervisor host or bare metal
			// Continue with additional checks just to be safe
		}
	}

	// Check DMI for VM-specific vendors (Linux)
	// These are much more reliable than kernel module detection
	if runtime.GOOS == "linux" {
		dmiPaths := []string{
			"/sys/class/dmi/id/product_name",
			"/sys/class/dmi/id/sys_vendor",
			"/sys/class/dmi/id/board_vendor",
			"/sys/class/dmi/id/bios_vendor",
		}

		// Only match actual VM product names, not generic hypervisor names
		vmProducts := []string{
			"vmware virtual",
			"virtualbox",
			"qemu",
			"kvm",
			"xen",
			"microsoft virtual",
			"microsoft corporation virtual",
			"amazon ec2",
			"google compute engine",
			"droplet",  // DigitalOcean
			"hvm domu", // Xen guest
			"bochs",
			"bhyve",
		}

		for _, path := range dmiPaths {
			data, err := os.ReadFile(path)
			if err == nil {
				content := strings.ToLower(strings.TrimSpace(string(data)))
				for _, vmProduct := range vmProducts {
					if strings.Contains(content, vmProduct) {
						log.Printf("VM detected via DMI: %s contains '%s'", path, vmProduct)
						return true
					}
				}
			}
		}

		// Check chassis type - VMs typically report type 1 (Other) or specific VM types
		chassisData, err := os.ReadFile("/sys/class/dmi/id/chassis_type")
		if err == nil {
			chassisType := strings.TrimSpace(string(chassisData))
			// Type 1 = Other (often VMs), but also some real hardware
			// More reliable: check if chassis_vendor indicates VM
			chassisVendor, _ := os.ReadFile("/sys/class/dmi/id/chassis_vendor")
			vendorLower := strings.ToLower(string(chassisVendor))
			if chassisType == "1" && (strings.Contains(vendorLower, "qemu") ||
				strings.Contains(vendorLower, "bochs") ||
				strings.Contains(vendorLower, "vmware")) {
				log.Printf("VM detected via chassis: type=%s, vendor=%s", chassisType, vendorLower)
				return true
			}
		}

		// Check for hypervisor flag in /proc/cpuinfo (most reliable for x86)
		cpuinfo, err := os.ReadFile("/proc/cpuinfo")
		if err == nil {
			if strings.Contains(string(cpuinfo), "hypervisor") {
				log.Println("VM detected via CPU hypervisor flag")
				return true
			}
		}
	}

	return false
}

// collectCPUTemperature gathers CPU temperature with platform-specific handling
func collectCPUTemperature(isVM bool) float64 {
	// VMs typically don't have reliable temp sensors
	if isVM {
		return 0
	}

	// Try gopsutil sensors first
	temps, err := host.SensorsTemperatures()
	if err == nil && len(temps) > 0 {
		// Priority order for CPU temp sensors
		priorityKeys := []string{"package", "tctl", "tdie", "core 0", "cpu"}

		for _, priority := range priorityKeys {
			for _, temp := range temps {
				nameLower := strings.ToLower(temp.SensorKey)
				if strings.Contains(nameLower, priority) {
					if temp.Temperature > 0 && temp.Temperature < 150 {
						return temp.Temperature
					}
				}
			}
		}

		// Fallback: any CPU-related temp
		for _, temp := range temps {
			nameLower := strings.ToLower(temp.SensorKey)
			if strings.Contains(nameLower, "core") || strings.Contains(nameLower, "cpu") {
				if temp.Temperature > 0 && temp.Temperature < 150 {
					return temp.Temperature
				}
			}
		}
	}

	// Windows fallback: try WMI via PowerShell
	if runtime.GOOS == "windows" {
		temp := getWindowsCPUTemp()
		if temp > 0 {
			return temp
		}
	}

	return 0
}

// getWindowsCPUTemp tries to get CPU temp on Windows via WMI
// Uses cached hardware monitor availability flags for faster queries
// Retries detection during first 3 minutes of startup in case HW monitor starts later
func getWindowsCPUTemp() float64 {
	now := time.Now()

	// Initialize startup tracking on first call
	if startupTime.IsZero() {
		startupTime = now
		startupChecksRemaining = 2 // Will check again 2 more times (3 total including initial)
		lastStartupCheck = now
	}

	// During startup period, re-check for hardware monitors every minute
	// This handles cases where LibreHardwareMonitor starts after the scribe
	if startupChecksRemaining > 0 && tempSourceChecked && !hasLibreHardwareMon && !hasOpenHardwareMon {
		if now.Sub(lastStartupCheck) >= time.Minute {
			log.Printf("Retrying hardware monitor detection (attempt %d of 3)...", 4-startupChecksRemaining)
			tempSourceChecked = false // Force re-check
			startupChecksRemaining--
			lastStartupCheck = now
		}
	}

	// If we already checked and know what's available, use fast path
	if tempSourceChecked {
		if hasLibreHardwareMon {
			cmd := exec.Command("powershell", "-NoProfile", "-Command",
				`Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and ($_.Name -like "*CPU Package*" -or $_.Name -like "*CPU Core*" -or $_.Name -like "*Core #0*") } | Select-Object -First 1 -ExpandProperty Value`)
			output, err := cmd.Output()
			if err == nil {
				temp, err := strconv.ParseFloat(strings.TrimSpace(string(output)), 64)
				if err == nil && temp > 0 && temp < 150 {
					return temp
				}
			}
		}
		if hasOpenHardwareMon {
			cmd := exec.Command("powershell", "-NoProfile", "-Command",
				`Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and $_.Name -like "*CPU*" } | Select-Object -First 1 -ExpandProperty Value`)
			output, err := cmd.Output()
			if err == nil {
				temp, err := strconv.ParseFloat(strings.TrimSpace(string(output)), 64)
				if err == nil && temp > 0 && temp < 150 {
					return temp
				}
			}
		}
		// No hardware monitor available
		return 0
	}

	// First-time check - probe all sources and remember what works
	tempSourceChecked = true

	// Try LibreHardwareMonitor WMI first (most common and reliable)
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and ($_.Name -like "*CPU Package*" -or $_.Name -like "*CPU Core*" -or $_.Name -like "*Core #0*") } | Select-Object -First 1 -ExpandProperty Value`)

	output, err := cmd.Output()
	if err == nil {
		temp, err := strconv.ParseFloat(strings.TrimSpace(string(output)), 64)
		if err == nil && temp > 0 && temp < 150 {
			hasLibreHardwareMon = true
			log.Println("✓ Found LibreHardwareMonitor - CPU temperature monitoring enabled")
			return temp
		}
	}

	// Try Open Hardware Monitor WMI (older but still used)
	cmd = exec.Command("powershell", "-NoProfile", "-Command",
		`Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and $_.Name -like "*CPU*" } | Select-Object -First 1 -ExpandProperty Value`)

	output, err = cmd.Output()
	if err == nil {
		temp, err := strconv.ParseFloat(strings.TrimSpace(string(output)), 64)
		if err == nil && temp > 0 && temp < 150 {
			hasOpenHardwareMon = true
			log.Println("✓ Found OpenHardwareMonitor - CPU temperature monitoring enabled")
			return temp
		}
	}

	// Log if no hardware monitor found (but only once per check cycle)
	if startupChecksRemaining == 0 {
		log.Println("⚠ No hardware monitor found (LibreHardwareMonitor/OpenHardwareMonitor) - CPU temp unavailable")
	}

	// Try MSAcpi_ThermalZoneTemperature (requires admin) - don't cache this, it may work sometimes
	cmd = exec.Command("powershell", "-NoProfile", "-Command",
		`(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace "root/wmi" 2>$null | Select-Object -First 1).CurrentTemperature / 10 - 273.15`)

	output, err = cmd.Output()
	if err == nil {
		temp, err := strconv.ParseFloat(strings.TrimSpace(string(output)), 64)
		if err == nil && temp > 0 && temp < 150 {
			return temp
		}
	}

	return 0
}

// collectGPUMetrics gathers GPU telemetry from NVIDIA, AMD, or Intel GPUs
// Uses caching to avoid repeated slow detection queries
func collectGPUMetrics() (percent float64, temp float64, name string) {
	// If we've already detected the GPU vendor, use cached info for fast path
	if gpuCached {
		switch cachedGPUVendor {
		case "nvidia":
			return collectNvidiaGPU()
		case "amd":
			return collectAMDGPUFast()
		case "intel":
			return collectIntelGPU()
		default:
			// No GPU found previously, just return cached name
			return 0, 0, cachedGPUName
		}
	}

	// First-time detection - try each vendor
	// Try NVIDIA first
	gpuPercent, gpuTemp, gpuName := collectNvidiaGPU()
	if gpuName != "" {
		gpuCached = true
		cachedGPUVendor = "nvidia"
		cachedGPUName = gpuName
		return gpuPercent, gpuTemp, gpuName
	}

	// Try AMD
	gpuPercent, gpuTemp, gpuName = collectAMDGPU()
	if gpuName != "" {
		gpuCached = true
		cachedGPUVendor = "amd"
		cachedGPUName = gpuName
		return gpuPercent, gpuTemp, gpuName
	}

	// Try Intel
	gpuPercent, gpuTemp, gpuName = collectIntelGPU()
	if gpuName != "" {
		gpuCached = true
		cachedGPUVendor = "intel"
		cachedGPUName = gpuName
		return gpuPercent, gpuTemp, gpuName
	}

	// No GPU found - cache this result too
	gpuCached = true
	cachedGPUVendor = ""
	cachedGPUName = ""
	return 0, 0, ""
}

// collectNvidiaGPU gathers NVIDIA GPU metrics via nvidia-smi
func collectNvidiaGPU() (percent float64, temp float64, name string) {
	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		nvidiaSmiPaths := []string{
			"nvidia-smi",
			"C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe",
			"C:\\Windows\\System32\\nvidia-smi.exe",
		}

		for _, path := range nvidiaSmiPaths {
			cmd = exec.Command(path, "--query-gpu=utilization.gpu,temperature.gpu,name", "--format=csv,noheader,nounits")
			output, err := cmd.Output()
			if err == nil && len(output) > 0 {
				return parseNvidiaSmiOutput(string(output))
			}
		}
	} else {
		cmd = exec.Command("nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,name", "--format=csv,noheader,nounits")
		output, err := cmd.Output()
		if err == nil && len(output) > 0 {
			return parseNvidiaSmiOutput(string(output))
		}
	}

	return 0, 0, ""
}

// collectAMDGPU gathers AMD GPU metrics
func collectAMDGPU() (percent float64, temp float64, name string) {
	if runtime.GOOS == "windows" {
		return collectAMDGPUWindows()
	}
	return collectAMDGPULinux()
}

// collectAMDGPUFast uses cached GPU name and only queries for metrics if hardware monitor is available
func collectAMDGPUFast() (percent float64, temp float64, name string) {
	if runtime.GOOS != "windows" {
		return collectAMDGPULinux()
	}

	// If we know hardware monitor is available, query it for live metrics
	if hasLibreHardwareMon {
		cmd := exec.Command("powershell", "-NoProfile", "-Command", `
$gpu = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Load" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$temp = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
if ($gpu -and $temp) {
    Write-Output "$($gpu.Value),$($temp.Value)"
}
`)
		output, err := cmd.Output()
		if err == nil && len(strings.TrimSpace(string(output))) > 0 {
			parts := strings.Split(strings.TrimSpace(string(output)), ",")
			if len(parts) >= 2 {
				pct, _ := strconv.ParseFloat(parts[0], 64)
				tmp, _ := strconv.ParseFloat(parts[1], 64)
				return pct, tmp, cachedGPUName
			}
		}
	}

	if hasOpenHardwareMon {
		cmd := exec.Command("powershell", "-NoProfile", "-Command", `
$gpu = Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Load" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$temp = Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
if ($gpu -and $temp) {
    Write-Output "$($gpu.Value),$($temp.Value)"
}
`)
		output, err := cmd.Output()
		if err == nil && len(strings.TrimSpace(string(output))) > 0 {
			parts := strings.Split(strings.TrimSpace(string(output)), ",")
			if len(parts) >= 2 {
				pct, _ := strconv.ParseFloat(parts[0], 64)
				tmp, _ := strconv.ParseFloat(parts[1], 64)
				return pct, tmp, cachedGPUName
			}
		}
	}

	// No hardware monitor available, just return cached name with no metrics
	return 0, 0, cachedGPUName
}

// collectAMDGPUWindows gathers AMD GPU metrics on Windows via WMI/PowerShell
// Sets hardware monitor availability flags for fast subsequent queries
func collectAMDGPUWindows() (percent float64, temp float64, name string) {
	// Try LibreHardwareMonitor first (most reliable for AMD)
	cmd := exec.Command("powershell", "-NoProfile", "-Command", `
$gpu = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Load" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$temp = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$hw = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Hardware 2>$null | Where-Object { $_.HardwareType -eq "GpuAmd" } | Select-Object -First 1
if ($gpu -and $temp -and $hw) {
    Write-Output "$($gpu.Value),$($temp.Value),$($hw.Name)"
}
`)
	output, err := cmd.Output()
	if err == nil && len(strings.TrimSpace(string(output))) > 0 {
		hasLibreHardwareMon = true
		return parseGPUOutput(string(output))
	}

	// Fallback: Try OpenHardwareMonitor
	cmd = exec.Command("powershell", "-NoProfile", "-Command", `
$gpu = Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Load" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$temp = Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$hw = Get-WmiObject -Namespace "root\OpenHardwareMonitor" -Class Hardware 2>$null | Where-Object { $_.HardwareType -eq "GpuAti" } | Select-Object -First 1
if ($gpu -and $temp -and $hw) {
    Write-Output "$($gpu.Value),$($temp.Value),$($hw.Name)"
}
`)
	output, err = cmd.Output()
	if err == nil && len(strings.TrimSpace(string(output))) > 0 {
		hasOpenHardwareMon = true
		return parseGPUOutput(string(output))
	}

	// Last resort: Get GPU name from WMI VideoController (no utilization/temp)
	cmd = exec.Command("powershell", "-NoProfile", "-Command",
		`(Get-WmiObject Win32_VideoController | Where-Object { $_.Name -match 'AMD|Radeon' } | Select-Object -First 1).Name`)
	output, err = cmd.Output()
	outStr := strings.TrimSpace(string(output))
	if err == nil && outStr != "" {
		return 0, 0, outStr
	}

	return 0, 0, ""
}

// collectAMDGPULinux gathers AMD GPU metrics on Linux via rocm-smi or sysfs
func collectAMDGPULinux() (percent float64, temp float64, name string) {
	// Try rocm-smi first
	cmd := exec.Command("rocm-smi", "--showuse", "--showtemp", "--showproductname", "--csv")
	output, err := cmd.Output()
	if err == nil && len(output) > 0 {
		return parseRocmSmiOutput(string(output))
	}

	// Fallback: Try reading from sysfs (AMDGPU driver)
	// Check for AMD GPU in /sys/class/drm/card*/device/vendor
	files, err := os.ReadDir("/sys/class/drm")
	if err != nil {
		return 0, 0, ""
	}

	for _, f := range files {
		if !strings.HasPrefix(f.Name(), "card") || strings.Contains(f.Name(), "-") {
			continue
		}

		cardPath := "/sys/class/drm/" + f.Name() + "/device"

		// Check if it's AMD (vendor 0x1002)
		vendorData, err := os.ReadFile(cardPath + "/vendor")
		if err != nil || !strings.Contains(string(vendorData), "0x1002") {
			continue
		}

		// Get GPU name
		nameData, _ := os.ReadFile(cardPath + "/product_name")
		if len(nameData) == 0 {
			nameData = []byte("AMD GPU")
		}
		name = strings.TrimSpace(string(nameData))

		// Get temperature (hwmon)
		hwmonPath := cardPath + "/hwmon"
		hwmonDirs, err := os.ReadDir(hwmonPath)
		if err == nil && len(hwmonDirs) > 0 {
			tempPath := hwmonPath + "/" + hwmonDirs[0].Name() + "/temp1_input"
			tempData, err := os.ReadFile(tempPath)
			if err == nil {
				tempMilliC, _ := strconv.ParseFloat(strings.TrimSpace(string(tempData)), 64)
				temp = tempMilliC / 1000.0
			}
		}

		// Get GPU utilization
		usagePath := cardPath + "/gpu_busy_percent"
		usageData, err := os.ReadFile(usagePath)
		if err == nil {
			percent, _ = strconv.ParseFloat(strings.TrimSpace(string(usageData)), 64)
		}

		return percent, temp, name
	}

	return 0, 0, ""
}

// parseRocmSmiOutput parses rocm-smi CSV output
func parseRocmSmiOutput(output string) (percent float64, temp float64, name string) {
	lines := strings.Split(output, "\n")
	var useLine, tempLine, nameLine string

	for _, line := range lines {
		if strings.Contains(line, "GPU use") || strings.Contains(line, "GPU%") {
			useLine = line
		}
		if strings.Contains(line, "Temperature") || strings.Contains(line, "Temp") {
			tempLine = line
		}
		if strings.Contains(line, "Card series") || strings.Contains(line, "Product") {
			nameLine = line
		}
	}

	// Parse utilization
	if useLine != "" {
		re := regexp.MustCompile(`(\d+(?:\.\d+)?)\s*%?`)
		matches := re.FindStringSubmatch(useLine)
		if len(matches) > 1 {
			percent, _ = strconv.ParseFloat(matches[1], 64)
		}
	}

	// Parse temperature
	if tempLine != "" {
		re := regexp.MustCompile(`(\d+(?:\.\d+)?)\s*[Cc]?`)
		matches := re.FindStringSubmatch(tempLine)
		if len(matches) > 1 {
			temp, _ = strconv.ParseFloat(matches[1], 64)
		}
	}

	// Parse name
	if nameLine != "" {
		parts := strings.Split(nameLine, ",")
		if len(parts) > 1 {
			name = strings.TrimSpace(parts[len(parts)-1])
		}
	}

	if name == "" {
		name = "AMD GPU"
	}

	return percent, temp, name
}

// collectIntelGPU gathers Intel integrated GPU metrics
func collectIntelGPU() (percent float64, temp float64, name string) {
	if runtime.GOOS == "windows" {
		return collectIntelGPUWindows()
	}
	return collectIntelGPULinux()
}

// collectIntelGPUWindows gathers Intel GPU metrics on Windows
func collectIntelGPUWindows() (percent float64, temp float64, name string) {
	// Try LibreHardwareMonitor for Intel
	cmd := exec.Command("powershell", "-NoProfile", "-Command", `
$gpu = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Load" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$temp = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Sensor 2>$null | Where-Object { $_.SensorType -eq "Temperature" -and $_.Name -eq "GPU Core" } | Select-Object -First 1
$hw = Get-WmiObject -Namespace "root\LibreHardwareMonitor" -Class Hardware 2>$null | Where-Object { $_.HardwareType -eq "GpuIntel" } | Select-Object -First 1
if ($gpu -and $temp -and $hw) {
    Write-Output "$($gpu.Value),$($temp.Value),$($hw.Name)"
}
`)
	output, err := cmd.Output()
	if err == nil && len(strings.TrimSpace(string(output))) > 0 {
		return parseGPUOutput(string(output))
	}

	// Fallback: Get GPU name from WMI VideoController (no utilization/temp)
	// Use -match with regex instead of -like for Go exec compatibility
	cmd = exec.Command("powershell", "-NoProfile", "-Command",
		`(Get-WmiObject Win32_VideoController | Where-Object { $_.Name -match 'Intel|UHD|Iris' } | Select-Object -First 1).Name`)
	output, err = cmd.Output()
	if err == nil && len(strings.TrimSpace(string(output))) > 0 {
		return 0, 0, strings.TrimSpace(string(output))
	}

	return 0, 0, ""
}

// collectIntelGPULinux gathers Intel GPU metrics on Linux
func collectIntelGPULinux() (percent float64, temp float64, name string) {
	// Try intel_gpu_top (requires intel-gpu-tools package)
	cmd := exec.Command("timeout", "1", "intel_gpu_top", "-o", "-", "-s", "100")
	output, err := cmd.Output()
	if err == nil && len(output) > 0 {
		// Parse intel_gpu_top JSON output
		re := regexp.MustCompile(`"Render/3D/0":\s*{\s*"busy":\s*(\d+(?:\.\d+)?)`)
		matches := re.FindStringSubmatch(string(output))
		if len(matches) > 1 {
			percent, _ = strconv.ParseFloat(matches[1], 64)
		}
	}

	// Check for Intel GPU in sysfs
	files, err := os.ReadDir("/sys/class/drm")
	if err != nil {
		return percent, 0, ""
	}

	for _, f := range files {
		if !strings.HasPrefix(f.Name(), "card") || strings.Contains(f.Name(), "-") {
			continue
		}

		cardPath := "/sys/class/drm/" + f.Name() + "/device"

		// Check if it's Intel (vendor 0x8086)
		vendorData, err := os.ReadFile(cardPath + "/vendor")
		if err != nil || !strings.Contains(string(vendorData), "0x8086") {
			continue
		}

		name = "Intel GPU"

		// Try to get device name
		deviceData, err := os.ReadFile(cardPath + "/device")
		if err == nil {
			name = "Intel GPU " + strings.TrimSpace(string(deviceData))
		}

		return percent, 0, name
	}

	return 0, 0, ""
}

// parseGPUOutput parses generic "utilization,temp,name" CSV output
func parseGPUOutput(output string) (percent float64, temp float64, name string) {
	output = strings.TrimSpace(output)
	parts := strings.Split(output, ",")
	if len(parts) >= 3 {
		percent, _ = strconv.ParseFloat(strings.TrimSpace(parts[0]), 64)
		temp, _ = strconv.ParseFloat(strings.TrimSpace(parts[1]), 64)
		name = strings.TrimSpace(parts[2])
	}
	return percent, temp, name
}

// parseNvidiaSmiOutput parses nvidia-smi CSV output
func parseNvidiaSmiOutput(output string) (percent float64, temp float64, name string) {
	lines := strings.Split(strings.TrimSpace(output), "\n")
	if len(lines) == 0 {
		return 0, 0, ""
	}

	// Take first GPU
	parts := strings.Split(lines[0], ", ")
	if len(parts) >= 3 {
		percent, _ = strconv.ParseFloat(strings.TrimSpace(parts[0]), 64)
		temp, _ = strconv.ParseFloat(strings.TrimSpace(parts[1]), 64)
		name = strings.TrimSpace(parts[2])
	}

	return percent, temp, name
}

// measurePingLatency measures latency to a host using TCP connect
func measurePingLatency(host string, timeout time.Duration) float64 {
	start := time.Now()

	conn, err := net.DialTimeout("tcp", host+":80", timeout)
	if err != nil {
		return -1.0 // Indicate failure
	}
	defer conn.Close()

	latency := time.Since(start)
	return float64(latency.Milliseconds())
}

// CollectTopProcesses gathers top 10 processes by CPU usage
func CollectTopProcesses() ([]ProcessInfo, error) {
	processes, err := process.Processes()
	if err != nil {
		return nil, fmt.Errorf("failed to get processes: %w", err)
	}

	type procData struct {
		pid        int32
		name       string
		cpuPercent float64
		ramPercent float64
	}

	var procList []procData

	// Collect process data
	for _, p := range processes {
		name, err := p.Name()
		if err != nil {
			continue
		}

		// Get CPU percent (0 duration = instant)
		cpuPercent, err := p.CPUPercent()
		if err != nil {
			cpuPercent = 0
		}

		// Get memory percent
		memPercent, err := p.MemoryPercent()
		if err != nil {
			memPercent = 0
		}

		procList = append(procList, procData{
			pid:        p.Pid,
			name:       name,
			cpuPercent: cpuPercent,
			ramPercent: float64(memPercent),
		})
	}

	// Sort by CPU usage (descending)
	sort.Slice(procList, func(i, j int) bool {
		return procList[i].cpuPercent > procList[j].cpuPercent
	})

	// Take top 10
	var top10 []ProcessInfo
	for i := 0; i < len(procList) && i < 10; i++ {
		top10 = append(top10, ProcessInfo{
			PID:        procList[i].pid,
			Name:       procList[i].name,
			CPUPercent: procList[i].cpuPercent,
			RAMPercent: procList[i].ramPercent,
		})
	}

	return top10, nil
}

// FetchPublicIP queries an external service to get the public IP
func FetchPublicIP() (string, error) {
	client := &http.Client{
		Timeout: 5 * time.Second,
	}

	resp, err := client.Get("https://api.ipify.org?format=text")
	if err != nil {
		return "", fmt.Errorf("failed to fetch public IP: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response: %w", err)
	}

	publicIP := strings.TrimSpace(string(body))
	return publicIP, nil
}

// CollectLoadAvg gets the 15-minute load average
func CollectLoadAvg() (float64, error) {
	loadAvg, err := load.Avg()
	if err != nil {
		return 0, fmt.Errorf("failed to get load average: %w", err)
	}

	// Return 15-minute load average
	return loadAvg.Load15, nil
}

// InitMetricsCollection initializes metrics collection (called once on WebSocket connect)
func InitMetricsCollection() error {
	// Initialize previous time
	prevTime = time.Now()

	// Collect initial data
	_, _ = CollectMetrics()
	log.Println("Initial baseline metrics collected")

	// Collect initial processes
	if procs, err := CollectTopProcesses(); err == nil {
		processMutex.Lock()
		topProcesses = procs
		processMutex.Unlock()
		log.Println("Initial top processes collected")
	}

	// Collect initial public IP
	if ip, err := FetchPublicIP(); err == nil {
		processMutex.Lock()
		currentPublicIP = ip
		processMutex.Unlock()
		log.Printf("Initial public IP: %s", ip)
	}

	// Collect initial load average
	if loadAvg, err := CollectLoadAvg(); err == nil {
		processMutex.Lock()
		currentLoadAvg = loadAvg
		processMutex.Unlock()
		log.Printf("Initial load average (15min): %.2f", loadAvg)
	}

	// Start background goroutines for process and IP updates
	go processUpdater()
	go ipUpdater()

	return nil
}

var (
	sysInfoSentAt    time.Time
	sysInfoSendMutex sync.Mutex
)

// ResetSysInfoSentTime resets the system info sent timestamp to force resend on next heartbeat
// This should be called when establishing a new WebSocket connection
func ResetSysInfoSentTime() {
	sysInfoSendMutex.Lock()
	defer sysInfoSendMutex.Unlock()
	sysInfoSentAt = time.Time{} // Zero time will trigger send in BuildHeartbeatPayload
	log.Println("System info will be sent on next heartbeat")
}

// BuildHeartbeatPayload creates HeartbeatPayload from metrics
func BuildHeartbeatPayload(metrics []MetricPoint) (*HeartbeatPayload, error) {
	// Get current process data (read-only lock)
	processMutex.RLock()
	processes := topProcesses
	publicIP := currentPublicIP
	loadAvg := currentLoadAvg
	processMutex.RUnlock()

	// Get auth token from global config
	// Prefer api_key (instance key) over auth_token (legacy per-agent token)
	authToken := ""
	if globalConfig != nil {
		if globalConfig.APIKey != "" {
			authToken = globalConfig.APIKey
		} else if globalConfig.AuthToken != "" {
			authToken = globalConfig.AuthToken
		}
	}

	payload := &HeartbeatPayload{
		AgentID:           agentID,
		Hostname:          hostname,
		Metrics:           metrics,
		Status:            "online",
		LastSeenAt:        time.Now(),
		Processes:         processes,
		PublicIP:          publicIP,
		LoadAvg:           loadAvg,
		ConnectionAddress: currentConnectionAddress,
		AuthToken:         authToken,
		Version:           Version, // Populate from global constant
	}

	// Include system info on first heartbeat and every hour thereafter
	sysInfoSendMutex.Lock()
	if sysInfoSentAt.IsZero() || time.Since(sysInfoSentAt) > time.Hour {
		if sysInfo := GetCachedSystemInfo(); sysInfo != nil {
			payload.SystemInfo = sysInfo
		}
		sysInfoSentAt = time.Now()
	}
	sysInfoSendMutex.Unlock()

	return payload, nil
}

// SetConnectionAddress sets the current server connection address for heartbeat reporting
func SetConnectionAddress(addr string) {
	processMutex.Lock()
	currentConnectionAddress = addr
	processMutex.Unlock()
}

// GetLocalIP returns the agent's local LAN IP address
func GetLocalIP() string {
	// Try to get the IP by connecting to a remote address (doesn't actually send data)
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return ""
	}
	defer conn.Close()

	localAddr := conn.LocalAddr().(*net.UDPAddr)
	return localAddr.IP.String()
}

// processUpdater updates process list every 30 seconds
func processUpdater() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		if procs, err := CollectTopProcesses(); err == nil {
			processMutex.Lock()
			topProcesses = procs
			processMutex.Unlock()

			// Also update load average
			if loadAvg, err := CollectLoadAvg(); err == nil {
				processMutex.Lock()
				currentLoadAvg = loadAvg
				processMutex.Unlock()
			}
		}
	}
}

// ipUpdater updates public IP every 5 minutes
func ipUpdater() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()

	for range ticker.C {
		if ip, err := FetchPublicIP(); err == nil {
			processMutex.Lock()
			oldIP := currentPublicIP
			currentPublicIP = ip
			processMutex.Unlock()

			if oldIP != ip {
				log.Printf("Public IP changed: %s -> %s", oldIP, ip)
			}
		}
	}
}

// GetSystemInfo initializes agent ID and hostname
func GetSystemInfo() error {
	var err error
	hostname, err = os.Hostname()
	if err != nil {
		hostname = "unknown"
	}

	// Get stable agent ID from MAC address
	macAddr := getPrimaryMACAddress()
	if macAddr != "" {
		// Use MAC address as stable identifier (remove colons for cleaner ID)
		cleanMAC := strings.ReplaceAll(macAddr, ":", "")
		cleanMAC = strings.ReplaceAll(cleanMAC, "-", "")
		agentID = fmt.Sprintf("%s-%s", hostname, cleanMAC)
	} else {
		// Fallback to hostname only if no MAC available
		agentID = hostname
	}

	log.Printf("Agent ID: %s", agentID)
	log.Printf("Hostname: %s", hostname)

	return nil
}

// getPrimaryMACAddress returns the MAC address of the primary network interface
func getPrimaryMACAddress() string {
	interfaces, err := net.Interfaces()
	if err != nil {
		log.Printf("Error getting network interfaces: %v", err)
		return ""
	}

	// Sort interfaces to get consistent ordering
	sort.Slice(interfaces, func(i, j int) bool {
		return interfaces[i].Name < interfaces[j].Name
	})

	for _, iface := range interfaces {
		// Skip loopback, down interfaces, and virtual interfaces
		if iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		if iface.Flags&net.FlagUp == 0 {
			continue
		}

		// Skip common virtual interface names
		nameLower := strings.ToLower(iface.Name)
		if strings.Contains(nameLower, "virtual") ||
			strings.Contains(nameLower, "veth") ||
			strings.Contains(nameLower, "docker") ||
			strings.Contains(nameLower, "br-") ||
			strings.Contains(nameLower, "virbr") {
			continue
		}

		// Check if it has a valid MAC address
		mac := iface.HardwareAddr.String()
		if mac != "" && mac != "00:00:00:00:00:00" {
			log.Printf("Using MAC address from interface %s: %s", iface.Name, mac)
			return mac
		}
	}

	return ""
}
