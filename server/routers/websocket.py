"""WebSocket endpoints for real-time updates."""

import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from ..models import NodeStatus
from ..services import (
    stream_diagnostics, stream_bool_topic, stream_mrm_status, stream_mrm_state,
    stream_diagnostics_json, stream_bool_topic_json, stream_mrm_status_json, stream_mrm_state_json,
    stream_group_echo,
)
from ..services.metrics import metrics
from ..services.droppable_queue import DroppableQueue
from ..connection import ContainerNotFoundError, ConnectionError as ConnError
from ..config import load_topic_groups_config

router = APIRouter(tags=["websocket"])

_ws_debug_counter = [0]  # mutable to allow closure update


@router.websocket("/ws/nodes/status")
async def nodes_status_websocket(websocket: WebSocket):
    """
    WebSocket for real-time node status updates.
    Sends updates every 5 seconds.
    """
    from ..main import app_state, disconnect_server

    await websocket.accept()
    metrics.ws_connect("status")

    try:
        while not app_state.is_shutting_down:
            if app_state.node_service:
                try:
                    # Refresh nodes
                    response = await app_state.node_service.refresh_nodes()

                    # Build status dict
                    nodes_status = {
                        n.name: n.status.value
                        for n in response.nodes
                    }

                    # Debug first update
                    if _ws_debug_counter[0] < 3:
                        _ws_debug_counter[0] += 1
                        logger.debug(f"[ws/nodes] Update #{_ws_debug_counter[0]}: "
                              f"active={response.active} inactive={response.inactive} total={response.total}")

                    # Send update
                    await websocket.send_json({
                        "type": "nodes_update",
                        "total": response.total,
                        "active": response.active,
                        "inactive": response.inactive,
                        "nodes": nodes_status,
                        "timestamp": datetime.now().isoformat()
                    })
                except (ContainerNotFoundError, ConnError) as e:
                    logger.warning(f"Connection lost, auto-disconnecting: {e}")
                    # Notify client about connection loss
                    await websocket.send_json({
                        "type": "container_stopped",
                        "message": str(e)
                    })
                    # Disconnect from server
                    await disconnect_server()
                    # Send disconnected status
                    await websocket.send_json({
                        "type": "disconnected",
                        "message": "Server disconnected due to connection loss"
                    })
            else:
                await websocket.send_json({
                    "type": "disconnected",
                    "message": "Not connected to server"
                })

            for _ in range(10):
                if app_state.is_shutting_down:
                    break
                await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        metrics.ws_disconnect("status")


@router.websocket("/ws/diagnostics")
async def diagnostics_websocket(websocket: WebSocket):
    """WebSocket for streaming /diagnostics topic data."""
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("diagnostic")

    if not app_state.connection or not app_state.connection.connected:
        await websocket.send_json({
            "type": "error",
            "message": "Not connected to server"
        })
        await websocket.close()
        metrics.ws_disconnect("diagnostic")
        return

    tasks = []
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Streaming diagnostics"
        })

        conn = app_state.connection

        # Detect agent mode for JSON-native streaming
        from ..connection.agent import AgentConnection
        is_agent = isinstance(conn, AgentConnection)

        async def _send_items(items):
            await websocket.send_json({
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
            })

        async def run_with_retry(name, coro_factory, retry_delay=5):
            """Run a stream coroutine with automatic retry on failure."""
            while True:
                try:
                    logger.debug(f"[diag] Starting stream: {name}")
                    async for items in coro_factory():
                        await _send_items(items)
                    # Stream ended normally (topic stopped publishing)
                    logger.debug(f"[diag] Stream ended: {name}, retrying in {retry_delay}s")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"[diag] Stream error in {name}: {e}, retrying in {retry_delay}s")
                await asyncio.sleep(retry_delay)

        if is_agent:
            tasks = [
                asyncio.create_task(run_with_retry(
                    "/diagnostics",
                    lambda: stream_diagnostics_json(conn),
                )),
                asyncio.create_task(run_with_retry(
                    "lidar_sync_flag",
                    lambda: stream_bool_topic_json(
                        conn,
                        "/sensing/lidar/concatenated/lidar_sync_checker/lidar_sync_flag",
                        "lidar_sync_flag",
                    ),
                )),
                asyncio.create_task(run_with_retry(
                    "mrm_status",
                    lambda: stream_mrm_status_json(conn),
                )),
                asyncio.create_task(run_with_retry(
                    "mrm_state",
                    lambda: stream_mrm_state_json(conn),
                )),
            ]
        else:
            tasks = [
                asyncio.create_task(run_with_retry(
                    "/diagnostics",
                    lambda: stream_diagnostics(conn),
                )),
                asyncio.create_task(run_with_retry(
                    "lidar_sync_flag",
                    lambda: stream_bool_topic(
                        conn,
                        "/sensing/lidar/concatenated/lidar_sync_checker/lidar_sync_flag",
                        "lidar_sync_flag",
                    ),
                )),
                asyncio.create_task(run_with_retry(
                    "mrm_status",
                    lambda: stream_mrm_status(conn),
                )),
                asyncio.create_task(run_with_retry(
                    "mrm_state",
                    lambda: stream_mrm_state(conn),
                )),
            ]

        # Sentinel: wait for client disconnect
        async def _wait_disconnect():
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass

        tasks.append(asyncio.create_task(_wait_disconnect()))
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Diagnostics WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        # Cancel all stream tasks
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        metrics.ws_disconnect("diagnostic")


@router.websocket("/ws/logs/all")
async def all_logs_websocket(websocket: WebSocket):
    """WebSocket for streaming ALL logs (unified stream via LogCollector)."""
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("log_all")

    if not app_state.log_collector:
        await websocket.send_json({
            "type": "error",
            "message": "Not connected to server"
        })
        await websocket.close()
        metrics.ws_disconnect("log_all")
        return

    queue = DroppableQueue(maxsize=1000)
    app_state.log_collector.subscribe_all(queue)

    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Streaming all logs"
        })

        # Send history from in-memory ring buffer
        history = app_state.log_collector.get_recent_logs(limit=1000, max_age_seconds=300)
        if history:
            await websocket.send_json({
                "type": "history",
                "logs": [
                    {
                        "timestamp": m.timestamp.isoformat(),
                        "level": m.level,
                        "node_name": m.node_name,
                        "message": m.message,
                    }
                    for m in history
                ],
            })

        while True:
            log_msg = await queue.get()
            # LogMessage is not a dict, so _dropped won't be attached — use reset_dropped()
            dropped = queue.reset_dropped()
            if dropped:
                await websocket.send_json({"type": "dropped", "count": dropped})
            await websocket.send_json({
                "type": "log",
                "timestamp": log_msg.timestamp.isoformat(),
                "level": log_msg.level,
                "node_name": log_msg.node_name,
                "message": log_msg.message,
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"All-logs WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        if app_state.log_collector:
            app_state.log_collector.unsubscribe_all(queue)
        metrics.ws_disconnect("log_all")


@router.websocket("/ws/logs/{node_name:path}")
async def node_logs_websocket(websocket: WebSocket, node_name: str):
    """WebSocket for streaming logs of a specific node (via LogCollector)."""
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("log")

    # Ensure node name starts with /
    if not node_name.startswith("/"):
        node_name = "/" + node_name

    if not app_state.log_collector:
        await websocket.send_json({
            "type": "error",
            "message": "Not connected to server"
        })
        await websocket.close()
        metrics.ws_disconnect("log")
        return

    queue = DroppableQueue(maxsize=1000)
    app_state.log_collector.subscribe(node_name, queue)

    try:
        await websocket.send_json({
            "type": "connected",
            "message": f"Streaming logs for {node_name}"
        })

        # Send history from in-memory ring buffer
        history = app_state.log_collector.get_recent_logs(
            node_name=node_name, limit=1000, max_age_seconds=300
        )
        if history:
            await websocket.send_json({
                "type": "history",
                "logs": [
                    {
                        "timestamp": m.timestamp.isoformat(),
                        "level": m.level,
                        "message": m.message,
                    }
                    for m in history
                ],
            })

        while True:
            log_msg = await queue.get()
            # LogMessage is not a dict, so _dropped won't be attached — use reset_dropped()
            dropped = queue.reset_dropped()
            if dropped:
                await websocket.send_json({"type": "dropped", "count": dropped})
            await websocket.send_json({
                "type": "log",
                "timestamp": log_msg.timestamp.isoformat(),
                "level": log_msg.level,
                "message": log_msg.message
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Node logs WebSocket error for {node_name}: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    finally:
        if app_state.log_collector:
            app_state.log_collector.unsubscribe(node_name, queue)
        metrics.ws_disconnect("log")

@router.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket):
    """
    WebSocket for real-time alert notifications.
    
    Sends alerts in format:
    {
        "type": "alert",
        "id": "abc123",
        "alert_type": "node_inactive",
        "severity": "error",
        "title": "Нода отключилась",
        "message": "/sensing/lidar/top/rslidar_node",
        "timestamp": "2026-01-26T15:30:00",
        "details": {...}
    }
    """
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("alert")

    if not app_state.alert_service:
        await websocket.send_json({
            "type": "error",
            "message": "Alert service not available"
        })
        await websocket.close()
        metrics.ws_disconnect("alert")
        return

    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to alert stream"
        })

        # Stream alerts
        async for alert in app_state.alert_service.get_alerts():
            try:
                await websocket.send_json({
                    "type": "alert",
                    "id": alert.id,
                    "alert_type": alert.alert_type.value,
                    "severity": alert.severity.value,
                    "title": alert.title,
                    "message": alert.message,
                    "timestamp": alert.timestamp.isoformat(),
                    "details": alert.details
                })
            except Exception as e:
                logger.error(f"Error sending alert: {e}")
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Alerts WebSocket error: {e}")
    finally:
        metrics.ws_disconnect("alert")


@router.websocket("/ws/topics/hz")
async def topic_hz_websocket(websocket: WebSocket):
    """WebSocket for streaming Hz values from shared TopicHzMonitor.

    Sends updates every 2 seconds with current Hz for all topic groups.
    """
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("topic_hz")

    if not app_state.topic_hz_monitor:
        await websocket.send_json({
            "type": "error",
            "message": "Topic monitoring not active",
        })
        await websocket.close()
        metrics.ws_disconnect("topic_hz")
        return

    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Streaming topic Hz",
        })

        while not app_state.is_shutting_down:
            if app_state.topic_hz_monitor:
                groups = app_state.topic_hz_monitor.get_groups_with_hz()
                await websocket.send_json({
                    "type": "hz_update",
                    "groups": groups,
                    "timestamp": datetime.now().isoformat(),
                })

            # Sleep 2 seconds in 0.5s increments (to check shutdown)
            for _ in range(4):
                if app_state.is_shutting_down:
                    break
                await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Topic Hz WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        metrics.ws_disconnect("topic_hz")


@router.websocket("/ws/topics/echo-single/{topic:path}")
async def topic_echo_single_websocket(websocket: WebSocket, topic: str):
    """WebSocket for streaming echo of a single topic.

    Uses SharedEchoMonitor for shared subscription across clients.
    """
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("topic_echo")

    if not topic.startswith("/"):
        topic = "/" + topic

    if not app_state.connection or not app_state.connection.connected:
        await websocket.send_json({"type": "error", "message": "Not connected to server"})
        await websocket.close()
        metrics.ws_disconnect("topic_echo")
        return

    queue = DroppableQueue(maxsize=200)
    app_state.shared_echo_monitor.subscribe([topic], queue)
    try:
        await websocket.send_json({
            "type": "connected",
            "message": f"Streaming echo for {topic}",
            "topic": topic,
        })

        while True:
            msg = await queue.get()
            dropped = msg.pop("_dropped", 0) if isinstance(msg, dict) else 0
            if dropped:
                await websocket.send_json({"type": "dropped", "count": dropped})
            await websocket.send_json({"type": "echo", **msg})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Single Topic Echo WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        app_state.shared_echo_monitor.unsubscribe(queue)
        metrics.ws_disconnect("topic_echo")


@router.websocket("/ws/topics/hz-single/{topic:path}")
async def topic_hz_single_websocket(websocket: WebSocket, topic: str):
    """WebSocket for streaming Hz of a single topic.

    Runs `ros2 topic hz` and parses output to send rate values.
    """
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("topic_hz")

    if not topic.startswith("/"):
        topic = "/" + topic

    if not app_state.connection or not app_state.connection.connected:
        await websocket.send_json({"type": "error", "message": "Not connected to server"})
        await websocket.close()
        metrics.ws_disconnect("topic_hz")
        return

    try:
        await websocket.send_json({
            "type": "connected",
            "message": f"Monitoring Hz for {topic}",
            "topic": topic,
        })

        cmd = f"ros2 topic hz {topic}"
        async for line in app_state.connection.exec_stream(cmd):
            line = line.strip()
            if "average rate:" in line:
                try:
                    rate = float(line.split("average rate:")[1].strip())
                    await websocket.send_json({
                        "type": "hz",
                        "topic": topic,
                        "hz": rate,
                        "timestamp": datetime.now().isoformat(),
                    })
                except (ValueError, IndexError):
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Single Topic Hz WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        metrics.ws_disconnect("topic_hz")


@router.websocket("/ws/topics/echo/{group_id}")
async def topic_echo_websocket(websocket: WebSocket, group_id: str):
    """WebSocket for streaming echo of all topics in a group.

    Shared: uses SharedEchoMonitor so multiple clients reuse the same streams.
    """
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("topic_echo")

    if not app_state.connection or not app_state.connection.connected:
        await websocket.send_json({
            "type": "error",
            "message": "Not connected to server",
        })
        await websocket.close()
        metrics.ws_disconnect("topic_echo")
        return

    # Find group by id
    config = load_topic_groups_config()
    group = None
    for g in config.topic_groups:
        if g.id == group_id:
            group = g
            break

    if not group:
        await websocket.send_json({
            "type": "error",
            "message": f"Group '{group_id}' not found",
        })
        await websocket.close()
        metrics.ws_disconnect("topic_echo")
        return

    queue = DroppableQueue(maxsize=200)
    app_state.shared_echo_monitor.subscribe(group.topics, queue)
    try:
        await websocket.send_json({
            "type": "connected",
            "message": f"Streaming echo for group '{group.name}'",
            "group_id": group.id,
            "topics": group.topics,
        })

        while True:
            msg = await queue.get()
            dropped = msg.pop("_dropped", 0) if isinstance(msg, dict) else 0
            if dropped:
                await websocket.send_json({"type": "dropped", "count": dropped})
            await websocket.send_json({
                "type": "echo",
                **msg,
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Topic Echo WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        app_state.shared_echo_monitor.unsubscribe(queue)
        metrics.ws_disconnect("topic_echo")
