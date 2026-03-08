"""Shared topic echo streaming with fan-out to multiple clients.

One subscription per topic, data broadcast to all connected clients.
In agent mode uses subscribe_json for direct JSON; falls back to exec_stream+YAML.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Union

from ..connection.base import BaseConnection
from .droppable_queue import DroppableQueue

logger = logging.getLogger(__name__)

# Messages larger than this (in JSON-serialized form) are truncated
_MAX_MESSAGE_BYTES = 10 * 1024  # 10 KB

# Type alias: subscribers may use either plain asyncio.Queue or DroppableQueue
_AnyQueue = Union[asyncio.Queue, DroppableQueue]


class SharedEchoMonitor:
    """Shared echo monitor — one subscription per topic, fan-out to all clients.

    Architecture:
    - subscribe(topics, queue) → client subscribes to a set of topics
    - unsubscribe(queue) → client disconnects
    - For each unique topic, one background task reads from agent
    - Messages are broadcast to all subscribed client queues
    - Ref-counting: topic task is started when first client subscribes,
      cancelled when last client unsubscribes
    """

    def __init__(self, connection: BaseConnection):
        self._connection = connection
        self._topic_tasks: dict[str, asyncio.Task] = {}
        self._topic_subscribers: dict[str, set[_AnyQueue]] = {}
        self._running = True

    def subscribe(self, topics: list[str], queue: _AnyQueue) -> None:
        """Subscribe a client queue to a set of topics.

        Starts a background streaming task for any topic that doesn't have one yet.
        """
        if not self._running:
            return

        for topic in topics:
            if topic not in self._topic_subscribers:
                self._topic_subscribers[topic] = set()

            self._topic_subscribers[topic].add(queue)

            # Start task if this is the first subscriber for this topic
            if topic not in self._topic_tasks:
                logger.info(f"SharedEchoMonitor: starting stream for {topic}")
                self._topic_tasks[topic] = asyncio.create_task(
                    self._stream_topic(topic)
                )

    def unsubscribe(self, queue: _AnyQueue) -> None:
        """Remove a client queue from all topics.

        Cancels background tasks for topics with no remaining subscribers.
        """
        topics_to_remove = []

        for topic, subscribers in self._topic_subscribers.items():
            subscribers.discard(queue)
            if not subscribers:
                topics_to_remove.append(topic)

        for topic in topics_to_remove:
            self._stop_topic(topic)

    def _stop_topic(self, topic: str) -> None:
        """Cancel task and clean up state for a topic."""
        task = self._topic_tasks.pop(topic, None)
        if task and not task.done():
            task.cancel()
        self._topic_subscribers.pop(topic, None)
        logger.info(f"SharedEchoMonitor: stopped stream for {topic}")

    async def _stream_topic(self, topic: str) -> None:
        """Background task: stream echo data for a single topic.

        Uses subscribe_json in agent mode for direct JSON,
        falls back to exec_stream with YAML buffering otherwise.
        Retries on error after 5 seconds.
        """
        retry_delay = 5

        while self._running:
            try:
                if self._is_agent_connection():
                    await self._stream_topic_agent(topic)
                else:
                    await self._stream_topic_exec(topic)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running and topic in self._topic_subscribers:
                    logger.error(f"SharedEchoMonitor: error streaming {topic}: {e}")

            # Retry if still running and topic still has subscribers
            if self._running and topic in self._topic_subscribers:
                await asyncio.sleep(retry_delay)
            else:
                break

    async def _stream_topic_agent(self, topic: str) -> None:
        """Stream topic via agent's subscribe_json (direct JSON)."""
        from ..connection.agent import AgentConnection

        conn: AgentConnection = self._connection  # type: ignore
        async for data in conn.subscribe_json('topic.echo', {'topic': topic, 'no_arr': True}):
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

    async def _stream_topic_exec(self, topic: str) -> None:
        """Stream topic via exec_stream (YAML output), buffering lines until '---'."""
        cmd = f"ros2 topic echo {topic} --no-arr"
        yaml_lines: list[str] = []

        async for line in self._connection.exec_stream(cmd):
            if not self._running or topic not in self._topic_subscribers:
                break

            if line.strip() == '---':
                if yaml_lines:
                    yaml_text = '\n'.join(yaml_lines)
                    message = {
                        "topic": topic,
                        "data": yaml_text,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "format": "yaml",
                    }
                    self._broadcast(topic, message)
                    yaml_lines.clear()
            else:
                yaml_lines.append(line)

    def _broadcast(self, topic: str, message: dict) -> None:
        """Send a message to all subscribers of a topic.

        Truncates messages exceeding _MAX_MESSAGE_BYTES.
        Uses DroppableQueue.put_nowait which tracks drops automatically;
        falls back to try/except for plain asyncio.Queue.
        """
        # Truncate oversized messages
        message = self._maybe_truncate(message)

        subscribers = self._topic_subscribers.get(topic)
        if not subscribers:
            return

        for queue in subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # DroppableQueue never raises; plain Queue drops silently

    @staticmethod
    def _maybe_truncate(message: dict) -> dict:
        """Truncate message data if JSON-serialized size exceeds limit."""
        try:
            data = message.get("data")
            if data is None:
                return message

            serialized = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
            if len(serialized.encode('utf-8')) <= _MAX_MESSAGE_BYTES:
                return message

            # Truncate: keep first N chars with a marker
            truncated = serialized[:_MAX_MESSAGE_BYTES] + "... [truncated]"
            return {
                **message,
                "data": truncated,
                "truncated": True,
            }
        except Exception:
            return message

    def _is_agent_connection(self) -> bool:
        """Check if the current connection is an AgentConnection (lazy import)."""
        from ..connection.agent import AgentConnection
        return isinstance(self._connection, AgentConnection)

    async def stop(self) -> None:
        """Stop all streaming tasks and clean up."""
        self._running = False
        logger.info("SharedEchoMonitor: stopping all...")

        for task in self._topic_tasks.values():
            task.cancel()

        if self._topic_tasks:
            await asyncio.gather(*self._topic_tasks.values(), return_exceptions=True)

        self._topic_tasks.clear()
        self._topic_subscribers.clear()
        logger.info("SharedEchoMonitor: stopped")
