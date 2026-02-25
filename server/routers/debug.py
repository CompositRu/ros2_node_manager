"""Debug/monitoring endpoints."""

from fastapi import APIRouter

from ..services.metrics import metrics

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/stats")
async def get_stats():
    """Return internal application metrics."""
    from ..main import app_state

    snapshot = metrics.snapshot()

    # Add connection info
    connection = app_state.connection
    snapshot["connection"] = {
        "server_id": app_state.current_server_id,
        "connected": connection is not None and connection.connected,
        "type": type(connection).__name__ if connection else None,
        "container": connection.container if connection else None,
    }

    # Add alert service status
    snapshot["alert_service"] = {
        "running": (
            app_state.alert_service is not None
            and app_state.alert_service._running
        ),
        "tasks": (
            len(app_state.alert_service._tasks)
            if app_state.alert_service
            else 0
        ),
    }

    return snapshot
