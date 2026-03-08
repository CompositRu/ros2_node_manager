"""WebSocket endpoints for real-time updates."""

import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from ..services.metrics import metrics
from ..services.droppable_queue import DroppableQueue

from ..config import load_topic_groups_config

router = APIRouter(tags=["websocket"])

@router.websocket("/ws/nodes/status")
async def nodes_status_websocket(websocket: WebSocket):
    """WebSocket for real-time node status updates."""
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("status")

    broadcaster = app_state.shared_node_status
    if not broadcaster:
        await websocket.send_json({
            "type": "disconnected",
            "message": "Not connected to server"
        })
        await websocket.close()
        metrics.ws_disconnect("status")
        return

    queue = DroppableQueue(maxsize=10)
    broadcaster.subscribe(queue)

    try:
        while not app_state.is_shutting_down:
            msg = await queue.get()
            if msg is None:
                break
            await websocket.send_json(msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        broadcaster.unsubscribe(queue)
        metrics.ws_disconnect("status")


@router.websocket("/ws/diagnostics")
async def diagnostics_websocket(websocket: WebSocket):
    """WebSocket for streaming /diagnostics topic data.

    Uses SharedDiagnosticsCollector — one set of subscriptions shared across all clients.
    """
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("diagnostic")

    collector = app_state.shared_diagnostics
    if not collector:
        await websocket.send_json({
            "type": "error",
            "message": "Not connected to server"
        })
        await websocket.close()
        metrics.ws_disconnect("diagnostic")
        return

    queue = DroppableQueue(maxsize=500)
    collector.subscribe(queue)

    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Streaming diagnostics"
        })

        while True:
            msg = await queue.get()
            if msg is None:
                break  # service stopped
            dropped = queue.reset_dropped()
            if dropped:
                await websocket.send_json({"type": "dropped", "count": dropped})
            await websocket.send_json(msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Diagnostics WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        collector.unsubscribe(queue)
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
            if log_msg is None:
                break  # service stopped
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
        except Exception:
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
            if log_msg is None:
                break  # service stopped
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
        except Exception:
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
            if msg is None:
                break  # service stopped
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
        except Exception:
            pass
    finally:
        app_state.shared_echo_monitor.unsubscribe(queue)
        metrics.ws_disconnect("topic_echo")


@router.websocket("/ws/topics/hz-single/{topic:path}")
async def topic_hz_single_websocket(websocket: WebSocket, topic: str):
    """WebSocket for streaming Hz of a single topic via shared TopicHzMonitor."""
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("topic_hz")

    if not topic.startswith("/"):
        topic = "/" + topic

    if not app_state.topic_hz_monitor:
        await websocket.send_json({"type": "error", "message": "Topic monitoring not active"})
        await websocket.close()
        metrics.ws_disconnect("topic_hz")
        return

    queue = DroppableQueue(maxsize=50)
    app_state.topic_hz_monitor.subscribe_topic(topic, queue)
    try:
        await websocket.send_json({
            "type": "connected",
            "message": f"Monitoring Hz for {topic}",
            "topic": topic,
        })

        while True:
            msg = await queue.get()
            if msg is None:
                break
            dropped = msg.pop("_dropped", 0) if isinstance(msg, dict) else 0
            if dropped:
                await websocket.send_json({"type": "dropped", "count": dropped})
            await websocket.send_json(msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Single Topic Hz WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        if app_state.topic_hz_monitor:
            app_state.topic_hz_monitor.unsubscribe_topic(topic, queue)
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
            if msg is None:
                break  # service stopped
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
        except Exception:
            pass
    finally:
        app_state.shared_echo_monitor.unsubscribe(queue)
        metrics.ws_disconnect("topic_echo")
