"""Queue wrapper that tracks dropped messages on overflow."""

import asyncio


class DroppableQueue:
    """asyncio.Queue wrapper that tracks dropped messages.

    When the queue is full, put_nowait() silently increments a drop counter
    instead of raising QueueFull.  The next successful get() attaches the
    accumulated drop count to the returned item (if it's a dict) via the
    ``_dropped`` key, then resets the counter.

    Usage in WebSocket endpoints::

        queue = DroppableQueue(maxsize=200)
        ...
        msg = await queue.get()
        dropped = msg.pop('_dropped', 0) if isinstance(msg, dict) else 0
        if dropped:
            await websocket.send_json({"type": "dropped", "count": dropped})
    """

    def __init__(self, maxsize: int = 200):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._dropped: int = 0

    def put_nowait(self, item) -> None:
        """Try to enqueue *item*. If the queue is full, increment the drop counter."""
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped += 1

    async def get(self):
        """Return the next item, attaching ``_dropped`` count if any were lost."""
        item = await self._queue.get()
        if self._dropped > 0 and isinstance(item, dict):
            item["_dropped"] = self._dropped
            self._dropped = 0
        return item

    @property
    def dropped(self) -> int:
        """Number of messages dropped since last reset."""
        return self._dropped

    def reset_dropped(self) -> int:
        """Return current drop count and reset it to zero."""
        count = self._dropped
        self._dropped = 0
        return count

    @property
    def full(self) -> bool:
        return self._queue.full()

    @property
    def empty(self) -> bool:
        return self._queue.empty()

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize
