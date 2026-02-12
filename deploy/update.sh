#!/bin/bash
#
# Quick update script - just sync code and restart
# Use this for fast iteration after initial deploy.sh
#
# Usage:
#   ./update.sh <host> [user]
#

set -e

REMOTE_HOST="${1:?Usage: $0 <host> [user]}"
REMOTE_USER="${2:-ubuntu}"
REMOTE_DIR="/opt/ros2-monitor"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

GREEN='\033[0;32m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

# Check directory
if [ ! -f "server/main.py" ]; then
    echo "Please run from ros2_node_manager directory"
    exit 1
fi

# Build frontend if sources changed
if [ "web/src" -nt "web/dist/index.html" ] 2>/dev/null || [ ! -d "web/dist" ]; then
    log_info "Building frontend..."
    cd web && npm run build && cd ..
fi

# Sync files
log_info "Syncing files..."
rsync -avz --delete \
    --exclude 'node_modules' \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'data/*.json' \
    --exclude 'web/node_modules' \
    --exclude 'web/src' \
    --exclude 'web/public' \
    --exclude 'web/*.json' \
    --exclude 'web/*.config.*' \
    --exclude 'web/index.html' \
    -e "ssh ${SSH_OPTS}" \
    ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

# Restart service
log_info "Restarting service..."
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl restart ros2-monitor"

sleep 1

log_info "Done! http://${REMOTE_HOST}:8080"
