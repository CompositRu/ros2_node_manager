"""Diagnostics collector for streaming ROS2 /diagnostics topic."""

import asyncio
import logging
import re
from datetime import datetime
from typing import AsyncIterator

from ..connection import AgentConnection, ConnectionError
from ..models import DiagnosticItem

logger = logging.getLogger(__name__)


# Diagnostic names to exclude from display
_FILTERED_SUBSTRINGS = ('bag_recorder_rec_status',)
_FILTERED_PREFIXES = ('trajectory_follower', 'blockage_diag', 'tram_longitudinal_controller')


def _is_filtered(name: str) -> bool:
    """Check if a diagnostic name should be excluded from display."""
    if any(s in name for s in _FILTERED_SUBSTRINGS):
        return True
    return any(name.startswith(p) for p in _FILTERED_PREFIXES)


# MRM status value → (diagnostic level, label)
_MRM_STATUS_MAP = {
    0: (0, "NORMAL"),      # OK
    1: (2, "ERROR"),       # ERROR
    2: (1, "OPERATING"),   # WARN
    3: (0, "SUCCEEDED"),   # OK
    4: (2, "FAILED"),      # ERROR
}


# MRM state value → (diagnostic level, label)
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


async def stream_diagnostics_json(
    connection: AgentConnection,
) -> AsyncIterator[list[DiagnosticItem]]:
    """Stream diagnostics via agent JSON subscription.

    Agent sends: {statuses: [{name, level, message, hardware_id, values: [{key, value}]}]}
    Level is already int.
    """

    msg_count = 0
    try:
        async for data in connection.subscribe_json('diagnostics'):
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
                logger.debug(f"Diagnostics JSON: {len(items)} items from {len(statuses)} statuses")
            if items:
                yield items

    except Exception as e:
        logger.error(f"Diagnostics JSON stream error: {e}", exc_info=True)


async def stream_mrm_status_json(
    connection: AgentConnection,
) -> AsyncIterator[list[DiagnosticItem]]:
    """Stream /display/mrm_status via agent JSON subscription.

    Agent sends: {data: {status: int}}
    """

    msg_count = 0
    try:
        async for data in connection.subscribe_json('topic.echo', {'topic': '/display/mrm_status'}):
            msg_count += 1
            status_val = int(data.get('data', {}).get('status', 0))
            level, label = _MRM_STATUS_MAP.get(status_val, (2, "ERROR"))
            if msg_count <= 2:
                logger.debug(f"MRM status JSON: {label} (val={status_val})")
            yield [DiagnosticItem(
                name="mrm_status",
                level=level,
                message=label,
                timestamp=datetime.now(),
            )]

    except Exception as e:
        logger.error(f"MRM status JSON stream error: {e}")


async def stream_mrm_state_json(
    connection: AgentConnection,
) -> AsyncIterator[list[DiagnosticItem]]:
    """Stream /api/fail_safe/mrm_state via agent JSON subscription.

    Agent sends: {data: {state: int, behavior: int}}
    """

    msg_count = 0
    try:
        async for data in connection.subscribe_json('mrm_state'):
            msg_count += 1
            inner = data.get('data', {})
            state_val = int(inner.get('state', 0))
            behavior_val = int(inner.get('behavior', 1))
            level, label = _MRM_STATE_MAP.get(state_val, (2, "MRM_FAILED"))
            behavior_label = _MRM_BEHAVIOR_MAP.get(behavior_val, "UNKNOWN")
            if msg_count <= 2:
                logger.debug(f"MRM state JSON: {label} behavior={behavior_label} (state={state_val})")
            yield [DiagnosticItem(
                name="mrm_state",
                level=level,
                message=label,
                values=[{"key": "behavior", "value": behavior_label}],
                timestamp=datetime.now(),
            )]

    except Exception as e:
        logger.error(f"MRM state JSON stream error: {e}")


async def stream_bool_topic_json(
    connection: AgentConnection,
    topic: str,
    name: str,
) -> AsyncIterator[list[DiagnosticItem]]:
    """Stream a Bool topic via agent JSON subscription.

    Agent sends: {data: {data: true/false}}
    """

    try:
        async for data in connection.subscribe_json('topic.echo', {'topic': topic}):
            value = bool(data.get('data', {}).get('data', False))
            yield [DiagnosticItem(
                name=name,
                level=0 if value else 1,
                message=str(value).lower(),
                timestamp=datetime.now(),
            )]

    except Exception as e:
        logger.error(f"Bool topic JSON stream error ({topic}): {e}")
