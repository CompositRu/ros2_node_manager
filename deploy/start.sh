#!/bin/bash
#
# Tram Monitoring System - Start Script
#
# Run this script on the server where ros2-monitor is deployed.
#
# Usage:
#   ./start.sh [--background]
#
# Options:
#   --background, -b    Run in background with nohup
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/ros2-monitor.log"
PID_FILE="${LOG_DIR}/ros2-monitor.pid"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

cd "$PROJECT_DIR"

# Check virtual environment
if [ ! -d ".venv" ]; then
    log_error "Virtual environment not found. Run deployment first."
    exit 1
fi

# Ensure logs directory exists
mkdir -p "$LOG_DIR"

# Activate venv
source .venv/bin/activate

# Get host IP for display (prefer ROS2_MONITOR_HOST if set, e.g. by start-remote.sh)
HOST_IP="${ROS2_MONITOR_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")}"

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    # Kill existing process by PID file
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            log_warn "Stopping existing process (PID: ${OLD_PID})..."
            kill "$OLD_PID"
            sleep 1
        fi
        rm -f "$PID_FILE"
    fi

    # Fallback: kill by process name
    pkill -f "uvicorn server.main:app" 2>/dev/null || true
    sleep 1

    # Write start marker to log
    echo "" >> "$LOG_FILE"
    echo "=== Started at $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG_FILE"

    # Start with nohup, append logs
    nohup uvicorn server.main:app --host 0.0.0.0 --port 8080 >> "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"

    sleep 2

    if ps -p "$PID" > /dev/null 2>&1; then
        log_info "Server started (PID: ${PID})"
        log_info "Access UI at:  http://${HOST_IP}:8080"
        echo ""
        log_info "View logs:  tail -f ${LOG_FILE}"
        log_info "Stop:       $(dirname "$0")/stop.sh"
    else
        log_error "Server failed to start. Last log entries:"
        echo "---"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
else
    # Foreground mode
    log_info "Starting ros2-monitor..."
    log_info "Access UI at: http://${HOST_IP}:8080"
    log_info "Log file:     ${LOG_FILE}"
    log_info "Press Ctrl+C to stop"
    echo ""

    exec uvicorn server.main:app --host 0.0.0.0 --port 8080 2>&1 | tee -a "$LOG_FILE"
fi
