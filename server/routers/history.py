"""History REST endpoints for querying stored logs and alerts."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(prefix="/api/history", tags=["history"])


def _get_store():
    from ..main import app_state

    if not app_state.history_store:
        raise HTTPException(503, "History store not available (not connected)")
    return app_state.history_store


@router.get("/logs")
async def get_log_history(
    level: Optional[str] = Query(None, description="Filter by level (DEBUG, INFO, WARN, ERROR, FATAL)"),
    node_name: Optional[str] = Query(None, description="Filter by node name (partial match)"),
    search: Optional[str] = Query(None, description="Search in message text"),
    since: Optional[str] = Query(None, description="ISO timestamp lower bound"),
    until: Optional[str] = Query(None, description="ISO timestamp upper bound"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    store = _get_store()
    return await store.query_logs(
        level=level,
        node_name=node_name,
        search=search,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/alerts")
async def get_alert_history(
    alert_type: Optional[str] = Query(None, description="Filter by alert type"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    node_name: Optional[str] = Query(None, description="Filter by node name (partial match)"),
    since: Optional[str] = Query(None, description="ISO timestamp lower bound"),
    until: Optional[str] = Query(None, description="ISO timestamp upper bound"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    store = _get_store()
    return await store.query_alerts(
        alert_type=alert_type,
        severity=severity,
        node_name=node_name,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/logs/export")
async def export_logs(
    format: str = Query("json", description="Export format: json or text"),
    level: Optional[str] = Query(None),
    node_name: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
):
    store = _get_store()
    data = await store.export_logs(
        format=format,
        level=level,
        node_name=node_name,
        search=search,
        since=since,
        until=until,
    )

    if format == "text":
        return PlainTextResponse(
            content=data,
            headers={"Content-Disposition": "attachment; filename=logs_export.txt"},
        )
    else:
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": "attachment; filename=logs_export.json"},
        )


@router.get("/stats")
async def get_history_stats():
    store = _get_store()
    return await store.get_stats()
