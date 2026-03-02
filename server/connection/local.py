"""Local Docker connection."""

import asyncio
from typing import AsyncIterator

from .base import BaseConnection, ConnectionError, ContainerNotFoundError
from ..services.metrics import metrics


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
        """Disconnect and clean up Docker-side processes."""
        await self.cleanup_docker_processes()
        self._connected = False
    
    async def exec_command(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute command in local Docker container."""
        if not self._connected:
            raise ConnectionError("Not connected")

        full_cmd = self._build_docker_cmd(cmd)
        metrics.subprocess_started()

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
                if "No such container" in error_msg:
                    self._connected = False
                    raise ContainerNotFoundError(f"Container '{self.container}' not found or stopped")
                if self._env_cached and self._ENV_CACHE_FILE in error_msg:
                    print(f"⚠ ROS env cache lost, falling back to full sourcing")
                    self._env_cached = False
                    result = await self.exec_command(cmd, timeout)
                    asyncio.ensure_future(self.cache_ros_env())
                    return result
                raise ConnectionError(error_msg)

            return stdout.decode()

        except asyncio.TimeoutError:
            raise ConnectionError(f"Command timed out after {timeout}s")
        except Exception as e:
            raise ConnectionError(f"Command execution failed: {e}")
        finally:
            metrics.subprocess_finished()
    
    async def exec_host_command(self, cmd: str, timeout: float = 15.0) -> str:
        """Execute command on local host (outside Docker)."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                raise ConnectionError(stderr.decode().strip() or f"Host command failed with code {proc.returncode}")
            return stdout.decode()
        except asyncio.TimeoutError:
            raise ConnectionError(f"Host command timed out after {timeout}s")

    async def exec_stream(self, cmd: str) -> AsyncIterator[str]:
        """Execute command and stream output line by line.

        The first output line is a ``__PID__<n>`` marker injected by
        ``_build_docker_cmd_stream``.  We capture it to track the
        Docker-side PID so we can kill the process on cleanup.
        """
        if not self._connected:
            raise ConnectionError("Not connected")

        full_cmd = self._build_docker_cmd_stream(cmd)
        docker_pid: int | None = None

        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        metrics.stream_started()

        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode().rstrip('\n\r')
                if not decoded:
                    continue
                # Extract Docker-side PID from the first marker line
                if docker_pid is None and decoded.startswith("__PID__"):
                    try:
                        docker_pid = int(decoded[7:])
                        self._register_docker_pid(docker_pid)
                    except ValueError:
                        yield decoded
                    continue
                yield decoded
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"exec_stream error: {e}")
        finally:
            metrics.stream_finished()
            # 1. Kill the process INSIDE Docker (the key fix)
            if docker_pid is not None:
                self._unregister_docker_pid(docker_pid)
                try:
                    await asyncio.shield(self._kill_docker_pid(docker_pid))
                except Exception:
                    pass
            # 2. Kill the host-side docker exec process
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except ProcessLookupError:
                pass
            except Exception:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def _kill_docker_pid(self, pid: int) -> None:
        """Kill a process inside the Docker container (no ROS env needed)."""
        try:
            kill_proc = await asyncio.create_subprocess_shell(
                f"docker exec {self.container} kill {pid} 2>/dev/null",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(kill_proc.wait(), timeout=3.0)
        except Exception:
            pass

    async def _kill_docker_pids(self, pids_str: str) -> None:
        """Kill multiple processes inside Docker container."""
        try:
            kill_proc = await asyncio.create_subprocess_shell(
                f"docker exec {self.container} bash -c 'kill {pids_str} 2>/dev/null; true'",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(kill_proc.wait(), timeout=5.0)
        except Exception:
            pass

