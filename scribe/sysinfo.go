package main

import (
	"bufio"
	"fmt"
	"log"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/host"
	"github.com/shirou/gopsutil/v3/mem"
	psnet "github.com/shirou/gopsutil/v3/net"
)

// SystemInfo contains comprehensive hardware and OS information
type SystemInfo struct {
	// OS Information
	OS              string `json:"os"`
	OSVersion       string `json:"os_version"`
	Platform        string `json:"platform"`
	PlatformVersion string `json:"platform_version"`
	KernelVersion   string `json:"kernel_version"`
	Hostname        string `json:"hostname"`
	Uptime          uint64 `json:"uptime"`
	BootTime        uint64 `json:"boot_time"`

	// CPU Information
	CPUModel   string  `json:"cpu_model"`
	CPUCores   int     `json:"cpu_cores"`
	CPUThreads int     `json:"cpu_threads"`
	CPUFreqMHz float64 `json:"cpu_freq_mhz"`
	CPUCache   string  `json:"cpu_cache"`
	CPUArch    string  `json:"cpu_arch"`

	// Memory Information
	RAMTotalGB float64 `json:"ram_total_gb"`
	RAMType    string  `json:"ram_type"`
	RAMSpeed   string  `json:"ram_speed"`

	// GPU Information
	GPUModel    string `json:"gpu_model"`
	GPUVendor   string `json:"gpu_vendor"`
	GPUMemoryMB int    `json:"gpu_memory_mb"`
	GPUDriver   string `json:"gpu_driver"`

	// Motherboard Information
	Motherboard  string `json:"motherboard"`
	BIOSVersion  string `json:"bios_version"`
	Manufacturer string `json:"manufacturer"`
	ProductName  string `json:"product_name"`
	SerialNumber string `json:"serial_number"`

	// Storage Information
	Disks []DiskDetails `json:"disks"`

	// Network Information
	NetworkInterfaces []NetworkInterface `json:"network_interfaces"`

	// Container/VM detection
	IsVM        bool   `json:"is_vm"`
	VMType      string `json:"vm_type"`
	IsContainer bool   `json:"is_container"`

	// Collected timestamp
	CollectedAt time.Time `json:"collected_at"`
}

// DiskDetails contains information about a storage device
type DiskDetails struct {
	Device      string  `json:"device"`
	Mountpoint  string  `json:"mountpoint"`
	FSType      string  `json:"fstype"`
	TotalGB     float64 `json:"total_gb"`
	Model       string  `json:"model"`
	Serial      string  `json:"serial"`
	IsRemovable bool    `json:"is_removable"`
	IsSSD       bool    `json:"is_ssd"`
}

// NetworkInterface contains information about a network adapter
type NetworkInterface struct {
	Name       string   `json:"name"`
	MAC        string   `json:"mac"`
	IPs        []string `json:"ips"`
	Speed      string   `json:"speed"`
	IsUp       bool     `json:"is_up"`
	IsLoopback bool     `json:"is_loopback"`
}

var (
	cachedSystemInfo *SystemInfo
	sysInfoMutex     sync.RWMutex
	sysInfoCollected bool
)

// GetCachedSystemInfo returns cached system info or collects it if not available
func GetCachedSystemInfo() *SystemInfo {
	sysInfoMutex.RLock()
	if sysInfoCollected && cachedSystemInfo != nil {
		defer sysInfoMutex.RUnlock()
		return cachedSystemInfo
	}
	sysInfoMutex.RUnlock()

	// Collect and cache
	info := CollectSystemInfo()

	sysInfoMutex.Lock()
	cachedSystemInfo = info
	sysInfoCollected = true
	sysInfoMutex.Unlock()

	return info
}

// CollectSystemInfo gathers comprehensive system information
func CollectSystemInfo() *SystemInfo {
	info := &SystemInfo{
		CollectedAt: time.Now(),
		CPUArch:     runtime.GOARCH,
	}

	// OS Information
	hostInfo, err := host.Info()
	if err == nil {
		info.OS = hostInfo.OS
		info.Platform = hostInfo.Platform
		info.PlatformVersion = hostInfo.PlatformVersion
		info.KernelVersion = hostInfo.KernelVersion
		info.Hostname = hostInfo.Hostname
		info.Uptime = hostInfo.Uptime
		info.BootTime = hostInfo.BootTime
		info.VMType = hostInfo.VirtualizationSystem
		info.IsVM = hostInfo.VirtualizationRole == "guest"
	}

	// CPU Information
	cpuInfo, err := cpu.Info()
	if err == nil && len(cpuInfo) > 0 {
		info.CPUModel = cpuInfo[0].ModelName
		info.CPUCores = int(cpuInfo[0].Cores)
		info.CPUFreqMHz = cpuInfo[0].Mhz
		info.CPUCache = fmt.Sprintf("%d KB", cpuInfo[0].CacheSize)
	}

	// CPU thread count
	info.CPUThreads = runtime.NumCPU()

	// Memory Information
	memInfo, err := mem.VirtualMemory()
	if err == nil {
		info.RAMTotalGB = float64(memInfo.Total) / (1024 * 1024 * 1024)
	}

	// Disk Information
	info.Disks = collectDiskInfo()

	// Network Interfaces
	info.NetworkInterfaces = collectNetworkInfo()

	// Platform-specific collection
	if runtime.GOOS == "windows" {
		collectWindowsSpecificInfo(info)
	} else {
		collectLinuxSpecificInfo(info)
	}

	// Check if running in container
	info.IsContainer = isRunningInContainer()

	return info
}

// collectDiskInfo gathers information about all storage devices
func collectDiskInfo() []DiskDetails {
	var disks []DiskDetails

	partitions, err := disk.Partitions(false)
	if err != nil {
		return disks
	}

	seen := make(map[string]bool)

	for _, part := range partitions {
		// Skip pseudo filesystems
		if shouldSkipFilesystem(part.Fstype) {
			continue
		}

		// Skip duplicate devices
		if seen[part.Device] {
			continue
		}
		seen[part.Device] = true

		usage, err := disk.Usage(part.Mountpoint)
		if err != nil {
			continue
		}

		diskDetail := DiskDetails{
			Device:     part.Device,
			Mountpoint: part.Mountpoint,
			FSType:     part.Fstype,
			TotalGB:    float64(usage.Total) / (1024 * 1024 * 1024),
		}

		disks = append(disks, diskDetail)
	}

	return disks
}

// collectNetworkInfo gathers information about network interfaces
func collectNetworkInfo() []NetworkInterface {
	var interfaces []NetworkInterface

	ifaces, err := psnet.Interfaces()
	if err != nil {
		return interfaces
	}

	for _, iface := range ifaces {
		netIface := NetworkInterface{
			Name:       iface.Name,
			MAC:        iface.HardwareAddr,
			IsUp:       strings.Contains(strings.Join(iface.Flags, ","), "up"),
			IsLoopback: strings.Contains(strings.Join(iface.Flags, ","), "loopback"),
		}

		for _, addr := range iface.Addrs {
			netIface.IPs = append(netIface.IPs, addr.Addr)
		}

		interfaces = append(interfaces, netIface)
	}

	return interfaces
}

// collectWindowsSpecificInfo gets Windows-specific hardware info
func collectWindowsSpecificInfo(info *SystemInfo) {
	// Get GPU info from LibreHardwareMonitor or WMI
	info.GPUModel = getCPUName() // This gets cached GPU name
	if info.GPUModel == "" {
		info.GPUModel = getWindowsGPUName()
	}

	// Get motherboard info
	info.Motherboard, info.Manufacturer = getWindowsMotherboardInfo()

	// Get BIOS info
	info.BIOSVersion = getWindowsBIOSInfo()

	// Get product name
	info.ProductName = getWindowsProductName()

	// Get RAM details
	info.RAMType, info.RAMSpeed = getWindowsRAMDetails()

	// OS Version details
	info.OSVersion = getWindowsVersion()

	// GPU Memory
	info.GPUMemoryMB = getWindowsGPUMemory()
}

// collectLinuxSpecificInfo gets Linux-specific hardware info
func collectLinuxSpecificInfo(info *SystemInfo) {
	// GPU info
	info.GPUModel = getLinuxGPUName()
	info.GPUVendor = getLinuxGPUVendor()

	// Motherboard/DMI info
	info.Motherboard = readDMIFile("/sys/class/dmi/id/board_name")
	info.Manufacturer = readDMIFile("/sys/class/dmi/id/board_vendor")
	info.BIOSVersion = readDMIFile("/sys/class/dmi/id/bios_version")
	info.ProductName = readDMIFile("/sys/class/dmi/id/product_name")
	info.SerialNumber = readDMIFile("/sys/class/dmi/id/product_serial")

	// RAM details from dmidecode (requires root)
	info.RAMType, info.RAMSpeed = getLinuxRAMDetails()

	// OS Version from /etc/os-release
	if osRelease, err := parseOSRelease("/etc/os-release"); err == nil {
		info.OSVersion = osRelease["PRETTY_NAME"]
		if info.OSVersion == "" {
			info.OSVersion = osRelease["NAME"] + " " + osRelease["VERSION"]
		}
	}
}

// Windows-specific helper functions

func getWindowsGPUName() string {
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`Get-WmiObject Win32_VideoController | Select-Object -First 1 -ExpandProperty Name`)
	output, err := cmd.Output()
	if err == nil {
		return strings.TrimSpace(string(output))
	}
	return ""
}

func getWindowsMotherboardInfo() (string, string) {
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`$b = Get-WmiObject Win32_BaseBoard; Write-Output "$($b.Product)|$($b.Manufacturer)"`)
	output, err := cmd.Output()
	if err == nil {
		parts := strings.Split(strings.TrimSpace(string(output)), "|")
		if len(parts) == 2 {
			return parts[0], parts[1]
		}
	}
	return "", ""
}

func getWindowsBIOSInfo() string {
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`(Get-WmiObject Win32_BIOS).SMBIOSBIOSVersion`)
	output, err := cmd.Output()
	if err == nil {
		return strings.TrimSpace(string(output))
	}
	return ""
}

func getWindowsProductName() string {
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`(Get-WmiObject Win32_ComputerSystem).Model`)
	output, err := cmd.Output()
	if err == nil {
		return strings.TrimSpace(string(output))
	}
	return ""
}

func getWindowsRAMDetails() (string, string) {
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`$m = Get-WmiObject Win32_PhysicalMemory | Select-Object -First 1; Write-Output "$($m.MemoryType)|$($m.Speed)"`)
	output, err := cmd.Output()
	if err == nil {
		parts := strings.Split(strings.TrimSpace(string(output)), "|")
		if len(parts) == 2 {
			memType := "Unknown"
			switch parts[0] {
			case "20":
				memType = "DDR"
			case "21":
				memType = "DDR2"
			case "22":
				memType = "DDR2 FB-DIMM"
			case "24":
				memType = "DDR3"
			case "26":
				memType = "DDR4"
			case "30":
				memType = "DDR5"
			}
			return memType, parts[1] + " MHz"
		}
	}
	return "", ""
}

func getWindowsVersion() string {
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`(Get-WmiObject Win32_OperatingSystem).Caption + " " + (Get-WmiObject Win32_OperatingSystem).Version`)
	output, err := cmd.Output()
	if err == nil {
		return strings.TrimSpace(string(output))
	}
	return ""
}

func getWindowsGPUMemory() int {
	cmd := exec.Command("powershell", "-NoProfile", "-Command",
		`(Get-WmiObject Win32_VideoController | Select-Object -First 1).AdapterRAM / 1MB`)
	output, err := cmd.Output()
	if err == nil {
		if mem, err := strconv.Atoi(strings.TrimSpace(string(output))); err == nil {
			return mem
		}
	}
	return 0
}

// Linux-specific helper functions

func getLinuxGPUName() string {
	// Try lspci first
	cmd := exec.Command("lspci")
	output, err := cmd.Output()
	if err == nil {
		lines := strings.Split(string(output), "\n")
		for _, line := range lines {
			if strings.Contains(strings.ToLower(line), "vga") || strings.Contains(strings.ToLower(line), "3d") {
				// Extract the GPU name (after the colon)
				parts := strings.SplitN(line, ": ", 2)
				if len(parts) == 2 {
					return strings.TrimSpace(parts[1])
				}
			}
		}
	}
	return ""
}

func getLinuxGPUVendor() string {
	gpuName := getLinuxGPUName()
	gpuLower := strings.ToLower(gpuName)

	if strings.Contains(gpuLower, "nvidia") {
		return "NVIDIA"
	} else if strings.Contains(gpuLower, "amd") || strings.Contains(gpuLower, "radeon") {
		return "AMD"
	} else if strings.Contains(gpuLower, "intel") {
		return "Intel"
	}
	return ""
}

func readDMIFile(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func getLinuxRAMDetails() (string, string) {
	// Try dmidecode (requires root)
	cmd := exec.Command("dmidecode", "-t", "memory")
	output, err := cmd.Output()
	if err != nil {
		return "", ""
	}

	var memType, speed string
	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "Type:") && memType == "" {
			memType = strings.TrimSpace(strings.TrimPrefix(line, "Type:"))
		}
		if strings.HasPrefix(line, "Speed:") && speed == "" {
			speed = strings.TrimSpace(strings.TrimPrefix(line, "Speed:"))
		}
	}

	return memType, speed
}

// parseOSRelease reads and parses /etc/os-release
func parseOSRelease(path string) (map[string]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	result := make(map[string]string)
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.Contains(line, "=") {
			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 {
				key := strings.TrimSpace(parts[0])
				value := strings.Trim(strings.TrimSpace(parts[1]), "\"")
				result[key] = value
			}
		}
	}
	return result, scanner.Err()
}

// isRunningInContainer checks if the process is running inside a container
func isRunningInContainer() bool {
	// Check for Docker
	if _, err := os.Stat("/.dockerenv"); err == nil {
		return true
	}
	// Check cgroup for container indicators
	if data, err := os.ReadFile("/proc/1/cgroup"); err == nil {
		content := string(data)
		if strings.Contains(content, "docker") ||
			strings.Contains(content, "kubepods") ||
			strings.Contains(content, "lxc") {
			return true
		}
	}
	return false
}

// LogSystemInfo prints a summary of system information
func LogSystemInfo(info *SystemInfo) {
	log.Printf("📊 System Information:")
	log.Printf("   OS: %s %s", info.Platform, info.PlatformVersion)
	log.Printf("   Kernel: %s", info.KernelVersion)
	log.Printf("   CPU: %s (%d cores, %d threads)", info.CPUModel, info.CPUCores, info.CPUThreads)
	log.Printf("   RAM: %.1f GB", info.RAMTotalGB)
	if info.GPUModel != "" {
		log.Printf("   GPU: %s", info.GPUModel)
	}
	if info.Motherboard != "" {
		log.Printf("   Motherboard: %s (%s)", info.Motherboard, info.Manufacturer)
	}
	log.Printf("   Disks: %d volumes", len(info.Disks))
	if info.IsVM {
		log.Printf("   VM Type: %s", info.VMType)
	}
	if info.IsContainer {
		log.Printf("   Running in container")
	}
}
