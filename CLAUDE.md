# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ROS2 Node Manager is a web interface for monitoring and managing ROS2 nodes running inside Docker containers. It supports both local Docker and remote SSH connections.

## Development Commands

### Backend (FastAPI/Python)
```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run development server (auto-reload)
uvicorn server.main:app --reload --port 8080

# Run production
uvicorn server.main:app --host 0.0.0.0 --port 8080
```

### Frontend (React/Vite)
```bash
cd web
npm install
npm run dev      # Development (port 3000)
npm run build    # Production build to web/dist/
```

### Full Stack Development
Run backend on port 8080, frontend dev server on port 3000. Frontend proxies API calls to backend.

## Architecture

### Backend (`server/`)

**Connection Layer** (`connection/`):
- `BaseConnection` - abstract class defining interface for Docker command execution
- `LocalDockerConnection` - executes `docker exec` locally
- `SSHDockerConnection` - executes `docker exec` via SSH tunnel (uses asyncssh)
- All ROS2 CLI commands wrapped as methods: `ros2_node_list()`, `ros2_node_info()`, `ros2_param_dump()`, `ros2_lifecycle_set()`, etc.
- Service cache for fast lifecycle node detection

**Services** (`services/`):
- `NodeService` - main business logic for node management, uses persister for state
- `LogCollector` - streams `/rosout` logs via WebSocket

**State** (`state/`):
- `StatePersister` - saves/loads node state to `data/{server_id}.json`
- Preserves inactive nodes for history tracking

**Routers** (`routers/`):
- `servers.py` - `/api/servers/*` endpoints for connection management
- `nodes.py` - `/api/nodes/*` endpoints for node operations
- `websocket.py` - `/ws/nodes/status` and `/ws/logs/{node}` for real-time updates

**Key Models** (`models.py`):
- `NodeType`: LIFECYCLE | REGULAR | UNKNOWN
- `NodeStatus`: ACTIVE | INACTIVE
- `LifecycleState`: UNCONFIGURED | INACTIVE | ACTIVE | FINALIZED

### Frontend (`web/src/`)

React 18 with Vite, TailwindCSS for styling.

**Components**:
- `NodeTree` - hierarchical namespace tree with node status indicators
- `NodeDetailPanel` - parameters, subscribers, publishers, lifecycle controls
- `LogPanel` - real-time log streaming
- `ServerSelector` - dropdown for switching servers

**Hooks**:
- `useNodes` - manages node list state and WebSocket updates
- `useServer` - server connection state

**Services**:
- `api.js` - REST API client
- `websocket.js` - WebSocket connection manager

## Configuration

Edit `config/servers.yaml` to configure Docker containers:
```yaml
servers:
  - id: local
    name: "Local Docker"
    type: local           # or "ssh"
    container: your_container_name
    # For SSH: host, user, port, ssh_key or password
```

First server auto-connects on startup. State persisted in `data/{server_id}.json`.

## ROS2 Environment

The base connection sets up ROS environment inside Docker:
- Sources `/opt/ros/humble/setup.bash`
- Reads `ROS_DOMAIN_ID` from `$HOME/tram.autoware/.ros_domain_id`
- Sets `ROS_LOCALHOST_ONLY=1` and `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`

Technical nodes (transform_listener, ros2cli, daemon, launch_ros) are filtered from display.
