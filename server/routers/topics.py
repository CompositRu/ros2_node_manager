"""REST endpoints for topic groups."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/topics", tags=["topics"])


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
