#!/bin/bash
#
# Tram Monitoring System - Resource Monitor
#
# Collects CPU, memory, and subprocess metrics for the ros2-monitor app
# and writes them to a CSV log file for analysis.
#
# Usage:
#   ./monitor-resources.sh [interval_seconds] [output_file]
#
# Example:
#   ./monitor-resources.sh 10                     # Every 10s, default output
#   ./monitor-resources.sh 5 /tmp/metrics.csv     # Every 5s, custom file
#

INTERVAL="${1:-10}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="${PROJECT_DIR}/logs"
OUTPUT="${2:-${LOG_DIR}/resource-metrics.csv}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Ensure logs directory exists
mkdir -p "$LOG_DIR"

# Find uvicorn PID
find_uvicorn_pid() {
    pgrep -f "uvicorn server.main:app" | head -1
}

UVICORN_PID=$(find_uvicorn_pid)
if [ -z "$UVICORN_PID" ]; then
    log_error "uvicorn process not found. Is ros2-monitor running?"
    log_info "Start it first: ./deploy/start.sh"
    exit 1
fi

log_info "Monitoring ros2-monitor (PID: ${UVICORN_PID})"
log_info "Interval: ${INTERVAL}s"
log_info "Output:   ${OUTPUT}"
log_info "Press Ctrl+C to stop"
echo ""

# Write CSV header if file doesn't exist
if [ ! -f "$OUTPUT" ]; then
    echo "timestamp,host_cpu_pct,host_mem_used_mb,host_mem_total_mb,uvicorn_pid,uvicorn_cpu_pct,uvicorn_rss_mb,uvicorn_threads,docker_exec_count,container_cpu_pct,container_mem_mb" > "$OUTPUT"
fi

# Main collection loop
while true; do
    # Re-check PID (process may have restarted)
    UVICORN_PID=$(find_uvicorn_pid)
    if [ -z "$UVICORN_PID" ]; then
        log_warn "uvicorn process disappeared, waiting..."
        sleep "$INTERVAL"
        continue
    fi

    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    # Host CPU usage
    HOST_CPU=$(top -bn1 2>/dev/null | grep "Cpu(s)" | awk '{print $2}' || echo "0")

    # Host memory
    HOST_MEM_USED=$(free -m 2>/dev/null | awk '/^Mem:/{print $3}' || echo "0")
    HOST_MEM_TOTAL=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo "0")

    # Uvicorn process metrics
    UVICORN_CPU=$(ps -p "$UVICORN_PID" -o %cpu --no-headers 2>/dev/null | tr -d ' ' || echo "0")
    UVICORN_RSS_KB=$(ps -p "$UVICORN_PID" -o rss --no-headers 2>/dev/null | tr -d ' ' || echo "0")
    UVICORN_RSS_MB=$(awk "BEGIN {printf \"%.1f\", ${UVICORN_RSS_KB:-0}/1024}")
    UVICORN_THREADS=$(ls /proc/"$UVICORN_PID"/task 2>/dev/null | wc -l || echo "0")

    # Count docker exec subprocesses
    DOCKER_EXEC_COUNT=$(pgrep -c -f "docker exec" 2>/dev/null || echo "0")

    # Docker container stats (best-effort via app endpoint)
    CONTAINER_CPU="N/A"
    CONTAINER_MEM="N/A"
    CONTAINER_NAME=$(curl -s --max-time 2 http://localhost:8080/api/debug/stats 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('connection',{}).get('container',''))" 2>/dev/null || echo "")

    if [ -n "$CONTAINER_NAME" ]; then
        DOCKER_STATS=$(docker stats "$CONTAINER_NAME" --no-stream --format "{{.CPUPerc}},{{.MemUsage}}" 2>/dev/null || echo ",")
        CONTAINER_CPU=$(echo "$DOCKER_STATS" | cut -d',' -f1 | tr -d '%' || echo "N/A")
        CONTAINER_MEM_RAW=$(echo "$DOCKER_STATS" | cut -d',' -f2 | cut -d'/' -f1 | tr -d ' ' || echo "N/A")
        if echo "$CONTAINER_MEM_RAW" | grep -q "GiB"; then
            CONTAINER_MEM=$(echo "$CONTAINER_MEM_RAW" | tr -d 'GiB' | awk '{printf "%.0f", $1*1024}')
        elif echo "$CONTAINER_MEM_RAW" | grep -q "MiB"; then
            CONTAINER_MEM=$(echo "$CONTAINER_MEM_RAW" | tr -d 'MiB')
        else
            CONTAINER_MEM="$CONTAINER_MEM_RAW"
        fi
    fi

    # Write CSV row
    echo "${TIMESTAMP},${HOST_CPU},${HOST_MEM_USED},${HOST_MEM_TOTAL},${UVICORN_PID},${UVICORN_CPU},${UVICORN_RSS_MB},${UVICORN_THREADS},${DOCKER_EXEC_COUNT},${CONTAINER_CPU},${CONTAINER_MEM}" >> "$OUTPUT"

    # Print summary to terminal
    printf "\r[%s] CPU: %s%% | RSS: %sMB | docker exec: %s | Container CPU: %s%%    " \
        "$TIMESTAMP" "$UVICORN_CPU" "$UVICORN_RSS_MB" "$DOCKER_EXEC_COUNT" "$CONTAINER_CPU"

    sleep "$INTERVAL"
done
