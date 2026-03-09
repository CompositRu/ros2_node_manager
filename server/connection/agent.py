"""Agent-based connection via WebSocket to monitoring_agent ROS2 node.

Connects to monitoring_agent over WebSocket using JSON-RPC 2.0.
All ROS2 operations use direct agent API calls.
Services use subscribe_json() for native JSON streaming (logs, diagnostics, echo).
exec_stream handles only topic.hz.
"""

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, AsyncIterator, Optional

if TYPE_CHECKING:
    from ..services.droppable_queue import DroppableQueue

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class ConnectionError(Exception):
    """Connection error."""
    pass


class ContainerNotFoundError(ConnectionError):
    """Container not found or stopped."""
    pass


_JSONRPC = "2.0"

# Channel-dependent queue sizes: critical channels get larger buffers,
# high-frequency data channels get smaller buffers (drops acceptable).
_CHANNEL_QUEUE_SIZES = {
    'logs': 2000,           # critical — large buffer to avoid losing log entries
    'diagnostics': 1000,    # critical — large buffer for diagnostic data
    'mrm_state': 500,       # critical — safety state must not be lost
    'topic.speed': 50,      # critical — dashboard speed, low traffic (single topic)
    'topic.echo': 200,      # data-heavy, high-frequency — smaller buffer, drops OK
    'topic.hz': 100,        # low traffic, periodic stats
}


class AgentConnection:
    """Connection to monitoring_agent ROS2 node via WebSocket."""

    def __init__(self, agent_url: str):
        self._agent_url = agent_url
        self._ws: Optional[WebSocketClientProtocol] = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._subscription_queues: dict[str, 'DroppableQueue'] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._reconnect_delay = 1.0
        self._connected = False
        self._disconnect_event = asyncio.Event()
        self._connect_event = asyncio.Event()
        self.container = ""

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Connect to the monitoring agent WebSocket server."""
        try:
            self._ws = await websockets.connect(
                self._agent_url,
                max_size=2 * 1024 * 1024,
                ping_interval=10,
                ping_timeout=30,
            )
            self._connected = True
            self._disconnect_event.clear()
            self._connect_event.set()
            self._reader_task = asyncio.create_task(self._reader_loop())
            logger.info(f'Connected to monitoring agent at {self._agent_url}')
        except Exception as e:
            self._connected = False
            self._connect_event.clear()
            raise ConnectionError(f'Failed to connect to agent at {self._agent_url}: {e}')

    async def wait_connected(self) -> None:
        """Wait until the connection is (re)established."""
        await self._connect_event.wait()

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._connected = False
        self._connect_event.clear()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError('Disconnected'))
        self._pending.clear()
        logger.info('Disconnected from monitoring agent')

    async def cache_ros_env(self) -> None:
        """No-op: agent handles its own ROS environment."""
        pass

    async def cleanup_docker_processes(self) -> None:
        """No-op: agent manages its own processes."""
        pass

    # === Low-level JSON-RPC ===

    async def _call(self, method: str, params: dict = None, timeout: float = 30.0):
        """Send a JSON-RPC request and wait for the response."""
        if not self._ws or not self._connected:
            raise ConnectionError('Not connected to agent')

        self._request_id += 1
        req_id = self._request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future

        msg = json.dumps({
            'jsonrpc': _JSONRPC,
            'method': method,
            'params': params or {},
            'id': req_id,
        })

        try:
            await self._ws.send(msg)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except ConnectionError:
            self._pending.pop(req_id, None)
            raise
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise ConnectionError(f'Agent call {method} timed out after {timeout}s')
        except websockets.exceptions.ConnectionClosed:
            self._connected = False
            self._connect_event.clear()
            self._pending.pop(req_id, None)
            raise ConnectionError('Agent connection lost')

    async def _subscribe(self, channel: str, params: dict = None) -> str:
        """Subscribe to a data channel. Returns subscription ID."""
        result = await self._call('subscribe', {
            'channel': channel,
            'params': params or {},
        })
        from ..services.droppable_queue import DroppableQueue
        sub_id = result['subscription']
        maxsize = _CHANNEL_QUEUE_SIZES.get(channel, 500)
        self._subscription_queues[sub_id] = DroppableQueue(maxsize=maxsize)
        return sub_id

    async def _unsubscribe(self, sub_id: str) -> None:
        """Unsubscribe from a data channel."""
        try:
            await self._call('unsubscribe', {'subscription': sub_id}, timeout=5.0)
        except Exception:
            pass
        self._subscription_queues.pop(sub_id, None)

    async def _reader_loop(self) -> None:
        """Background task: read WebSocket messages and dispatch, with auto-reconnect."""
        delay = self._reconnect_delay
        max_delay = 30.0

        while True:
            try:
                async for raw in self._ws:
                    delay = self._reconnect_delay
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if 'id' in msg and msg['id'] is not None:
                        req_id = msg['id']
                        fut = self._pending.pop(req_id, None)
                        if fut and not fut.done():
                            if 'error' in msg:
                                err = msg['error']
                                fut.set_exception(ConnectionError(
                                    f"Agent error {err.get('code')}: {err.get('message')}"
                                ))
                            else:
                                fut.set_result(msg.get('result'))

                    elif msg.get('method') == 'event':
                        params = msg.get('params', {})
                        sub_id = params.get('subscription', '')
                        queue = self._subscription_queues.get(sub_id)
                        if queue:
                            queue.put_nowait(params.get('data'))

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f'Agent WebSocket connection lost: {e}')

            self._connected = False
            self._connect_event.clear()
            # Notify all active subscribe_json() / exec_stream() iterators about disconnect
            self._disconnect_event.set()
            for queue in self._subscription_queues.values():
                try:
                    queue.put_nowait(None)  # sentinel
                except Exception:
                    pass
            self._subscription_queues.clear()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError('Connection lost'))
            self._pending.clear()

            logger.info(f'Reconnecting to agent in {delay:.0f}s...')
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

            try:
                self._ws = await websockets.connect(
                    self._agent_url,
                    max_size=2 * 1024 * 1024,
                    ping_interval=10,
                    ping_timeout=30,
                )
                self._connected = True
                self._disconnect_event.clear()
                self._connect_event.set()
                delay = self._reconnect_delay
                logger.info(f'Reconnected to monitoring agent at {self._agent_url}')
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f'Reconnect failed: {e}')

    # === High-level streaming ===

    async def subscribe_json(self, channel: str, params: dict = None) -> AsyncIterator[dict]:
        """Subscribe to an agent channel and yield raw JSON data."""
        if not self._connected:
            raise ConnectionError('Not connected')

        sub_id = None
        try:
            sub_id = await self._subscribe(channel, params or {})
            queue = self._subscription_queues.get(sub_id)

            disconnect_task = asyncio.ensure_future(self._disconnect_event.wait())
            try:
                while self._connected:
                    get_task = asyncio.ensure_future(queue.get())

                    done, pending = await asyncio.wait(
                        [get_task, disconnect_task],
                        timeout=60.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # Only cancel get_task if pending — never cancel disconnect_task
                    # (it's reused across iterations; cancelling it would make it
                    # appear in `done` on the next asyncio.wait call).
                    if get_task in pending:
                        get_task.cancel()

                    if disconnect_task in done:
                        get_task.cancel()
                        raise ConnectionError('Agent connection lost')

                    if not done:
                        continue

                    data = get_task.result()
                    if data is None:  # sentinel
                        raise ConnectionError('Agent connection lost')
                    yield data
            finally:
                disconnect_task.cancel()
        except asyncio.CancelledError:
            raise
        except ConnectionError:
            raise
        except Exception as e:
            logger.error(f'subscribe_json error ({channel}): {e}')
        finally:
            if sub_id:
                await self._unsubscribe(sub_id)

    async def exec_stream(self, cmd: str) -> AsyncIterator[str]:
        """Translate a streaming ROS2 CLI command to agent subscription.

        Currently only handles 'ros2 topic hz' commands.
        """
        if not self._connected:
            raise ConnectionError('Not connected')

        sub_id = None
        try:
            channel, params = self._parse_stream_command(cmd)
            sub_id = await self._subscribe(channel, params)
            queue = self._subscription_queues.get(sub_id)

            disconnect_task = asyncio.ensure_future(self._disconnect_event.wait())
            try:
                while self._connected:
                    get_task = asyncio.ensure_future(queue.get())

                    done, pending = await asyncio.wait(
                        [get_task, disconnect_task],
                        timeout=60.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if get_task in pending:
                        get_task.cancel()

                    if disconnect_task in done:
                        get_task.cancel()
                        raise ConnectionError('Agent connection lost')

                    if not done:
                        continue

                    data = get_task.result()
                    if data is None:  # sentinel
                        raise ConnectionError('Agent connection lost')

                    if channel == 'topic.hz':
                        hz = data.get('hz', 0.0)
                        if hz > 0:
                            yield f'average rate: {hz:.3f}'
            finally:
                disconnect_task.cancel()
        except asyncio.CancelledError:
            raise
        except ConnectionError:
            raise
        except Exception as e:
            logger.error(f'exec_stream error: {e}')
        finally:
            if sub_id:
                await self._unsubscribe(sub_id)

    async def exec_command(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute a command by translating to agent RPC calls."""
        cmd = cmd.strip()
        return await self._translate_command(cmd, timeout)

    # === ROS2 API methods ===

    async def ros2_node_list(self, timeout: float = 10.0) -> list[str]:
        return await self._call('graph.nodes', timeout=timeout)

    async def ros2_node_info(self, node_name: str) -> dict:
        return await self._call('graph.node_info', {'node': node_name})

    async def ros2_param_dump(self, node_name: str) -> dict:
        try:
            return await self._call('params.dump', {'node': node_name})
        except Exception as e:
            logger.error(f'Error getting params for {node_name}: {e}')
            return {}

    async def ros2_topic_list(self, timeout: float = 10.0) -> list[dict]:
        return await self._call('graph.topics', timeout=timeout)

    async def ros2_topic_info(self, topic_name: str) -> dict:
        return await self._call('graph.topic_info', {'topic': topic_name})

    async def ros2_service_list(self, timeout: float = 10.0) -> list[str]:
        return await self._call('graph.services', timeout=timeout)

    async def ros2_service_list_typed(self) -> list[dict]:
        return await self._call('graph.services_typed')

    async def ros2_interface_show(self, interface_type: str) -> str:
        result = await self._call('graph.interface_show', {'type': interface_type})
        return result.get('definition', '')

    async def ros2_service_call(self, service_name: str, service_type: str,
                                request_yaml: str) -> str:
        import yaml
        try:
            request_dict = yaml.safe_load(request_yaml) or {}
        except Exception:
            request_dict = {}
        result = await self._call('service.call', {
            'service': service_name,
            'type': service_type,
            'request': request_dict,
        })
        return json.dumps(result.get('response', {}), indent=2)

    async def is_lifecycle_node(self, node_name: str) -> bool:
        result = await self._call('lifecycle.is_lifecycle', {'node': node_name})
        return result.get('is_lifecycle', False)

    async def ros2_lifecycle_get_state(self, node_name: str) -> Optional[str]:
        try:
            result = await self._call('lifecycle.get_state', {'node': node_name})
            return result.get('state')
        except Exception as e:
            logger.error(f'Error getting lifecycle state for {node_name}: {e}')
            return None

    async def ros2_lifecycle_set(self, node_name: str, transition: str) -> tuple[bool, str]:
        try:
            result = await self._call('lifecycle.set_state', {
                'node': node_name,
                'transition': transition,
            })
            return result.get('success', False), result.get('message', '')
        except Exception as e:
            return False, str(e)

    async def kill_process(self, pattern: str) -> bool:
        try:
            result = await self._call('process.kill', {'pattern': pattern})
            return result.get('success', False)
        except Exception:
            return False

    async def get_agent_stats(self) -> dict | None:
        try:
            return await self._call('system.stats', timeout=5.0)
        except Exception:
            return None

    async def get_agent_resources(self) -> dict | None:
        try:
            return await self._call('system.resources', timeout=10.0)
        except Exception:
            return None

    def invalidate_services_cache(self) -> None:
        pass

    # === Command translation helpers ===

    async def _translate_command(self, cmd: str, timeout: float) -> str:
        """Translate a ros2 CLI command string to an agent RPC call."""
        if cmd.startswith('ros2 topic list'):
            if '-t' in cmd:
                topics = await self.ros2_topic_list(timeout=timeout)
                return '\n'.join(f"{t['name']} [{t['type']}]" for t in topics)
            else:
                topics = await self.ros2_topic_list(timeout=timeout)
                return '\n'.join(t['name'] for t in topics)

        if cmd.startswith('ros2 node list'):
            nodes = await self.ros2_node_list(timeout=timeout)
            return '\n'.join(nodes)

        if cmd.startswith('ros2 service list'):
            if '-t' in cmd:
                services = await self.ros2_service_list_typed()
                return '\n'.join(f"{s['name']} [{s['type']}]" for s in services)
            else:
                services = await self.ros2_service_list(timeout=timeout)
                return '\n'.join(services)

        m = re.match(r'ros2 topic echo\s+(\S+).*--once', cmd)
        if m:
            topic = m.group(1)
            if topic == '/api/fail_safe/mrm_state':
                channel, params = 'mrm_state', {}
            else:
                channel, params = 'topic.echo', {'topic': topic}
            sub_id = await self._subscribe(channel, params)
            queue = self._subscription_queues.get(sub_id)
            try:
                data = await asyncio.wait_for(queue.get(), timeout=timeout)
                return '\n'.join(self._json_to_yaml_lines(data.get('data', {})))
            finally:
                await self._unsubscribe(sub_id)

        m = re.match(r'ros2 node info\s+(\S+)', cmd)
        if m:
            info = await self.ros2_node_info(m.group(1))
            return self._format_node_info(info)

        m = re.match(r'ros2 lifecycle get\s+(\S+)', cmd)
        if m:
            state = await self.ros2_lifecycle_get_state(m.group(1))
            return state or 'unknown'

        raise ConnectionError(f'Command not supported: {cmd[:80]}')

    def _parse_stream_command(self, cmd: str) -> tuple[str, dict]:
        m = re.match(r'ros2 topic hz\s+(\S+)', cmd)
        if m:
            return 'topic.hz', {'topic': m.group(1)}
        raise ConnectionError(f'Cannot parse stream command: {cmd[:80]}')

    @staticmethod
    def _json_to_yaml_lines(data, indent: int = 0) -> list[str]:
        """Convert JSON data to YAML-like lines recursively."""
        prefix = '  ' * indent
        lines = []
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict):
                    lines.append(f'{prefix}{key}:')
                    lines.extend(AgentConnection._json_to_yaml_lines(value, indent + 1))
                elif isinstance(value, list):
                    lines.append(f'{prefix}{key}:')
                    lines.extend(AgentConnection._list_to_yaml_lines(value, indent))
                else:
                    lines.append(f'{prefix}{key}: {value}')
        elif isinstance(data, list):
            lines.extend(AgentConnection._list_to_yaml_lines(data, indent))
        return lines

    @staticmethod
    def _list_to_yaml_lines(items: list, indent: int) -> list[str]:
        prefix = '  ' * indent
        lines = []
        for item in items:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    if first:
                        leader = f'{prefix}- {k}:'
                        first = False
                    else:
                        leader = f'{prefix}  {k}:'
                    if isinstance(v, (dict, list)):
                        lines.append(leader)
                        lines.extend(AgentConnection._json_to_yaml_lines(v, indent + 2))
                    else:
                        lines.append(f'{leader} {v}')
            else:
                lines.append(f'{prefix}- {item}')
        return lines

    @staticmethod
    def _format_node_info(info: dict) -> str:
        lines = ['  Subscribers:']
        for t in info.get('subscribers', []):
            lines.append(f'    {t}')
        lines.append('  Publishers:')
        for t in info.get('publishers', []):
            lines.append(f'    {t}')
        lines.append('  Service Servers:')
        for s in info.get('services', []):
            lines.append(f'    {s}')
        return '\n'.join(lines)
