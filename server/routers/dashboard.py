"""Dashboard endpoint — aggregated system overview."""

import asyncio
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


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
    }

    conn = app_state.connection
    if not conn or not conn.connected:
        return result

    result["docker"]["container"] = conn.container
    result["docker"]["running"] = True

    # Gather data concurrently
    docker_info, docker_stats, gpu_info, node_counts, topic_count, service_count, cpu_count, speed = await asyncio.gather(
        _get_docker_info(conn),
        _get_docker_stats(conn),
        _get_gpu_info(conn),
        _get_node_counts(app_state),
        _get_topic_count(conn),
        _get_service_count(conn),
        _get_cpu_count(conn),
        _get_speed(conn),
    )

    # Docker info (uptime)
    if docker_info:
        result["docker"]["started_at"] = docker_info.get("started_at")
        result["docker"]["uptime_seconds"] = docker_info.get("uptime_seconds")

    # Docker stats (CPU, RAM) — normalize CPU by core count
    if docker_stats:
        raw_cpu = docker_stats.get("cpu_percent", 0)
        if cpu_count and cpu_count > 0:
            result["resources"]["cpu_percent"] = round(raw_cpu / cpu_count, 1)
        else:
            result["resources"]["cpu_percent"] = raw_cpu
        result["resources"]["memory_used_gb"] = docker_stats.get("memory_used_gb")
        result["resources"]["memory_limit_gb"] = docker_stats.get("memory_limit_gb")
        result["resources"]["memory_percent"] = docker_stats.get("memory_percent")

    # GPU
    if gpu_info:
        result["resources"]["gpu_percent"] = gpu_info.get("gpu_percent")
        result["resources"]["gpu_memory_used_mb"] = gpu_info.get("memory_used_mb")
        result["resources"]["gpu_memory_total_mb"] = gpu_info.get("memory_total_mb")
        result["resources"]["gpu_name"] = gpu_info.get("name")

    # Node counts
    result["nodes"] = node_counts

    # Topic/service counts
    result["topics_count"] = topic_count
    result["services_count"] = service_count

    # Speed
    result["speed_kmh"] = speed

    return result


async def _get_docker_info(conn) -> dict | None:
    """Get container start time and uptime via docker inspect."""
    try:
        output = await conn.exec_host_command(
            f"docker inspect {conn.container} --format '{{{{json .State}}}}'"
        )
        state = json.loads(output.strip().strip("'"))
        started_at = state.get("StartedAt", "")
        if started_at and started_at != "0001-01-01T00:00:00Z":
            # Parse ISO timestamp
            started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            uptime = (datetime.now(timezone.utc) - started_dt).total_seconds()
            return {"started_at": started_at, "uptime_seconds": int(uptime)}
    except Exception as e:
        print(f"Dashboard: docker inspect error: {e}")
    return None


async def _get_docker_stats(conn) -> dict | None:
    """Get container CPU and memory via docker stats."""
    try:
        output = await conn.exec_host_command(
            f"docker stats {conn.container} --no-stream --format '{{{{.CPUPerc}}}}|{{{{.MemUsage}}}}|{{{{.MemPerc}}}}'"
        )
        parts = output.strip().strip("'").split("|")
        if len(parts) >= 3:
            cpu = float(parts[0].strip().rstrip("%"))
            mem_percent = float(parts[2].strip().rstrip("%"))

            # Parse memory: "12.3GiB / 31.27GiB" or "1234MiB / 31270MiB"
            mem_used_gb, mem_limit_gb = _parse_mem_usage(parts[1].strip())

            return {
                "cpu_percent": round(cpu, 1),
                "memory_used_gb": mem_used_gb,
                "memory_limit_gb": mem_limit_gb,
                "memory_percent": round(mem_percent, 1),
            }
    except Exception as e:
        print(f"Dashboard: docker stats error: {e}")
    return None


def _parse_mem_usage(mem_str: str) -> tuple[float | None, float | None]:
    """Parse '12.3GiB / 31.27GiB' or '1234MiB / 31270MiB'."""
    try:
        parts = mem_str.split("/")
        used = _parse_mem_value(parts[0].strip())
        limit = _parse_mem_value(parts[1].strip())
        return used, limit
    except Exception:
        return None, None


def _parse_mem_value(s: str) -> float | None:
    """Parse a memory value like '12.3GiB' or '1234MiB' to GB."""
    s = s.strip()
    match = re.match(r"([\d.]+)\s*(GiB|MiB|KiB|B)", s)
    if not match:
        return None
    val = float(match.group(1))
    unit = match.group(2)
    if unit == "GiB":
        return round(val, 1)
    elif unit == "MiB":
        return round(val / 1024, 1)
    elif unit == "KiB":
        return round(val / 1024 / 1024, 2)
    return round(val / 1024 / 1024 / 1024, 2)


async def _get_gpu_info(conn) -> dict | None:
    """Get GPU utilization via nvidia-smi. Returns None if no GPU."""
    try:
        output = await conn.exec_host_command(
            "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,name "
            "--format=csv,noheader,nounits",
            timeout=5.0,
        )
        line = output.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            return {
                "gpu_percent": int(parts[0]),
                "memory_used_mb": int(parts[1]),
                "memory_total_mb": int(parts[2]),
                "name": parts[3],
            }
    except Exception:
        pass  # No GPU or nvidia-smi not available
    return None


async def _get_node_counts(app_state) -> dict:
    """Get node counts from NodeService."""
    try:
        if app_state.node_service:
            response = app_state.node_service.get_cached_nodes()
            return {
                "active": response.active,
                "inactive": response.inactive,
                "total": response.total,
            }
    except Exception as e:
        print(f"Dashboard: node counts error: {e}")
    return {"active": 0, "inactive": 0, "total": 0}


async def _get_topic_count(conn) -> int:
    """Get total number of ROS2 topics."""
    try:
        topics = await conn.ros2_topic_list()
        return len(topics)
    except Exception:
        return 0


async def _get_service_count(conn) -> int:
    """Get total number of ROS2 services."""
    try:
        services = await conn.ros2_service_list()
        return len(services)
    except Exception:
        return 0


async def _get_cpu_count(conn) -> int:
    """Get number of CPU cores on the host."""
    try:
        output = await conn.exec_host_command("nproc", timeout=5.0)
        return int(output.strip())
    except Exception:
        return 0


async def _get_speed(conn) -> float | None:
    """Get current speed from /localization/kinematic_state (Odometry)."""
    try:
        output = await conn.exec_command(
            "ros2 topic echo /localization/kinematic_state --once --no-arr "
            "--field twist.twist.linear.x",
            timeout=3.0,
        )
        for line in output.strip().split("\n"):
            line = line.strip().rstrip("---").strip()
            if not line:
                continue
            speed_ms = float(line)
            return round(abs(speed_ms) * 3.6, 1)
    except Exception:
        pass
    return None
