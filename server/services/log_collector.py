"""Log collector service — single /rosout stream for all consumers."""

import asyncio
import re
from datetime import datetime
from typing import Optional, Callable
from collections import defaultdict

from ..connection import BaseConnection, ConnectionError
from ..models import LogMessage


class LogCollector:
    """
    Single background stream from /rosout that fans out to all consumers.

    Consumers:
    - subscribe_all(queue)  — WebSocket /ws/logs/all clients
    - subscribe(node, queue) — WebSocket /ws/logs/{node} clients
    - add_callback(fn)      — HistoryStore, AlertService (sync callbacks)
    """

    def __init__(self, connection: BaseConnection):
        self.conn = connection
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Queue-based subscribers (for WebSocket clients)
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._all_subscribers: set[asyncio.Queue] = set()

        # Callback subscribers (for HistoryStore, AlertService)
        self._callbacks: list[Callable[[LogMessage], None]] = []

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
        print("📋 Log collector started (single /rosout stream)")

    async def stop(self) -> None:
        """Stop the background stream."""
        self._running = False
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
        print("📋 Log collector stopped")

    # ─────────────────────────────────────────────────────────────────
    # Queue-based subscriptions (for WebSocket endpoints)
    # ─────────────────────────────────────────────────────────────────

    def subscribe(self, node_name: str, queue: asyncio.Queue) -> None:
        """Subscribe to logs for a specific node."""
        self._subscribers[node_name].add(queue)

    def unsubscribe(self, node_name: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from node-specific logs."""
        self._subscribers[node_name].discard(queue)
        if not self._subscribers[node_name]:
            del self._subscribers[node_name]

    def subscribe_all(self, queue: asyncio.Queue) -> None:
        """Subscribe to all logs."""
        self._all_subscribers.add(queue)

    def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from all logs."""
        self._all_subscribers.discard(queue)

    # ─────────────────────────────────────────────────────────────────
    # Callback subscriptions (for services: HistoryStore, AlertService)
    # ─────────────────────────────────────────────────────────────────

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
        """Main loop: always streams /rosout, dispatches to all consumers."""
        cmd = "ros2 topic echo /rosout --no-arr --qos-reliability best_effort --qos-history keep_last --qos-depth 1000"

        while self._running:
            try:
                buffer = []
                async for line in self.conn.exec_stream(cmd):
                    if not self._running:
                        break

                    buffer.append(line)

                    if line.strip() == "---":
                        msg = self._parse_rosout_message("\n".join(buffer))
                        buffer = []
                        if msg:
                            self._dispatch(msg)

            except ConnectionError as e:
                print(f"Log collector connection error: {e}")
                if self._running:
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Log collector error: {e}")
                if self._running:
                    await asyncio.sleep(5)

    # ─────────────────────────────────────────────────────────────────
    # Dispatch
    # ─────────────────────────────────────────────────────────────────

    def _dispatch(self, msg: LogMessage) -> None:
        """Fan out a log message to all consumers."""
        # 1. Callbacks (HistoryStore, AlertService)
        for cb in self._callbacks:
            try:
                cb(msg)
            except Exception as e:
                print(f"Log callback error: {e}")

        # 2. All-subscribers (WebSocket /ws/logs/all)
        for queue in self._all_subscribers:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # drop: client is slow

        # 3. Node-specific subscribers (WebSocket /ws/logs/{node})
        #    Match by full name and by short name (last segment)
        if self._subscribers:
            short_name = msg.node_name.rsplit("/", 1)[-1] if "/" in msg.node_name else msg.node_name
            for sub_name, queues in self._subscribers.items():
                sub_short = sub_name.rsplit("/", 1)[-1] if "/" in sub_name else sub_name
                if msg.node_name == sub_name or short_name == sub_short:
                    for queue in queues:
                        try:
                            queue.put_nowait(msg)
                        except asyncio.QueueFull:
                            pass

    # ─────────────────────────────────────────────────────────────────
    # Parsing
    # ─────────────────────────────────────────────────────────────────

    def _parse_rosout_message(self, text: str) -> Optional[LogMessage]:
        """Parse a rosout YAML message into LogMessage."""
        try:
            stamp_match = re.search(r"sec:\s*(\d+)", text)
            nanosec_match = re.search(r"nanosec:\s*(\d+)", text)
            level_match = re.search(r"level:\s*(\d+)", text)
            name_match = re.search(r"name:\s*['\"]?([^'\"}\n]+)['\"]?", text)
            msg_match = (
                re.search(r"msg:\s*'([^']*)'", text)
                or re.search(r'msg:\s*"([^"]*)"', text)
                or re.search(r"msg:\s*([^\n]+)", text)
            )

            if not all([stamp_match, level_match, name_match, msg_match]):
                return None

            sec = int(stamp_match.group(1))
            nanosec = int(nanosec_match.group(1)) if nanosec_match else 0
            timestamp = datetime.fromtimestamp(sec + nanosec / 1e9)
            level = self._level_map.get(int(level_match.group(1)), "INFO")
            node_name = name_match.group(1).strip()
            message = msg_match.group(1).strip()

            return LogMessage(
                timestamp=timestamp,
                level=level,
                node_name=node_name,
                message=message,
            )
        except Exception:
            return None
