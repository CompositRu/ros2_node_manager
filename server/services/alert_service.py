"""Alert monitoring service for Tram Monitoring System."""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional, Callable, Set, Dict
import uuid

logger = logging.getLogger(__name__)

from ..connection import AgentConnection
from ..models import Alert, AlertType, AlertSeverity, AlertConfig, NodeStatus, LogMessage


class AlertService:
    """
    Service for monitoring and generating alerts.
    
    Features:
    - Background monitoring (независимо от WebSocket подключений)
    - Дедупликация с cooldown
    - Очередь алертов для WebSocket subscribers
    - Мониторинг: падение нод, пропажа топиков, паттерны в логах
    """

    def __init__(self, connection: AgentConnection, config: AlertConfig):
        self.conn = connection
        self.config = config

        # External refs (set after init)
        self.node_service = None  # set by main.py — share node list cache
        self.history_store = None

        # Node status tracking
        self._node_statuses: Dict[str, NodeStatus] = {}

        # Alert deduplication: key -> last_alert_time
        self._alert_cooldowns: Dict[str, datetime] = {}

        # Alert queue for WebSocket subscribers
        self._alert_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        # Subscribers (callbacks)
        self._subscribers: Dict[str, Callable[[Alert], None]] = {}

        # Known missing topics (для отслеживания восстановления)
        self._missing_topics: Set[str] = set()

        # Pre-compile error patterns for on_log_message callback
        self._compiled_patterns: list[tuple[re.Pattern, str]] = []
        if self.config.error_patterns:
            for p in self.config.error_patterns:
                try:
                    self._compiled_patterns.append((
                        re.compile(p["pattern"], re.IGNORECASE),
                        p.get("severity", "error")
                    ))
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{p['pattern']}': {e}")

        # Running state
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all monitoring tasks."""
        if not self.config.enabled:
            logger.warning("Alert service disabled in config")
            return

        self._running = True
        logger.info("Alert service starting...")

        # Start monitoring tasks
        # Note: rosout pattern matching is now handled by on_log_message() callback
        # registered with LogCollector (single /rosout stream)
        self._tasks = [
            asyncio.create_task(self._monitor_nodes_loop()),
            asyncio.create_task(self._monitor_missing_topics()),
            asyncio.create_task(self._monitor_topic_values()),
        ]
        
        logger.info("Alert service started")

    async def stop(self) -> None:
        """Stop all monitoring tasks."""
        self._running = False
        logger.info("Alert service stopping...")
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks = []
        self._subscribers.clear()
        logger.info("Alert service stopped")

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def subscribe(self, callback: Callable[[Alert], None]) -> str:
        """Subscribe to alerts. Returns subscription ID."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """Unsubscribe from alerts."""
        self._subscribers.pop(sub_id, None)

    async def get_alerts(self) -> AsyncIterator[Alert]:
        """Async iterator for alerts (for WebSocket)."""
        while self._running:
            try:
                alert = await asyncio.wait_for(
                    self._alert_queue.get(),
                    timeout=1.0
                )
                yield alert
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def update_node_status(self, node_name: str, status: NodeStatus) -> None:
        """
        Update node status and generate alert if needed.
        Called from NodeService when node status changes.
        """
        previous = self._node_statuses.get(node_name)
        self._node_statuses[node_name] = status

        # Skip if no previous status (initial load)
        if previous is None:
            return

        # ACTIVE -> INACTIVE: node died
        if previous == NodeStatus.ACTIVE and status == NodeStatus.INACTIVE:
            self._emit_alert(
                alert_type=AlertType.NODE_INACTIVE,
                severity=AlertSeverity.ERROR,
                title="Нода отключилась",
                message=node_name,
                details={"node_name": node_name},
                cooldown_key=f"node_inactive:{node_name}"
            )
        
        # INACTIVE -> ACTIVE: node recovered
        elif previous == NodeStatus.INACTIVE and status == NodeStatus.ACTIVE:
            self._emit_alert(
                alert_type=AlertType.NODE_RECOVERED,
                severity=AlertSeverity.INFO,
                title="Нода восстановилась",
                message=node_name,
                details={"node_name": node_name},
                cooldown_key=f"node_recovered:{node_name}"
            )

    # ─────────────────────────────────────────────────────────────────
    # Callback from LogCollector (sync, called for every log message)
    # ─────────────────────────────────────────────────────────────────

    def on_log_message(self, log_msg: LogMessage) -> None:
        """Called by LogCollector for every /rosout message. Checks error patterns."""
        if not self._compiled_patterns:
            return

        msg = log_msg.message
        node_name = log_msg.node_name

        for pattern, severity in self._compiled_patterns:
            if pattern.search(msg):
                display_msg = msg[:150] + "..." if len(msg) > 150 else msg

                self._emit_alert(
                    alert_type=AlertType.ERROR_PATTERN,
                    severity=AlertSeverity(severity),
                    title="Ошибка в логах",
                    message=f"[{node_name}] {display_msg}",
                    details={
                        "node_name": node_name,
                        "pattern": pattern.pattern,
                        "full_message": msg
                    },
                    cooldown_key=f"error_pattern:{pattern.pattern}:{node_name}"
                )
                break  # Only one alert per message

    # ─────────────────────────────────────────────────────────────────
    # Internal: Alert emission with deduplication
    # ─────────────────────────────────────────────────────────────────

    def _emit_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        details: dict = None,
        cooldown_key: str = None
    ) -> bool:
        """
        Emit alert with deduplication.
        Returns True if alert was emitted, False if deduplicated.
        """
        # Check cooldown
        if cooldown_key:
            last_alert = self._alert_cooldowns.get(cooldown_key)
            if last_alert:
                elapsed = datetime.now() - last_alert
                if elapsed < timedelta(seconds=self.config.cooldown_seconds):
                    return False  # Still in cooldown
            
            self._alert_cooldowns[cooldown_key] = datetime.now()

        # Create alert
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            details=details or {}
        )

        # Persist to history store (tracked task with error callback)
        if self.history_store:
            try:
                task = asyncio.ensure_future(self.history_store.store_alert(alert))
                task.add_done_callback(self._on_store_alert_done)
            except Exception as e:
                logger.error(f"Failed to persist alert: {e}")

        # Add to queue (for WebSocket async iterator)
        try:
            self._alert_queue.put_nowait(alert)
        except asyncio.QueueFull:
            # Remove oldest and add new
            try:
                self._alert_queue.get_nowait()
                self._alert_queue.put_nowait(alert)
            except:
                pass

        # Notify subscribers
        for callback in self._subscribers.values():
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Error in alert subscriber: {e}")

        logger.info(f"Alert: [{severity.value}] {title}: {message}")
        return True

    @staticmethod
    def _on_store_alert_done(task: asyncio.Task) -> None:
        """Log errors from store_alert tasks instead of losing them silently."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Failed to persist alert to DB: {exc}")

    def _cleanup_cooldowns(self) -> None:
        """Remove expired cooldown entries to prevent unbounded dict growth."""
        now = datetime.now()
        cutoff = timedelta(seconds=self.config.cooldown_seconds * 2)
        expired = [k for k, v in self._alert_cooldowns.items() if (now - v) > cutoff]
        for k in expired:
            del self._alert_cooldowns[k]

    def _cleanup_node_statuses(self) -> None:
        """Remove node statuses for nodes not seen in current active set."""
        if not self.node_service:
            return
        response = self.node_service.get_cached_nodes()
        active_names = {n.name for n in response.nodes}
        stale = [k for k in self._node_statuses if k not in active_names]
        for k in stale:
            del self._node_statuses[k]

    # ─────────────────────────────────────────────────────────────────
    # Background monitoring tasks
    # ─────────────────────────────────────────────────────────────────

    async def _monitor_nodes_loop(self) -> None:
        """
        Background task to monitor node statuses.
        Uses NodeService cached data instead of calling ros2 node list directly.
        """
        _iterations = 0
        while self._running:
            try:
                # Use NodeService cached node list (no extra ros2 CLI call)
                if self.node_service:
                    response = self.node_service.get_cached_nodes()
                    current_nodes = {
                        n.name for n in response.nodes
                        if n.status == NodeStatus.ACTIVE
                    }
                else:
                    # Fallback: call ros2 directly (shouldn't happen normally)
                    nodes = await self.conn.ros2_node_list()
                    current_nodes = set(nodes)

                # Check for nodes that disappeared
                for node_name, status in list(self._node_statuses.items()):
                    if status == NodeStatus.ACTIVE and node_name not in current_nodes:
                        self.update_node_status(node_name, NodeStatus.INACTIVE)

                # Check for nodes that appeared
                for node_name in current_nodes:
                    prev_status = self._node_statuses.get(node_name)
                    if prev_status == NodeStatus.INACTIVE:
                        self.update_node_status(node_name, NodeStatus.ACTIVE)
                    elif prev_status is None:
                        # New node, just track it
                        self._node_statuses[node_name] = NodeStatus.ACTIVE

                # Periodic cleanup of stale dicts (~every 5 min)
                _iterations += 1
                if _iterations % 60 == 0:
                    self._cleanup_cooldowns()
                    self._cleanup_node_statuses()

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in node monitoring: {e}")
                if self._running and not self.conn.connected:
                    await self.conn.wait_connected()
                if self._running:
                    await asyncio.sleep(5)

    async def _monitor_missing_topics(self) -> None:
        """Monitor for missing important topics. Backs off on repeated failures."""
        if not self.config.important_topics:
            return

        interval = 10  # base interval in seconds

        while self._running:
            try:
                # Get current topic list
                output = await self.conn.exec_command("ros2 topic list", timeout=10.0)
                current_topics = set(
                    line.strip()
                    for line in output.strip().split("\n")
                    if line.strip().startswith("/")
                )

                for topic in self.config.important_topics:
                    # Topic missing
                    if topic not in current_topics:
                        if topic not in self._missing_topics:
                            self._missing_topics.add(topic)
                            self._emit_alert(
                                alert_type=AlertType.MISSING_TOPIC,
                                severity=AlertSeverity.WARNING,
                                title="Топик не найден",
                                message=topic,
                                details={"topic": topic},
                                cooldown_key=f"missing_topic:{topic}"
                            )
                    # Topic recovered
                    elif topic in self._missing_topics:
                        self._missing_topics.discard(topic)
                        self._emit_alert(
                            alert_type=AlertType.TOPIC_RECOVERED,
                            severity=AlertSeverity.INFO,
                            title="Топик восстановлен",
                            message=topic,
                            details={"topic": topic},
                            cooldown_key=f"topic_recovered:{topic}"
                        )

                interval = 10  # reset on success
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring topics: {e}")
                if self._running and not self.conn.connected:
                    await self.conn.wait_connected()
                    interval = 10
                else:
                    interval = min(interval * 2, 120)  # backoff: 10→20→40→80→120s max
                if self._running:
                    await asyncio.sleep(interval)

    async def _monitor_topic_values(self) -> None:
        """Monitor specific topics for alert values."""
        if not self.config.monitored_topics:
            return

        # Start a task for each monitored topic
        topic_tasks = [
            asyncio.create_task(self._monitor_single_topic(tc))
            for tc in self.config.monitored_topics
        ]

        try:
            await asyncio.gather(*topic_tasks)
        except asyncio.CancelledError:
            for t in topic_tasks:
                t.cancel()
            await asyncio.gather(*topic_tasks, return_exceptions=True)
            raise

    async def _monitor_single_topic(self, topic_config: dict) -> None:
        """Monitor a single topic for specific values."""
        topic = topic_config.get("topic", "")
        field = topic_config.get("field", "data")
        alert_value = topic_config.get("alert_on_value", False)
        
        if not topic:
            return

        last_alerted = False

        while self._running:
            try:
                output = await self.conn.exec_command(
                    f"ros2 topic echo {topic} --once",
                    timeout=10.0
                )

                # Parse the field value
                field_match = re.search(rf"{field}:\s*(\S+)", output)
                if field_match:
                    value_str = field_match.group(1).lower().strip()
                    value = value_str in ('true', '1', 'yes')

                    # Alert on matching value
                    if value == alert_value and not last_alerted:
                        last_alerted = True
                        self._emit_alert(
                            alert_type=AlertType.TOPIC_VALUE,
                            severity=AlertSeverity.CRITICAL,
                            title="Критическое значение топика",
                            message=f"{topic}.{field} = {value}",
                            details={
                                "topic": topic,
                                "field": field,
                                "value": value
                            },
                            cooldown_key=f"topic_value:{topic}:{field}"
                        )
                    elif value != alert_value:
                        last_alerted = False

                await asyncio.sleep(2)  # Check every 2 seconds

            except asyncio.CancelledError:
                break
            except Exception:
                if self._running and not self.conn.connected:
                    await self.conn.wait_connected()
                if self._running:
                    await asyncio.sleep(2)
