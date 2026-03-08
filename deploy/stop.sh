#!/bin/bash
#
# Tram Monitoring System - Stop Script
#
# Stops the background ros2-monitor process.
#
# Usage:
#   ./stop.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

LOG_DIR="${PROJECT_DIR}/logs"
PID_FILE="${LOG_DIR}/ros2-monitor.pid"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

STOPPED=0

# Stop by PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        log_info "Stopping ros2-monitor (PID: ${PID})..."
        kill "$PID"
        sleep 1
        if ps -p "$PID" > /dev/null 2>&1; then
            log_warn "Process still running, sending SIGKILL..."
            kill -9 "$PID"
        fi
        STOPPED=1
    else
        log_warn "PID ${PID} not running (stale PID file)"
    fi
    rm -f "$PID_FILE"
fi

# Fallback: kill by process name
REMAINING=$(pgrep -f "uvicorn server.main:app" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    log_warn "Found orphan uvicorn processes, killing..."
    pkill -f "uvicorn server.main:app" 2>/dev/null || true
    STOPPED=1
fi

if [ "$STOPPED" -eq 1 ]; then
    log_info "ros2-monitor stopped."
else
    log_warn "ros2-monitor was not running."
fi

