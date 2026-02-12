#!/bin/bash
#
# ROS2 Node Manager - Deployment Script
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
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

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
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "sudo mkdir -p ${REMOTE_DIR} && sudo chown ${REMOTE_USER}:${REMOTE_USER} ${REMOTE_DIR}"

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

# === Step 5: Install systemd service ===

log_info "Installing systemd service..."
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" << 'REMOTE_SCRIPT'
set -e

# Copy service file
sudo cp /opt/ros2-monitor/deploy/ros2-monitor.service /etc/systemd/system/

# Update user in service file to match current user
sudo sed -i "s/User=ubuntu/User=$(whoami)/" /etc/systemd/system/ros2-monitor.service
sudo sed -i "s/Group=ubuntu/Group=$(whoami)/" /etc/systemd/system/ros2-monitor.service

# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable ros2-monitor

echo "Systemd service installed"
REMOTE_SCRIPT

# === Step 6: Restart service ===

log_info "Restarting ros2-monitor service..."
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl restart ros2-monitor"

# Wait a bit for service to start
sleep 2

# Check status
log_info "Checking service status..."
ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl status ros2-monitor --no-pager" || true

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
