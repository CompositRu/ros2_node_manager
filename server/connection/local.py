"""Local Docker connection."""

import asyncio
from typing import AsyncIterator

from .base import BaseConnection, ConnectionError


class LocalDockerConnection(BaseConnection):
    """Connection to local Docker container."""
    
    async def connect(self) -> None:
        """Check if Docker container is running."""
        try:
            proc = await asyncio.create_subprocess_shell(
                f"docker inspect {self.container} --format '{{{{.State.Running}}}}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                raise ConnectionError(f"Container '{self.container}' not found")
            
            if stdout.decode().strip().lower() != "true":
                raise ConnectionError(f"Container '{self.container}' is not running")
            
            self._connected = True
            
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to local Docker: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect (no-op for local)."""
        self._connected = False
    
    async def exec_command(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute command in local Docker container."""
        if not self._connected:
            raise ConnectionError("Not connected")
        
        full_cmd = self._build_docker_cmd(cmd)
        
        try:
            proc = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )
            
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() or f"Command failed with code {proc.returncode}"
                raise ConnectionError(error_msg)
            
            return stdout.decode()
            
        except asyncio.TimeoutError:
            raise ConnectionError(f"Command timed out after {timeout}s")
        except Exception as e:
            raise ConnectionError(f"Command execution failed: {e}")
    
    async def exec_stream(self, cmd: str) -> AsyncIterator[str]:
        """Execute command and stream output line by line."""
        if not self._connected:
            raise ConnectionError("Not connected")
        
        # Используем -t для pseudo-TTY (меньше буферизации)
        full_cmd = self._build_docker_cmd_stream(cmd)
        
        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Merge stderr to stdout
        )
        
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode().rstrip('\n\r')
                if decoded:  # Skip empty lines
                    yield decoded
        except Exception as e:
            print(f"exec_stream error: {e}")
        finally:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except:
                proc.kill()

    def _build_docker_cmd_stream(self, cmd: str) -> str:
        """Build docker exec command for streaming (with pseudo-TTY)."""
        escaped_cmd = cmd.replace("'", "'\"'\"'")
        ros_env = (
            'ROS_DOMAIN_ID=$(cat $HOME/tram.autoware/.ros_domain_id 2>/dev/null || echo 0) && '
            'export ROS_DOMAIN_ID && '
            'export ROS_LOCALHOST_ONLY=1 && '
            'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp'
        )
        return f"docker exec {self.container} script -q -c \"bash -c '{ros_env} && source {self.ros_setup} && {escaped_cmd}'\" /dev/null"
