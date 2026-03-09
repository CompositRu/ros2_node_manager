#!/bin/bash
#
# Tram Monitoring System - Remote Uninstall Script
#
# Removes ros2-monitor from systemd on a remote server via SSH.
#
# Usage:
#   ./uninstall-remote.sh <host> [user] [--purge]
#
# Example:
#   ./uninstall-remote.sh 192.168.1.10
#   ./uninstall-remote.sh 192.168.1.10 tram --purge
#

set -e

REMOTE_HOST="${1:?Usage: $0 <host> [user] [--purge]}"
REMOTE_USER="${2:-ubuntu}"
REMOTE_DIR="\$HOME/ros2-monitor"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
PURGE=""

for arg in "$@"; do
    if [ "$arg" == "--purge" ]; then
        PURGE="--purge"
    fi
done

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

log_info "Connecting to ${REMOTE_USER}@${REMOTE_HOST}..."

# Check deployment exists
if ! ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "test -d ${REMOTE_DIR}" 2>/dev/null; then
    log_error "ros2-monitor not found at ${REMOTE_DIR}."
    exit 1
fi

log_info "Running uninstall on ${REMOTE_USER}@${REMOTE_HOST}..."
ssh ${SSH_OPTS} -t "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_DIR} && ./deploy/uninstall.sh ${PURGE}"
