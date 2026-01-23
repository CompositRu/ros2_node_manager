"""Server management router."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..config import load_servers_config, get_server_by_id
from ..models import ServerStatus, ServerType

router = APIRouter(prefix="/api/servers", tags=["servers"])


class ConnectRequest(BaseModel):
    server_id: str
    password: Optional[str] = None  # Optional password override


@router.get("", response_model=list[ServerStatus])
async def list_servers():
    """Get list of available servers."""
    from ..main import app_state
    
    servers = load_servers_config()
    result = []
    
    for srv in servers:
        is_current = (
            app_state.current_server_id == srv.id 
            and app_state.connection is not None
            and app_state.connection.connected
        )
        
        result.append(ServerStatus(
            id=srv.id,
            name=srv.name,
            type=srv.type,
            connected=is_current
        ))
    
    return result


@router.get("/current")
async def get_current_server():
    """Get currently connected server."""
    from ..main import app_state
    
    if not app_state.current_server_id or not app_state.connection:
        return {"connected": False, "server": None}
    
    srv = get_server_by_id(app_state.current_server_id)
    if not srv:
        return {"connected": False, "server": None}
    
    return {
        "connected": app_state.connection.connected,
        "server": ServerStatus(
            id=srv.id,
            name=srv.name,
            type=srv.type,
            connected=app_state.connection.connected
        )
    }


@router.post("/connect")
async def connect_to_server(request: ConnectRequest):
    """Connect to a server."""
    from ..main import app_state, connect_to_server as do_connect
    
    srv = get_server_by_id(request.server_id)
    if not srv:
        raise HTTPException(404, f"Server '{request.server_id}' not found")
    
    # Use provided password if given
    password = request.password or srv.password
    
    try:
        await do_connect(srv, password_override=password)
        return {
            "success": True,
            "message": f"Connected to {srv.name}",
            "server": ServerStatus(
                id=srv.id,
                name=srv.name,
                type=srv.type,
                connected=True
            )
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to connect: {e}")


@router.post("/disconnect")
async def disconnect_from_server():
    """Disconnect from current server."""
    from ..main import app_state
    
    if app_state.connection:
        await app_state.connection.disconnect()
        app_state.connection = None
        app_state.node_service = None
        
        old_server = app_state.current_server_id
        app_state.current_server_id = None
        
        return {"success": True, "message": f"Disconnected from {old_server}"}
    
    return {"success": True, "message": "Not connected"}
