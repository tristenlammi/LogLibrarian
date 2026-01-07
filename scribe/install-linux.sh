#!/bin/bash
set -e

# Scribe Agent - Linux Installation Script
# Compatible with: Ubuntu, Debian, CentOS, RHEL, Fedora, Arch, openSUSE, Alpine, Unraid

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Scribe Agent Installation Script   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}✗ Please run as root (sudo)${NC}"
    exit 1
fi

# Detect OS Distribution
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_NAME="${ID}"
        OS_VERSION="${VERSION_ID}"
        OS_PRETTY="${PRETTY_NAME}"
    elif [ -f /etc/redhat-release ]; then
        OS_NAME="rhel"
        OS_PRETTY=$(cat /etc/redhat-release)
    elif [ -f /etc/debian_version ]; then
        OS_NAME="debian"
        OS_PRETTY="Debian $(cat /etc/debian_version)"
    else
        OS_NAME="unknown"
        OS_PRETTY="Unknown Linux"
    fi
    
    # Detect Unraid specifically
    if [ -f /etc/unraid-version ]; then
        OS_NAME="unraid"
        OS_PRETTY="Unraid $(cat /etc/unraid-version 2>/dev/null || echo '')"
    fi
    
    echo -e "${GREEN}✓${NC} Detected OS: ${BLUE}${OS_PRETTY}${NC}"
}

# Get appropriate log file path based on OS
get_default_log_path() {
    case "$OS_NAME" in
        ubuntu|debian|linuxmint|pop|elementary|zorin)
            # Debian-based distros use syslog
            if [ -f /var/log/syslog ]; then
                DEFAULT_LOG_FILE="/var/log/syslog"
            elif [ -f /var/log/messages ]; then
                DEFAULT_LOG_FILE="/var/log/messages"
            else
                DEFAULT_LOG_FILE="/var/log/syslog"
            fi
            ;;
        centos|rhel|fedora|rocky|almalinux|oracle|amazon)
            # RHEL-based distros use messages
            DEFAULT_LOG_FILE="/var/log/messages"
            ;;
        arch|manjaro|endeavouros|artix)
            # Arch-based - typically uses journald, but messages fallback
            if [ -f /var/log/messages ]; then
                DEFAULT_LOG_FILE="/var/log/messages"
            else
                DEFAULT_LOG_FILE="/var/log/syslog"
            fi
            ;;
        opensuse*|suse|sles)
            # openSUSE uses messages
            DEFAULT_LOG_FILE="/var/log/messages"
            ;;
        alpine)
            # Alpine uses messages
            DEFAULT_LOG_FILE="/var/log/messages"
            ;;
        unraid)
            # Unraid uses syslog
            DEFAULT_LOG_FILE="/var/log/syslog"
            ;;
        gentoo)
            DEFAULT_LOG_FILE="/var/log/messages"
            ;;
        *)
            # Default fallback - check what exists
            if [ -f /var/log/syslog ]; then
                DEFAULT_LOG_FILE="/var/log/syslog"
            elif [ -f /var/log/messages ]; then
                DEFAULT_LOG_FILE="/var/log/messages"
            else
                DEFAULT_LOG_FILE="/var/log/syslog"
            fi
            ;;
    esac
    
    echo -e "${GREEN}✓${NC} Default log path: ${BLUE}${DEFAULT_LOG_FILE}${NC}"
}

# Run OS detection
detect_os
get_default_log_path

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        ARCH="amd64"
        ;;
    aarch64)
        ARCH="arm64"
        ;;
    *)
        echo -e "${RED}✗ Unsupported architecture: $ARCH${NC}"
        exit 1
        ;;
esac

echo -e "${GREEN}✓${NC} Architecture: $ARCH"

# Check for Go
if ! command -v go &> /dev/null; then
    echo -e "${YELLOW}⚠ Go not found. Building requires Go 1.21+${NC}"
    echo "  Install Go from: https://go.dev/doc/install"
    echo "  Or use a pre-built binary"
    exit 1
fi

GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
echo -e "${GREEN}✓${NC} Go version: $GO_VERSION"

# Get server host
echo ""
echo -e "${YELLOW}Configuration:${NC}"
read -p "Enter LogLibrarian server address (e.g., 192.168.1.100:8000): " SERVER_HOST
if [ -z "$SERVER_HOST" ]; then
    echo -e "${RED}✗ Server address is required${NC}"
    exit 1
fi

# Get API key (can be passed as environment variable or entered interactively)
if [ -z "$API_KEY" ]; then
    read -p "Enter LogLibrarian API key (from Settings > API Key): " API_KEY
    if [ -z "$API_KEY" ]; then
        echo -e "${RED}✗ API key is required for authentication${NC}"
        echo -e "  Get your API key from: Settings > API Key in the dashboard"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Using API key from environment variable"
fi

# Get agent name
read -p "Enter agent name [$(hostname)]: " AGENT_NAME
if [ -z "$AGENT_NAME" ]; then
    AGENT_NAME=$(hostname)
fi

# Get log file path (using detected default)
read -p "Enter log file path to monitor [${DEFAULT_LOG_FILE}]: " LOG_FILE
if [ -z "$LOG_FILE" ]; then
    LOG_FILE="${DEFAULT_LOG_FILE}"
fi

# Get security log path (optional - for antivirus/security scanner logs)
echo ""
echo -e "${BLUE}Security Log Collection (optional):${NC}"
echo "  If you have antivirus/security scanners, enter their log paths."
echo "  You can enter multiple paths separated by commas."
echo "  Examples:"
echo "    /var/log/clamav/clamav.log              - ClamAV"
echo "    /var/log/rkhunter.log                   - Rootkit Hunter"
echo "    /var/log/fail2ban.log                   - Fail2ban"
echo "    /var/log/clamav/clamav.log,/var/log/fail2ban.log - Multiple"
echo "    (leave blank to skip)"
read -p "Security log path(s) []: " SECURITY_LOG_INPUT

# Convert comma-separated input to JSON array
if [ -z "$SECURITY_LOG_INPUT" ]; then
    SECURITY_LOG_PATHS="[]"
else
    # Split by comma and build JSON array
    SECURITY_LOG_PATHS="["
    first=true
    IFS=',' read -ra PATHS <<< "$SECURITY_LOG_INPUT"
    for path in "${PATHS[@]}"; do
        path=$(echo "$path" | xargs)  # trim whitespace
        if [ -n "$path" ]; then
            if [ "$first" = true ]; then
                first=false
            else
                SECURITY_LOG_PATHS+=","
            fi
            SECURITY_LOG_PATHS+="\"$path\""
        fi
    done
    SECURITY_LOG_PATHS+="]"
fi

# Verify log file exists
if [ ! -f "$LOG_FILE" ]; then
    echo -e "${YELLOW}⚠ Warning: Log file does not exist yet: ${LOG_FILE}${NC}"
    read -p "Continue anyway? (Y/n): " CONTINUE
    if [ "$CONTINUE" = "n" ] || [ "$CONTINUE" = "N" ]; then
        echo -e "${YELLOW}Other common log locations:${NC}"
        echo "  /var/log/syslog   - Ubuntu/Debian"
        echo "  /var/log/messages - CentOS/RHEL/Fedora"
        echo "  /var/log/kern.log - Kernel messages"
        echo "  /var/log/auth.log - Authentication logs"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}Building agent...${NC}"

# Build the agent
cd "$(dirname "$0")"
go build -o scribe-agent -ldflags="-s -w" .

if [ ! -f "scribe-agent" ]; then
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Build successful"

# Create directories
echo ""
echo -e "${GREEN}Creating directories...${NC}"
mkdir -p /opt/scribe
mkdir -p /etc/scribe
mkdir -p /var/log/scribe

# Create scribe user
if ! id -u scribe &>/dev/null; then
    echo -e "${GREEN}Creating scribe user...${NC}"
    useradd -r -s /bin/false scribe
    echo -e "${GREEN}✓${NC} User created"
else
    echo -e "${GREEN}✓${NC} User already exists"
fi

# Copy binary
echo -e "${GREEN}Installing binary...${NC}"
cp scribe-agent /opt/scribe/
chmod +x /opt/scribe/scribe-agent
chown scribe:scribe /opt/scribe/scribe-agent
echo -e "${GREEN}✓${NC} Binary installed to /opt/scribe/scribe-agent"

# Create configuration file
echo -e "${GREEN}Creating configuration...${NC}"
cat > /etc/scribe/config.json <<EOF
{
  "server_host": "${SERVER_HOST}",
  "agent_name": "${AGENT_NAME}",
  "api_key": "${API_KEY}",
  "log_file": "${LOG_FILE}",
  "security_log_paths": ${SECURITY_LOG_PATHS},
  "metrics_interval": 60,
  "log_batch_size": 50,
  "log_batch_interval": 5,
  "ssl_enabled": false,
  "ssl_verify": true,
  "agent_id": ""
}
EOF

chown scribe:scribe /etc/scribe/config.json
chmod 600 /etc/scribe/config.json
echo -e "${GREEN}✓${NC} Configuration saved to /etc/scribe/config.json"

# Create systemd service
echo -e "${GREEN}Creating systemd service...${NC}"
cat > /etc/systemd/system/scribe.service <<EOF
[Unit]
Description=Scribe Monitoring Agent
Documentation=https://github.com/your-org/scribe
After=network-online.target
Wants=network-online.target

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
SyslogIdentifier=scribe

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/scribe

[Install]
WantedBy=multi-user.target
EOF

# Set permissions
chown -R scribe:scribe /opt/scribe
chown -R scribe:scribe /var/log/scribe

# Reload systemd
systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd service created"

# Enable and start service
echo ""
read -p "Start Scribe agent now? (Y/n): " START_NOW
if [ -z "$START_NOW" ] || [ "$START_NOW" = "Y" ] || [ "$START_NOW" = "y" ]; then
    systemctl enable scribe
    systemctl start scribe
    
    echo ""
    echo -e "${GREEN}✓${NC} Service started and enabled"
    
    # Show status
    sleep 2
    echo ""
    echo -e "${YELLOW}Service Status:${NC}"
    systemctl status scribe --no-pager -l
else
    systemctl enable scribe
    echo -e "${GREEN}✓${NC} Service enabled (run 'sudo systemctl start scribe' to start)"
fi

# Installation summary
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Installation Complete! 🎉        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "Binary:        /opt/scribe/scribe-agent"
echo -e "Config:        /etc/scribe/config.json"
echo -e "Logs:          /var/log/scribe/"
echo -e "Service:       scribe.service"
echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo -e "  Status:      sudo systemctl status scribe"
echo -e "  Logs:        sudo journalctl -u scribe -f"
echo -e "  Restart:     sudo systemctl restart scribe"
echo -e "  Stop:        sudo systemctl stop scribe"
echo -e "  Edit config: sudo nano /etc/scribe/config.json"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo -e "  1. Verify agent appears in LogLibrarian dashboard"
echo -e "  2. Check logs: sudo journalctl -u scribe -f"
echo -e "  3. Edit /etc/scribe/config.json to customize settings"
echo ""
