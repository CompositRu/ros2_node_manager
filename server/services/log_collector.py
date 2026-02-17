"""Log collector service for streaming ROS2 logs."""

import asyncio
import re
from datetime import datetime
from typing import AsyncIterator, Optional
from collections import defaultdict

from ..connection import BaseConnection, ConnectionError
from ..models import LogMessage


class LogCollector:
    """
    Collects logs from /rosout topic and streams to subscribers.
    
    Uses: ros2 topic echo /rosout --no-arr
    Then filters by node name.
    """
    
    def __init__(self, connection: BaseConnection):
        self.conn = connection
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._all_subscribers: set[asyncio.Queue] = set()
        
        # Regex to parse rosout messages
        # Format varies, but typically contains:
        # stamp: {sec: X, nanosec: Y}
        # level: N (where 10=DEBUG, 20=INFO, 30=WARN, 40=ERROR, 50=FATAL)
        # name: '/node_name'
        # msg: 'message'
        self._level_map = {
            10: "DEBUG",
            20: "INFO",
            30: "WARN",
            40: "ERROR",
            50: "FATAL"
        }
    
    async def start(self) -> None:
        """Start collecting logs."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
    
    async def stop(self) -> None:
        """Stop collecting logs."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
    
    def subscribe(self, node_name: str, queue: asyncio.Queue) -> None:
        """Subscribe to logs for a specific node."""
        self._subscribers[node_name].add(queue)
    
    def unsubscribe(self, node_name: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from logs."""
        self._subscribers[node_name].discard(queue)
        if not self._subscribers[node_name]:
            del self._subscribers[node_name]
    
    def subscribe_all(self, queue: asyncio.Queue) -> None:
        """Subscribe to all logs."""
        self._all_subscribers.add(queue)
    
    def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from all logs."""
        self._all_subscribers.discard(queue)
    
    async def _collect_loop(self) -> None:
        """Main loop for collecting logs."""
        while self._running:
            try:
                # Only collect if there are subscribers
                if not self._subscribers and not self._all_subscribers:
                    await asyncio.sleep(1)
                    continue
                
                # Stream logs from /rosout
                cmd = "ros2 topic echo /rosout --no-arr"
                
                buffer = []
                async for line in self.conn.exec_stream(cmd):
                    if not self._running:
                        break
                    
                    # Accumulate lines until we have a complete message
                    buffer.append(line)
                    
                    # Check if we have a complete message (ends with ---)
                    if line.strip() == "---":
                        msg = self._parse_rosout_message("\n".join(buffer))
                        buffer = []
                        
                        if msg:
                            await self._dispatch_message(msg)
                
            except ConnectionError as e:
                print(f"Log collector connection error: {e}")
                await asyncio.sleep(5)  # Wait before retry
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Log collector error: {e}")
                await asyncio.sleep(5)
    
    def _parse_rosout_message(self, text: str) -> Optional[LogMessage]:
        """Parse a rosout message from ros2 topic echo output."""
        try:
            # Extract fields using regex
            # stamp
            stamp_match = re.search(r"sec:\s*(\d+)", text)
            nanosec_match = re.search(r"nanosec:\s*(\d+)", text)
            
            # level
            level_match = re.search(r"level:\s*(\d+)", text)
            
            # name (node name)
            name_match = re.search(r"name:\s*['\"]?([^'\"}\n]+)['\"]?", text)
            
            # msg
            msg_match = re.search(r"msg:\s*['\"]?([^'\"}\n]*)['\"]?", text)
            
            if not all([stamp_match, level_match, name_match, msg_match]):
                return None
            
            # Build timestamp
            sec = int(stamp_match.group(1))
            nanosec = int(nanosec_match.group(1)) if nanosec_match else 0
            timestamp = datetime.fromtimestamp(sec + nanosec / 1e9)
            
            # Get level
            level_num = int(level_match.group(1))
            level = self._level_map.get(level_num, "INFO")
            
            # Get node name
            node_name = name_match.group(1).strip()
            
            # Get message
            message = msg_match.group(1).strip()
            
            return LogMessage(
                timestamp=timestamp,
                level=level,
                node_name=node_name,
                message=message
            )
        except Exception:
            return None
    
    async def _dispatch_message(self, msg: LogMessage) -> None:
        """Dispatch log message to subscribers."""
        # Send to node-specific subscribers
        if msg.node_name in self._subscribers:
            for queue in self._subscribers[msg.node_name]:
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    pass  # Drop message if queue is full
        
        # Send to all-subscribers
        for queue in self._all_subscribers:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass


async def stream_node_logs(
    connection: BaseConnection,
    node_name: str
) -> AsyncIterator[LogMessage]:
    """
    Simple generator to stream logs for a specific node.
    Uses grep filtering instead of LogCollector.
    """
    import re
    
    # Extract short name for grep (last part of node name)
    short_name = node_name.split("/")[-1]
    
    # cmd = f"ros2 topic echo /rosout --no-arr"

    # stdbuf -oL отключает буферизацию stdout (line-buffered)
    # cmd = f"stdbuf -oL ros2 topic echo /rosout --no-arr"

    # QoS параметры для получения всех сообщений
    cmd = "ros2 topic echo /rosout --no-arr --qos-reliability best_effort --qos-history keep_last --qos-depth 1000"
    
    buffer = []
    level_map = {10: "DEBUG", 20: "INFO", 30: "WARN", 40: "ERROR", 50: "FATAL"}
    
    try:
        line_count = 0
        async for line in connection.exec_stream(cmd):
            line_count += 1
            if line_count <= 3:
                print(f"DEBUG stream_node_logs: line {line_count}: {line[:100]}")
            buffer.append(line)
            
            # Check for message boundary
            if line.strip() == "---":
                text = "\n".join(buffer)
                buffer = []
                
                # Check if this message is for our node
                if short_name not in text and node_name not in text:
                    continue
                
                # Parse message
                try:
                    stamp_match = re.search(r"sec:\s*(\d+)", text)
                    level_match = re.search(r"level:\s*(\d+)", text)
                    msg_match = re.search(r"msg:\s*['\"]?([^'\"}\n]*)['\"]?", text)
                    
                    if stamp_match and level_match and msg_match:
                        sec = int(stamp_match.group(1))
                        timestamp = datetime.fromtimestamp(sec)
                        level = level_map.get(int(level_match.group(1)), "INFO")
                        message = msg_match.group(1).strip()
                        
                        yield LogMessage(
                            timestamp=timestamp,
                            level=level,
                            node_name=node_name,
                            message=message
                        )
                except Exception:
                    pass
    except Exception as e:
        import traceback
        print(f"Log stream error for {node_name}: {e}")
        traceback.print_exc()
