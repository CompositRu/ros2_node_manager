"""Periodic metrics logger — writes observability data to logs/metrics.log.

Collects: WebSocket client counts, queue drops, queue sizes, agent subscriptions.
Runs every INTERVAL seconds. Logs only when there are active connections.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import AppState

logger = logging.getLogger(__name__)

_INTERVAL = 60  # seconds


class MetricsLogger:
    """Periodically logs queue/drop/client metrics to a dedicated log file."""

    def __init__(self, app_state: 'AppState'):
        self._app_state = app_state
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info("MetricsLogger started (interval=%ds)", _INTERVAL)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("MetricsLogger stopped")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(_INTERVAL)
            try:
                self._collect_and_log()
            except Exception as e:
                logger.error("MetricsLogger error: %s", e)

    def _collect_and_log(self) -> None:
        st = self._app_state

        # --- WebSocket clients (from Metrics singleton) ---
        from .metrics import metrics
        snap = metrics.snapshot()
        ws = snap["websockets"]
        total_ws = ws["total"]

        if total_ws == 0 and not self._has_active_subscriptions():
            return  # nothing to report

        logger.info(
            "ws_clients: total=%d status=%d log=%d log_all=%d alert=%d diag=%d hz=%d echo=%d",
            total_ws, ws["status"], ws["log"], ws["log_all"],
            ws["alert"], ws["diagnostic"], ws["topic_hz"], ws["topic_echo"],
        )

        # --- Agent connection queues ---
        conn = st.connection
        if conn and conn.connected:
            subs = getattr(conn, '_subscription_queues', {})
            if subs:
                for sub_id, queue in subs.items():
                    if queue.qsize > 0 or queue.dropped > 0:
                        logger.info(
                            "agent_queue: sub=%s qsize=%d/%d dropped=%d",
                            sub_id, queue.qsize, queue.maxsize, queue.dropped,
                        )

        # --- SharedEchoMonitor ---
        sem = st.shared_echo_monitor
        if sem:
            for topic, subscribers in sem._topic_subscribers.items():
                total_drops = sum(
                    q.dropped for q in subscribers
                    if hasattr(q, 'dropped')
                )
                sizes = [q.qsize for q in subscribers if hasattr(q, 'qsize')]
                max_qsize = max(sizes) if sizes else 0
                if len(subscribers) > 0:
                    logger.info(
                        "echo: topic=%s clients=%d max_qsize=%d drops=%d",
                        topic, len(subscribers), max_qsize, total_drops,
                    )

        # --- LogCollector ---
        lc = st.log_collector
        if lc:
            all_count = len(lc._all_subscribers)
            node_count = sum(len(qs) for qs in lc._subscribers.values())
            if all_count > 0 or node_count > 0:
                total_drops = sum(
                    q.dropped for q in lc._all_subscribers
                    if hasattr(q, 'dropped')
                )
                logger.info(
                    "logs: all_clients=%d node_clients=%d drops=%d",
                    all_count, node_count, total_drops,
                )

        # --- Process stats ---
        proc = snap["process"]
        logger.info(
            "process: rss_mb=%.1f cpu=%.1f%% threads=%d",
            proc["rss_mb"], proc["cpu_percent"], proc["threads"],
        )

    def _has_active_subscriptions(self) -> bool:
        conn = self._app_state.connection
        if conn and conn.connected:
            subs = getattr(conn, '_subscription_queues', {})
            if subs:
                return True
        return False
