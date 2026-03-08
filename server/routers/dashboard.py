"""Dashboard endpoint — aggregated system overview."""

import asyncio
import logging
import re
import time

from fastapi import APIRouter

logger = logging.getLogger(__name__)

from ..services.speed_monitor import SpeedMonitor
from ..services.diagnostics_collector import _MRM_STATE_MAP, _MRM_BEHAVIOR_MAP

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Lazy speed monitor — started on first dashboard request, stopped on inactivity
_speed_monitor: SpeedMonitor | None = None
_speed_monitor_last_access: float = 0
_speed_monitor_watchdog: asyncio.Task | None = None
_SPEED_INACTIVITY_TIMEOUT = 15  # seconds


async def _ensure_speed_monitor(conn) -> SpeedMonitor | None:
    """Start speed monitor lazily, reset inactivity timer."""
    global _speed_monitor, _speed_monitor_last_access, _speed_monitor_watchdog

    _speed_monitor_last_access = time.monotonic()

    if _speed_monitor and _speed_monitor._running:
        return _speed_monitor

    # Start new monitor
    _speed_monitor = SpeedMonitor(conn)
    await _speed_monitor.start()

    # Start watchdog task
    if _speed_monitor_watchdog is None or _speed_monitor_watchdog.done():
        _speed_monitor_watchdog = asyncio.create_task(_speed_inactivity_watchdog())

    return _speed_monitor


async def _speed_inactivity_watchdog():
    """Stop speed monitor if no dashboard requests for a while."""
    global _speed_monitor, _speed_monitor_last_access
    while True:
        await asyncio.sleep(5)
        if time.monotonic() - _speed_monitor_last_access > _SPEED_INACTIVITY_TIMEOUT:
            if _speed_monitor:
                await _speed_monitor.stop()
                _speed_monitor = None
            break


@router.get("")
async def get_dashboard():
    """Return aggregated dashboard data: docker, resources, nodes, counts."""
    from ..main import app_state

    result = {
        "docker": {"running": False, "container": None, "started_at": None, "uptime_seconds": None},
        "resources": {
            "cpu_percent": None,
            "memory_used_gb": None,
            "memory_limit_gb": None,
            "memory_percent": None,
            "gpu_percent": None,
            "gpu_memory_used_mb": None,
            "gpu_memory_total_mb": None,
            "gpu_name": None,
        },
        "nodes": {"active": 0, "inactive": 0, "total": 0},
        "topics_count": 0,
        "services_count": 0,
        "speed_kmh": None,
        "mrm_state": None,
    }

    conn = app_state.connection
    if not conn or not conn.connected:
        return result

    result["docker"]["container"] = conn.container
    result["docker"]["running"] = True

    # Ensure speed monitor is running
    speed_mon = await _ensure_speed_monitor(conn)

    # Get resources from agent inside Docker
    agent_resources, node_counts, topic_count, service_count, mrm_state = await asyncio.gather(
        conn.get_agent_resources(),
        _get_node_counts(app_state),
        _get_topic_count(conn),
        _get_service_count(conn),
        _get_mrm_state(conn),
    )

    if agent_resources:
        result["docker"]["uptime_seconds"] = agent_resources.get("uptime_seconds")
        result["resources"]["cpu_percent"] = agent_resources.get("cpu_percent")
        result["resources"]["memory_used_gb"] = agent_resources.get("memory_used_gb")
        result["resources"]["memory_limit_gb"] = agent_resources.get("memory_limit_gb")
        result["resources"]["memory_percent"] = agent_resources.get("memory_percent")
        result["resources"]["gpu_percent"] = agent_resources.get("gpu_percent")
        result["resources"]["gpu_memory_used_mb"] = agent_resources.get("gpu_memory_used_mb")
        result["resources"]["gpu_memory_total_mb"] = agent_resources.get("gpu_memory_total_mb")
        result["resources"]["gpu_name"] = agent_resources.get("gpu_name")

    # Node counts
    result["nodes"] = node_counts

    # Topic/service counts
    result["topics_count"] = topic_count
    result["services_count"] = service_count

    # Speed — read latest from background monitor
    if speed_mon:
        result["speed_kmh"] = speed_mon.speed_kmh

    # MRM state
    result["mrm_state"] = mrm_state

    return result


async def _get_node_counts(app_state) -> dict:
    """Get node counts from NodeService (triggers refresh if stale)."""
    try:
        if app_state.node_service:
            response = await app_state.node_service.refresh_nodes()
            return {
                "active": response.active,
                "inactive": response.inactive,
                "total": response.total,
            }
    except Exception as e:
        logger.warning(f"Dashboard: node counts error: {e}")
    return {"active": 0, "inactive": 0, "total": 0}


# TTL cache for topic/service counts (avoid redundant ros2 CLI calls)
_topic_cache: tuple[float, int] = (0, 0)   # (timestamp, count)
_service_cache: tuple[float, int] = (0, 0)  # (timestamp, count)
_COUNT_CACHE_TTL = 5.0  # seconds


async def _get_topic_count(conn) -> int:
    """Get total number of ROS2 topics (cached for 5s)."""
    global _topic_cache
    now = time.time()
    if now - _topic_cache[0] < _COUNT_CACHE_TTL:
        return _topic_cache[1]
    try:
        topics = await conn.ros2_topic_list()
        count = len(topics)
        _topic_cache = (now, count)
        return count
    except Exception:
        return _topic_cache[1]  # return stale cache on error


async def _get_service_count(conn) -> int:
    """Get total number of ROS2 services, excluding technical (cached for 5s)."""
    global _service_cache
    now = time.time()
    if now - _service_cache[0] < _COUNT_CACHE_TTL:
        return _service_cache[1]
    from .services import _is_technical_service
    try:
        services = await conn.ros2_service_list()
        count = sum(1 for s in services if not _is_technical_service(s))
        _service_cache = (now, count)
        return count
    except Exception:
        return _service_cache[1]  # return stale cache on error


async def _get_mrm_state(conn) -> dict | None:
    """Get MRM state via one-shot topic echo."""
    try:
        output = await conn.exec_command(
            "ros2 topic echo /api/fail_safe/mrm_state --once",
            timeout=3.0,
        )
        state_match = re.search(r"state:\s*(\d+)", output)
        if not state_match:
            return None
        state_val = int(state_match.group(1))
        behavior_match = re.search(r"behavior:\s*(\d+)", output)
        behavior_val = int(behavior_match.group(1)) if behavior_match else 1
        _, state_label = _MRM_STATE_MAP.get(state_val, (2, "MRM_FAILED"))
        behavior_label = _MRM_BEHAVIOR_MAP.get(behavior_val, "UNKNOWN")
        return {
            "state": state_val,
            "behavior": behavior_val,
            "state_label": state_label,
            "behavior_label": behavior_label,
        }
    except Exception:
        return None
