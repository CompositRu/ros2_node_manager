#!/bin/bash
#
# Tram Monitoring System - Local Start Script
#
# Sets up environment, builds frontend, and starts the server.
# With --fast flag, skips setup and just starts.
#
# Usage:
#   ./start.sh              # Full setup + build + start
#   ./start.sh -f           # Fast start (skip setup/build)
#   ./start.sh --background # Full setup + build + start in background
#   ./start.sh -f -b        # Fast start in background
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load nvm if available (for correct Node.js version)
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/ros2-monitor.log"
PID_FILE="${LOG_DIR}/ros2-monitor.pid"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Parse flags
FAST=0
BACKGROUND=0
for arg in "$@"; do
    case "$arg" in
        -f|--fast) FAST=1 ;;
        -b|--background) BACKGROUND=1 ;;
    esac
done

# === Setup (skipped with --fast) ===

if [ "$FAST" -eq 0 ]; then
    # Python virtual environment
    if [ ! -d ".venv" ]; then
        log_info "Creating virtual environment..."
        python3 -m venv .venv
    fi
    source .venv/bin/activate

    log_info "Installing Python dependencies..."
    pip install --upgrade pip -q
    pip install -r server/requirements.txt -q
    log_info "Python environment ready"

    # Frontend build
    log_info "Building frontend..."
    cd web
    if [ ! -d "node_modules" ]; then
        log_info "Installing npm dependencies..."
        npm install
    fi
    npm run build
    cd ..

    if [ ! -d "web/dist" ]; then
        log_error "Frontend build failed - web/dist not found"
        exit 1
    fi
    log_info "Frontend build complete"
else
    # Fast mode: just activate venv
    if [ ! -d ".venv" ]; then
        log_error "Virtual environment not found. Run without --fast first."
        exit 1
    fi
    source .venv/bin/activate

    if [ ! -d "web/dist" ]; then
        log_warn "web/dist not found — frontend not built. Run without --fast to build."
    fi
fi

# === Start ===

mkdir -p "$LOG_DIR"

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")"

if [ "$BACKGROUND" -eq 1 ]; then
    # Kill existing process
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            log_warn "Stopping existing process (PID: ${OLD_PID})..."
            kill "$OLD_PID"
            sleep 1
        fi
        rm -f "$PID_FILE"
    fi
    pkill -f "uvicorn server.main:app" 2>/dev/null || true
    sleep 1

    echo "" >> "$LOG_FILE"
    echo "=== Started at $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG_FILE"

    nohup uvicorn server.main:app --host 0.0.0.0 --port 8080 >> "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"

    sleep 2

    if ps -p "$PID" > /dev/null 2>&1; then
        log_info "Server started (PID: ${PID})"
        log_info "Access UI at:  http://${HOST_IP}:8080"
        echo ""
        log_info "View logs:  tail -f ${LOG_FILE}"
        log_info "Stop:       ./deploy/stop.sh"
    else
        log_error "Server failed to start. Last log entries:"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
else
    log_info "Starting ros2-monitor..."
    log_info "Access UI at: http://${HOST_IP}:8080"
    log_info "Press Ctrl+C to stop"
    echo ""
    exec uvicorn server.main:app --host 0.0.0.0 --port 8080
fi
