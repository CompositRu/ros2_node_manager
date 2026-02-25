"""Diagnostics collector for streaming ROS2 /diagnostics topic."""

import re
import yaml
from datetime import datetime
from typing import AsyncIterator

from ..connection import BaseConnection, ConnectionError
from ..models import DiagnosticItem


def _normalize_byte_levels(text: str) -> str:
    """Preprocess YAML text to convert byte level representations to integers.

    ROS2 byte fields may appear as escaped strings in ros2 topic echo output:
    level: "\\x01" or level: '\\0' etc. Convert to plain integers.
    """
    # Handle hex escapes: level: "\x00", level: "\x01", level: "\x02", level: "\x03"
    text = re.sub(
        r'''level:\s*["']\\x([0-9a-fA-F]{2})["']''',
        lambda m: f'level: {int(m.group(1), 16)}',
        text,
    )
    # Handle null escape: level: "\0" or level: '\0'
    text = re.sub(r'''level:\s*["']\\0["']''', 'level: 0', text)
    # Handle raw single-byte characters (non-printable) between quotes
    text = re.sub(
        r'''level:\s*["']([\x00-\x03])["']''',
        lambda m: f'level: {ord(m.group(1))}',
        text,
    )
    return text


# Diagnostic names to exclude from display
_FILTERED_SUBSTRINGS = ('bag_recorder_rec_status',)
_FILTERED_PREFIXES = ('trajectory_follower', 'blockage_diag', 'tram_longitudinal_controller')


def _is_filtered(name: str) -> bool:
    """Check if a diagnostic name should be excluded from display."""
    if any(s in name for s in _FILTERED_SUBSTRINGS):
        return True
    return any(name.startswith(p) for p in _FILTERED_PREFIXES)


def _parse_level(raw_level) -> int:
    """Convert diagnostic level from various YAML representations to int.

    The level field is a byte in ROS2. ros2 topic echo may output it as:
    - int: 0, 1, 2, 3
    - escaped string after normalization
    - raw byte in string
    """
    if isinstance(raw_level, int):
        return raw_level
    if isinstance(raw_level, bytes):
        return raw_level[0] if raw_level else 0
    if isinstance(raw_level, str):
        if len(raw_level) == 1:
            return ord(raw_level)
        try:
            return int(raw_level)
        except ValueError:
            pass
    return 0  # Default to OK


async def stream_diagnostics(
    connection: BaseConnection,
) -> AsyncIterator[list[DiagnosticItem]]:
    """
    Stream diagnostic messages from /diagnostics topic.
    Each yield is a list of DiagnosticItem from one DiagnosticArray message.
    """
    cmd = "ros2 topic echo /diagnostics"

    buffer = []
    msg_count = 0

    try:
        async for line in connection.exec_stream(cmd):
            buffer.append(line)

            if line.strip() == "---":
                text = "\n".join(buffer)
                buffer = []
                msg_count += 1

                if msg_count <= 2:
                    # Log first messages for debugging level format
                    print(f"DEBUG diagnostics msg #{msg_count} (first 500 chars): {text[:500]}")

                items = _parse_diagnostic_array(text)
                if items and msg_count <= 2:
                    print(f"DEBUG parsed {len(items)} items, first level={items[0].level} name={items[0].name}")
                if items:
                    yield items

    except Exception as e:
        import traceback
        print(f"Diagnostics stream error: {e}")
        traceback.print_exc()


def _parse_diagnostic_array(text: str) -> list[DiagnosticItem]:
    """Parse a DiagnosticArray message from ros2 topic echo output."""
    items = []

    # Normalize byte level values to integers before parsing
    text = _normalize_byte_levels(text)

    try:
        data = yaml.safe_load(text)
        if not data or not isinstance(data, dict):
            return items
    except yaml.YAMLError:
        # Fallback to regex parsing if YAML fails
        return _parse_diagnostic_array_regex(text)

    # Use reception time — header stamp is often zero in /diagnostics
    timestamp = datetime.now()

    # Parse status array
    status_list = data.get("status", [])
    if not isinstance(status_list, list):
        return items

    for entry in status_list:
        if not isinstance(entry, dict):
            continue

        level = _parse_level(entry.get("level", 0))
        name = str(entry.get("name", "")).strip()
        if not name or _is_filtered(name):
            continue

        message = str(entry.get("message", "")).strip()
        hardware_id = str(entry.get("hardware_id", "")).strip()

        # Parse key-value pairs
        values = []
        raw_values = entry.get("values", [])
        if isinstance(raw_values, list):
            for kv in raw_values:
                if isinstance(kv, dict):
                    values.append({
                        "key": str(kv.get("key", "")),
                        "value": str(kv.get("value", "")),
                    })

        items.append(DiagnosticItem(
            name=name,
            level=level,
            message=message,
            hardware_id=hardware_id,
            values=values,
            timestamp=timestamp,
        ))

    return items


def _parse_diagnostic_array_regex(text: str) -> list[DiagnosticItem]:
    """Fallback regex-based parser for when YAML parsing fails."""
    items = []

    # Normalize byte level values (already done in caller for YAML path,
    # but regex path may be called directly on error)
    text = _normalize_byte_levels(text)

    # Split into individual status entries by looking for "- level:" pattern
    entries = re.split(r'\n- level:', text)
    if len(entries) < 2:
        return items

    # Use reception time — header stamp is often zero in /diagnostics
    timestamp = datetime.now()

    # Parse each entry (skip first which is header)
    for entry_text in entries[1:]:
        entry_text = "level:" + entry_text  # restore stripped prefix

        level_match = re.search(r"level:\s*(\d+)", entry_text)
        name_match = (
            re.search(r"name:\s*'([^']*)'", entry_text) or
            re.search(r'name:\s*"([^"]*)"', entry_text) or
            re.search(r"name:\s*([^\n]+)", entry_text)
        )
        msg_match = (
            re.search(r"message:\s*'([^']*)'", entry_text) or
            re.search(r'message:\s*"([^"]*)"', entry_text) or
            re.search(r"message:\s*([^\n]+)", entry_text)
        )
        hw_match = (
            re.search(r"hardware_id:\s*'([^']*)'", entry_text) or
            re.search(r'hardware_id:\s*"([^"]*)"', entry_text) or
            re.search(r"hardware_id:\s*([^\n]+)", entry_text)
        )

        if not name_match:
            continue

        name = name_match.group(1).strip()
        if not name or _is_filtered(name):
            continue

        level = int(level_match.group(1)) if level_match else 0
        message = msg_match.group(1).strip() if msg_match else ""
        hardware_id = hw_match.group(1).strip() if hw_match else ""

        # Parse key-value pairs
        values = []
        kv_pattern = re.finditer(
            r"-\s*key:\s*['\"]?([^'\"\n]+)['\"]?\s*\n\s*value:\s*['\"]?([^'\"\n]*)['\"]?",
            entry_text
        )
        for kv in kv_pattern:
            values.append({
                "key": kv.group(1).strip(),
                "value": kv.group(2).strip(),
            })

        items.append(DiagnosticItem(
            name=name,
            level=level,
            message=message,
            hardware_id=hardware_id,
            values=values,
            timestamp=timestamp,
        ))

    return items
