"""Agent-based connection via WebSocket to monitoring_agent ROS2 node.

Replaces docker exec calls with JSON-RPC 2.0 over WebSocket.
All ros2_* methods are overridden to use direct agent API calls.
exec_stream is translated from ROS2 CLI commands to agent subscriptions,
producing YAML-compatible output for backward compatibility with services.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from typing import AsyncIterator, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from .base import BaseConnection, ConnectionError, ContainerNotFoundError

logger = logging.getLogger(__name__)

_JSONRPC = "2.0"


class AgentConnection(BaseConnection):
    """Connection to monitoring_agent ROS2 node via WebSocket."""

    def __init__(self, agent_url: str, **kwargs):
        # Agent mode doesn't need container/ros_setup, but base class requires them
        super().__init__(container=kwargs.get('container', ''), **{
            k: v for k, v in kwargs.items() if k in ('ros_setup', 'ros_workspace')
        })
        self._agent_url = agent_url
        self._ws: Optional[WebSocketClientProtocol] = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._subscription_queues: dict[str, asyncio.Queue] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._reconnect_delay = 1.0

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
            self._reader_task = asyncio.create_task(self._reader_loop())
            logger.info(f'Connected to monitoring agent at {self._agent_url}')
        except Exception as e:
            self._connected = False
            raise ConnectionError(f'Failed to connect to agent at {self._agent_url}: {e}')

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._connected = False
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        # Fail any pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError('Disconnected'))
        self._pending.clear()
        logger.info('Disconnected from monitoring agent')

    # === Low-level JSON-RPC ===

    async def _call(self, method: str, params: dict = None, timeout: float = 30.0):
        """Send a JSON-RPC request and wait for the response."""
        if not self._ws or not self._connected:
            raise ConnectionError('Not connected to agent')

        self._request_id += 1
        req_id = self._request_id
        future = asyncio.get_event_loop().create_future()
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
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise ConnectionError(f'Agent call {method} timed out after {timeout}s')
        except websockets.exceptions.ConnectionClosed:
            self._connected = False
            self._pending.pop(req_id, None)
            raise ConnectionError('Agent connection lost')

    async def _subscribe(self, channel: str, params: dict = None) -> str:
        """Subscribe to a data channel. Returns subscription ID."""
        result = await self._call('subscribe', {
            'channel': channel,
            'params': params or {},
        })
        sub_id = result['subscription']
        self._subscription_queues[sub_id] = asyncio.Queue(maxsize=500)
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
                    delay = self._reconnect_delay  # reset on successful message
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Response to a request
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

                    # Subscription event
                    elif msg.get('method') == 'event':
                        params = msg.get('params', {})
                        sub_id = params.get('subscription', '')
                        queue = self._subscription_queues.get(sub_id)
                        if queue:
                            try:
                                queue.put_nowait(params.get('data'))
                            except asyncio.QueueFull:
                                pass  # Drop oldest if full

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f'Agent WebSocket connection lost: {e}')

            # Connection lost — fail pending requests and clear subscriptions
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError('Connection lost'))
            self._pending.clear()
            self._subscription_queues.clear()

            # Auto-reconnect with exponential backoff
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
                delay = self._reconnect_delay
                logger.info(f'Reconnected to monitoring agent at {self._agent_url}')
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f'Reconnect failed: {e}')
                # Loop continues, will retry with increased delay

    # === BaseConnection abstract methods ===

    async def exec_command(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute a command by translating to agent RPC calls.

        Parses known ros2 CLI patterns and routes to appropriate agent methods.
        For unknown commands, raises an error since agent doesn't support
        arbitrary shell execution.
        """
        cmd = cmd.strip()
        return await self._translate_command(cmd, timeout)

    async def exec_stream(self, cmd: str) -> AsyncIterator[str]:
        """Translate a streaming ROS2 CLI command to agent subscription.

        Converts agent JSON events back to YAML-formatted lines for
        backward compatibility with existing service parsers.
        """
        if not self._connected:
            raise ConnectionError('Not connected')

        sub_id = None

        try:
            # Parse the command to determine subscription type
            channel, params = self._parse_stream_command(cmd)
            # Extract local-only options before sending to agent
            field_path = params.pop('_field_path', None)
            sub_id = await self._subscribe(channel, params)
            queue = self._subscription_queues.get(sub_id)

            while self._connected:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    continue

                # Convert agent JSON data to YAML lines for backward compat
                if channel == 'topic.echo':
                    msg_data = data.get('data', {})
                    # Apply --field extraction (e.g. twist.twist.linear)
                    if field_path:
                        for part in field_path.split('.'):
                            if isinstance(msg_data, dict):
                                msg_data = msg_data.get(part, {})
                            else:
                                msg_data = {}
                                break
                    for line in self._json_to_yaml_lines(msg_data):
                        yield line
                    yield '---'
                elif channel == 'topic.hz':
                    hz = data.get('hz', 0.0)
                    if hz > 0:
                        yield f'average rate: {hz:.3f}'
                elif channel == 'logs':
                    for line in self._log_event_to_yaml(data):
                        yield line
                    yield '---'
                elif channel == 'diagnostics':
                    for line in self._diag_event_to_yaml(data):
                        yield line
                    yield '---'
                elif channel == 'mrm_state':
                    msg_data = data.get('data', {})
                    for line in self._json_to_yaml_lines(msg_data):
                        yield line
                    yield '---'
        except asyncio.CancelledError:
            raise
        except ConnectionError:
            raise
        except Exception as e:
            logger.error(f'exec_stream error: {e}')
        finally:
            if sub_id:
                await self._unsubscribe(sub_id)

    async def exec_host_command(self, cmd: str, timeout: float = 15.0) -> str:
        """Execute command on the host. Not supported in agent mode."""
        raise ConnectionError('Host commands not supported in agent mode')

    async def _kill_docker_pids(self, pids_str: str) -> None:
        """Not applicable in agent mode — processes are managed by the agent."""
        pass

    # === Overridden ROS2 CLI wrappers (direct agent calls) ===

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
        """Get monitoring agent's system stats (CPU, RAM)."""
        try:
            return await self._call('system.stats', timeout=5.0)
        except Exception:
            return None

    async def get_agent_resources(self) -> dict | None:
        """Get container-level resources (CPU, RAM, GPU) for dashboard."""
        try:
            return await self._call('system.resources', timeout=10.0)
        except Exception:
            return None

    # === No-op overrides for agent mode ===

    async def cache_ros_env(self) -> None:
        """No-op: agent handles its own ROS environment."""
        pass

    def invalidate_services_cache(self) -> None:
        """No-op: agent manages its own caches."""
        pass

    async def _refresh_services_cache(self) -> None:
        """No-op: agent manages its own service cache."""
        self._services_cache = set()

    # === Command translation helpers ===

    async def _translate_command(self, cmd: str, timeout: float) -> str:
        """Translate a ros2 CLI command string to an agent RPC call."""
        # ros2 topic list [-t]
        if cmd.startswith('ros2 topic list'):
            if '-t' in cmd:
                topics = await self.ros2_topic_list(timeout=timeout)
                return '\n'.join(
                    f"{t['name']} [{t['type']}]" for t in topics
                )
            else:
                topics = await self.ros2_topic_list(timeout=timeout)
                return '\n'.join(t['name'] for t in topics)

        # ros2 node list
        if cmd.startswith('ros2 node list'):
            nodes = await self.ros2_node_list(timeout=timeout)
            return '\n'.join(nodes)

        # ros2 service list [-t]
        if cmd.startswith('ros2 service list'):
            if '-t' in cmd:
                services = await self.ros2_service_list_typed()
                return '\n'.join(
                    f"{s['name']} [{s['type']}]" for s in services
                )
            else:
                services = await self.ros2_service_list(timeout=timeout)
                return '\n'.join(services)

        # ros2 topic echo {topic} --once
        m = re.match(r'ros2 topic echo\s+(\S+).*--once', cmd)
        if m:
            topic = m.group(1)
            # Route well-known topics to dedicated channels
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

        # ros2 node info {node}
        m = re.match(r'ros2 node info\s+(\S+)', cmd)
        if m:
            info = await self.ros2_node_info(m.group(1))
            return self._format_node_info(info)

        # ros2 lifecycle get {node}
        m = re.match(r'ros2 lifecycle get\s+(\S+)', cmd)
        if m:
            state = await self.ros2_lifecycle_get_state(m.group(1))
            return state or 'unknown'

        # Fallback: unsupported command
        raise ConnectionError(
            f'Command not supported in agent mode: {cmd[:80]}'
        )

    def _parse_stream_command(self, cmd: str) -> tuple[str, dict]:
        """Parse a ros2 streaming command into (channel, params)."""
        # ros2 topic echo {topic} [options]
        m = re.match(r'ros2 topic echo\s+(\S+)', cmd)
        if m:
            topic = m.group(1)
            # Route well-known topics to dedicated agent channels
            if topic == '/diagnostics':
                return 'diagnostics', {}
            if topic == '/rosout':
                return 'logs', {}
            if topic == '/api/fail_safe/mrm_state':
                return 'mrm_state', {}
            no_arr = '--no-arr' in cmd
            # Extract --field option (e.g. --field twist.twist.linear)
            field_match = re.search(r'--field\s+(\S+)', cmd)
            field_path = field_match.group(1) if field_match else None
            return 'topic.echo', {
                'topic': topic, 'no_arr': no_arr,
                '_field_path': field_path,  # local-only, not sent to agent
            }

        # ros2 topic hz {topic}
        m = re.match(r'ros2 topic hz\s+(\S+)', cmd)
        if m:
            return 'topic.hz', {'topic': m.group(1)}

        raise ConnectionError(f'Cannot parse stream command: {cmd[:80]}')

    # === Output formatting helpers ===

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
        """Convert a list to YAML-like lines."""
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
    def _log_event_to_yaml(data: dict) -> list[str]:
        """Convert log event to YAML format matching ros2 topic echo /rosout."""
        ts = data.get('timestamp', 0)
        sec = int(ts)
        nanosec = int((ts - sec) * 1e9)
        level = data.get('level', 0)
        node = data.get('node', '')
        msg = data.get('message', '')
        return [
            'stamp:',
            f'  sec: {sec}',
            f'  nanosec: {nanosec}',
            f'level: {level}',
            f'name: {node}',
            f'msg: {msg}',
        ]

    @staticmethod
    def _diag_event_to_yaml(data: dict) -> list[str]:
        """Convert diagnostics event to YAML format."""
        lines = ['status:']
        for s in data.get('statuses', []):
            lines.append(f'- name: "{s.get("name", "")}"')
            lines.append(f'  level: {s.get("level", 0)}')
            lines.append(f'  message: "{s.get("message", "")}"')
            lines.append(f'  hardware_id: "{s.get("hardware_id", "")}"')
            lines.append('  values:')
            for kv in s.get('values', []):
                lines.append(f'  - key: "{kv.get("key", "")}"')
                lines.append(f'    value: "{kv.get("value", "")}"')
        return lines

    @staticmethod
    def _format_node_info(info: dict) -> str:
        """Format node info dict as ros2 node info output."""
        lines = []
        lines.append('  Subscribers:')
        for t in info.get('subscribers', []):
            lines.append(f'    {t}')
        lines.append('  Publishers:')
        for t in info.get('publishers', []):
            lines.append(f'    {t}')
        lines.append('  Service Servers:')
        for s in info.get('services', []):
            lines.append(f'    {s}')
        return '\n'.join(lines)
