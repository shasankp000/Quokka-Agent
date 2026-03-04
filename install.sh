#!/bin/bash
#
# Quokka Agent Installer
# Installs the agent as a systemd service that runs on startup
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
AGENT_NAME="quokka-agent"
INSTALL_DIR="/opt/quokka-agent"
SERVICE_USER="quokka"
SERVICE_GROUP="quokka"
CONFIG_DIR="/etc/quokka"
DATA_DIR="/var/lib/quokka"
LOG_DIR="/var/log/quokka"

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           🦘 Quokka Agent Installer                       ║"
echo "║     Local Automation Agent with Telegram Control          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo ./install.sh${NC}"
    exit 1
fi

# Check for systemd
if [ ! -d /run/systemd/system ]; then
    echo -e "${RED}This script requires systemd. Your system doesn't appear to use systemd.${NC}"
    exit 1
fi

# Check for Python 3.10+
echo -e "${BLUE}Checking prerequisites...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is not installed. Please install Python 3.10 or higher.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo -e "${RED}Python 3.10 or higher is required. You have Python $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"

# Check for pip
if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
    echo -e "${RED}pip is not installed. Please install pip.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ pip found${NC}"

# Check for Ollama (optional but recommended)
echo -e "${BLUE}Checking for Ollama...${NC}"
if command -v ollama &> /dev/null; then
    echo -e "${GREEN}✓ Ollama found${NC}"
    # Check if ollama is running
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Ollama is running${NC}"
    else
        echo -e "${YELLOW}⚠ Ollama is installed but not running. Start it with: ollama serve${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Ollama not found. Install from https://ollama.ai for local LLM support${NC}"
    echo -e "${YELLOW}  You can still use OpenRouter as fallback${NC}"
fi

# Ask for confirmation
echo ""
echo -e "${BLUE}Installation Details:${NC}"
echo "  Install Directory: $INSTALL_DIR"
echo "  Config Directory:  $CONFIG_DIR"
echo "  Data Directory:    $DATA_DIR"
echo "  Log Directory:     $LOG_DIR"
echo "  Service User:      $SERVICE_USER"
echo ""
read -p "Continue with installation? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Installation cancelled.${NC}"
    exit 0
fi

# Create directories
echo -e "${BLUE}Creating directories...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"/{sessions,tasks,logs/audit}
mkdir -p "$LOG_DIR"

# Create service user
echo -e "${BLUE}Creating service user...${NC}"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -d "$DATA_DIR" "$SERVICE_USER"
    echo -e "${GREEN}✓ Created user $SERVICE_USER${NC}"
else
    echo -e "${YELLOW}⚠ User $SERVICE_USER already exists${NC}"
fi

# Copy agent files
echo -e "${BLUE}Installing agent files...${NC}"
EXTRACT_DIR=""

# Determine source location
if [ -d "$SCRIPT_DIR/quokka" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    # Source is extracted flat structure (quokka folder at root level)
    echo -e "${BLUE}Copying from extracted archive...${NC}"
    cp -r "$SCRIPT_DIR/quokka" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true
    [ -d "$SCRIPT_DIR/config" ] && cp -r "$SCRIPT_DIR/config" "$INSTALL_DIR/"
    
elif [ -f "$SCRIPT_DIR/quokka-agent.zip" ]; then
    # Source is ZIP file
    echo -e "${BLUE}Extracting from ZIP file...${NC}"
    EXTRACT_DIR=$(mktemp -d)
    unzip -o "$SCRIPT_DIR/quokka-agent.zip" -d "$EXTRACT_DIR"
    
    # Check structure - quokka folder should be at root of ZIP
    if [ -d "$EXTRACT_DIR/quokka" ]; then
        cp -r "$EXTRACT_DIR/quokka" "$INSTALL_DIR/"
        [ -f "$EXTRACT_DIR/pyproject.toml" ] && cp "$EXTRACT_DIR/pyproject.toml" "$INSTALL_DIR/"
        [ -f "$EXTRACT_DIR/requirements.txt" ] && cp "$EXTRACT_DIR/requirements.txt" "$INSTALL_DIR/"
        [ -f "$EXTRACT_DIR/README.md" ] && cp "$EXTRACT_DIR/README.md" "$INSTALL_DIR/"
        [ -d "$EXTRACT_DIR/config" ] && cp -r "$EXTRACT_DIR/config" "$INSTALL_DIR/"
    else
        echo -e "${RED}Could not find quokka folder in ZIP${NC}"
        echo -e "${YELLOW}Contents of extract directory:${NC}"
        ls -la "$EXTRACT_DIR"
        rm -rf "$EXTRACT_DIR"
        exit 1
    fi
    
    # Cleanup
    rm -rf "$EXTRACT_DIR"
    
else
    echo -e "${RED}Could not find agent files.${NC}"
    echo -e "${YELLOW}Expected one of:${NC}"
    echo "  - $SCRIPT_DIR/quokka/ (directory with pyproject.toml)"
    echo "  - $SCRIPT_DIR/quokka-agent.zip (zip file)"
    echo ""
    echo -e "${YELLOW}Current directory contents:${NC}"
    ls -la "$SCRIPT_DIR"
    exit 1
fi

echo -e "${GREEN}✓ Agent files installed${NC}"

# Verify installation
if [ ! -f "$INSTALL_DIR/quokka/agent.py" ]; then
    echo -e "${RED}Installation verification failed. quokka/agent.py not found.${NC}"
    echo -e "${YELLOW}Contents of $INSTALL_DIR:${NC}"
    ls -la "$INSTALL_DIR"
    exit 1
fi

# Create virtual environment
echo -e "${BLUE}Creating virtual environment...${NC}"
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
echo -e "${GREEN}✓ Virtual environment created${NC}"

# Install dependencies
echo -e "${BLUE}Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -e "$INSTALL_DIR"
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Deactivate virtual environment
deactivate

# Copy/create config file (always create fresh config with absolute paths for service)
echo -e "${BLUE}Setting up configuration...${NC}"

# Check if config exists and backup
if [ -f "$CONFIG_DIR/config.yaml" ]; then
    echo -e "${YELLOW}Backing up existing config to $CONFIG_DIR/config.yaml.bak${NC}"
    cp "$CONFIG_DIR/config.yaml" "$CONFIG_DIR/config.yaml.bak"
fi

# Always create fresh config with absolute paths for systemd service
cat > "$CONFIG_DIR/config.yaml" << 'EOF'
# Quokka Agent Configuration
environment: production

telegram:
  token: ""
  allowed_users: []
  admin_users: []
  polling_timeout: 30
  polling_interval: 0.5

ollama:
  base_url: "http://localhost:11434"
  model: "llama3.1:8b"
  timeout: 120
  context_window: 8192
  temperature: 0.7

openrouter:
  api_key: ""
  base_url: "https://openrouter.ai/api/v1"
  model: "anthropic/claude-3.5-sonnet"
  timeout: 180
  temperature: 0.7

router:
  complexity_threshold: 0.5
  always_local_tools:
    - shell_exec
    - file_ops
    - obsidian_read
    - obsidian_write
  always_cloud_patterns:
    - complex reasoning
    - code review
    - detailed analysis

security:
  enabled: true
  dry_run_default: false
  allowed_commands:
    - ls
    - cat
    - head
    - tail
    - grep
    - find
    - pwd
    - echo
    - git
    - python
    - pip
    - npm
    - node
    - bun
    - code
    - nvim
    - mkdir
    - touch
    - cp
    - mv
    - rm
    - chmod
  blocked_commands:
    - sudo
    - su
    - passwd
    - chmod 777
    - dd
    - mkfs
  allowed_directories:
    - "~"
  blocked_directories:
    - /etc/passwd
    - /etc/shadow
    - ~/.ssh
    - ~/.gnupg
  max_command_timeout: 300
  audit_log: true

executor:
  max_concurrent_tasks: 3
  default_timeout: 60
  containerized: false
  output_poll_interval: 0.5

memory:
  session_dir: "/var/lib/quokka/sessions"
  task_queue_file: "/var/lib/quokka/tasks/queue.json"
  max_session_messages: 100
  session_ttl_hours: 24

multimodal:
  ocr_enabled: true
  ocr_language: "eng"
  pdf_enabled: true
  max_image_size_mb: 10
  max_pdf_size_mb: 50

logging:
  level: "INFO"
  file: "/var/log/quokka/agent.log"
  max_size_mb: 10
  backup_count: 5
EOF
echo -e "${GREEN}✓ Configuration file created at $CONFIG_DIR/config.yaml${NC}"

# Create environment file
echo -e "${BLUE}Creating environment file...${NC}"
cat > "$CONFIG_DIR/environment" << 'EOF'
# Quokka Agent Environment Variables
# Uncomment and set as needed

# Telegram bot token (required)
# QUOKKA_TELEGRAM__TOKEN=your_token_here

# OpenRouter API key (optional, for cloud LLM fallback)
# QUOKKA_OPENROUTER__API_KEY=your_key_here

# Obsidian vault path (optional)
# OBSIDIAN_VAULT=/path/to/your/vault

# Config file path
QUOKKA_CONFIG=/etc/quokka/config.yaml
EOF
echo -e "${GREEN}✓ Environment file created at $CONFIG_DIR/environment${NC}"

# Create systemd service file
echo -e "${BLUE}Creating systemd service...${NC}"
cat > /etc/systemd/system/quokka-agent.service << EOF
[Unit]
Description=Quokka Agent - Local Automation Assistant
Documentation=https://github.com/quokka-agent
After=network.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
Environment="QUOKKA_CONFIG=$CONFIG_DIR/config.yaml"
EnvironmentFile=-$CONFIG_DIR/environment
ExecStart=$INSTALL_DIR/venv/bin/python -m quokka
Restart=always
RestartSec=10
TimeoutStartSec=30
TimeoutStopSec=30

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DATA_DIR $LOG_DIR
ReadOnlyPaths=$INSTALL_DIR $CONFIG_DIR
PrivateTmp=true

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=quokka-agent

[Install]
WantedBy=multi-user.target
EOF
echo -e "${GREEN}✓ Systemd service created${NC}"

# Set permissions
echo -e "${BLUE}Setting permissions...${NC}"
chown -R $SERVICE_USER:$SERVICE_GROUP "$INSTALL_DIR"
chown -R $SERVICE_USER:$SERVICE_GROUP "$DATA_DIR"
chown -R $SERVICE_USER:$SERVICE_GROUP "$LOG_DIR"
chown -R root:$SERVICE_GROUP "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"
chmod 640 "$CONFIG_DIR/config.yaml"
chmod 640 "$CONFIG_DIR/environment"
echo -e "${GREEN}✓ Permissions set${NC}"

# Reload systemd
echo -e "${BLUE}Reloading systemd daemon...${NC}"
systemctl daemon-reload

# Enable service
echo -e "${BLUE}Enabling service...${NC}"
systemctl enable quokka-agent.service
echo -e "${GREEN}✓ Service enabled${NC}"

# Summary
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✅ Installation Complete!                    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo -e "1. ${YELLOW}Configure your Telegram bot token:${NC}"
echo "   sudo nano $CONFIG_DIR/config.yaml"
echo "   Or:   sudo nano $CONFIG_DIR/environment"
echo ""
echo -e "2. ${YELLOW}Make sure Ollama is running (for local LLM):${NC}"
echo "   ollama serve"
echo "   ollama pull llama3.1:8b"
echo ""
echo -e "3. ${YELLOW}Start the service:${NC}"
echo "   sudo systemctl start quokka-agent"
echo ""
echo -e "4. ${YELLOW}Check status:${NC}"
echo "   sudo systemctl status quokka-agent"
echo ""
echo -e "5. ${YELLOW}View logs:${NC}"
echo "   sudo journalctl -u quokka-agent -f"
echo ""
echo -e "${BLUE}Useful Commands:${NC}"
echo "   Start:   sudo systemctl start quokka-agent"
echo "   Stop:    sudo systemctl stop quokka-agent"
echo "   Restart: sudo systemctl restart quokka-agent"
echo "   Status:  sudo systemctl status quokka-agent"
echo "   Logs:    sudo journalctl -u quokka-agent -f"
echo ""
read -p "Start the service now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Starting Quokka Agent...${NC}"
    systemctl start quokka-agent
    sleep 2
    systemctl status quokka-agent --no-pager || true
    echo ""
    echo -e "${YELLOW}Check logs with: sudo journalctl -u quokka-agent -f${NC}"
fi

echo ""
echo -e "${GREEN}🦘 Quokka Agent installation complete!${NC}"
