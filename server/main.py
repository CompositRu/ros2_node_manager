"""Tram Monitoring System - Main Application."""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


# --- File logging setup (overwritten on each restart) ---
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "app.log"

_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_file_handler = logging.FileHandler(_LOG_FILE, mode="w", encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(_log_formatter)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(_log_formatter)

logging.root.addHandler(_file_handler)
logging.root.addHandler(_console_handler)
logging.root.setLevel(logging.INFO)


# Disable uvicorn access logs (noisy polling spam)
_uv_access = logging.getLogger("uvicorn.access")
_uv_access.handlers.clear()
_uv_access.propagate = False

from .models import ServerConfig
from .connection import AgentConnection, ConnectionError, ContainerNotFoundError
from .state import StatePersister
# from .services import NodeServicee
from .routers import servers_router, nodes_router, websocket_router, debug_router, topics_router, history_router, dashboard_router, services_router
from .config import settings, load_servers_config, get_server_by_id, load_alert_config, load_topic_groups_config
from .services import NodeService, AlertService, TopicHzMonitor, SharedEchoMonitor, HistoryStore, LogCollector
from fastapi.responses import FileResponse, JSONResponse


@dataclass
class AppState:
    """Global application state."""
    connection: Optional[AgentConnection] = None
    current_server_id: Optional[str] = None
    node_service: Optional[NodeService] = None
    persister: Optional[StatePersister] = None
    alert_service: Optional[AlertService] = None
    topic_hz_monitor: Optional[TopicHzMonitor] = None
    shared_echo_monitor: Optional[SharedEchoMonitor] = None
    history_store: Optional[HistoryStore] = None
    log_collector: Optional[LogCollector] = None
    is_shutting_down: bool = False


# Global state
app_state = AppState()


async def connect_to_server(server: ServerConfig) -> None:
    """Connect to a server and initialize services."""
    global app_state

    # Stop previous services if running
    if app_state.log_collector:
        await app_state.log_collector.stop()
        app_state.log_collector = None
    if app_state.history_store:
        await app_state.history_store.close()
        app_state.history_store = None
    if app_state.topic_hz_monitor:
        await app_state.topic_hz_monitor.stop()
        app_state.topic_hz_monitor = None
    if app_state.shared_echo_monitor:
        await app_state.shared_echo_monitor.stop()
        app_state.shared_echo_monitor = None
    if app_state.alert_service:
        await app_state.alert_service.stop()
        app_state.alert_service = None

    # Disconnect from current server if any
    if app_state.connection:
        await app_state.connection.disconnect()

    connection = AgentConnection(agent_url=server.agent_url)
    await connection.connect()

    # Initialize persister and service
    persister = StatePersister(server.id)
    persister.load()
    
    node_service = NodeService(connection, persister)

    # Initialize alert service (shares node_service cache to avoid duplicate polling)
    alert_config = load_alert_config()
    alert_service = AlertService(connection, alert_config)
    alert_service.node_service = node_service
    await alert_service.start()

    # Initialize topic hz monitor (on-demand, no groups active by default)
    topic_groups_config = load_topic_groups_config()
    topic_hz_monitor = TopicHzMonitor(connection, topic_groups_config.topic_groups)

    # Initialize shared echo monitor (one subscription per topic, fan-out to all clients)
    shared_echo_monitor = SharedEchoMonitor(connection)

    # Initialize history store (persistent log/alert storage)
    history_store = HistoryStore(server.id, settings.data_dir)
    await history_store.initialize()
    alert_service.history_store = history_store

    # Initialize single LogCollector — one /rosout stream for everything
    log_collector = LogCollector(connection)
    log_collector.add_callback(history_store.on_log_message)
    log_collector.add_callback(alert_service.on_log_message)
    await log_collector.start()

    # Update state
    app_state.connection = connection
    app_state.current_server_id = server.id
    app_state.persister = persister
    app_state.node_service = node_service
    app_state.alert_service = alert_service
    app_state.topic_hz_monitor = topic_hz_monitor
    app_state.shared_echo_monitor = shared_echo_monitor
    app_state.history_store = history_store
    app_state.log_collector = log_collector


async def disconnect_server() -> None:
    """Disconnect from current server and cleanup services."""
    global app_state

    # Stop log collector first (it feeds history_store and alert_service)
    if app_state.log_collector:
        await app_state.log_collector.stop()
        app_state.log_collector = None

    # Stop history store
    if app_state.history_store:
        await app_state.history_store.close()
        app_state.history_store = None

    # Stop topic hz monitor
    if app_state.topic_hz_monitor:
        await app_state.topic_hz_monitor.stop()
        app_state.topic_hz_monitor = None

    # Stop shared echo monitor
    if app_state.shared_echo_monitor:
        await app_state.shared_echo_monitor.stop()
        app_state.shared_echo_monitor = None

    # Stop alert service
    if app_state.alert_service:
        await app_state.alert_service.stop()
        app_state.alert_service = None

    # Disconnect
    if app_state.connection:
        try:
            await app_state.connection.disconnect()
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
        app_state.connection = None

    # Clear state
    app_state.node_service = None
    app_state.current_server_id = None
    app_state.persister = None

    logger.info("Disconnected from server")


async def _auto_connect_loop():
    """Background task: retry connecting to first server until success."""
    import asyncio

    servers = load_servers_config()
    if not servers:
        return

    first_server = servers[0]
    retry_interval = 5  # seconds

    while not app_state.is_shutting_down:
        if app_state.connection and app_state.connection.connected:
            return  # already connected, done
        try:
            await connect_to_server(first_server)
            logger.info(f"Auto-connected to '{first_server.name}'")
            return
        except Exception as e:
            logger.warning(f"Auto-connect to '{first_server.name}' failed: {e} (retrying in {retry_interval}s)")
            await asyncio.sleep(retry_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    import asyncio

    # Startup
    logger.info("Tram Monitoring System starting...")

    # Ensure data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    # Auto-connect to first server if available
    servers = load_servers_config()
    auto_connect_task = None
    if servers:
        first_server = servers[0]
        logger.info(f"Auto-connecting to '{first_server.name}'...")
        try:
            await connect_to_server(first_server)
            logger.info(f"Connected to '{first_server.name}'")
        except Exception as e:
            logger.warning(f"Could not auto-connect: {e}")
            logger.info("Will retry in background...")
            auto_connect_task = asyncio.create_task(_auto_connect_loop())

    yield

    # Shutdown — with hard timeout so a single Ctrl+C is enough
    logger.info("Shutting down...")
    app_state.is_shutting_down = True

    if auto_connect_task and not auto_connect_task.done():
        auto_connect_task.cancel()

    # Stop all services in parallel with a timeout
    try:
        await asyncio.wait_for(_shutdown_services(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("Shutdown timed out after 10s, forcing disconnect...")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

    # Always clean up Docker processes and disconnect, even after timeout
    if app_state.connection:
        try:
            await asyncio.wait_for(
                app_state.connection.cleanup_docker_processes(), timeout=5.0
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                app_state.connection.disconnect(), timeout=5.0
            )
        except Exception:
            pass

    logger.info("Shutdown complete.")


async def _shutdown_services() -> None:
    """Stop all services in parallel."""
    import asyncio
    tasks = []
    if app_state.log_collector:
        tasks.append(app_state.log_collector.stop())
    if app_state.topic_hz_monitor:
        tasks.append(app_state.topic_hz_monitor.stop())
    if app_state.shared_echo_monitor:
        tasks.append(app_state.shared_echo_monitor.stop())
    if app_state.alert_service:
        tasks.append(app_state.alert_service.stop())
    if app_state.history_store:
        tasks.append(app_state.history_store.close())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# Create FastAPI app
app = FastAPI(
    title="Tram Monitoring System",
    description="Web interface for managing ROS2 nodes in Docker containers",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(servers_router)
app.include_router(nodes_router)
app.include_router(websocket_router)
app.include_router(debug_router)
app.include_router(topics_router)
app.include_router(history_router)
app.include_router(dashboard_router)
app.include_router(services_router)


# === Health check (must be before SPA catch-all) ===

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "connected": app_state.connection is not None and app_state.connection.connected,
        "server": app_state.current_server_id,
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "connected": app_state.connection is not None and app_state.connection.connected,
        "server": app_state.current_server_id,
    }


# === Static files and SPA routing (Production) ===

from fastapi.responses import JSONResponse

STATIC_DIR = Path(__file__).parent.parent / "web" / "dist"
ASSETS_DIR = STATIC_DIR / "assets"

# Serve static assets if build exists
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """Serve React SPA for all non-API routes."""
    # Don't serve SPA for API routes
    if full_path.startswith("api/") or full_path.startswith("ws/"):
        raise HTTPException(status_code=404, detail="Not found")

    # Check if static build exists
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            status_code=200,
            content={"message": "Tram Monitoring System API", "docs": "/docs", "mode": "development"}
        )

    # Try to serve the exact file first
    file_path = STATIC_DIR / full_path
    if file_path.is_file():
        return FileResponse(file_path)

    # Otherwise serve index.html (SPA routing)
    return FileResponse(index_file)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )
