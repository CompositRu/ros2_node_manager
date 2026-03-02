#!/bin/bash
#
# Tram Monitoring System - Deployment Script
#
# Usage:
#   ./deploy.sh <host> [user]
#
# Example:
#   ./deploy.sh 192.168.1.10 ubuntu
#   ./deploy.sh tram-30639.local
#

set -e

# === Configuration ===
REMOTE_HOST="${1:?Usage: $0 <host> [user]}"
REMOTE_USER="${2:-ubuntu}"
REMOTE_DIR="/opt/ros2-monitor"
CTRL_SOCKET="/tmp/.ssh-deploy-$$"
SSH_BASE="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
SSH_OPTS="${SSH_BASE} -o ControlPath=${CTRL_SOCKET}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# === Functions ===

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

cleanup() {
    ssh -o ControlPath="${CTRL_SOCKET}" -O exit "${REMOTE_USER}@${REMOTE_HOST}" 2>/dev/null || true
}
trap cleanup EXIT

# === Pre-flight checks ===

log_info "Starting deployment to ${REMOTE_USER}@${REMOTE_HOST}"

# Check we're in the right directory
if [ ! -f "server/main.py" ]; then
    log_error "Please run this script from the ros2_node_manager directory"
    exit 1
fi

# Establish persistent SSH connection (password entered once here)
log_info "Establishing SSH connection..."
ssh -fNM ${SSH_BASE} -o ControlMaster=yes -o ControlPath="${CTRL_SOCKET}" "${REMOTE_USER}@${REMOTE_HOST}"
log_info "SSH connection established"

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

# === Step 2: Create remote directory (sudo) ===

log_info "Creating remote directory..."
ssh ${SSH_OPTS} -tt "${REMOTE_USER}@${REMOTE_HOST}" "sudo mkdir -p ${REMOTE_DIR} && sudo chown ${REMOTE_USER}:${REMOTE_USER} ${REMOTE_DIR}"

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
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" << 'REMOTE_SCRIPT'
set -e
cd /opt/ros2-monitor

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

# === Step 5: Install systemd service + restart (sudo) ===

log_info "Installing systemd service and starting..."
ssh ${SSH_OPTS} -tt "${REMOTE_USER}@${REMOTE_HOST}" "\
sudo cp ${REMOTE_DIR}/deploy/ros2-monitor.service /etc/systemd/system/ && \
sudo sed -i \"s/User=ubuntu/User=\$(whoami)/\" /etc/systemd/system/ros2-monitor.service && \
sudo sed -i \"s/Group=ubuntu/Group=\$(whoami)/\" /etc/systemd/system/ros2-monitor.service && \
sudo systemctl daemon-reload && \
sudo systemctl enable ros2-monitor && \
sudo systemctl restart ros2-monitor && \
sleep 2 && \
echo '' && \
sudo systemctl status ros2-monitor --no-pager || true"

# === Done ===

echo ""
log_info "=========================================="
log_info "Deployment complete!"
log_info "=========================================="
echo ""
log_info "Access the UI at: http://${REMOTE_HOST}:8080"
echo ""
log_info "Useful commands:"
echo "  Check status:  ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo systemctl status ros2-monitor'"
echo "  View logs:     ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo journalctl -u ros2-monitor -f'"
echo "  Restart:       ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo systemctl restart ros2-monitor'"
echo ""
