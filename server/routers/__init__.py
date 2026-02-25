"""API routers module."""

from .servers import router as servers_router
from .nodes import router as nodes_router
from .websocket import router as websocket_router
from .debug import router as debug_router

__all__ = ["servers_router", "nodes_router", "websocket_router", "debug_router"]
