"""REST endpoints for topics."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/topics", tags=["topics"])


@router.get("/list")
async def get_topic_list():
    """Get flat list of all ROS2 topics with their message types."""
    from ..main import app_state

    if not app_state.connection or not app_state.connection.connected:
        raise HTTPException(status_code=503, detail="Not connected to any server")

    try:
        topics = await app_state.connection.ros2_topic_list()
        return {"topics": topics, "count": len(topics)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list topics: {e}")


@router.get("/info/{topic_name:path}")
async def get_topic_info(topic_name: str):
    """Get detailed info (type, publishers, subscribers) for a topic."""
    from ..main import app_state

    if not topic_name.startswith("/"):
        topic_name = "/" + topic_name

    if not app_state.connection or not app_state.connection.connected:
        raise HTTPException(status_code=503, detail="Not connected to any server")

    try:
        info = await app_state.connection.ros2_topic_info(topic_name)
        return {"topic": topic_name, **info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get topic info: {e}")


@router.get("/groups")
async def get_topic_groups():
    """Get all topic groups with current Hz values."""
    from ..main import app_state

    if not app_state.topic_hz_monitor:
        raise HTTPException(status_code=503, detail="Topic monitoring not active")

    return {
        "groups": app_state.topic_hz_monitor.get_groups_with_hz(),
    }


@router.post("/groups/{group_id}/hz")
async def toggle_group_hz(group_id: str):
    """Toggle Hz monitoring for a specific group."""
    from ..main import app_state

    if not app_state.topic_hz_monitor:
        raise HTTPException(status_code=503, detail="Topic monitoring not active")

    now_active = await app_state.topic_hz_monitor.toggle_group(group_id)
    return {
        "group_id": group_id,
        "active": now_active,
    }
