"""Speed monitor — background stream from /localization/kinematic_state."""

import asyncio
import math
from typing import Optional

from ..connection import BaseConnection


class SpeedMonitor:
    """
    Background stream that subscribes to /localization/kinematic_state
    and keeps the latest speed value in memory.
    """

    TOPIC = "/localization/kinematic_state"

    def __init__(self, connection: BaseConnection):
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
        """Stream topic and parse speed from YAML output."""
        while self._running:
            try:
                cmd = (
                    f"ros2 topic echo {self.TOPIC} "
                    "--no-arr --field twist.twist.linear"
                )
                vals = {}
                async for line in self.conn.exec_stream(cmd):
                    if not self._running:
                        break
                    line = line.strip()
                    if line == "---":
                        if "x" in vals and "y" in vals:
                            speed_ms = math.sqrt(vals["x"] ** 2 + vals["y"] ** 2)
                            self.speed_kmh = round(speed_ms * 3.6, 1)
                        vals = {}
                    elif ":" in line:
                        key, val = line.split(":", 1)
                        try:
                            vals[key.strip()] = float(val.strip())
                        except ValueError:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"SpeedMonitor: stream error: {e}")
                self.speed_kmh = None
                if self._running:
                    await asyncio.sleep(5)
