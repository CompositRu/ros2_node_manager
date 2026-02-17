#!/bin/bash
#
# ROS2 Node Manager - Simple Deployment Script (without systemd)
#
# Usage:
#   ./deploy-simple.sh <host> [user]
#
# Example:
#   ./deploy-simple.sh 192.168.1.10 ubuntu
#   ./deploy-simple.sh tram-30639.local
#

set -e

# === Configuration ===
REMOTE_HOST="${1:?Usage: $0 <host> [user]}"
REMOTE_USER="${2:-ubuntu}"
REMOTE_DIR="~/ros2-monitor"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# === Pre-flight checks ===

log_info "Starting deployment to ${REMOTE_USER}@${REMOTE_HOST}"

# Check we're in the right directory
if [ ! -f "server/main.py" ]; then
    log_error "Please run this script from the ros2_node_manager directory"
    exit 1
fi

# Check SSH connection
log_info "Checking SSH connection..."
if ! ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "echo 'SSH OK'" > /dev/null 2>&1; then
    log_error "Cannot connect to ${REMOTE_USER}@${REMOTE_HOST}"
    exit 1
fi

# === Step 1: Build Frontend ===

log_info "Building React frontend..."
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

# === Step 2: Create remote directory ===

log_info "Creating remote directory..."
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p ${REMOTE_DIR} && chown ${REMOTE_USER}:${REMOTE_USER} ${REMOTE_DIR}"

# === Step 3: Sync files ===

log_info "Syncing files to remote server..."
rsync -avz --delete \
    --exclude 'node_modules' \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'data/*.json' \
    --exclude 'web/node_modules' \
    --exclude 'web/src' \
    --exclude 'web/public' \
    --exclude 'web/*.json' \
    --exclude 'web/*.config.*' \
    --exclude 'web/index.html' \
    -e "ssh ${SSH_OPTS}" \
    ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

log_info "Files synced"

# === Step 4: Setup Python environment ===

log_info "Setting up Python virtual environment..."
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" << REMOTE_SCRIPT
set -e
cd ${REMOTE_DIR}

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate and install dependencies
source .venv/bin/activate
pip install --upgrade pip
pip install -r server/requirements.txt

echo "Python environment ready"
REMOTE_SCRIPT

# === Done ===

echo ""
log_info "=========================================="
log_info "Deployment complete!"
log_info "=========================================="
echo ""
log_info "To start the server, run:"
echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} 'cd ${REMOTE_DIR} && ./deploy/start.sh'"
echo ""
log_info "Or use the remote start script:"
echo "  ./deploy/start-remote.sh ${REMOTE_HOST} ${REMOTE_USER}"
echo ""
