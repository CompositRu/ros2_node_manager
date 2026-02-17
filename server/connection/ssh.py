"""SSH Docker connection."""

import asyncio
from typing import AsyncIterator, Optional

import asyncssh

from .base import BaseConnection, ConnectionError, ContainerNotFoundError


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
        ros_setup: str = "/opt/ros/humble/setup.bash"
    ):
        super().__init__(container, ros_setup)
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
        """Close SSH connection."""
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
                raise ConnectionError(error_msg)
            
            return result.stdout
            
        except asyncio.TimeoutError:
            raise ConnectionError(f"Command timed out after {timeout}s")
        except asyncssh.Error as e:
            raise ConnectionError(f"SSH command failed: {e}")
    
    async def exec_stream(self, cmd: str) -> AsyncIterator[str]:
        """Execute command and stream output via SSH."""
        if not self._connected or not self._conn:
            raise ConnectionError("Not connected")

        # Use _build_docker_cmd_stream which runs `script` INSIDE the container
        # for unbuffered output (same approach as LocalDockerConnection)
        full_cmd = self._build_docker_cmd_stream(cmd)

        try:
            async with self._conn.create_process(full_cmd) as proc:
                async for line in proc.stdout:
                    stripped = line.rstrip('\n\r')
                    if stripped:
                        yield stripped
        except asyncssh.Error as e:
            print(f"SSH exec_stream error: {e}")
        except Exception as e:
            print(f"exec_stream error: {e}")