"""Log collector service — single /rosout stream for all consumers."""

import asyncio
import logging
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional, Callable

from ..connection import AgentConnection, ConnectionError
from ..models import LogMessage
from .droppable_queue import DroppableQueue

logger = logging.getLogger(__name__)


class LogCollector:
    """
    Single background stream from /rosout that fans out to all consumers.

    Consumers:
    - subscribe_all(queue)  — WebSocket /ws/logs/all clients
    - subscribe(node, queue) — WebSocket /ws/logs/{node} clients
    - add_callback(fn)      — HistoryStore, AlertService (sync callbacks)
    """

    def __init__(self, connection: AgentConnection):
        self.conn = connection
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Queue-based subscribers (for WebSocket clients)
        # Accept both asyncio.Queue and DroppableQueue
        self._subscribers: dict[str, set] = defaultdict(set)
        self._all_subscribers: set = set()

        # Reverse lookup for O(1) dispatch
        self._full_name_queues: dict[str, set] = defaultdict(set)   # full_name -> queues
        self._short_name_queues: dict[str, set] = defaultdict(set)  # short_name -> queues

        # Callback subscribers (for HistoryStore, AlertService)
        self._callbacks: list[Callable[[LogMessage], None]] = []

        # In-memory history ring buffer (all levels, for quick replay on WS connect)
        self._history: deque[LogMessage] = deque(maxlen=5000)

        # Parsing
        self._level_map = {
            10: "DEBUG",
            20: "INFO",
            30: "WARN",
            40: "ERROR",
            50: "FATAL",
        }

    async def start(self) -> None:
        """Start the background /rosout stream."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("Log collector started (single /rosout stream)")

    async def stop(self) -> None:
        """Stop the background stream."""
        self._running = False
        # Send sentinel to all subscriber queues so WebSocket loops exit
        for queue in self._all_subscribers:
            try:
                queue.put_nowait(None)
            except Exception:
                pass
        for queues in self._subscribers.values():
            for queue in queues:
                try:
                    queue.put_nowait(None)
                except Exception:
                    pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._callbacks.clear()
        self._all_subscribers.clear()
        self._subscribers.clear()
        self._full_name_queues.clear()
        self._short_name_queues.clear()
        logger.info("Log collector stopped")

    # ─────────────────────────────────────────────────────────────────
    # Queue-based subscriptions (for WebSocket endpoints)
    # ─────────────────────────────────────────────────────────────────

    def subscribe(self, node_name: str, queue: asyncio.Queue) -> None:
        """Subscribe to logs for a specific node."""
        self._subscribers[node_name].add(queue)
        # Update reverse lookup
        self._full_name_queues[node_name].add(queue)
        short = node_name.rsplit("/", 1)[-1] if "/" in node_name else node_name
        self._short_name_queues[short].add(queue)

    def unsubscribe(self, node_name: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from node-specific logs."""
        self._subscribers[node_name].discard(queue)
        if not self._subscribers[node_name]:
            del self._subscribers[node_name]
        # Update reverse lookup
        self._full_name_queues[node_name].discard(queue)
        if not self._full_name_queues[node_name]:
            del self._full_name_queues[node_name]
        short = node_name.rsplit("/", 1)[-1] if "/" in node_name else node_name
        self._short_name_queues[short].discard(queue)
        if not self._short_name_queues[short]:
            del self._short_name_queues[short]

    def subscribe_all(self, queue: asyncio.Queue) -> None:
        """Subscribe to all logs."""
        self._all_subscribers.add(queue)

    def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from all logs."""
        self._all_subscribers.discard(queue)

    # ─────────────────────────────────────────────────────────────────
    # Callback subscriptions (for services: HistoryStore, AlertService)
    # ─────────────────────────────────────────────────────────────────

    def get_recent_logs(
        self,
        node_name: Optional[str] = None,
        limit: int = 1000,
        max_age_seconds: int = 300,
    ) -> list[LogMessage]:
        """Return recent logs from the in-memory ring buffer.

        Args:
            node_name: Filter by node (smart matching by full or short name). None = all.
            limit: Max number of messages to return.
            max_age_seconds: Only include messages newer than this many seconds.
        """
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        result: list[LogMessage] = []

        for msg in self._history:
            if msg.timestamp < cutoff:
                continue
            if node_name:
                short_sub = node_name.rsplit("/", 1)[-1] if "/" in node_name else node_name
                short_msg = msg.node_name.rsplit("/", 1)[-1] if "/" in msg.node_name else msg.node_name
                if msg.node_name != node_name and short_msg != short_sub:
                    continue
            result.append(msg)

        return result[-limit:]

    def add_callback(self, fn: Callable[[LogMessage], None]) -> None:
        """Register a callback invoked for every log message."""
        self._callbacks.append(fn)

    def remove_callback(self, fn: Callable[[LogMessage], None]) -> None:
        """Remove a previously registered callback."""
        try:
            self._callbacks.remove(fn)
        except ValueError:
            pass

    # ─────────────────────────────────────────────────────────────────
    # Background stream
    # ─────────────────────────────────────────────────────────────────

    async def _collect_loop(self) -> None:
        """Main loop: subscribe to JSON log stream from agent."""
        while self._running:
            try:
                logger.info("Starting /rosout JSON stream (agent mode)...")
                msg_count = 0
                async for data in self.conn.subscribe_json('logs'):
                    if not self._running:
                        break

                    msg = self._parse_json_log(data)
                    if msg:
                        msg_count += 1
                        if msg_count <= 3:
                            logger.debug(f"[logs] Message #{msg_count}: [{msg.level}] {msg.node_name}: {msg.message[:80]}")
                        elif msg_count == 4:
                            logger.debug("[logs] Stream working, suppressing further debug output")
                        self._dispatch(msg)

                logger.info(f"/rosout JSON stream ended after {msg_count} messages, retrying in 5s...")

            except ConnectionError as e:
                logger.warning(f"Connection error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in JSON log stream: {e}")

            if not self._running:
                break
            if not self.conn.connected:
                await self.conn.wait_connected()
            if self._running:
                await asyncio.sleep(1)

    def _parse_json_log(self, data: dict) -> Optional[LogMessage]:
        """Convert agent JSON log dict directly to LogMessage."""
        try:
            ts = data.get('timestamp', 0)
            if isinstance(ts, dict):
                sec = ts.get('sec', 0)
                nanosec = ts.get('nanosec', 0)
            else:
                sec = int(ts)
                nanosec = int((ts - sec) * 1e9) if isinstance(ts, float) else 0
            timestamp = datetime.fromtimestamp(sec + nanosec / 1e9)

            level_int = data.get('level', 20)
            level = self._level_map.get(level_int, "INFO")
            node_name = data.get('node', '')
            # ROS2 logger names use dots (e.g. "sensing.lidar.front.convert_filter")
            # but node names from graph API use slashes ("/sensing/lidar/front/convert_filter").
            # Normalize to slash format for consistent matching.
            if node_name and '/' not in node_name:
                node_name = '/' + node_name.replace('.', '/')
            message = data.get('message', '')

            if not node_name:
                return None

            return LogMessage(
                timestamp=timestamp,
                level=level,
                node_name=node_name,
                message=message,
            )
        except Exception:
            return None

    # ─────────────────────────────────────────────────────────────────
    # Dispatch
    # ─────────────────────────────────────────────────────────────────

    def _dispatch(self, msg: LogMessage) -> None:
        """Fan out a log message to all consumers."""
        # 0. Store in ring buffer
        self._history.append(msg)

        # 1. Callbacks (HistoryStore, AlertService)
        for cb in self._callbacks:
            try:
                cb(msg)
            except Exception as e:
                logger.error(f"Log callback error: {e}")

        # 2. All-subscribers (WebSocket /ws/logs/all)
        #    DroppableQueue.put_nowait tracks drops; plain Queue drops silently.
        for queue in self._all_subscribers:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # drop: client is slow

        # 3. Node-specific subscribers — O(1) lookup
        if self._full_name_queues or self._short_name_queues:
            target_queues = set()
            # Match by full name
            target_queues.update(self._full_name_queues.get(msg.node_name, ()))
            # Match by short name
            short_name = msg.node_name.rsplit("/", 1)[-1] if "/" in msg.node_name else msg.node_name
            target_queues.update(self._short_name_queues.get(short_name, ()))

            for queue in target_queues:
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    pass

