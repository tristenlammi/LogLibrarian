# Scribe Agent - Windows Installation Script
# Run as Administrator

param(
    [string]$ServerHost,
    [string]$ApiKey,
    [string]$AgentName = $env:COMPUTERNAME,
    [string]$LogFile = "C:\Windows\System32\winevt\Logs\Application.evtx",
    [switch]$NoStart
)

# Color functions
function Write-Success { Write-Host "✓ $args" -ForegroundColor Green }
function Write-Error { Write-Host "✗ $args" -ForegroundColor Red }
function Write-Info { Write-Host "ℹ $args" -ForegroundColor Cyan }
function Write-Warning { Write-Host "⚠ $args" -ForegroundColor Yellow }

# Banner
Write-Host ""
Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║   Scribe Agent Installation Script   ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

# Check if running as Administrator
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "Please run as Administrator"
    Write-Info "Right-click PowerShell and select 'Run as Administrator'"
    exit 1
}

Write-Success "Running as Administrator"

# Check for Go
$goPath = Get-Command go -ErrorAction SilentlyContinue
if (-not $goPath) {
    Write-Warning "Go not found. Building requires Go 1.21+"
    Write-Info "Install Go from: https://go.dev/doc/install"
    Write-Info "Or use a pre-built binary"
    exit 1
}

$goVersion = (go version) -replace ".*go([\d.]+).*", '$1'
Write-Success "Go version: $goVersion"

# Get configuration
Write-Host ""
Write-Info "Configuration:"

if (-not $ServerHost) {
    $ServerHost = Read-Host "Enter LogLibrarian server address (e.g., 192.168.1.100:8000)"
    if (-not $ServerHost) {
        Write-Error "Server address is required"
        exit 1
    }
}

if (-not $ApiKey) {
    $ApiKey = Read-Host "Enter LogLibrarian API key"
    if (-not $ApiKey) {
        Write-Error "API key is required"
        exit 1
    }
}

if (-not $AgentName) {
    $input = Read-Host "Enter agent name [$env:COMPUTERNAME]"
    if ($input) { $AgentName = $input }
    else { $AgentName = $env:COMPUTERNAME }
}

if (-not $LogFile) {
    $input = Read-Host "Enter log file path [C:\Windows\System32\winevt\Logs\Application.evtx]"
    if ($input) { $LogFile = $input }
    else { $LogFile = "C:\Windows\System32\winevt\Logs\Application.evtx" }
}

Write-Host ""
Write-Info "Building agent..."

# Build the agent
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

$env:GOOS = "windows"
$env:GOARCH = "amd64"
go build -o scribe-agent.exe -ldflags="-s -w" .

if (-not (Test-Path "scribe-agent.exe")) {
    Write-Error "Build failed"
    exit 1
}

Write-Success "Build successful"

# Create directories
Write-Host ""
Write-Info "Creating directories..."

$installDir = "C:\Program Files\Scribe"
$configDir = "C:\ProgramData\Scribe"
$logDir = "C:\ProgramData\Scribe\logs"

New-Item -Path $installDir -ItemType Directory -Force | Out-Null
New-Item -Path $configDir -ItemType Directory -Force | Out-Null
New-Item -Path $logDir -ItemType Directory -Force | Out-Null

Write-Success "Directories created"

# Copy binary
Write-Info "Installing binary..."
Copy-Item "scribe-agent.exe" "$installDir\" -Force
Write-Success "Binary installed to $installDir\scribe-agent.exe"

# Create configuration file
Write-Info "Creating configuration..."

$config = @{
    server_host = $ServerHost
    api_key = $ApiKey
    agent_name = $AgentName
    log_file = $LogFile.Replace("\", "\\")
    metrics_interval = 60
    log_batch_size = 50
    log_batch_interval = 5
    ssl_enabled = $false
    ssl_verify = $true
    agent_id = ""
} | ConvertTo-Json

$configPath = "$configDir\config.json"
$config | Out-File -FilePath $configPath -Encoding UTF8 -Force

Write-Success "Configuration saved to $configPath"

# Check for sc.exe (built-in Windows service manager)
Write-Host ""
Write-Info "Installing as Windows Service..."

# Stop service if it exists
$existingService = Get-Service -Name "Scribe" -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Warning "Existing service found. Stopping..."
    Stop-Service -Name "Scribe" -Force
    sc.exe delete Scribe
    Start-Sleep -Seconds 2
}

# Create Windows Service using sc.exe
$servicePath = "`"$installDir\scribe-agent.exe`" install -config `"$configPath`""
$result = sc.exe create Scribe binPath= $servicePath start= auto DisplayName= "Scribe Monitoring Agent" obj= "LocalSystem"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create service"
    Write-Info "Error: $result"
    exit 1
}

# Set service description
sc.exe description Scribe "Collects system metrics, processes, and logs for LogLibrarian"

# Set service recovery options
sc.exe failure Scribe reset= 86400 actions= restart/5000/restart/10000/restart/30000

Write-Success "Service created"

# Start service
if (-not $NoStart) {
    Write-Host ""
    $start = Read-Host "Start Scribe agent now? (Y/n)"
    
    if ([string]::IsNullOrWhiteSpace($start) -or $start -eq "Y" -or $start -eq "y") {
        Write-Info "Starting service..."
        Start-Service -Name "Scribe"
        Start-Sleep -Seconds 2
        
        $service = Get-Service -Name "Scribe"
        if ($service.Status -eq "Running") {
            Write-Success "Service started successfully"
        } else {
            Write-Warning "Service status: $($service.Status)"
        }
        
        # Show service status
        Write-Host ""
        Write-Info "Service Status:"
        Get-Service -Name "Scribe" | Format-Table -AutoSize
    } else {
        Write-Success "Service created but not started"
        Write-Info "Run 'Start-Service Scribe' to start the service"
    }
} else {
    Write-Success "Service created but not started (use -NoStart flag)"
}

# Installation summary
Write-Host ""
Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║     Installation Complete! 🎉        ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "Binary:        $installDir\scribe-agent.exe"
Write-Host "Config:        $configPath"
Write-Host "Logs:          $logDir\"
Write-Host "Service:       Scribe"
Write-Host ""
Write-Warning "Useful Commands:"
Write-Host "  Status:      Get-Service Scribe"
Write-Host "  Logs:        Get-Content '$logDir\stdout.log' -Tail 20 -Wait"
Write-Host "  Restart:     Restart-Service Scribe"
Write-Host "  Stop:        Stop-Service Scribe"
Write-Host "  Edit config: notepad '$configPath'"
Write-Host ""
Write-Warning "Next Steps:"
Write-Host "  1. Verify agent appears in LogLibrarian dashboard"
Write-Host "  2. Check logs in $logDir\"
Write-Host "  3. Edit $configPath to customize settings"
Write-Host ""

# Create uninstall script
$uninstallScript = @"
# Scribe Agent - Uninstall Script
# Run as Administrator

Write-Host "Uninstalling Scribe Agent..." -ForegroundColor Yellow

`$service = Get-Service -Name "Scribe" -ErrorAction SilentlyContinue
if (`$service) {
    Stop-Service -Name "Scribe" -Force
    sc.exe delete Scribe
    Write-Host "✓ Service removed" -ForegroundColor Green
}

if (Test-Path "$installDir") {
    Remove-Item "$installDir" -Recurse -Force
    Write-Host "✓ Installation directory removed" -ForegroundColor Green
}

if (Test-Path "$configDir") {
    Remove-Item "$configDir" -Recurse -Force
    Write-Host "✓ Configuration and logs removed" -ForegroundColor Green
}

Write-Host ""
Write-Host "Scribe Agent has been uninstalled" -ForegroundColor Green
"@

$uninstallScript | Out-File -FilePath "$installDir\uninstall.ps1" -Encoding UTF8 -Force
Write-Success "Uninstall script created: $installDir\uninstall.ps1"
Write-Host ""
