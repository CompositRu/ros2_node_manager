"""Shared topic echo streaming with fan-out to multiple clients.

One subscription per topic, data broadcast to all connected clients via subscribe_json.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Union

from ..connection import AgentConnection
from .droppable_queue import DroppableQueue

logger = logging.getLogger(__name__)

# Messages larger than this (in JSON-serialized form) are truncated
_MAX_MESSAGE_BYTES = 10 * 1024  # 10 KB

_AnyQueue = Union[asyncio.Queue, DroppableQueue]


class SharedEchoMonitor:
    """Shared echo monitor — one subscription per topic, fan-out to all clients.

    Architecture:
    - subscribe(topics, queue) -> client subscribes to a set of topics
    - unsubscribe(queue) -> client disconnects
    - For each unique topic, one background task reads from agent
    - Messages are broadcast to all subscribed client queues
    - Ref-counting: topic task is started when first client subscribes,
      cancelled when last client unsubscribes
    """

    def __init__(self, connection: AgentConnection):
        self._connection = connection
        self._topic_tasks: dict[str, asyncio.Task] = {}
        self._topic_subscribers: dict[str, set[_AnyQueue]] = {}
        self._running = True

    def subscribe(self, topics: list[str], queue: _AnyQueue) -> None:
        if not self._running:
            return

        for topic in topics:
            if topic not in self._topic_subscribers:
                self._topic_subscribers[topic] = set()

            self._topic_subscribers[topic].add(queue)

            if topic not in self._topic_tasks:
                logger.info(f"SharedEchoMonitor: starting stream for {topic}")
                self._topic_tasks[topic] = asyncio.create_task(
                    self._stream_topic(topic)
                )

    def unsubscribe(self, queue: _AnyQueue) -> None:
        topics_to_remove = []

        for topic, subscribers in self._topic_subscribers.items():
            subscribers.discard(queue)
            if not subscribers:
                topics_to_remove.append(topic)

        for topic in topics_to_remove:
            self._stop_topic(topic)

    def _stop_topic(self, topic: str) -> None:
        task = self._topic_tasks.pop(topic, None)
        if task and not task.done():
            task.cancel()
        self._topic_subscribers.pop(topic, None)
        logger.info(f"SharedEchoMonitor: stopped stream for {topic}")

    async def _stream_topic(self, topic: str) -> None:
        """Background task: stream echo data for a single topic via subscribe_json."""
        retry_delay = 5

        while self._running:
            try:
                async for data in self._connection.subscribe_json(
                    'topic.echo', {'topic': topic, 'no_arr': True}
                ):
                    if not self._running or topic not in self._topic_subscribers:
                        break
                    msg_data = data.get('data', {}) if isinstance(data, dict) else data
                    message = {
                        "topic": topic,
                        "data": msg_data,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "format": "json",
                    }
                    self._broadcast(topic, message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running and topic in self._topic_subscribers:
                    logger.error(f"SharedEchoMonitor: error streaming {topic}: {e}")

            if not self._running or topic not in self._topic_subscribers:
                break
            if not self._connection.connected:
                await self._connection.wait_connected()
            if self._running and topic in self._topic_subscribers:
                await asyncio.sleep(1)

    def _broadcast(self, topic: str, message: dict) -> None:
        message = self._maybe_truncate(message)

        subscribers = self._topic_subscribers.get(topic)
        if not subscribers:
            return

        for queue in list(subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass

    @staticmethod
    def _maybe_truncate(message: dict) -> dict:
        try:
            data = message.get("data")
            if data is None:
                return message

            # Fast path: skip obviously-small messages without json.dumps overhead.
            # For strings, len() is accurate. For dicts, use str() as a cheap estimate
            # (slightly overestimates due to repr formatting, but avoids json.dumps).
            if isinstance(data, str):
                if len(data) < _MAX_MESSAGE_BYTES:
                    return message
            elif len(str(data)) < _MAX_MESSAGE_BYTES:
                return message

            # Slow path: full serialization for potentially-large messages
            serialized = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
            if len(serialized.encode('utf-8')) <= _MAX_MESSAGE_BYTES:
                return message

            truncated = serialized[:_MAX_MESSAGE_BYTES] + "... [truncated]"
            return {
                **message,
                "data": truncated,
                "truncated": True,
            }
        except Exception:
            return message

    async def stop(self) -> None:
        self._running = False
        logger.info("SharedEchoMonitor: stopping all...")

        # Send sentinel to all subscriber queues so WebSocket loops exit
        for subscribers in self._topic_subscribers.values():
            for queue in subscribers:
                try:
                    queue.put_nowait(None)
                except Exception:
                    pass

        for task in self._topic_tasks.values():
            task.cancel()

        if self._topic_tasks:
            await asyncio.gather(*self._topic_tasks.values(), return_exceptions=True)

        self._topic_tasks.clear()
        self._topic_subscribers.clear()
        logger.info("SharedEchoMonitor: stopped")
