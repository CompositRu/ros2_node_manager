"""Base connection class for Docker command execution."""

from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator


class ConnectionError(Exception):
    """Connection error."""
    pass


class ContainerNotFoundError(ConnectionError):
    """Container not found or stopped."""
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
    
    def _ros_env(self) -> str:
        """Build ROS environment setup commands."""
        return (
            'ROS_DOMAIN_ID=$(cat $HOME/tram.autoware/.ros_domain_id 2>/dev/null || echo 0) && '
            'export ROS_DOMAIN_ID && '
            'export ROS_LOCALHOST_ONLY=1 && '
            'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && '
            'if [ -z "$CYCLONEDDS_URI" ]; then '
            'export CYCLONEDDS_URI="<CycloneDDS><Domain><Discovery><MaxAutoParticipantIndex>200</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>"; '
            'fi'
        )

    def _build_docker_cmd(self, cmd: str) -> str:
        """Build full docker exec command with ROS setup."""
        escaped_cmd = cmd.replace("'", "'\"'\"'")
        ros_env = self._ros_env()
        return f"docker exec {self.container} bash -c '{ros_env} && source {self.ros_setup} && {escaped_cmd}'"

    def _build_docker_cmd_stream(self, cmd: str) -> str:
        """Build docker exec command for streaming (with unbuffered output)."""
        escaped_cmd = cmd.replace("'", "'\"'\"'")
        ros_env = self._ros_env()
        # PYTHONUNBUFFERED=1 forces unbuffered output for Python-based ROS2 CLI tools
        return f"docker exec {self.container} bash -c 'export PYTHONUNBUFFERED=1 && {ros_env} && source {self.ros_setup} && {escaped_cmd}'"

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
            output = await self.exec_command(f"ros2 param dump {node_name}")
            
            # Filter out the "Git config" line and parse YAML
            lines = output.strip().split('\n')
            filtered_lines = [l for l in lines if not l.startswith('Git config')]
            clean_output = '\n'.join(filtered_lines)
            
            import yaml
            data = yaml.safe_load(clean_output)
            
            if not data:
                return {}
            
            # Structure: {node_name: {ros__parameters: {...}}}
            # We need to extract ros__parameters
            for key, value in data.items():
                if isinstance(value, dict) and 'ros__parameters' in value:
                    return value['ros__parameters']
            
            # If no ros__parameters found, return the whole thing
            return data
            
        except Exception as e:
            import traceback
            print(f"Error getting params for {node_name}: {e}")
            traceback.print_exc()
            return {}
    
    async def ros2_service_list(self) -> list[str]:
        """Get list of services."""
        output = await self.exec_command("ros2 service list")
        services = [s.strip() for s in output.strip().split("\n") if s.strip()]
        return services
        
    async def is_lifecycle_node(self, node_name: str) -> bool:
        """Check if node is a lifecycle node."""
        get_state_service = f"{node_name}/get_state"
        
        # Используем кэшированный список сервисов
        if not hasattr(self, '_services_cache') or self._services_cache is None:
            await self._refresh_services_cache()
        
        return get_state_service in self._services_cache

    async def _refresh_services_cache(self) -> None:
        """Refresh cached list of services."""
        try:
            output = await self.exec_command("ros2 service list", timeout=30.0)
            lines = output.strip().split('\n')
            self._services_cache = set(line.strip() for line in lines if line.strip().startswith('/'))
            # print(f"DEBUG: Cached {len(self._services_cache)} services")
        except Exception as e:
            print(f"Error refreshing services cache: {e}")
            self._services_cache = set()

    def invalidate_services_cache(self) -> None:
        """Invalidate services cache."""
        self._services_cache = None
    
    async def ros2_lifecycle_get_state(self, node_name: str) -> Optional[str]:
        """Get current lifecycle state of a node."""
        try:
            output = await self.exec_command(f"ros2 lifecycle get {node_name}")
            # Filter Git config and parse state
            for line in output.strip().split('\n'):
                line = line.strip()
                if line.startswith('Git config'):
                    continue
                if line:
                    # Format: "active [3]" or "finalized [4]"
                    # Extract just the state name
                    state = line.split('[')[0].strip().lower()
                    return state
            return None
        except Exception as e:
            print(f"Error getting lifecycle state for {node_name}: {e}")
            return None
    
    async def ros2_lifecycle_set(self, node_name: str, transition: str) -> tuple[bool, str]:
        """Set lifecycle state (activate, deactivate, shutdown, etc.)."""
        try:
            output = await self.exec_command(f"ros2 lifecycle set {node_name} {transition}")
            # Filter out Git config line
            lines = [l for l in output.strip().split('\n') if not l.startswith('Git config')]
            clean_output = '\n'.join(lines).strip()
            return True, clean_output or f"Transition '{transition}' successful"
        except Exception as e:
            error_msg = str(e)
            # Filter Git config from error too
            if 'Git config' in error_msg:
                lines = [l for l in error_msg.split('\n') if 'Git config' not in l]
                error_msg = '\n'.join(lines).strip()
            return False, error_msg
    
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
