"""Node management router."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import asyncio

from ..models import NodesResponse, NodeDetailResponse, ActionResponse, NodeType

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


def get_node_service():
    """Get node service or raise error."""
    from ..main import app_state
    
    if not app_state.node_service:
        raise HTTPException(503, "Not connected to any server")
    return app_state.node_service


@router.get("", response_model=NodesResponse)
async def list_nodes(refresh: bool = Query(True, description="Refresh from ROS2")):
    """Get list of all nodes."""
    service = get_node_service()
    
    if refresh:
        return await service.refresh_nodes()
    else:
        return service.get_cached_nodes()


@router.get("/{node_name:path}", response_model=NodeDetailResponse)
async def get_node_detail(node_name: str, refresh: bool = Query(True, description="Fetch fresh data from ROS2")):
    """
    Get detailed information about a node.
    - refresh=False: Return cached data immediately (fast)
    - refresh=True: Fetch fresh data from ROS2 (slow)
    """
    service = get_node_service()
    
    if not node_name.startswith("/"):
        node_name = "/" + node_name
    
    result = await service.get_node_detail(node_name, refresh=refresh)
    
    if not result:
        raise HTTPException(404, f"Node '{node_name}' not found")
    
    return result


class LifecycleRequest(BaseModel):
    transition: str  # configure, activate, deactivate, shutdown, cleanup


@router.post("/{node_name:path}/lifecycle", response_model=ActionResponse)
async def lifecycle_transition(node_name: str, request: LifecycleRequest):
    """
    Perform lifecycle transition on a node.
    Valid transitions: configure, activate, deactivate, shutdown, cleanup
    """
    service = get_node_service()
    
    if not node_name.startswith("/"):
        node_name = "/" + node_name
    
    valid_transitions = ["configure", "activate", "deactivate", "shutdown", "cleanup"]
    if request.transition not in valid_transitions:
        return ActionResponse(
            success=False, 
            message=f"Invalid transition. Valid: {', '.join(valid_transitions)}"
        )
    
    success, message = await service.lifecycle_transition(node_name, request.transition)
    return ActionResponse(success=success, message=message)


class ShutdownRequest(BaseModel):
    force: bool = False


@router.post("/{node_name:path}/shutdown", response_model=ActionResponse)
async def shutdown_node(node_name: str, request: ShutdownRequest):
    """Shutdown a node."""
    service = get_node_service()
    
    if not node_name.startswith("/"):
        node_name = "/" + node_name
    
    success, message = await service.shutdown_node(node_name, force=request.force)
    return ActionResponse(success=success, message=message)


class GroupActionRequest(BaseModel):
    action: str  # shutdown, kill
    namespace: str
    force: bool = False


class GroupActionResponse(BaseModel):
    success: bool
    total: int
    succeeded: int
    failed: int
    results: list[dict]


@router.post("/group/action", response_model=GroupActionResponse)
async def group_action(request: GroupActionRequest):
    """
    Perform action on all nodes in a namespace.
    """
    service = get_node_service()
    
    namespace = request.namespace
    if not namespace.startswith("/"):
        namespace = "/" + namespace
    
    # Get all nodes in namespace
    all_nodes = service.persister.get_all_nodes()
    target_nodes = [
        node for name, node in all_nodes.items()
        if name.startswith(namespace) and node.status.value == "active"
    ]
    
    if not target_nodes:
        return GroupActionResponse(
            success=True,
            total=0,
            succeeded=0,
            failed=0,
            results=[]
        )
    
    results = []
    succeeded = 0
    failed = 0
    skipped = 0
    
    for node in target_nodes:
        try:
            # Skip unknown nodes
            if node.type == NodeType.UNKNOWN:
                results.append({
                    "node": node.name,
                    "success": False,
                    "message": "Skipped: node type unknown (still detecting)"
                })
                skipped += 1
                continue
            
            if request.action == "shutdown":
                if node.type == NodeType.LIFECYCLE:
                    success, message = await service.lifecycle_transition(node.name, "shutdown")
                elif node.type == NodeType.REGULAR and request.force:
                    success, message = await service.shutdown_node(node.name, force=True)
                else:
                    success = False
                    message = f"Cannot shutdown regular node without force"
            elif request.action == "kill":
                if node.type == NodeType.LIFECYCLE:
                    # For lifecycle nodes, try shutdown first
                    success, message = await service.lifecycle_transition(node.name, "shutdown")
                else:
                    success, message = await service.shutdown_node(node.name, force=True)
            else:
                success = False
                message = f"Unknown action: {request.action}"
            
            results.append({
                "node": node.name,
                "success": success,
                "message": message
            })
            
            if success:
                succeeded += 1
            else:
                failed += 1
                
        except Exception as e:
            results.append({
                "node": node.name,
                "success": False,
                "message": str(e)
            })
            failed += 1
    
    return GroupActionResponse(
        success=failed == 0 and skipped == 0,
        total=len(target_nodes),
        succeeded=succeeded,
        failed=failed + skipped,
        results=results
    )