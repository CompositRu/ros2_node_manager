"""Base connection class for Docker command execution."""

import logging
from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator

logger = logging.getLogger(__name__)


class ConnectionError(Exception):
    """Connection error."""
    pass


class ContainerNotFoundError(ConnectionError):
    """Container not found or stopped."""
    pass


class BaseConnection(ABC):
    """Abstract base class for Docker connections."""

    _ENV_CACHE_FILE = "/tmp/.ros2nm_env_cache"
    _ENV_VARS_TO_CACHE = [
        "AMENT_PREFIX_PATH", "PYTHONPATH", "PATH", "LD_LIBRARY_PATH",
        "CMAKE_PREFIX_PATH", "COLCON_PREFIX_PATH",
        "ROS_DOMAIN_ID", "ROS_LOCALHOST_ONLY", "RMW_IMPLEMENTATION",
        "CYCLONEDDS_URI", "ROS_DISTRO", "ROS_VERSION", "ROS_PYTHON_VERSION",
    ]

    def __init__(self, container: str, ros_setup: str = "/opt/ros/humble/setup.bash",
                 ros_workspace: Optional[str] = None):
        self.container = container
        self.ros_setup = ros_setup
        self.ros_workspace = ros_workspace
        self._connected = False
        self._env_cached = False
        self._active_docker_pids: set[int] = set()
    
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

    @abstractmethod
    async def exec_host_command(self, cmd: str, timeout: float = 15.0) -> str:
        """Execute command on the host machine (outside Docker container)."""
        pass

    def _ros_env(self) -> str:
        """Build ROS environment setup commands.

        ROS_DOMAIN_ID detection order:
        1. Config file ($ros_workspace/.ros_domain_id)
        2. Auto-detect from running ros2 daemon process args (--ros-domain-id N)
        3. Default to 0
        """
        ws = self.ros_workspace or "$HOME/tram.autoware"
        return (
            f'_df=$(cat {ws}/.ros_domain_id 2>/dev/null); '
            '_dp=$(ps -eo args 2>/dev/null | grep -o "ros-domain-id [0-9][0-9]*" | head -1 | cut -d" " -f2); '
            'ROS_DOMAIN_ID=${_df:-${_dp:-0}} && '
            'export ROS_DOMAIN_ID && '
            'export ROS_LOCALHOST_ONLY=1 && '
            'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp'
        )

    def _source_ros(self) -> str:
        """Build ROS source commands (base + workspace overlay if exists)."""
        sources = f"source {self.ros_setup}"
        if self.ros_workspace:
            ws_setup = f"{self.ros_workspace}/install/setup.bash"
            sources += f" && {{ [ -f {ws_setup} ] && source {ws_setup} || true; }}"
        return sources

    async def cache_ros_env(self) -> None:
        """Source ROS workspace once, save env vars to a file inside container.

        Subsequent commands source this small file instead of the heavy workspace,
        cutting docker exec startup from ~20s to near-instant.

        Also tries to capture CYCLONEDDS_URI from a running ROS2 process,
        since the entrypoint may set DDS config not present in setup.bash.
        """
        vars_str = " ".join(self._ENV_VARS_TO_CACHE)
        # `; true` ensures exit code 0 even if some vars don't exist
        cmd = f"declare -p {vars_str} 2>/dev/null > {self._ENV_CACHE_FILE}; true"
        try:
            # First call — uses the slow path (full sourcing) since cache is empty
            await self.exec_command(cmd, timeout=60)
            self._env_cached = True

            # Patch cache with DDS env vars from a running ROS2 process.
            # The entrypoint may set CYCLONEDDS_URI that isn't in setup.bash.
            # Without matching DDS config, ros2 topic echo can't discover publishers.
            await self._patch_cache_from_running_process()

            # Log detected values for debugging
            try:
                info = (await self.exec_command(
                    "echo ROS_DOMAIN_ID=$ROS_DOMAIN_ID CYCLONEDDS_URI=${CYCLONEDDS_URI:0:80}", timeout=5
                )).strip()
                logger.info(f"Cached ROS env to {self._ENV_CACHE_FILE} ({info})")
            except Exception:
                logger.info(f"Cached ROS env to {self._ENV_CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Failed to cache ROS env: {e}")
            self._env_cached = False

    async def _patch_cache_from_running_process(self) -> None:
        """Read DDS env vars from a running ROS2 process and patch the cache.

        /proc/1/environ only has the initial Docker env, not what the
        entrypoint script sets via source/export.  So we find a running
        ROS2 process (e.g. component_container) and read ITS environment
        to capture CYCLONEDDS_URI and other DDS settings.
        """
        patch_vars = ["CYCLONEDDS_URI"]

        try:
            raw = await self.exec_command(
                'pid=$(pgrep -f "component_container|ros2_daemon" | head -1) && '
                '[ -n "$pid" ] && cat /proc/$pid/environ 2>/dev/null | tr "\\0" "\\n"',
                timeout=5,
            )
            if not raw.strip():
                return

            found_env = {}
            for line in raw.strip().split("\n"):
                if "=" in line:
                    key, _, val = line.partition("=")
                    if key in patch_vars and val:
                        found_env[key] = val

            if not found_env:
                return

            patch_lines = []
            for key, val in found_env.items():
                escaped_val = val.replace('"', '\\"')
                patch_lines.append(f'declare -x {key}="{escaped_val}"')

            patch_cmd = " && ".join(
                f"echo '{line}' >> {self._ENV_CACHE_FILE}" for line in patch_lines
            )
            await self.exec_command(patch_cmd, timeout=5)
            logger.info(f"Patched cache from running process: {list(found_env.keys())}")

        except Exception as e:
            # Not critical — DDS may work without patching
            pass

    def _build_docker_cmd(self, cmd: str) -> str:
        """Build full docker exec command with ROS setup."""
        escaped_cmd = cmd.replace("'", "'\"'\"'")
        if self._env_cached:
            return f"docker exec {self.container} bash -c 'source {self._ENV_CACHE_FILE} && {escaped_cmd}'"
        ros_env = self._ros_env()
        source_ros = self._source_ros()
        return f"docker exec {self.container} bash -c '{ros_env} && {source_ros} && {escaped_cmd}'"

    def _build_docker_cmd_stream(self, cmd: str) -> str:
        """Build docker exec command for streaming with PID tracking.

        Injects ``echo __PID__$$ && exec <cmd>`` so the first output line
        carries the Docker-side PID.  ``exec`` replaces bash with the
        actual command, so that PID *is* the ros2 process we need to kill.
        """
        escaped_cmd = cmd.replace("'", "'\"'\"'")
        if self._env_cached:
            return (f"docker exec {self.container} bash -c "
                    f"'export PYTHONUNBUFFERED=1 && source {self._ENV_CACHE_FILE} && echo __PID__$$ && exec {escaped_cmd}'")
        ros_env = self._ros_env()
        source_ros = self._source_ros()
        return (f"docker exec {self.container} bash -c "
                f"'export PYTHONUNBUFFERED=1 && {ros_env} && {source_ros} && echo __PID__$$ && exec {escaped_cmd}'")

    # === Docker-side process cleanup ===

    def _register_docker_pid(self, pid: int) -> None:
        self._active_docker_pids.add(pid)

    def _unregister_docker_pid(self, pid: int) -> None:
        self._active_docker_pids.discard(pid)

    async def cleanup_docker_processes(self) -> None:
        """Kill all tracked processes inside the Docker container."""
        if not self._active_docker_pids:
            return
        pids = list(self._active_docker_pids)
        self._active_docker_pids.clear()
        pids_str = " ".join(str(p) for p in pids)
        logger.info(f"Cleaning up {len(pids)} Docker-side processes: {pids_str}")
        try:
            await self._kill_docker_pids(pids_str)
        except Exception as e:
            logger.warning(f"Docker cleanup failed: {e}")

    @abstractmethod
    async def _kill_docker_pids(self, pids_str: str) -> None:
        """Kill processes inside Docker container by PID string (e.g. '123 456')."""
        pass

    # === ROS2 CLI wrappers ===
    
    async def ros2_node_list(self, timeout: float = 10.0) -> list[str]:
        """Get list of running nodes."""
        output = await self.exec_command("ros2 node list", timeout=timeout)
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
            logger.error(f"Error getting params for {node_name}: {e}")
            traceback.print_exc()
            return {}
    
    async def ros2_topic_list(self, timeout: float = 10.0) -> list[dict]:
        """Get list of all topics with their message types."""
        output = await self.exec_command("ros2 topic list -t", timeout=timeout)
        topics = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line or not line.startswith("/"):
                continue
            if " [" in line and line.endswith("]"):
                bracket_idx = line.rindex(" [")
                name = line[:bracket_idx].strip()
                msg_type = line[bracket_idx + 2:-1]
            else:
                name = line
                msg_type = ""
            topics.append({"name": name, "type": msg_type})
        return topics

    async def ros2_topic_info(self, topic_name: str) -> dict:
        """Get detailed info for a topic: type, publishers, subscribers."""
        output = await self.exec_command(f"ros2 topic info {topic_name} -v")
        return self._parse_topic_info(output)

    def _parse_topic_info(self, output: str) -> dict:
        """Parse ros2 topic info -v output.

        Example output:
            Type: geometry_msgs/msg/Twist

            Publisher count: 2
              Node name: /teleop_turtle
              Node name: /other_node
            Subscription count: 1
              Node name: /turtlesim
        """
        result = {
            "type": "",
            "publishers": [],
            "subscribers": [],
        }

        section = None  # "pub" or "sub"

        for line in output.split("\n"):
            stripped = line.strip()

            if stripped.startswith("Type:"):
                result["type"] = stripped.split("Type:", 1)[1].strip()
            elif "Publisher count:" in stripped:
                section = "pub"
            elif "Subscription count:" in stripped:
                section = "sub"
            elif stripped.startswith("Node name:"):
                node_name = stripped.split("Node name:", 1)[1].strip()
                if section == "pub":
                    result["publishers"].append(node_name)
                elif section == "sub":
                    result["subscribers"].append(node_name)

        return result

    async def ros2_service_list(self, timeout: float = 10.0) -> list[str]:
        """Get list of services."""
        output = await self.exec_command("ros2 service list", timeout=timeout)
        services = [s.strip() for s in output.strip().split("\n") if s.strip()]
        return services

    async def ros2_service_list_typed(self) -> list[dict]:
        """Get list of all services with their interface types."""
        output = await self.exec_command("ros2 service list -t")
        services = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line or not line.startswith("/"):
                continue
            if " [" in line and line.endswith("]"):
                bracket_idx = line.rindex(" [")
                name = line[:bracket_idx].strip()
                srv_type = line[bracket_idx + 2:-1]
            else:
                name = line
                srv_type = ""
            services.append({"name": name, "type": srv_type})
        return services

    async def ros2_interface_show(self, interface_type: str) -> str:
        """Get interface definition (request/response fields for services)."""
        output = await self.exec_command(f"ros2 interface show {interface_type}")
        return output.strip()

    async def ros2_service_call(self, service_name: str, service_type: str, request_yaml: str) -> str:
        """Call a ROS2 service and return the response text."""
        escaped_yaml = request_yaml.replace("'", "'\"'\"'")
        cmd = f"ros2 service call {service_name} {service_type} '{escaped_yaml}'"
        output = await self.exec_command(cmd, timeout=30.0)
        return output.strip()
        
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
            output = await self.exec_command("ros2 service list", timeout=10.0)
            lines = output.strip().split('\n')
            self._services_cache = set(line.strip() for line in lines if line.strip().startswith('/'))
            # print(f"DEBUG: Cached {len(self._services_cache)} services")
        except Exception as e:
            logger.error(f"Error refreshing services cache: {e}")
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
            logger.error(f"Error getting lifecycle state for {node_name}: {e}")
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
