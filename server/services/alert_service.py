"""Alert monitoring service for ROS2 Node Manager."""

import asyncio
import re
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional, Callable, Set, Dict
import uuid

from ..connection import BaseConnection
from ..models import Alert, AlertType, AlertSeverity, AlertConfig, NodeStatus


class AlertService:
    """
    Service for monitoring and generating alerts.
    
    Features:
    - Background monitoring (независимо от WebSocket подключений)
    - Дедупликация с cooldown
    - Очередь алертов для WebSocket subscribers
    - Мониторинг: падение нод, пропажа топиков, паттерны в логах
    """

    def __init__(self, connection: BaseConnection, config: AlertConfig):
        self.conn = connection
        self.config = config
        
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
        
        # Running state
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all monitoring tasks."""
        if not self.config.enabled:
            print("⚠️ Alert service disabled in config")
            return

        self._running = True
        print("🔔 Alert service starting...")

        # Start monitoring tasks
        self._tasks = [
            asyncio.create_task(self._monitor_nodes_loop()),
            asyncio.create_task(self._monitor_missing_topics()),
            asyncio.create_task(self._monitor_rosout_patterns()),
            asyncio.create_task(self._monitor_topic_values()),
        ]
        
        print("🔔 Alert service started")

    async def stop(self) -> None:
        """Stop all monitoring tasks."""
        self._running = False
        print("🔔 Alert service stopping...")
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks = []
        self._subscribers.clear()
        print("🔔 Alert service stopped")

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
                print(f"Error in alert subscriber: {e}")

        print(f"🔔 Alert: [{severity.value}] {title}: {message}")
        return True

    # ─────────────────────────────────────────────────────────────────
    # Background monitoring tasks
    # ─────────────────────────────────────────────────────────────────

    async def _monitor_nodes_loop(self) -> None:
        """
        Background task to monitor node statuses.
        This runs independently of WebSocket connections.
        """
        while self._running:
            try:
                # Get current nodes
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

                await asyncio.sleep(5)  # Check every 5 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in node monitoring: {e}")
                await asyncio.sleep(5)

    async def _monitor_missing_topics(self) -> None:
        """Monitor for missing important topics."""
        if not self.config.important_topics:
            return

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

                await asyncio.sleep(10)  # Check every 10 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error monitoring topics: {e}")
                await asyncio.sleep(10)

    async def _monitor_rosout_patterns(self) -> None:
        """Monitor /rosout for error patterns."""
        if not self.config.error_patterns:
            return

        # Compile patterns
        compiled_patterns = []
        for p in self.config.error_patterns:
            try:
                compiled_patterns.append((
                    re.compile(p["pattern"], re.IGNORECASE),
                    p.get("severity", "error")
                ))
            except re.error as e:
                print(f"Invalid regex pattern '{p['pattern']}': {e}")

        if not compiled_patterns:
            return

        cmd = "ros2 topic echo /rosout --no-arr --qos-reliability best_effort --qos-history keep_last --qos-depth 100"
        buffer = []

        while self._running:
            try:
                async for line in self.conn.exec_stream(cmd):
                    if not self._running:
                        break

                    buffer.append(line)

                    # Message separator
                    if line.strip() == "---":
                        text = "\n".join(buffer)
                        buffer = []

                        # Extract message and node name
                        msg_match = re.search(r"msg:\s*['\"]?([^'\"}\n]*)", text)
                        name_match = re.search(r"name:\s*['\"]?([^'\"}\n]+)", text)

                        if msg_match:
                            msg = msg_match.group(1).strip()
                            node_name = name_match.group(1).strip() if name_match else "unknown"

                            # Check against patterns
                            for pattern, severity in compiled_patterns:
                                if pattern.search(msg):
                                    # Truncate long messages
                                    display_msg = msg[:150] + "..." if len(msg) > 150 else msg
                                    
                                    self._emit_alert(
                                        alert_type=AlertType.ERROR_PATTERN,
                                        severity=AlertSeverity(severity),
                                        title=f"Ошибка в логах",
                                        message=f"[{node_name}] {display_msg}",
                                        details={
                                            "node_name": node_name,
                                            "pattern": pattern.pattern,
                                            "full_message": msg
                                        },
                                        cooldown_key=f"error_pattern:{pattern.pattern}:{node_name}"
                                    )
                                    break  # Only one alert per message

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error monitoring rosout: {e}")
                await asyncio.sleep(5)

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
                await asyncio.sleep(5)
