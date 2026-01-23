"""Node management router."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from ..models import NodesResponse, NodeDetailResponse, ActionResponse

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


def get_node_service():
    """Get node service or raise error."""
    from ..main import app_state
    
    if not app_state.node_service:
        raise HTTPException(503, "Not connected to any server")
    return app_state.node_service


@router.get("", response_model=NodesResponse)
async def list_nodes(refresh: bool = Query(True, description="Refresh from ROS2")):
    """
    Get list of all nodes.
    
    - refresh=True: Fetch fresh list from ROS2 (default)
    - refresh=False: Return cached list
    """
    service = get_node_service()
    
    if refresh:
        return await service.refresh_nodes()
    else:
        return service.get_cached_nodes()


@router.get("/{node_name:path}", response_model=NodeDetailResponse)
async def get_node_detail(node_name: str):
    """Get detailed information about a node."""
    service = get_node_service()
    
    # Ensure node name starts with /
    if not node_name.startswith("/"):
        node_name = "/" + node_name
    
    result = await service.get_node_detail(node_name)
    
    if not result:
        raise HTTPException(404, f"Node '{node_name}' not found")
    
    return result


class ShutdownRequest(BaseModel):
    force: bool = False


@router.post("/{node_name:path}/shutdown", response_model=ActionResponse)
async def shutdown_node(node_name: str, request: ShutdownRequest):
    """
    Shutdown a node.
    
    - For lifecycle nodes: Uses ros2 lifecycle set shutdown
    - For regular nodes: Requires force=True to kill process
    """
    service = get_node_service()
    
    # Ensure node name starts with /
    if not node_name.startswith("/"):
        node_name = "/" + node_name
    
    success, message = await service.shutdown_node(node_name, force=request.force)
    
    return ActionResponse(success=success, message=message)
