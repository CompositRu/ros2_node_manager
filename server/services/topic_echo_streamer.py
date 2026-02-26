"""Per-client topic echo streaming with multiplexing.

Starts `ros2 topic echo` for each topic in a group and multiplexes
the output into a single async stream tagged with source topic names.
"""

import asyncio
import re
from datetime import datetime
from typing import AsyncIterator

from ..connection.base import BaseConnection

# Max size per message before truncation
ECHO_MAX_SIZE = 10 * 1024  # 10 KB


async def stream_group_echo(
    connection: BaseConnection,
    topics: list[str],
) -> AsyncIterator[dict]:
    """Multiplex echo from multiple topics into one stream.

    Yields dicts: {"topic": "/full/topic", "data": "yaml text", "timestamp": "iso"}
    """
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
    tasks: list[asyncio.Task] = []

    async def _echo_single_topic(topic: str) -> None:
        """Stream echo for one topic, push messages to shared queue."""
        cmd = f"ros2 topic echo {topic} --no-arr"
        buffer: list[str] = []

        try:
            async for line in connection.exec_stream(cmd):
                if line.strip() == "---":
                    if buffer:
                        data = "\n".join(buffer)
                        # Truncate large messages
                        if len(data) > ECHO_MAX_SIZE:
                            data = data[:ECHO_MAX_SIZE] + f"\n... (truncated, {len(data)} bytes total)"
                        try:
                            queue.put_nowait({
                                "topic": topic,
                                "data": data,
                                "timestamp": datetime.now().isoformat(),
                            })
                        except asyncio.QueueFull:
                            pass  # Drop message if consumer is too slow
                    buffer = []
                else:
                    buffer.append(line)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            try:
                queue.put_nowait({
                    "topic": topic,
                    "data": f"[error: {e}]",
                    "timestamp": datetime.now().isoformat(),
                })
            except asyncio.QueueFull:
                pass

    # Start echo for each topic
    for topic in topics:
        tasks.append(asyncio.create_task(_echo_single_topic(topic)))

    # Sentinel to detect when all tasks are done
    done_event = asyncio.Event()

    async def _watch_tasks():
        await asyncio.gather(*tasks, return_exceptions=True)
        done_event.set()

    watcher = asyncio.create_task(_watch_tasks())

    try:
        while not done_event.is_set():
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield msg
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        watcher.cancel()
        await asyncio.gather(*tasks, watcher, return_exceptions=True)
