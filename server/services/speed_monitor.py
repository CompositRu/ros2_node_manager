"""Speed monitor — background stream from /localization/kinematic_state."""

import asyncio
import logging
import math
from typing import Optional

from ..connection import AgentConnection

logger = logging.getLogger(__name__)


class SpeedMonitor:
    """
    Background stream that subscribes to /localization/kinematic_state
    and keeps the latest speed value in memory.
    """

    TOPIC = "/localization/kinematic_state"

    def __init__(self, connection: AgentConnection):
        self.conn = connection
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.speed_kmh: Optional[float] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._stream_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.speed_kmh = None

    async def _stream_loop(self) -> None:
        """Stream topic via subscribe_json and parse speed."""
        while self._running:
            try:
                async for data in self.conn.subscribe_json(
                    'topic.echo',
                    {'topic': self.TOPIC, 'no_arr': True, 'field': 'twist.twist.linear'},
                ):
                    if not self._running:
                        break
                    inner = data.get('data', {})
                    if isinstance(inner, dict):
                        x = inner.get('x', 0.0)
                        y = inner.get('y', 0.0)
                        try:
                            speed_ms = math.sqrt(float(x) ** 2 + float(y) ** 2)
                            self.speed_kmh = round(speed_ms * 3.6, 1)
                        except (TypeError, ValueError):
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SpeedMonitor: stream error: {e}")
                self.speed_kmh = None

            if not self._running:
                break
            if not self.conn.connected:
                await self.conn.wait_connected()
            if self._running:
                await asyncio.sleep(1)
