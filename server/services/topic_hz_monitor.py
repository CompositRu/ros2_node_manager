"""Shared background service for monitoring topic Hz rates.

Hz monitoring is on-demand per group: user clicks "Hz" to start/stop.
Runs one `ros2 topic hz` process per topic in active groups.
All WebSocket clients read from the same cache — no duplicate processes.
"""

import asyncio
import logging
import re
from typing import Optional

from ..connection.base import BaseConnection
from ..models import TopicGroup

logger = logging.getLogger(__name__)

# Matches "average rate: 20.003" from ros2 topic hz output
_HZ_PATTERN = re.compile(r"average rate:\s*([\d.]+)")


class TopicHzMonitor:
    """On-demand Hz monitor for configured topic groups."""

    def __init__(self, connection: BaseConnection, groups: list[TopicGroup]):
        self._connection = connection
        self._groups = groups
        self._groups_by_id: dict[str, TopicGroup] = {g.id: g for g in groups}
        self._hz_values: dict[str, Optional[float]] = {}
        self._tasks: dict[str, asyncio.Task] = {}  # topic -> task
        self._active_groups: set[str] = set()  # group ids currently monitoring
        self._running = True

    def is_group_active(self, group_id: str) -> bool:
        return group_id in self._active_groups

    async def start_group(self, group_id: str) -> bool:
        """Start Hz monitoring for a specific group. Returns True if started."""
        if not self._running:
            return False
        group = self._groups_by_id.get(group_id)
        if not group:
            return False
        if group_id in self._active_groups:
            return True  # already active

        self._active_groups.add(group_id)
        logger.info(f"TopicHzMonitor: starting hz for group '{group.name}' ({len(group.topics)} topics)")

        for topic in group.topics:
            if topic not in self._tasks:
                self._hz_values[topic] = None
                self._tasks[topic] = asyncio.create_task(self._monitor_topic(topic))

        return True

    async def stop_group(self, group_id: str) -> bool:
        """Stop Hz monitoring for a specific group. Returns True if stopped."""
        group = self._groups_by_id.get(group_id)
        if not group:
            return False
        if group_id not in self._active_groups:
            return True  # already inactive

        self._active_groups.discard(group_id)
        logger.info(f"TopicHzMonitor: stopping hz for group '{group.name}'")

        # Find topics that are no longer needed by any active group
        still_needed: set[str] = set()
        for active_gid in self._active_groups:
            active_group = self._groups_by_id.get(active_gid)
            if active_group:
                still_needed.update(active_group.topics)

        # Cancel tasks for topics no longer needed
        for topic in group.topics:
            if topic not in still_needed and topic in self._tasks:
                self._tasks[topic].cancel()
                try:
                    await self._tasks[topic]
                except (asyncio.CancelledError, Exception):
                    pass
                del self._tasks[topic]
                self._hz_values.pop(topic, None)

        return True

    async def toggle_group(self, group_id: str) -> bool:
        """Toggle Hz for a group. Returns True if now active."""
        if group_id in self._active_groups:
            await self.stop_group(group_id)
            return False
        else:
            await self.start_group(group_id)
            return True

    async def stop(self) -> None:
        """Stop all monitoring (called on disconnect/shutdown)."""
        self._running = False
        logger.info("TopicHzMonitor: stopping all...")

        for task in self._tasks.values():
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        self._tasks.clear()
        self._hz_values.clear()
        self._active_groups.clear()
        logger.info("TopicHzMonitor: stopped")

    def get_groups_with_hz(self) -> list[dict]:
        """Get groups enriched with current Hz values and active state."""
        result = []
        for group in self._groups:
            active = group.id in self._active_groups
            topics_with_hz = []
            for topic in group.topics:
                topics_with_hz.append({
                    "topic": topic,
                    "hz": self._hz_values.get(topic) if active else None,
                })
            result.append({
                "id": group.id,
                "name": group.name,
                "active": active,
                "topics": topics_with_hz,
            })
        return result

    async def _monitor_topic(self, topic: str) -> None:
        """Monitor Hz for a single topic. Restarts on failure."""
        retry_delay = 5

        while self._running:
            try:
                cmd = f"ros2 topic hz {topic}"
                async for line in self._connection.exec_stream(cmd):
                    if not self._running:
                        break
                    match = _HZ_PATTERN.search(line)
                    if match:
                        self._hz_values[topic] = round(float(match.group(1)), 2)

                # Stream ended — mark as no data
                if self._running:
                    self._hz_values[topic] = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"TopicHzMonitor: error monitoring {topic}: {e}")
                    self._hz_values[topic] = None

            if self._running:
                await asyncio.sleep(retry_delay)
