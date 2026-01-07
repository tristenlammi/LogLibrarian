# Scribe Agent - Deployment Checklist

Use this checklist when deploying the Scribe agent to new systems.

## Pre-Deployment

- [ ] **Backend Running**: Confirm LogLibrarian backend is accessible
  ```bash
  curl http://your-server:8000/health
  ```

- [ ] **Network Access**: Verify target system can reach backend
  - HTTP/HTTPS port 8000
  - WebSocket connections allowed
  - Firewall rules configured

- [ ] **System Requirements Met**:
  - [ ] Linux: systemd-based OS (Ubuntu 18.04+, CentOS 7+, etc.)
  - [ ] Windows: Windows 10/Server 2016 or newer
  - [ ] Minimum: 256MB RAM, 100MB disk space
  - [ ] Go 1.21+ installed (if building from source)

- [ ] **Log Files Accessible**: Identify which log files to monitor
  - Linux common paths: `/var/log/syslog`, `/var/log/messages`, `/var/log/nginx/`
  - Windows: Event logs or application log files

---

## Installation - Linux

### 1. Transfer Files

- [ ] Copy `scribe` directory to target system
  ```bash
  scp -r scribe/ user@target-host:/tmp/
  ```

### 2. Run Installation

- [ ] SSH to target system
  ```bash
  ssh user@target-host
  ```

- [ ] Navigate to directory
  ```bash
  cd /tmp/scribe
  ```

- [ ] Run install script
  ```bash
  sudo ./install-linux.sh
  ```

- [ ] Enter configuration when prompted:
  - Server address: `your-server:8000`
  - Agent name: `[hostname or custom name]`
  - Log file path: `/var/log/syslog`

### 3. Verify Installation

- [ ] Check service status
  ```bash
  sudo systemctl status scribe
  ```

- [ ] View logs for errors
  ```bash
  sudo journalctl -u scribe -n 50
  ```

- [ ] Check WebSocket connection
  ```bash
  sudo journalctl -u scribe | grep -i "websocket connected"
  ```

### 4. Confirm in Dashboard

- [ ] Open LogLibrarian dashboard
- [ ] Verify agent appears in agents list
- [ ] Check metrics are updating
- [ ] Verify logs are streaming

---

## Installation - Windows

### 1. Transfer Files

- [ ] Copy `scribe` directory to target system
  - Use RDP file transfer, network share, or SCP

### 2. Run Installation

- [ ] Open PowerShell as Administrator
  ```powershell
  cd C:\path\to\scribe
  ```

- [ ] Run install script
  ```powershell
  .\install-windows.ps1
  ```

- [ ] Enter configuration when prompted:
  - Server address: `your-server:8000`
  - Agent name: `[hostname or custom name]`
  - Log file path: `C:\Windows\System32\winevt\Logs\Application.evtx`

### 3. Verify Installation

- [ ] Check service status
  ```powershell
  Get-Service Scribe
  ```

- [ ] View logs for errors
  ```powershell
  Get-Content "C:\ProgramData\Scribe\logs\stdout.log" -Tail 50
  ```

- [ ] Check for WebSocket connection
  ```powershell
  Select-String -Path "C:\ProgramData\Scribe\logs\stdout.log" -Pattern "websocket connected"
  ```

### 4. Confirm in Dashboard

- [ ] Open LogLibrarian dashboard
- [ ] Verify agent appears in agents list
- [ ] Check metrics are updating
- [ ] Verify logs are streaming

---

## Post-Deployment

### Configuration Tuning

- [ ] **Adjust metrics interval** based on monitoring needs
  - High-frequency: `"metrics_interval": 10` (every 10 seconds)
  - Standard: `"metrics_interval": 60` (every minute)
  - Low-resource: `"metrics_interval": 300` (every 5 minutes)

- [ ] **Optimize log batching** for your log volume
  - High volume: `"log_batch_size": 100, "log_batch_interval": 2`
  - Low volume: `"log_batch_size": 20, "log_batch_interval": 10`

- [ ] **Enable SSL** for production
  ```json
  {
    "ssl_enabled": true,
    "ssl_verify": true
  }
  ```

### Monitoring Setup

- [ ] Set up alerts for agent offline
- [ ] Configure log retention policies
- [ ] Document agent location and purpose
- [ ] Add to inventory/CMDB

### Documentation

- [ ] Document server-specific configuration
- [ ] Note any custom log paths
- [ ] Record agent ID for reference
- [ ] Update team wiki/runbook

---

## Troubleshooting

### Agent Not Appearing

**Check network connectivity:**
```bash
# Linux
telnet your-server 8000

# Windows
Test-NetConnection -ComputerName your-server -Port 8000
```

**Check service logs:**
```bash
# Linux
sudo journalctl -u scribe -f

# Windows
Get-Content "C:\ProgramData\Scribe\logs\stdout.log" -Tail 20 -Wait
```

### WebSocket Connection Failures

- [ ] Verify backend is running: `curl http://your-server:8000/health`
- [ ] Check firewall allows WebSocket (ws://) connections
- [ ] Verify no proxy blocking WebSocket upgrades
- [ ] Check SSL certificate if using `ssl_enabled: true`

### High Resource Usage

- [ ] Increase `metrics_interval` to reduce CPU usage
- [ ] Increase `log_batch_interval` to reduce network traffic
- [ ] Check for log file growth/rotation issues
- [ ] Monitor process count and memory usage in dashboard

### Permission Errors

**Linux:**
```bash
# Check file permissions
ls -la /var/log/syslog

# Add scribe to log group if needed
sudo usermod -a -G adm scribe
sudo systemctl restart scribe
```

**Windows:**
- Grant scribe service read access to log files
- Check Event Viewer for permission errors

---

## Rollback Procedure

### Linux

```bash
sudo systemctl stop scribe
sudo systemctl disable scribe
sudo rm /etc/systemd/system/scribe.service
sudo systemctl daemon-reload
sudo rm -rf /opt/scribe /etc/scribe
```

### Windows

```powershell
Stop-Service Scribe
sc.exe delete Scribe
Remove-Item "C:\Program Files\Scribe" -Recurse -Force
Remove-Item "C:\ProgramData\Scribe" -Recurse -Force
```

---

## Deployment Automation

### Ansible Playbook (Linux)

```yaml
- name: Deploy Scribe Agent
  hosts: all
  become: yes
  vars:
    scribe_server: "loglibrarian.example.com:8000"
    scribe_log_file: "/var/log/syslog"
  
  tasks:
    - name: Copy scribe directory
      copy:
        src: scribe/
        dest: /tmp/scribe/
        mode: '0755'
    
    - name: Run installation script
      shell: |
        cd /tmp/scribe
        ./install-linux.sh
      environment:
        SERVER_HOST: "{{ scribe_server }}"
        LOG_FILE: "{{ scribe_log_file }}"
```

### PowerShell Remoting (Windows)

```powershell
$servers = @("server1", "server2", "server3")
$serverHost = "loglibrarian.example.com:8000"

foreach ($server in $servers) {
    Invoke-Command -ComputerName $server -ScriptBlock {
        param($host)
        
        # Copy files
        Copy-Item -Path "\\share\scribe" -Destination "C:\Temp\" -Recurse
        
        # Run installation
        cd C:\Temp\scribe
        .\install-windows.ps1 -ServerHost $host -NoStart
        
        # Start service
        Start-Service Scribe
    } -ArgumentList $serverHost
}
```

---

## Sign-Off

**Deployed by:** _______________  
**Date:** _______________  
**System:** _______________  
**Agent Name:** _______________  
**Agent ID:** _______________  
**Notes:** _______________
