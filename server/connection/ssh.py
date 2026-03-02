"""SSH Docker connection."""

import asyncio
from typing import AsyncIterator, Optional

import asyncssh

from .base import BaseConnection, ConnectionError, ContainerNotFoundError
from ..services.metrics import metrics


class SSHDockerConnection(BaseConnection):
    """Connection to Docker container on remote server via SSH."""
    
    def __init__(
        self,
        container: str,
        host: str,
        user: str,
        port: int = 22,
        ssh_key: Optional[str] = None,
        password: Optional[str] = None,
        ros_setup: str = "/opt/ros/humble/setup.bash",
        ros_workspace: Optional[str] = None,
    ):
        super().__init__(container, ros_setup, ros_workspace=ros_workspace)
        self.host = host
        self.user = user
        self.port = port
        self.ssh_key = ssh_key
        self.password = password
        self._conn: Optional[asyncssh.SSHClientConnection] = None
    
    async def connect(self) -> None:
        """Establish SSH connection and verify Docker container."""
        try:
            # Build connection options
            connect_opts = {
                "host": self.host,
                "port": self.port,
                "username": self.user,
                "known_hosts": None,  # Disable host key checking (dev mode)
            }
            
            if self.ssh_key:
                connect_opts["client_keys"] = [self.ssh_key]
            elif self.password:
                connect_opts["password"] = self.password
            
            # Connect
            self._conn = await asyncssh.connect(**connect_opts)
            
            # Verify container is running
            result = await self._conn.run(
                f"docker inspect {self.container} --format '{{{{.State.Running}}}}'"
            )
            
            if result.exit_status != 0:
                raise ConnectionError(f"Container '{self.container}' not found on {self.host}")
            
            if result.stdout.strip().lower() != "true":
                raise ConnectionError(f"Container '{self.container}' is not running on {self.host}")
            
            self._connected = True
            
        except asyncssh.Error as e:
            self._connected = False
            raise ConnectionError(f"SSH connection failed: {e}")
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect: {e}")
    
    async def disconnect(self) -> None:
        """Close SSH connection and clean up Docker-side processes."""
        # Kill Docker processes before closing SSH
        if self._conn and self._connected:
            await self.cleanup_docker_processes()
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
        self._connected = False
    
    async def exec_command(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute command in Docker container on remote server."""
        if not self._connected or not self._conn:
            raise ConnectionError("Not connected")

        full_cmd = self._build_docker_cmd(cmd)
        metrics.subprocess_started()

        try:
            result = await asyncio.wait_for(
                self._conn.run(full_cmd),
                timeout=timeout
            )

            if result.exit_status != 0:
                error_msg = result.stderr.strip() or f"Command failed with code {result.exit_status}"
                if "No such container" in error_msg:
                    self._connected = False
                    raise ContainerNotFoundError(f"Container '{self.container}' not found or stopped")
                if self._env_cached and self._ENV_CACHE_FILE in error_msg:
                    print(f"⚠ ROS env cache lost, falling back to full sourcing")
                    self._env_cached = False
                    result_str = await self.exec_command(cmd, timeout)
                    asyncio.ensure_future(self.cache_ros_env())
                    return result_str
                raise ConnectionError(error_msg)

            return result.stdout

        except asyncio.TimeoutError:
            raise ConnectionError(f"Command timed out after {timeout}s")
        except asyncssh.Error as e:
            raise ConnectionError(f"SSH command failed: {e}")
        finally:
            metrics.subprocess_finished()
    
    async def exec_host_command(self, cmd: str, timeout: float = 15.0) -> str:
        """Execute command on remote host (outside Docker) via SSH."""
        if not self._connected or not self._conn:
            raise ConnectionError("Not connected")
        try:
            result = await asyncio.wait_for(self._conn.run(cmd), timeout=timeout)
            if result.exit_status != 0:
                raise ConnectionError(result.stderr.strip() or f"Host command failed with code {result.exit_status}")
            return result.stdout
        except asyncio.TimeoutError:
            raise ConnectionError(f"Host command timed out after {timeout}s")
        except asyncssh.Error as e:
            raise ConnectionError(f"SSH host command failed: {e}")

    async def exec_stream(self, cmd: str) -> AsyncIterator[str]:
        """Execute command and stream output via SSH with PID tracking.

        The first output line is a ``__PID__<n>`` marker.  We capture it
        to track the Docker-side PID for cleanup when the stream ends.
        """
        if not self._connected or not self._conn:
            raise ConnectionError("Not connected")

        full_cmd = self._build_docker_cmd_stream(cmd)
        docker_pid: int | None = None
        metrics.stream_started()

        try:
            async with self._conn.create_process(full_cmd) as proc:
                async for line in proc.stdout:
                    stripped = line.rstrip('\n\r')
                    if not stripped:
                        continue
                    # Extract Docker-side PID from the first marker line
                    if docker_pid is None and stripped.startswith("__PID__"):
                        try:
                            docker_pid = int(stripped[7:])
                            self._register_docker_pid(docker_pid)
                        except ValueError:
                            yield stripped
                        continue
                    yield stripped
        except asyncio.CancelledError:
            raise
        except asyncssh.Error as e:
            print(f"SSH exec_stream error: {e}")
        except Exception as e:
            print(f"exec_stream error: {e}")
        finally:
            metrics.stream_finished()
            # Kill the process INSIDE Docker via SSH
            if docker_pid is not None:
                self._unregister_docker_pid(docker_pid)
                try:
                    await asyncio.shield(self._kill_docker_pid(docker_pid))
                except Exception:
                    pass

    async def _kill_docker_pid(self, pid: int) -> None:
        """Kill a process inside Docker container via SSH."""
        if not self._conn:
            return
        try:
            await asyncio.wait_for(
                self._conn.run(f"docker exec {self.container} kill {pid} 2>/dev/null; true"),
                timeout=3.0,
            )
        except Exception:
            pass

    async def _kill_docker_pids(self, pids_str: str) -> None:
        """Kill multiple processes inside Docker container via SSH."""
        if not self._conn:
            return
        try:
            await asyncio.wait_for(
                self._conn.run(
                    f"docker exec {self.container} bash -c 'kill {pids_str} 2>/dev/null; true'"
                ),
                timeout=5.0,
            )
        except Exception:
            pass