# Scribe Agent - Installation Guide

## Overview

Scribe is a lightweight monitoring agent that collects metrics, processes, and logs from your system and sends them to the LogLibrarian backend.

**Supported Platforms:**
- Linux (systemd)
- Windows (Windows Service)
- macOS (launchd)

---

## Prerequisites

### Option 1: Pre-built Binary (Recommended)
Download the pre-built binary for your platform from the releases page.

### Option 2: Build from Source
- Go 1.21 or higher
- Git

---

## Quick Install

### Linux (Ubuntu/Debian/CentOS/RHEL)

```bash
# Download and run install script
curl -fsSL https://raw.githubusercontent.com/your-org/scribe/main/install.sh | sudo bash

# Or manually:
sudo ./install-linux.sh
```

### Windows (PowerShell as Administrator)

```powershell
# Download and run install script
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/your-org/scribe/main/install.ps1" -OutFile install.ps1
.\install.ps1

# Or manually:
.\install-windows.ps1
```

---

## Manual Installation

### Linux

#### 1. Build the Agent

```bash
cd scribe
go build -o scribe-agent .
```

#### 2. Create Installation Directory

```bash
sudo mkdir -p /opt/scribe
sudo mkdir -p /etc/scribe
sudo mkdir -p /var/log/scribe
```

#### 3. Copy Binary

```bash
sudo cp scribe-agent /opt/scribe/
sudo chmod +x /opt/scribe/scribe-agent
```

#### 4. Create Configuration File

```bash
sudo tee /etc/scribe/config.json > /dev/null <<EOF
{
  "server_host": "your-loglibrarian-server:8000",
  "agent_name": "$(hostname)",
  "log_file": "/var/log/syslog",
  "metrics_interval": 60,
  "log_batch_size": 50,
  "log_batch_interval": 5
}
EOF
```

#### 5. Create systemd Service

```bash
sudo tee /etc/systemd/system/scribe.service > /dev/null <<EOF
[Unit]
Description=Scribe Monitoring Agent
After=network.target

[Service]
Type=simple
User=scribe
Group=scribe
WorkingDirectory=/opt/scribe
ExecStart=/opt/scribe/scribe-agent -config /etc/scribe/config.json
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

#### 6. Create Service User

```bash
sudo useradd -r -s /bin/false scribe
sudo chown -R scribe:scribe /opt/scribe
sudo chown -R scribe:scribe /var/log/scribe
```

#### 7. Start the Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable scribe
sudo systemctl start scribe
```

#### 8. Check Status

```bash
sudo systemctl status scribe
sudo journalctl -u scribe -f
```

---

### Windows

#### 1. Build the Agent

```powershell
cd scribe
go build -o scribe-agent.exe .
```

#### 2. Create Installation Directory

```powershell
New-Item -Path "C:\Program Files\Scribe" -ItemType Directory -Force
New-Item -Path "C:\ProgramData\Scribe" -ItemType Directory -Force
New-Item -Path "C:\ProgramData\Scribe\logs" -ItemType Directory -Force
```

#### 3. Copy Binary

```powershell
Copy-Item scribe-agent.exe "C:\Program Files\Scribe\"
```

#### 4. Create Configuration File

```powershell
@"
{
  "server_host": "your-loglibrarian-server:8000",
  "agent_name": "$env:COMPUTERNAME",
  "log_file": "C:\\Windows\\System32\\winevt\\Logs\\Application.evtx",
  "metrics_interval": 60,
  "log_batch_size": 50,
  "log_batch_interval": 5
}
"@ | Out-File -FilePath "C:\ProgramData\Scribe\config.json" -Encoding UTF8
```

#### 5. Install as Windows Service

```powershell
# Using NSSM (Non-Sucking Service Manager)
# Download from: https://nssm.cc/download

nssm install Scribe "C:\Program Files\Scribe\scribe-agent.exe"
nssm set Scribe AppDirectory "C:\Program Files\Scribe"
nssm set Scribe AppParameters "-config C:\ProgramData\Scribe\config.json"
nssm set Scribe DisplayName "Scribe Monitoring Agent"
nssm set Scribe Description "Collects metrics and logs for LogLibrarian"
nssm set Scribe Start SERVICE_AUTO_START
nssm set Scribe AppStdout "C:\ProgramData\Scribe\logs\stdout.log"
nssm set Scribe AppStderr "C:\ProgramData\Scribe\logs\stderr.log"
```

#### 6. Start the Service

```powershell
Start-Service Scribe
```

#### 7. Check Status

```powershell
Get-Service Scribe
Get-Content "C:\ProgramData\Scribe\logs\stdout.log" -Tail 20 -Wait
```

---

## Configuration

### Configuration File (`config.json`)

```json
{
  "server_host": "loglibrarian.example.com:8000",
  "agent_name": "web-server-01",
  "log_file": "/var/log/syslog",
  "metrics_interval": 60,
  "log_batch_size": 50,
  "log_batch_interval": 5,
  "ssl_enabled": false,
  "ssl_verify": true,
  "agent_id": ""
}
```

**Parameters:**

- `server_host` - LogLibrarian backend address (host:port)
- `agent_name` - Human-readable agent name (defaults to hostname)
- `log_file` - Path to log file to tail
- `metrics_interval` - Seconds between metric collections (default: 60)
- `log_batch_size` - Number of logs per batch (default: 50)
- `log_batch_interval` - Seconds between log batches (default: 5)
- `ssl_enabled` - Use HTTPS/WSS for connections
- `ssl_verify` - Verify SSL certificates
- `agent_id` - UUID for agent (auto-generated if empty)

---

## Building for Multiple Platforms

### Cross-Compile All Platforms

```bash
# Linux AMD64
GOOS=linux GOARCH=amd64 go build -o scribe-agent-linux-amd64 .

# Linux ARM64
GOOS=linux GOARCH=arm64 go build -o scribe-agent-linux-arm64 .

# Windows AMD64
GOOS=windows GOARCH=amd64 go build -o scribe-agent-windows-amd64.exe .

# macOS AMD64
GOOS=darwin GOARCH=amd64 go build -o scribe-agent-darwin-amd64 .

# macOS ARM64 (M1/M2)
GOOS=darwin GOARCH=arm64 go build -o scribe-agent-darwin-arm64 .
```

### Using Makefile

```bash
make build-all
```

---

## Troubleshooting

### Linux

**Check service status:**
```bash
sudo systemctl status scribe
```

**View logs:**
```bash
sudo journalctl -u scribe -f
sudo journalctl -u scribe --since "1 hour ago"
```

**Restart service:**
```bash
sudo systemctl restart scribe
```

**Stop service:**
```bash
sudo systemctl stop scribe
```

### Windows

**Check service status:**
```powershell
Get-Service Scribe
```

**View logs:**
```powershell
Get-Content "C:\ProgramData\Scribe\logs\stdout.log" -Tail 50
```

**Restart service:**
```powershell
Restart-Service Scribe
```

**Stop service:**
```powershell
Stop-Service Scribe
```

---

## Uninstallation

### Linux

```bash
sudo systemctl stop scribe
sudo systemctl disable scribe
sudo rm /etc/systemd/system/scribe.service
sudo systemctl daemon-reload
sudo rm -rf /opt/scribe
sudo rm -rf /etc/scribe
sudo userdel scribe
```

### Windows

```powershell
Stop-Service Scribe
nssm remove Scribe confirm
Remove-Item "C:\Program Files\Scribe" -Recurse -Force
Remove-Item "C:\ProgramData\Scribe" -Recurse -Force
```

---

## Security Considerations

1. **Run as non-root/non-admin** - The agent should run with minimal privileges
2. **File permissions** - Restrict access to configuration files
3. **Network security** - Use SSL/TLS for production
4. **Firewall rules** - Allow outbound connections to LogLibrarian backend
5. **Log rotation** - Configure log rotation to prevent disk fill

---

## Performance Tuning

### Low-Resource Systems
```json
{
  "metrics_interval": 300,
  "log_batch_size": 20,
  "log_batch_interval": 10
}
```

### High-Volume Systems
```json
{
  "metrics_interval": 10,
  "log_batch_size": 100,
  "log_batch_interval": 2
}
```

---

## Support

- **Documentation:** https://github.com/your-org/scribe/docs
- **Issues:** https://github.com/your-org/scribe/issues
- **Community:** https://discord.gg/your-channel
