"""Persistent storage for log and alert history using SQLite."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

from ..models import LogMessage, Alert


# Retention limits
MAX_LOGS = 50_000
MAX_ALERTS = 10_000
RETENTION_CHECK_INTERVAL = 100  # check every N inserts
LOG_FLUSH_INTERVAL = 1.0  # seconds
LOG_FLUSH_BATCH = 50  # flush after N buffered logs

# Log level priorities (higher = more severe)
LOG_LEVEL_PRIORITY = {
    "DEBUG": 0,
    "INFO": 1,
    "WARN": 2,
    "ERROR": 3,
    "FATAL": 4,
}


class HistoryStore:
    """Async SQLite storage for log and alert history."""

    def __init__(self, server_id: str, data_dir: Path, min_log_level: str = "WARN"):
        self.server_id = server_id
        self.db_path = data_dir / f"history_{server_id}.db"
        self.min_log_level = min_log_level.upper()
        self._min_level_priority = LOG_LEVEL_PRIORITY.get(self.min_log_level, 2)
        self._db: Optional[aiosqlite.Connection] = None
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None

        # Batched log writes
        self._log_buffer: list[LogMessage] = []

        # Retention counters
        self._log_insert_count = 0
        self._alert_insert_count = 0

    async def initialize(self) -> None:
        """Open DB and create tables/indexes."""
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                node_name TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                node_name TEXT DEFAULT '',
                details TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
            CREATE INDEX IF NOT EXISTS idx_logs_node_name ON logs(node_name);
            CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);
            CREATE INDEX IF NOT EXISTS idx_alerts_alert_type ON alerts(alert_type);
            CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_node_name ON alerts(node_name);
        """)
        await self._db.commit()
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(f"History store initialized: {self.db_path} (min_log_level={self.min_log_level})")

    async def close(self) -> None:
        """Stop background tasks and close DB."""
        self._running = False

        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Flush remaining logs
        await self._flush_log_buffer()

        if self._db:
            await self._db.close()
            self._db = None
        logger.info("History store closed")

    # ─────────────────────────────────────────────────────────────────
    # Callback from LogCollector (sync, called for every log message)
    # ─────────────────────────────────────────────────────────────────

    def on_log_message(self, log_msg: LogMessage) -> None:
        """Called by LogCollector for every /rosout message. Filters and buffers."""
        level_priority = LOG_LEVEL_PRIORITY.get(log_msg.level.upper(), 1)
        if level_priority < self._min_level_priority:
            return

        self._log_buffer.append(log_msg)
        if len(self._log_buffer) >= LOG_FLUSH_BATCH:
            asyncio.ensure_future(self._flush_log_buffer())

    async def _periodic_flush(self) -> None:
        """Flush log buffer periodically."""
        while self._running:
            try:
                await asyncio.sleep(LOG_FLUSH_INTERVAL)
                await self._flush_log_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"History flush error: {e}")

    async def _flush_log_buffer(self) -> None:
        """Write buffered logs to SQLite."""
        if not self._log_buffer or not self._db:
            return

        batch = self._log_buffer[:]
        self._log_buffer.clear()

        try:
            await self._db.executemany(
                "INSERT INTO logs (timestamp, level, node_name, message) VALUES (?, ?, ?, ?)",
                [(l.timestamp.isoformat(), l.level, l.node_name, l.message) for l in batch],
            )
            await self._db.commit()

            self._log_insert_count += len(batch)
            if self._log_insert_count >= RETENTION_CHECK_INTERVAL:
                self._log_insert_count = 0
                await self._enforce_log_retention()
        except Exception as e:
            logger.error(f"History flush DB error: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Write: alerts
    # ─────────────────────────────────────────────────────────────────

    async def store_alert(self, alert: Alert) -> None:
        """Persist a single alert."""
        if not self._db:
            return

        node_name = alert.details.get("node_name", "") if alert.details else ""
        details_json = json.dumps(alert.details or {}, default=str)

        try:
            await self._db.execute(
                "INSERT OR IGNORE INTO alerts (id, alert_type, severity, title, message, timestamp, node_name, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alert.id,
                    alert.alert_type.value,
                    alert.severity.value,
                    alert.title,
                    alert.message,
                    alert.timestamp.isoformat(),
                    node_name,
                    details_json,
                ),
            )
            await self._db.commit()

            self._alert_insert_count += 1
            if self._alert_insert_count >= RETENTION_CHECK_INTERVAL:
                self._alert_insert_count = 0
                await self._enforce_alert_retention()
        except Exception as e:
            logger.error(f"History store alert error: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Read: logs
    # ─────────────────────────────────────────────────────────────────

    async def query_logs(
        self,
        *,
        level: Optional[str] = None,
        node_name: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Query logs with filters and pagination."""
        conditions, params = self._build_log_conditions(level, node_name, search, since, until)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        async with self._db.execute(f"SELECT COUNT(*) FROM logs{where}", params) as cursor:
            row = await cursor.fetchone()
            total = row[0]

        async with self._db.execute(
            f"SELECT * FROM logs{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cursor:
            rows = await cursor.fetchall()

        items = [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "level": r["level"],
                "node_name": r["node_name"],
                "message": r["message"],
            }
            for r in rows
        ]

        return {"items": items, "total": total, "limit": limit, "offset": offset}

    # ─────────────────────────────────────────────────────────────────
    # Read: alerts
    # ─────────────────────────────────────────────────────────────────

    async def query_alerts(
        self,
        *,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        node_name: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Query alerts with filters and pagination."""
        conditions: list[str] = []
        params: list = []

        if alert_type:
            conditions.append("alert_type = ?")
            params.append(alert_type)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if node_name:
            conditions.append("node_name LIKE ?")
            params.append(f"%{node_name}%")
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        async with self._db.execute(f"SELECT COUNT(*) FROM alerts{where}", params) as cursor:
            row = await cursor.fetchone()
            total = row[0]

        async with self._db.execute(
            f"SELECT * FROM alerts{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cursor:
            rows = await cursor.fetchall()

        items = [
            {
                "id": r["id"],
                "alert_type": r["alert_type"],
                "severity": r["severity"],
                "title": r["title"],
                "message": r["message"],
                "timestamp": r["timestamp"],
                "node_name": r["node_name"],
                "details": json.loads(r["details"]) if r["details"] else {},
            }
            for r in rows
        ]

        return {"items": items, "total": total, "limit": limit, "offset": offset}

    # ─────────────────────────────────────────────────────────────────
    # Export
    # ─────────────────────────────────────────────────────────────────

    async def export_logs(
        self,
        *,
        format: str = "json",
        level: Optional[str] = None,
        node_name: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> list | str:
        """Export logs (no pagination, up to 100k rows)."""
        conditions, params = self._build_log_conditions(level, node_name, search, since, until)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        async with self._db.execute(
            f"SELECT * FROM logs{where} ORDER BY timestamp DESC LIMIT 100000",
            params,
        ) as cursor:
            rows = await cursor.fetchall()

        if format == "json":
            return [
                {
                    "timestamp": r["timestamp"],
                    "level": r["level"],
                    "node_name": r["node_name"],
                    "message": r["message"],
                }
                for r in rows
            ]
        else:
            lines = []
            for r in rows:
                ts = r["timestamp"]
                lines.append(f"{ts} [{r['level']}] [{r['node_name']}] {r['message']}")
            return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────
    # Stats
    # ─────────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        """Get history statistics."""
        if not self._db:
            return {"logs_count": 0, "alerts_count": 0}

        async with self._db.execute("SELECT COUNT(*) FROM logs") as cursor:
            logs_count = (await cursor.fetchone())[0]

        async with self._db.execute("SELECT COUNT(*) FROM alerts") as cursor:
            alerts_count = (await cursor.fetchone())[0]

        async with self._db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM logs"
        ) as cursor:
            row = await cursor.fetchone()
            logs_oldest = row[0]
            logs_newest = row[1]

        async with self._db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM alerts"
        ) as cursor:
            row = await cursor.fetchone()
            alerts_oldest = row[0]
            alerts_newest = row[1]

        return {
            "logs_count": logs_count,
            "alerts_count": alerts_count,
            "logs_oldest": logs_oldest,
            "logs_newest": logs_newest,
            "alerts_oldest": alerts_oldest,
            "alerts_newest": alerts_newest,
        }

    # ─────────────────────────────────────────────────────────────────
    # Retention
    # ─────────────────────────────────────────────────────────────────

    async def _enforce_log_retention(self) -> None:
        """Delete oldest logs if over limit."""
        try:
            async with self._db.execute("SELECT COUNT(*) FROM logs") as cursor:
                count = (await cursor.fetchone())[0]
            if count > MAX_LOGS:
                excess = count - MAX_LOGS
                await self._db.execute(
                    "DELETE FROM logs WHERE id IN (SELECT id FROM logs ORDER BY timestamp ASC LIMIT ?)",
                    (excess,),
                )
                await self._db.commit()
                logger.info(f"Retention: deleted {excess} old logs")
        except Exception as e:
            logger.error(f"Retention error (logs): {e}")

    async def _enforce_alert_retention(self) -> None:
        """Delete oldest alerts if over limit."""
        try:
            async with self._db.execute("SELECT COUNT(*) FROM alerts") as cursor:
                count = (await cursor.fetchone())[0]
            if count > MAX_ALERTS:
                excess = count - MAX_ALERTS
                await self._db.execute(
                    "DELETE FROM alerts WHERE id IN (SELECT id FROM alerts ORDER BY timestamp ASC LIMIT ?)",
                    (excess,),
                )
                await self._db.commit()
                logger.info(f"Retention: deleted {excess} old alerts")
        except Exception as e:
            logger.error(f"Retention error (alerts): {e}")

    # ─────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────

    def _build_log_conditions(self, level, node_name, search, since, until):
        conditions: list[str] = []
        params: list = []

        if level:
            conditions.append("level = ?")
            params.append(level)
        if node_name:
            conditions.append("node_name LIKE ?")
            params.append(f"%{node_name}%")
        if search:
            conditions.append("message LIKE ?")
            params.append(f"%{search}%")
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        return conditions, params
