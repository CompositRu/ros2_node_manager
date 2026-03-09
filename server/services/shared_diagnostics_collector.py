"""Shared diagnostics collector — one set of subscriptions, fan-out to all clients.

Instead of each /ws/diagnostics client creating 4 separate subscribe_json() calls,
this service maintains a single set of 4 background tasks and broadcasts parsed
DiagnosticItems to all connected clients via DroppableQueue.
"""

import asyncio
import logging
from datetime import datetime

from ..connection import AgentConnection
from ..models import DiagnosticItem
from .droppable_queue import DroppableQueue

logger = logging.getLogger(__name__)

# Diagnostic names to exclude from display
_FILTERED_SUBSTRINGS = ('bag_recorder_rec_status',)
_FILTERED_PREFIXES = ('trajectory_follower', 'blockage_diag', 'tram_longitudinal_controller')


def _is_filtered(name: str) -> bool:
    if any(s in name for s in _FILTERED_SUBSTRINGS):
        return True
    return any(name.startswith(p) for p in _FILTERED_PREFIXES)


# MRM status value -> (diagnostic level, label)
_MRM_STATUS_MAP = {
    0: (0, "NORMAL"),
    1: (2, "ERROR"),
    2: (1, "OPERATING"),
    3: (0, "SUCCEEDED"),
    4: (2, "FAILED"),
}

# MRM state value -> (diagnostic level, label)
_MRM_STATE_MAP = {
    1: (0, "NORMAL"),
    2: (1, "MRM_OPERATING"),
    3: (0, "MRM_SUCCEEDED"),
    4: (2, "MRM_FAILED"),
}

_MRM_BEHAVIOR_MAP = {
    1: "NONE",
    2: "EMERGENCY_STOP",
    3: "COMFORTABLE_STOP",
}


class SharedDiagnosticsCollector:
    """Shared diagnostics collector — one subscription per channel, broadcast to all clients.

    4 background tasks:
    1. diagnostics channel — parses DiagnosticItem from statuses
    2. topic.echo /sensing/lidar/.../lidar_sync_flag — parses bool -> DiagnosticItem
    3. topic.echo /display/mrm_status — parses mrm_status -> DiagnosticItem
    4. mrm_state channel — parses mrm_state -> DiagnosticItem
    """

    def __init__(self, connection: AgentConnection):
        self._connection = connection
        self._subscribers: set[DroppableQueue] = set()
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def subscribe(self, queue: DroppableQueue) -> None:
        self._subscribers.add(queue)
        logger.debug(f"[shared-diag] subscriber added, total={len(self._subscribers)}")

    def unsubscribe(self, queue: DroppableQueue) -> None:
        self._subscribers.discard(queue)
        logger.debug(f"[shared-diag] subscriber removed, total={len(self._subscribers)}")

    def _broadcast(self, items: list[DiagnosticItem]) -> None:
        if not items or not self._subscribers:
            return

        message = {
            "type": "diagnostics",
            "items": [
                {
                    "name": item.name,
                    "level": item.level,
                    "message": item.message,
                    "hardware_id": item.hardware_id,
                    "values": item.values,
                    "timestamp": item.timestamp.isoformat(),
                }
                for item in items
            ],
        }

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except Exception:
                pass

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("[shared-diag] starting 4 background tasks")
        self._tasks = [
            asyncio.create_task(self._stream_diagnostics(), name="shared-diag-diagnostics"),
            asyncio.create_task(self._stream_lidar_sync(), name="shared-diag-lidar-sync"),
            asyncio.create_task(self._stream_mrm_status(), name="shared-diag-mrm-status"),
            asyncio.create_task(self._stream_mrm_state(), name="shared-diag-mrm-state"),
        ]

    async def stop(self) -> None:
        self._running = False
        logger.info("[shared-diag] stopping all tasks...")

        # Notify waiting clients so they don't hang on queue.get()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(None)
            except Exception:
                pass

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        self._subscribers.clear()
        logger.info("[shared-diag] stopped")

    # --- Background stream tasks ---

    async def _stream_diagnostics(self) -> None:
        """Stream /diagnostics channel — parse DiagnosticItem from statuses."""
        retry_delay = 5
        msg_count = 0

        while self._running:
            try:
                async for data in self._connection.subscribe_json('diagnostics'):
                    if not self._running:
                        break
                    msg_count += 1
                    statuses = data.get('statuses', [])
                    if not isinstance(statuses, list):
                        continue

                    timestamp = datetime.now()
                    items = []
                    for entry in statuses:
                        if not isinstance(entry, dict):
                            continue

                        name = str(entry.get('name', '')).strip()
                        if not name or _is_filtered(name):
                            continue

                        level = int(entry.get('level', 0))
                        message = str(entry.get('message', '')).strip()
                        hardware_id = str(entry.get('hardware_id', '')).strip()

                        values = []
                        raw_values = entry.get('values', [])
                        if isinstance(raw_values, list):
                            for kv in raw_values:
                                if isinstance(kv, dict):
                                    values.append({
                                        'key': str(kv.get('key', '')),
                                        'value': str(kv.get('value', '')),
                                    })

                        items.append(DiagnosticItem(
                            name=name,
                            level=level,
                            message=message,
                            hardware_id=hardware_id,
                            values=values,
                            timestamp=timestamp,
                        ))

                    if msg_count <= 2:
                        logger.debug(f"[shared-diag] diagnostics: {len(items)} items from {len(statuses)} statuses")
                    self._broadcast(items)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"[shared-diag] diagnostics stream error: {e}")

            if not self._running:
                break
            if not self._connection.connected:
                await self._connection.wait_connected()
            if self._running:
                await asyncio.sleep(1)

    async def _stream_lidar_sync(self) -> None:
        """Stream lidar_sync_flag Bool topic -> DiagnosticItem."""
        retry_delay = 5
        topic = "/sensing/lidar/concatenated/lidar_sync_checker/lidar_sync_flag"

        while self._running:
            try:
                async for data in self._connection.subscribe_json('topic.echo', {'topic': topic}):
                    if not self._running:
                        break
                    value = bool(data.get('data', {}).get('data', False))
                    self._broadcast([DiagnosticItem(
                        name="lidar_sync_flag",
                        level=0 if value else 1,
                        message=str(value).lower(),
                        timestamp=datetime.now(),
                    )])

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"[shared-diag] lidar_sync_flag stream error: {e}")

            if not self._running:
                break
            if not self._connection.connected:
                await self._connection.wait_connected()
            if self._running:
                await asyncio.sleep(1)

    async def _stream_mrm_status(self) -> None:
        """Stream /display/mrm_status topic -> DiagnosticItem."""
        retry_delay = 5
        msg_count = 0

        while self._running:
            try:
                async for data in self._connection.subscribe_json('topic.echo', {'topic': '/display/mrm_status'}):
                    if not self._running:
                        break
                    msg_count += 1
                    status_val = int(data.get('data', {}).get('status', 0))
                    level, label = _MRM_STATUS_MAP.get(status_val, (2, "ERROR"))
                    if msg_count <= 2:
                        logger.debug(f"[shared-diag] mrm_status: {label} (val={status_val})")
                    self._broadcast([DiagnosticItem(
                        name="mrm_status",
                        level=level,
                        message=label,
                        timestamp=datetime.now(),
                    )])

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"[shared-diag] mrm_status stream error: {e}")

            if not self._running:
                break
            if not self._connection.connected:
                await self._connection.wait_connected()
            if self._running:
                await asyncio.sleep(1)

    async def _stream_mrm_state(self) -> None:
        """Stream mrm_state channel -> DiagnosticItem."""
        retry_delay = 5
        msg_count = 0

        while self._running:
            try:
                async for data in self._connection.subscribe_json('mrm_state'):
                    if not self._running:
                        break
                    msg_count += 1
                    inner = data.get('data', {})
                    state_val = int(inner.get('state', 0))
                    behavior_val = int(inner.get('behavior', 1))
                    level, label = _MRM_STATE_MAP.get(state_val, (2, "MRM_FAILED"))
                    behavior_label = _MRM_BEHAVIOR_MAP.get(behavior_val, "UNKNOWN")
                    if msg_count <= 2:
                        logger.debug(f"[shared-diag] mrm_state: {label} behavior={behavior_label} (state={state_val})")
                    self._broadcast([DiagnosticItem(
                        name="mrm_state",
                        level=level,
                        message=label,
                        values=[{"key": "behavior", "value": behavior_label}],
                        timestamp=datetime.now(),
                    )])

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"[shared-diag] mrm_state stream error: {e}")

            if not self._running:
                break
            if not self._connection.connected:
                await self._connection.wait_connected()
            if self._running:
                await asyncio.sleep(1)
