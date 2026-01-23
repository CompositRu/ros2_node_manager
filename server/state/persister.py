"""State persistence for nodes."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import NodeInfo, NodeState, NodeType, NodeStatus
from ..config import settings


class StatePersister:
    """Manages persistence of node state to JSON file."""
    
    def __init__(self, server_id: str):
        self.server_id = server_id
        self.file_path = settings.data_dir / f"node_state_{server_id}.json"
        self._state: Optional[NodeState] = None
    
    def load(self) -> NodeState:
        """Load state from file or create new."""
        if self.file_path.exists():
            try:
                with open(self.file_path) as f:
                    data = json.load(f)
                
                # Convert nodes dict
                nodes = {}
                for name, node_data in data.get("nodes", {}).items():
                    # Convert datetime strings
                    node_data["first_seen"] = datetime.fromisoformat(node_data["first_seen"])
                    node_data["last_seen"] = datetime.fromisoformat(node_data["last_seen"])
                    nodes[name] = NodeInfo(**node_data)
                
                self._state = NodeState(
                    last_updated=datetime.fromisoformat(data["last_updated"]),
                    server_id=data["server_id"],
                    nodes=nodes
                )
            except Exception as e:
                print(f"Error loading state: {e}, creating new")
                self._state = self._create_empty_state()
        else:
            self._state = self._create_empty_state()
        
        return self._state
    
    def save(self) -> None:
        """Save state to file."""
        if not self._state:
            return
        
        # Ensure directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to JSON-serializable format
        data = {
            "last_updated": self._state.last_updated.isoformat(),
            "server_id": self._state.server_id,
            "nodes": {}
        }
        
        for name, node in self._state.nodes.items():
            node_dict = node.model_dump()
            node_dict["first_seen"] = node.first_seen.isoformat()
            node_dict["last_seen"] = node.last_seen.isoformat()
            data["nodes"][name] = node_dict
        
        with open(self.file_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def get_state(self) -> NodeState:
        """Get current state."""
        if not self._state:
            self.load()
        return self._state
    
    def update_node(self, node: NodeInfo) -> None:
        """Update or add a node."""
        if not self._state:
            self.load()
        
        self._state.nodes[node.name] = node
        self._state.last_updated = datetime.now()
    
    def get_node(self, name: str) -> Optional[NodeInfo]:
        """Get node by name."""
        if not self._state:
            self.load()
        return self._state.nodes.get(name)
    
    def set_node_status(self, name: str, status: NodeStatus) -> None:
        """Update node status."""
        if not self._state:
            self.load()
        
        if name in self._state.nodes:
            self._state.nodes[name].status = status
            self._state.nodes[name].last_seen = datetime.now()
            self._state.last_updated = datetime.now()
    
    def set_node_type(self, name: str, node_type: NodeType) -> None:
        """Update node type."""
        if not self._state:
            self.load()
        
        if name in self._state.nodes:
            self._state.nodes[name].type = node_type
            self._state.last_updated = datetime.now()
    
    def add_new_node(self, name: str) -> NodeInfo:
        """Add a new node with unknown type."""
        if not self._state:
            self.load()
        
        now = datetime.now()
        node = NodeInfo(
            name=name,
            first_seen=now,
            last_seen=now,
            type=NodeType.UNKNOWN,
            status=NodeStatus.ACTIVE
        )
        self._state.nodes[name] = node
        self._state.last_updated = now
        return node
    
    def get_all_nodes(self) -> dict[str, NodeInfo]:
        """Get all nodes."""
        if not self._state:
            self.load()
        return self._state.nodes
    
    def get_counts(self) -> tuple[int, int, int]:
        """Get (total, active, inactive) counts."""
        if not self._state:
            self.load()
        
        total = len(self._state.nodes)
        active = sum(1 for n in self._state.nodes.values() if n.status == NodeStatus.ACTIVE)
        inactive = total - active
        
        return total, active, inactive
    
    def _create_empty_state(self) -> NodeState:
        """Create empty state."""
        return NodeState(
            last_updated=datetime.now(),
            server_id=self.server_id,
            nodes={}
        )
