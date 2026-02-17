#!/bin/bash
#
# ROS2 Node Manager - Remote Start Script
#
# Starts ros2-monitor on a remote server via SSH.
#
# Usage:
#   ./start-remote.sh <host> [user] [--background]
#
# Example:
#   ./start-remote.sh 192.168.1.10 ubuntu
#   ./start-remote.sh tram-30639.local ubuntu --background
#

set -e

# === Configuration ===
REMOTE_HOST="${1:?Usage: $0 <host> [user] [--background]}"
REMOTE_USER="${2:-ubuntu}"
REMOTE_DIR="\$HOME/ros2-monitor"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
BACKGROUND=""

# Check for --background flag
for arg in "$@"; do
    if [ "$arg" == "--background" ] || [ "$arg" == "-b" ]; then
        BACKGROUND="--background"
    fi
done

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check SSH connection
log_info "Connecting to ${REMOTE_USER}@${REMOTE_HOST}..."
if ! ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "test -d ${REMOTE_DIR}" 2>/dev/null; then
    log_error "ros2-monitor not found at ${REMOTE_DIR}. Run deploy-simple.sh first."
    exit 1
fi

if [ -n "$BACKGROUND" ]; then
    # Background mode - run and exit
    log_info "Starting ros2-monitor in background..."
    ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_DIR} && ./deploy/start.sh --background"
    echo ""
    log_info "Server started on ${REMOTE_HOST}"
    log_info "Access UI at: http://${REMOTE_HOST}:8080"
else
    # Foreground mode - keep SSH session open
    log_info "Starting ros2-monitor (Ctrl+C to stop)..."
    echo ""
    ssh ${SSH_OPTS} -t "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_DIR} && ./deploy/start.sh"
fi
