"""Lightweight metrics tracker for resource monitoring."""

import os
import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class Metrics:
    """Global application metrics (singleton)."""

    _start_time: float = field(default_factory=time.time)

    # Subprocess tracking
    _active_subprocesses: int = 0
    _total_commands_executed: int = 0
    _active_streams: int = 0
    _lock: Lock = field(default_factory=Lock)

    # WebSocket tracking
    _ws_status_connections: int = 0
    _ws_log_connections: int = 0
    _ws_log_all_connections: int = 0
    _ws_alert_connections: int = 0
    _ws_diagnostic_connections: int = 0

    def subprocess_started(self) -> None:
        with self._lock:
            self._active_subprocesses += 1
            self._total_commands_executed += 1

    def subprocess_finished(self) -> None:
        with self._lock:
            self._active_subprocesses = max(0, self._active_subprocesses - 1)

    def stream_started(self) -> None:
        with self._lock:
            self._active_streams += 1

    def stream_finished(self) -> None:
        with self._lock:
            self._active_streams = max(0, self._active_streams - 1)

    def ws_connect(self, ws_type: str) -> None:
        """ws_type: 'status', 'log', or 'alert'"""
        attr = f"_ws_{ws_type}_connections"
        with self._lock:
            setattr(self, attr, getattr(self, attr) + 1)

    def ws_disconnect(self, ws_type: str) -> None:
        attr = f"_ws_{ws_type}_connections"
        with self._lock:
            setattr(self, attr, max(0, getattr(self, attr) - 1))

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    def snapshot(self) -> dict:
        """Return a copy of all metrics as a dict."""
        import psutil

        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()

        with self._lock:
            return {
                "uptime_seconds": round(self.uptime_seconds, 1),
                "subprocesses": {
                    "active_exec": self._active_subprocesses,
                    "active_streams": self._active_streams,
                    "total_commands": self._total_commands_executed,
                },
                "websockets": {
                    "status": self._ws_status_connections,
                    "log": self._ws_log_connections,
                    "log_all": self._ws_log_all_connections,
                    "alert": self._ws_alert_connections,
                    "diagnostic": self._ws_diagnostic_connections,
                    "total": (
                        self._ws_status_connections
                        + self._ws_log_connections
                        + self._ws_log_all_connections
                        + self._ws_alert_connections
                        + self._ws_diagnostic_connections
                    ),
                },
                "process": {
                    "pid": os.getpid(),
                    "rss_mb": round(mem_info.rss / 1024 / 1024, 1),
                    "vms_mb": round(mem_info.vms / 1024 / 1024, 1),
                    "cpu_percent": proc.cpu_percent(interval=0),
                    "threads": proc.num_threads(),
                },
            }


# Singleton instance
metrics = Metrics()
