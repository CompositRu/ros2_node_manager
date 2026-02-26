"""WebSocket endpoints for real-time updates."""

import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..models import NodeStatus
from ..services import stream_node_logs, stream_all_logs, stream_diagnostics, stream_bool_topic
from ..services.metrics import metrics
from ..connection import ContainerNotFoundError

router = APIRouter(tags=["websocket"])


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

                    # Send update
                    await websocket.send_json({
                        "type": "nodes_update",
                        "total": response.total,
                        "active": response.active,
                        "inactive": response.inactive,
                        "nodes": nodes_status,
                        "timestamp": datetime.now().isoformat()
                    })
                except ContainerNotFoundError as e:
                    print(f"Container stopped, auto-disconnecting: {e}")
                    # Notify client about container stop
                    await websocket.send_json({
                        "type": "container_stopped",
                        "message": str(e)
                    })
                    # Disconnect from server
                    await disconnect_server()
                    # Send disconnected status
                    await websocket.send_json({
                        "type": "disconnected",
                        "message": "Server disconnected due to container stop"
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
        print(f"WebSocket error: {e}")
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

    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Streaming diagnostics"
        })

        lock = asyncio.Lock()
        conn = app_state.connection

        async def _send_items(items):
            async with lock:
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

        async def run_diagnostics():
            async for diag_items in stream_diagnostics(conn):
                await _send_items(diag_items)

        async def run_lidar_sync():
            async for items in stream_bool_topic(
                conn,
                "/sensing/lidar/concatenated/lidar_sync_checker/lidar_sync_flag",
                "lidar_sync_flag",
            ):
                await _send_items(items)

        await asyncio.gather(run_diagnostics(), run_lidar_sync())

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Diagnostics WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        metrics.ws_disconnect("diagnostic")


@router.websocket("/ws/logs/all")
async def all_logs_websocket(websocket: WebSocket):
    """WebSocket for streaming ALL logs (unified stream)."""
    from ..main import app_state

    await websocket.accept()
    metrics.ws_connect("log_all")

    if not app_state.connection or not app_state.connection.connected:
        await websocket.send_json({
            "type": "error",
            "message": "Not connected to server"
        })
        await websocket.close()
        metrics.ws_disconnect("log_all")
        return

    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Streaming all logs"
        })

        async for log_msg in stream_all_logs(app_state.connection):
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
        print(f"All-logs WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        metrics.ws_disconnect("log_all")


@router.websocket("/ws/logs/{node_name:path}")
async def node_logs_websocket(websocket: WebSocket, node_name: str):
    """
    WebSocket for streaming logs of a specific node.
    """
    from ..main import app_state
    
    await websocket.accept()
    metrics.ws_connect("log")

    # Ensure node name starts with /
    if not node_name.startswith("/"):
        node_name = "/" + node_name

    print(f"DEBUG: Logs WebSocket opened for {node_name}")

    if not app_state.connection or not app_state.connection.connected:
        await websocket.send_json({
            "type": "error",
            "message": "Not connected to server"
        })
        await websocket.close()
        metrics.ws_disconnect("log")
        return

    try:
        # Send initial message
        await websocket.send_json({
            "type": "connected",
            "message": f"Streaming logs for {node_name}"
        })

        print(f"DEBUG: Starting log stream for {node_name}")

        # Stream logs
        async for log_msg in stream_node_logs(app_state.connection, node_name):
            print(f"DEBUG: Got log message: {log_msg.message[:50]}...")
            await websocket.send_json({
                "type": "log",
                "timestamp": log_msg.timestamp.isoformat(),
                "level": log_msg.level,
                "message": log_msg.message
            })

    except WebSocketDisconnect:
        print(f"DEBUG: WebSocket disconnected for {node_name}")
    except Exception as e:
        print(f"DEBUG: WebSocket error for {node_name}: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    finally:
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
                print(f"Error sending alert: {e}")
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Alerts WebSocket error: {e}")
    finally:
        metrics.ws_disconnect("alert")
