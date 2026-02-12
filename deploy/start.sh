#!/bin/bash
#
# ROS2 Node Manager - Start Script
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

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

cd "$PROJECT_DIR"

# Check virtual environment
if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment not found. Run deployment first."
    exit 1
fi

# Activate venv
source .venv/bin/activate

# Get host IP for display
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    # Background mode
    log_info "Starting ros2-monitor in background..."

    # Kill existing process if running
    pkill -f "uvicorn server.main:app" 2>/dev/null || true
    sleep 1

    # Start with nohup
    nohup uvicorn server.main:app --host 0.0.0.0 --port 8080 > /tmp/ros2-monitor.log 2>&1 &
    PID=$!

    sleep 2

    if ps -p $PID > /dev/null 2>&1; then
        log_info "Server started with PID: $PID"
        log_info "Access UI at: http://${HOST_IP}:8080"
        echo ""
        log_info "View logs: tail -f /tmp/ros2-monitor.log"
        log_info "Stop server: pkill -f 'uvicorn server.main:app'"
    else
        echo "Error: Server failed to start. Check /tmp/ros2-monitor.log"
        exit 1
    fi
else
    # Foreground mode
    log_info "Starting ros2-monitor..."
    log_info "Access UI at: http://${HOST_IP}:8080"
    log_info "Press Ctrl+C to stop"
    echo ""

    exec uvicorn server.main:app --host 0.0.0.0 --port 8080
fi
