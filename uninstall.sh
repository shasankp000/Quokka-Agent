#!/bin/bash
#
# Quokka Agent Uninstaller
# Removes the agent service and files
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
INSTALL_DIR="/opt/quokka-agent"
CONFIG_DIR="/etc/quokka"
DATA_DIR="/var/lib/quokka"
LOG_DIR="/var/log/quokka"
SERVICE_USER="quokka"

echo -e "${RED}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           🦘 Quokka Agent Uninstaller                     ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo ./uninstall.sh${NC}"
    exit 1
fi

echo -e "${YELLOW}This will remove:${NC}"
echo "  - Service: quokka-agent"
echo "  - Install Directory: $INSTALL_DIR"
echo "  - Config Directory: $CONFIG_DIR"
echo "  - Data Directory: $DATA_DIR"
echo "  - Log Directory: $LOG_DIR"
echo "  - User: $SERVICE_USER"
echo ""
echo -e "${RED}WARNING: All data including session history and logs will be deleted!${NC}"
echo ""
read -p "Are you sure you want to uninstall? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Uninstall cancelled.${NC}"
    exit 0
fi

# Stop service
echo -e "${BLUE}Stopping service...${NC}"
systemctl stop quokka-agent 2>/dev/null || true
systemctl disable quokka-agent 2>/dev/null || true
echo -e "${GREEN}✓ Service stopped and disabled${NC}"

# Remove service file
echo -e "${BLUE}Removing service file...${NC}"
rm -f /etc/systemd/system/quokka-agent.service
systemctl daemon-reload
echo -e "${GREEN}✓ Service file removed${NC}"

# Ask about keeping config/data
read -p "Keep configuration and data? (y/N) " -n 1 -r
echo
KEEP_DATA=$REPLY

if [[ ! $KEEP_DATA =~ ^[Yy]$ ]]; then
    # Remove directories
    echo -e "${BLUE}Removing directories...${NC}"
    rm -rf "$INSTALL_DIR"
    rm -rf "$CONFIG_DIR"
    rm -rf "$DATA_DIR"
    rm -rf "$LOG_DIR"
    echo -e "${GREEN}✓ Directories removed${NC}"
else
    # Remove only install directory
    echo -e "${BLUE}Removing install directory (keeping config/data)...${NC}"
    rm -rf "$INSTALL_DIR"
    echo -e "${GREEN}✓ Install directory removed${NC}"
    echo -e "${YELLOW}Config preserved at: $CONFIG_DIR${NC}"
    echo -e "${YELLOW}Data preserved at: $DATA_DIR${NC}"
fi

# Remove user (if no files owned)
echo -e "${BLUE}Removing service user...${NC}"
if id "$SERVICE_USER" &>/dev/null; then
    # Check if user owns any files
    if find / -user "$SERVICE_USER" 2>/dev/null | head -1 | grep -q .; then
        echo -e "${YELLOW}⚠ User $SERVICE_USER still owns files, not removing${NC}"
    else
        userdel "$SERVICE_USER" 2>/dev/null || true
        echo -e "${GREEN}✓ User removed${NC}"
    fi
fi

echo ""
echo -e "${GREEN}✅ Quokka Agent uninstalled successfully!${NC}"
echo ""
if [[ $KEEP_DATA =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}To completely remove, run:${NC}"
    echo "  sudo rm -rf $CONFIG_DIR $DATA_DIR $LOG_DIR"
fi
