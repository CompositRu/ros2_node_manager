"""Base connection class for Docker command execution."""

from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator


class ConnectionError(Exception):
    """Connection error."""
    pass


class BaseConnection(ABC):
    """Abstract base class for Docker connections."""
    
    def __init__(self, container: str, ros_setup: str = "/opt/ros/humble/setup.bash"):
        self.container = container
        self.ros_setup = ros_setup
        self._connected = False
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        pass
    
    @abstractmethod
    async def exec_command(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute command in Docker container and return output."""
        pass
    
    @abstractmethod
    async def exec_stream(self, cmd: str) -> AsyncIterator[str]:
        """Execute command and stream output line by line."""
        pass
    
    def _build_docker_cmd(self, cmd: str) -> str:
        """Build full docker exec command with ROS setup."""
        escaped_cmd = cmd.replace("'", "'\"'\"'")
        # Читаем ROS_DOMAIN_ID из файла, устанавливаем ROS окружение
        ros_env = (
            'ROS_DOMAIN_ID=$(cat $HOME/tram.autoware/.ros_domain_id 2>/dev/null || echo 0) && '
            'export ROS_DOMAIN_ID && '
            'export ROS_LOCALHOST_ONLY=1'
        )
        return f"docker exec {self.container} bash -c '{ros_env} && source {self.ros_setup} && {escaped_cmd}'"
    
    # === ROS2 CLI wrappers ===
    
    async def ros2_node_list(self) -> list[str]:
        """Get list of running nodes."""
        output = await self.exec_command("ros2 node list")
        # print(f"DEBUG ros2_node_list raw output: '{output}'")  # <-- добавь это
        # print(f"DEBUG output repr: {repr(output)}")  # <-- и это
        nodes = []
        for line in output.strip().split("\n"):
            line = line.strip()
            # print(f"DEBUG line: '{line}' startswith /: {line.startswith('/')}")  # <-- и это
            # Только строки начинающиеся с / — это имена нод
            if line.startswith("/"):
                nodes.append(line)
        # print(f"DEBUG final nodes: {nodes}")  # <-- и это
        return nodes
    
    async def ros2_node_info(self, node_name: str) -> dict:
        """Get node info (subscribers, publishers, services)."""
        output = await self.exec_command(f"ros2 node info {node_name}")
        return self._parse_node_info(output)
    
    async def ros2_param_dump(self, node_name: str) -> dict:
        """Get all parameters of a node."""
        try:
            output = await self.exec_command(f"ros2 param dump {node_name} --print")
            import yaml
            data = yaml.safe_load(output)
            # Extract parameters from the nested structure
            if data and node_name.lstrip('/').replace('/', '.') in str(data):
                # Find the ros__parameters section
                for key in data:
                    if 'ros__parameters' in data.get(key, {}):
                        return data[key]['ros__parameters']
            return data or {}
        except Exception:
            return {}
    
    async def ros2_service_list(self) -> list[str]:
        """Get list of services."""
        output = await self.exec_command("ros2 service list")
        services = [s.strip() for s in output.strip().split("\n") if s.strip()]
        return services
    
    async def is_lifecycle_node(self, node_name: str) -> bool:
        """Check if node is a lifecycle node."""
        services = await self.ros2_service_list()
        get_state_service = f"{node_name}/get_state"
        return get_state_service in services
    
    async def ros2_lifecycle_get_state(self, node_name: str) -> Optional[str]:
        """Get lifecycle state of a node."""
        try:
            output = await self.exec_command(f"ros2 lifecycle get {node_name}")
            # Output format: "current state: active" or similar
            if "current state:" in output.lower():
                state = output.split(":")[-1].strip().lower()
                return state
            return None
        except Exception:
            return None
    
    async def ros2_lifecycle_set(self, node_name: str, transition: str) -> bool:
        """Set lifecycle state (activate, deactivate, shutdown, etc.)."""
        try:
            await self.exec_command(f"ros2 lifecycle set {node_name} {transition}")
            return True
        except Exception:
            return False
    
    async def kill_process(self, pattern: str) -> bool:
        """Try to kill a process by pattern (inside Docker)."""
        try:
            # Find PID
            output = await self.exec_command(f"pgrep -f '{pattern}'")
            pids = [p.strip() for p in output.strip().split("\n") if p.strip()]
            
            if not pids:
                return False
            
            # Kill first matching PID
            await self.exec_command(f"kill {pids[0]}")
            return True
        except Exception:
            return False
    
    def _parse_node_info(self, output: str) -> dict:
        """Parse ros2 node info output."""
        result = {
            "subscribers": [],
            "publishers": [],
            "services": [],
            "actions": []
        }
        
        current_section = None
        
        for line in output.split("\n"):
            line = line.strip()
            
            if "Subscribers:" in line:
                current_section = "subscribers"
            elif "Publishers:" in line:
                current_section = "publishers"
            elif "Service Servers:" in line or "Services:" in line:
                current_section = "services"
            elif "Action Servers:" in line:
                current_section = "actions"
            elif "Action Clients:" in line:
                current_section = None  # Skip action clients
            elif "Service Clients:" in line:
                current_section = None  # Skip service clients
            elif line.startswith("/") and current_section:
                # Extract topic/service name (before the colon if present)
                name = line.split(":")[0].strip()
                result[current_section].append(name)
        
        return result
