#!/bin/bash
#
# Tram Monitoring System - Uninstall Script
#
# Removes ros2-monitor from systemd and optionally deletes app files.
# Run directly on the target machine (tram).
#
# Usage:
#   ./uninstall.sh              # Remove systemd service only
#   ./uninstall.sh --purge      # Also remove /opt/ros2-monitor
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SERVICE_NAME="ros2-monitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
APP_DIR="/opt/ros2-monitor"
PURGE=0

if [ "$1" = "--purge" ]; then
    PURGE=1
fi

log_info "Uninstalling ${SERVICE_NAME}..."

# --- Stop running processes ---

# Stop systemd service if active
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    log_info "Stopping ${SERVICE_NAME} service..."
    sudo systemctl stop "$SERVICE_NAME"
fi

# Kill any orphan uvicorn processes
REMAINING=$(pgrep -f "uvicorn server.main:app" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    log_warn "Found running uvicorn processes, stopping..."
    pkill -f "uvicorn server.main:app" 2>/dev/null || true
    sleep 1
fi

# --- Remove systemd service ---

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    log_info "Disabling ${SERVICE_NAME} service..."
    sudo systemctl disable "$SERVICE_NAME"
fi

if [ -f "$SERVICE_FILE" ]; then
    log_info "Removing ${SERVICE_FILE}..."
    sudo rm -f "$SERVICE_FILE"
    sudo systemctl daemon-reload
    log_info "Systemd service removed."
else
    log_warn "Service file ${SERVICE_FILE} not found — already removed or was never installed."
fi

# --- Remove PID file if exists ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="${PROJECT_DIR}/logs/ros2-monitor.pid"
if [ -f "$PID_FILE" ]; then
    rm -f "$PID_FILE"
    log_info "Removed PID file."
fi

# --- Purge app directory ---

if [ "$PURGE" -eq 1 ]; then
    if [ -d "$APP_DIR" ]; then
        log_info "Removing ${APP_DIR}..."
        sudo rm -rf "$APP_DIR"
        log_info "App directory removed."
    else
        log_warn "${APP_DIR} not found — skipping."
    fi
fi

# --- Done ---

echo ""
log_info "=========================================="
log_info "Uninstall complete!"
log_info "=========================================="
if [ "$PURGE" -eq 0 ]; then
    echo ""
    log_info "App files in ${APP_DIR} were kept."
    log_info "To also remove them, run: $0 --purge"
fi
echo ""
