"""Shared node status broadcaster — one polling loop, fan-out to all clients."""

import asyncio
import logging
from datetime import datetime

from ..services.droppable_queue import DroppableQueue
from ..connection import ContainerNotFoundError, ConnectionError as ConnError

logger = logging.getLogger(__name__)


class SharedNodeStatusBroadcaster:
    """Single background poller that broadcasts node status to all WebSocket clients.

    One refresh_nodes() call every 5 seconds -> prepared message -> broadcast to all queues.
    """

    def __init__(self):
        self._subscribers: set[DroppableQueue] = set()
        self._running = False
        self._task = None
        # These are set externally before start()
        self._node_service = None
        self._disconnect_callback = None  # async callable for auto-disconnect

    def subscribe(self, queue: DroppableQueue) -> None:
        self._subscribers.add(queue)

    def unsubscribe(self, queue: DroppableQueue) -> None:
        self._subscribers.discard(queue)

    async def start(self, node_service, disconnect_callback) -> None:
        if self._running:
            return
        self._node_service = node_service
        self._disconnect_callback = disconnect_callback
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("SharedNodeStatusBroadcaster started")

    async def stop(self) -> None:
        self._running = False
        # Notify waiting clients
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(None)
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._subscribers.clear()
        logger.info("SharedNodeStatusBroadcaster stopped")

    async def _poll_loop(self) -> None:
        """Background loop: poll node status every 5 seconds, broadcast to all."""
        while self._running:
            try:
                if self._node_service:
                    try:
                        response = await self._node_service.refresh_nodes()

                        nodes_status = {
                            n.name: n.status.value
                            for n in response.nodes
                        }

                        message = {
                            "type": "nodes_update",
                            "total": response.total,
                            "active": response.active,
                            "inactive": response.inactive,
                            "nodes": nodes_status,
                            "timestamp": datetime.now().isoformat()
                        }
                        self._broadcast(message)

                    except (ContainerNotFoundError, ConnError) as e:
                        logger.warning(f"Connection lost, auto-disconnecting: {e}")
                        # Notify all clients about connection loss
                        self._broadcast({
                            "type": "container_stopped",
                            "message": str(e)
                        })
                        # Fire-and-forget: disconnect_server() will call stop() on us,
                        # so we must not await it directly (would deadlock).
                        if self._disconnect_callback:
                            task = asyncio.create_task(self._disconnect_callback())
                            task.add_done_callback(self._on_disconnect_done)
                        self._running = False
                        break
                else:
                    self._broadcast({
                        "type": "disconnected",
                        "message": "Not connected to server"
                    })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SharedNodeStatusBroadcaster error: {e}")

            # Sleep 5 seconds in 0.5s increments
            for _ in range(10):
                if not self._running:
                    break
                await asyncio.sleep(0.5)

    @staticmethod
    def _on_disconnect_done(task: asyncio.Task) -> None:
        """Log errors from disconnect callback instead of losing them."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Error in disconnect callback: {exc}")

    def _broadcast(self, message: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except Exception:
                pass
