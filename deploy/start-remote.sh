#!/bin/bash
#
# Tram Monitoring System - Remote Start Script
#
# Starts ros2-monitor on a remote server via SSH.
#
# Usage:
#   ./start-remote.sh <host> [user] [--background]
#
# Example:
#   ./start-remote.sh 192.168.1.10
#   ./start-remote.sh 192.168.1.10 ubuntu --background
#

set -e

REMOTE_HOST="${1:?Usage: $0 <host> [user] [--background]}"
REMOTE_USER="${2:-ubuntu}"
REMOTE_DIR="\$HOME/ros2-monitor"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
BACKGROUND=""

for arg in "$@"; do
    if [ "$arg" == "--background" ] || [ "$arg" == "-b" ]; then
        BACKGROUND="--background"
    fi
done

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check deployment exists
log_info "Connecting to ${REMOTE_USER}@${REMOTE_HOST}..."
if ! ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "test -d ${REMOTE_DIR}" 2>/dev/null; then
    log_error "ros2-monitor not found at ${REMOTE_DIR}. Run deploy-simple.sh first."
    exit 1
fi

if [ -n "$BACKGROUND" ]; then
    ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_DIR} && ROS2_MONITOR_HOST=${REMOTE_HOST} ./deploy/start.sh --background"
    echo ""
    log_info "Useful commands:"
    log_info "  Logs:   ssh ${REMOTE_USER}@${REMOTE_HOST} 'tail -f ${REMOTE_DIR}/logs/ros2-monitor.log'"
    log_info "  Stop:   ssh ${REMOTE_USER}@${REMOTE_HOST} '${REMOTE_DIR}/deploy/stop.sh'"
    log_info "  Restart: $0 $1 $2 --background"
else
    log_info "Starting ros2-monitor (Ctrl+C to stop)..."
    echo ""
    ssh ${SSH_OPTS} -t "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_DIR} && ROS2_MONITOR_HOST=${REMOTE_HOST} ./deploy/start.sh"
fi
