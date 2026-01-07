# 🚀 Quick Start - Agent Installation

This guide will get your Scribe monitoring agent up and running in 5 minutes.

## Prerequisites

- **Linux**: systemd-based distribution (Ubuntu, Debian, CentOS, RHEL, Fedora)
- **Windows**: Windows 10/11 or Windows Server 2016+
- **Go**: 1.21+ (only if building from source)

## Installation Methods

### Method 1: Quick Install Script (Recommended)

#### Linux

```bash
cd scribe
sudo ./install-linux.sh
```

The script will:
1. Build the agent binary
2. Install to `/opt/scribe`
3. Create systemd service
4. Configure and start the agent

#### Windows (PowerShell as Administrator)

```powershell
cd scribe
.\install-windows.ps1
```

The script will:
1. Build the agent binary
2. Install to `C:\Program Files\Scribe`
3. Create Windows service
4. Configure and start the agent

### Method 2: Pre-built Binaries

If you have pre-built binaries, skip the build step in the installation scripts.

### Method 3: Manual Installation

See [AGENT_INSTALLATION.md](../AGENT_INSTALLATION.md) for detailed manual installation instructions.

---

## Configuration

After installation, edit the configuration file:

**Linux:**
```bash
sudo nano /etc/scribe/config.json
```

**Windows:**
```powershell
notepad C:\ProgramData\Scribe\config.json
```

### Configuration Options

```json
{
  "server_host": "your-loglibrarian-server:8000",
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

**Key Settings:**

- `server_host` - Your LogLibrarian backend address (required)
- `agent_name` - Display name in dashboard (defaults to hostname)
- `log_file` - Path to log file to monitor
- `metrics_interval` - Seconds between metric updates (60 = 1 minute)

After changing configuration, restart the service:

**Linux:**
```bash
sudo systemctl restart scribe
```

**Windows:**
```powershell
Restart-Service Scribe
```

---

## Verification

### Check Service Status

**Linux:**
```bash
sudo systemctl status scribe
```

**Windows:**
```powershell
Get-Service Scribe
```

### View Logs

**Linux:**
```bash
sudo journalctl -u scribe -f
```

**Windows:**
```powershell
Get-Content "C:\ProgramData\Scribe\logs\stdout.log" -Tail 20 -Wait
```

### Check Dashboard

Open LogLibrarian dashboard and verify your agent appears in the agents list.

---

## Common Issues

### Agent not appearing in dashboard

1. **Check connectivity:**
   ```bash
   # Linux
   curl http://your-server:8000/health
   
   # Windows
   Invoke-WebRequest http://your-server:8000/health
   ```

2. **Check firewall:**
   - Ensure outbound connections allowed to port 8000
   - WebSocket connections (ws://) must be allowed

3. **Check logs for errors:**
   - Look for "connection refused" or "timeout" messages

### High CPU/Memory usage

Increase `metrics_interval` and `log_batch_interval` in config:
```json
{
  "metrics_interval": 300,
  "log_batch_interval": 10
}
```

### Log file permission denied

**Linux:**
```bash
# Add scribe user to appropriate group
sudo usermod -a -G adm scribe
sudo systemctl restart scribe
```

**Windows:**
- Run service as administrator or grant read permissions

---

## Useful Commands

### Linux

```bash
# Start service
sudo systemctl start scribe

# Stop service
sudo systemctl stop scribe

# Restart service
sudo systemctl restart scribe

# View status
sudo systemctl status scribe

# View real-time logs
sudo journalctl -u scribe -f

# View last 100 lines
sudo journalctl -u scribe -n 100

# Disable service
sudo systemctl disable scribe

# Re-enable service
sudo systemctl enable scribe
```

### Windows

```powershell
# Start service
Start-Service Scribe

# Stop service
Stop-Service Scribe

# Restart service
Restart-Service Scribe

# View status
Get-Service Scribe

# View logs
Get-Content "C:\ProgramData\Scribe\logs\stdout.log" -Tail 50

# Watch logs in real-time
Get-Content "C:\ProgramData\Scribe\logs\stdout.log" -Tail 20 -Wait
```

---

## Building from Source

### Prerequisites

Install Go 1.21+:
- **Linux:** https://go.dev/doc/install
- **Windows:** https://go.dev/dl/

### Build for Current Platform

```bash
cd scribe
go build -o scribe-agent .
```

### Build for All Platforms

```bash
cd scribe
./build-all.sh
```

This creates binaries in `dist/`:
- `scribe-agent-linux-amd64`
- `scribe-agent-linux-arm64`
- `scribe-agent-windows-amd64.exe`
- `scribe-agent-darwin-amd64`
- `scribe-agent-darwin-arm64`

---

## Uninstallation

### Linux

```bash
sudo systemctl stop scribe
sudo systemctl disable scribe
sudo rm /etc/systemd/system/scribe.service
sudo systemctl daemon-reload
sudo rm -rf /opt/scribe /etc/scribe /var/log/scribe
sudo userdel scribe
```

### Windows

Run the uninstall script created during installation:
```powershell
C:\"Program Files"\Scribe\uninstall.ps1
```

Or manually:
```powershell
Stop-Service Scribe
sc.exe delete Scribe
Remove-Item "C:\Program Files\Scribe" -Recurse -Force
Remove-Item "C:\ProgramData\Scribe" -Recurse -Force
```

---

## Next Steps

1. ✅ Install agent on target systems
2. ✅ Verify agents appear in dashboard
3. ✅ Configure log file paths for your environment
4. ✅ Set appropriate `metrics_interval` based on your needs
5. ✅ Set up alerts and monitoring rules in LogLibrarian

---

## Support

- **Documentation:** [AGENT_INSTALLATION.md](../AGENT_INSTALLATION.md)
- **Issues:** File an issue in the repository
- **Configuration Examples:** See `config.example.json`

## Security Notes

- Agent runs as non-privileged user (`scribe` on Linux, `LocalSystem` on Windows)
- Configuration files have restricted permissions (600)
- Use SSL/TLS for production deployments
- Keep agents updated with latest security patches
