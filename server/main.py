"""ROS2 Node Manager - Main Application."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# from .config import settings, load_servers_config, get_server_by_id
from .models import ServerConfig, ServerType
from .connection import BaseConnection, LocalDockerConnection, SSHDockerConnection, ConnectionError, ContainerNotFoundError
from .state import StatePersister
# from .services import NodeServicee
from .routers import servers_router, nodes_router, websocket_router
from .config import settings, load_servers_config, get_server_by_id, load_alert_config
from .services import NodeService, AlertService
from fastapi.responses import FileResponse, JSONResponse


@dataclass
class AppState:
    """Global application state."""
    connection: Optional[BaseConnection] = None
    current_server_id: Optional[str] = None
    node_service: Optional[NodeService] = None
    persister: Optional[StatePersister] = None
    alert_service: Optional[AlertService] = None


# Global state
app_state = AppState()


async def connect_to_server(
    server: ServerConfig,
    # servers: dict[str, ServerConfig],
    password_override: Optional[str] = None
) -> None:
    """Connect to a server and initialize services."""
    global app_state
    
    # Stop previous alert service if running
    if app_state.alert_service:
        await app_state.alert_service.stop()
        app_state.alert_service = None

    # Disconnect from current server if any
    if app_state.connection:
        await app_state.connection.disconnect()
    
    # Create connection based on server type
    if server.type == ServerType.LOCAL:
        connection = LocalDockerConnection(server.container)
    else:
        connection = SSHDockerConnection(
            container=server.container,
            host=server.host,
            user=server.user,
            port=server.port,
            ssh_key=server.ssh_key,
            password=password_override or server.password
        )
    
    # Connect
    await connection.connect()
    
    # Initialize persister and service
    persister = StatePersister(server.id)
    persister.load()
    
    node_service = NodeService(connection, persister)

    # Initialize alert service
    alert_config = load_alert_config()
    alert_service = AlertService(connection, alert_config)
    await alert_service.start()

    # Update state
    app_state.connection = connection
    app_state.current_server_id = server.id
    app_state.persister = persister
    app_state.node_service = node_service
    app_state.alert_service = alert_service


async def disconnect_server() -> None:
    """Disconnect from current server and cleanup services."""
    global app_state

    # Stop alert service
    if app_state.alert_service:
        await app_state.alert_service.stop()
        app_state.alert_service = None

    # Disconnect
    if app_state.connection:
        try:
            await app_state.connection.disconnect()
        except Exception as e:
            print(f"Error during disconnect: {e}")
        app_state.connection = None

    # Clear state
    app_state.node_service = None
    app_state.current_server_id = None
    app_state.persister = None

    print("🔌 Disconnected from server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    print("🚀 ROS2 Node Manager starting...")
    
    # Ensure data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    
    # Auto-connect to first server if available
    servers = load_servers_config()
    if servers:
        first_server = servers[0]
        print(f"📡 Auto-connecting to '{first_server.name}'...")
        try:
            await connect_to_server(first_server)
            print(f"✅ Connected to '{first_server.name}'")
        except ConnectionError as e:
            print(f"⚠️  Could not auto-connect: {e}")
    
    yield
    
    # Shutdown
    print("👋 Shutting down...")
    if app_state.alert_service:
        await app_state.alert_service.stop()
    if app_state.connection:
        await app_state.connection.disconnect()


# Create FastAPI app
app = FastAPI(
    title="ROS2 Node Manager",
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


# Serve static files (React build)
static_dir = Path(__file__).parent.parent / "web" / "dist"
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
    
    @app.get("/")
    async def serve_index():
        return FileResponse(static_dir / "index.html")
    
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        # Serve index.html for client-side routing
        file_path = static_dir / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(static_dir / "index.html")


# Health check
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "connected": app_state.connection is not None and app_state.connection.connected,
        "server": app_state.current_server_id
    }


# === Static files and SPA routing (Production) ===

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Path to React build
STATIC_DIR = Path(__file__).parent.parent / "web" / "dist"
ASSETS_DIR = STATIC_DIR / "assets"


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "connected": app_state.connection is not None and app_state.connection._connected,
        "server": app_state.current_server_id,
    }


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
            content={"message": "ROS2 Node Manager API", "docs": "/docs", "mode": "development"}
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
