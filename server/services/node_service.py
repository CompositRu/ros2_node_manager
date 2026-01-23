"""Node service for managing ROS2 nodes."""

import asyncio
from datetime import datetime
from typing import Optional

from ..connection import BaseConnection, ConnectionError
from ..state import StatePersister
from ..models import (
    NodeInfo, NodeType, NodeStatus, LifecycleState,
    NodesResponse, NodeSummary, NodeDetailResponse
)
from ..config import settings


class NodeService:
    """Service for managing ROS2 nodes."""
    
    def __init__(self, connection: BaseConnection, persister: StatePersister):
        self.conn = connection
        self.persister = persister
        self._type_check_tasks: dict[str, asyncio.Task] = {}
    
    async def refresh_nodes(self) -> NodesResponse:
        """
        Refresh node list from ROS2 and update state.
        Returns current nodes summary.
        """
        # Get current running nodes
        try:
            running_nodes = await self.conn.ros2_node_list()
        except ConnectionError:
            running_nodes = []
        
        running_set = set(running_nodes)
        
        # Update existing nodes and add new ones
        for node_name in running_nodes:
            existing = self.persister.get_node(node_name)
            
            if existing:
                # Update existing node
                self.persister.set_node_status(node_name, NodeStatus.ACTIVE)
            else:
                # Add new node
                node = self.persister.add_new_node(node_name)
                # Schedule type check in background
                self._schedule_type_check(node_name)
        
        # Mark missing nodes as inactive
        for node_name, node in self.persister.get_all_nodes().items():
            if node_name not in running_set and node.status == NodeStatus.ACTIVE:
                self.persister.set_node_status(node_name, NodeStatus.INACTIVE)
        
        # Save state
        self.persister.save()
        
        # Build response
        return self._build_nodes_response()
    
    async def get_node_detail(self, node_name: str) -> Optional[NodeDetailResponse]:
        """Get detailed information about a node."""
        node = self.persister.get_node(node_name)
        
        if not node:
            return None
        
        # If node is active, fetch fresh info
        if node.status == NodeStatus.ACTIVE:
            try:
                # Get node info (subscribers, publishers, services)
                info = await self.conn.ros2_node_info(node_name)
                node.subscribers = info.get("subscribers", [])
                node.publishers = info.get("publishers", [])
                node.services = info.get("services", [])
                
                # Get parameters
                params = await self.conn.ros2_param_dump(node_name)
                node.parameters = params
                
                # Check lifecycle state if lifecycle node
                if node.type == NodeType.LIFECYCLE:
                    state = await self.conn.ros2_lifecycle_get_state(node_name)
                    if state:
                        node.lifecycle_state = LifecycleState(state)
                
                # Update last seen
                node.last_seen = datetime.now()
                
                # Save
                self.persister.update_node(node)
                self.persister.save()
                
            except ConnectionError as e:
                print(f"Error fetching node detail: {e}")
        
        return NodeDetailResponse(node=node)
    
    async def shutdown_node(self, node_name: str, force: bool = False) -> tuple[bool, str]:
        """
        Shutdown a node.
        - For lifecycle nodes: ros2 lifecycle set shutdown
        - For regular nodes: kill process (if force=True)
        """
        node = self.persister.get_node(node_name)
        
        if not node:
            return False, "Node not found"
        
        if node.status != NodeStatus.ACTIVE:
            return False, "Node is not active"
        
        if node.type == NodeType.UNKNOWN:
            return False, "Node type is unknown, please wait for type detection"
        
        try:
            if node.type == NodeType.LIFECYCLE:
                # Use lifecycle transition
                success = await self.conn.ros2_lifecycle_set(node_name, "shutdown")
                if success:
                    self.persister.set_node_status(node_name, NodeStatus.INACTIVE)
                    self.persister.save()
                    return True, "Lifecycle node shutdown successfully"
                else:
                    return False, "Failed to shutdown lifecycle node"
            
            elif node.type == NodeType.REGULAR:
                if not force:
                    return False, "Regular node requires force=True to kill process"
                
                # Try to kill by node name pattern
                # Extract the last part of the node name as pattern
                pattern = node_name.split("/")[-1]
                success = await self.conn.kill_process(pattern)
                
                if success:
                    self.persister.set_node_status(node_name, NodeStatus.INACTIVE)
                    self.persister.save()
                    return True, "Process killed (node may restart if managed by launch)"
                else:
                    return False, f"Could not find process matching '{pattern}'"
        
        except ConnectionError as e:
            return False, f"Connection error: {e}"
    
    def get_cached_nodes(self) -> NodesResponse:
        """Get nodes from cache without refreshing."""
        return self._build_nodes_response()
    
    def _build_nodes_response(self) -> NodesResponse:
        """Build NodesResponse from current state."""
        total, active, inactive = self.persister.get_counts()
        
        nodes = []
        for name, node in self.persister.get_all_nodes().items():
            nodes.append(NodeSummary(
                name=name,
                type=node.type,
                status=node.status,
                lifecycle_state=node.lifecycle_state
            ))
        
        # Sort by name
        nodes.sort(key=lambda n: n.name)
        
        return NodesResponse(
            total=total,
            active=active,
            inactive=inactive,
            nodes=nodes
        )
    
    def _schedule_type_check(self, node_name: str) -> None:
        """Schedule background task to check node type."""
        if node_name in self._type_check_tasks:
            return
        
        task = asyncio.create_task(self._check_node_type(node_name))
        self._type_check_tasks[node_name] = task
    
    async def _check_node_type(self, node_name: str) -> None:
        """Check if node is lifecycle or regular."""
        try:
            # Small delay to allow services to be registered
            await asyncio.sleep(settings.type_check_delay)
            
            is_lifecycle = await self.conn.is_lifecycle_node(node_name)
            
            node_type = NodeType.LIFECYCLE if is_lifecycle else NodeType.REGULAR
            self.persister.set_node_type(node_name, node_type)
            
            # If lifecycle, get current state
            if is_lifecycle:
                state = await self.conn.ros2_lifecycle_get_state(node_name)
                if state:
                    node = self.persister.get_node(node_name)
                    if node:
                        node.lifecycle_state = LifecycleState(state)
                        self.persister.update_node(node)
            
            self.persister.save()
            
        except Exception as e:
            print(f"Error checking node type for {node_name}: {e}")
        finally:
            self._type_check_tasks.pop(node_name, None)
