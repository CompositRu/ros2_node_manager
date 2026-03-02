"""Lightweight metrics tracker for resource monitoring."""

import os
import time
from dataclasses import dataclass, field
from threading import Lock

import psutil


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
    _ws_topic_hz_connections: int = 0
    _ws_topic_echo_connections: int = 0

    # CPU tracking (persistent process handle + cumulative times)
    _proc: object = field(default=None, repr=False)
    _last_cpu_time: float = 0.0
    _last_cpu_check: float = 0.0
    _last_cpu_percent: float = 0.0

    def __post_init__(self):
        self._proc = psutil.Process(os.getpid())
        self._last_cpu_time = self._get_total_cpu_time()
        self._last_cpu_check = time.time()

    def _get_total_cpu_time(self) -> float:
        """Get cumulative CPU time (user+system) for this process + all children.

        Uses children_user/children_system from getrusage(RUSAGE_CHILDREN),
        which includes CPU time of all waited-for child processes (docker exec, etc.)
        even after they terminate.
        """
        try:
            t = self._proc.cpu_times()
            return (t.user + t.system +
                    getattr(t, 'children_user', 0) +
                    getattr(t, 'children_system', 0))
        except Exception:
            return 0.0

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
        # CPU: delta of cumulative time / wall clock delta
        now = time.time()
        current_cpu_time = self._get_total_cpu_time()
        elapsed = now - self._last_cpu_check
        if elapsed > 0.5:  # avoid division by tiny intervals
            self._last_cpu_percent = round(
                (current_cpu_time - self._last_cpu_time) / elapsed * 100, 1
            )
            self._last_cpu_time = current_cpu_time
            self._last_cpu_check = now

        # Memory: main process + live children
        mem_info = self._proc.memory_info()
        children_rss = 0
        children_count = 0
        try:
            for child in self._proc.children(recursive=True):
                try:
                    children_rss += child.memory_info().rss
                    children_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

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
                    "topic_hz": self._ws_topic_hz_connections,
                    "topic_echo": self._ws_topic_echo_connections,
                    "total": (
                        self._ws_status_connections
                        + self._ws_log_connections
                        + self._ws_log_all_connections
                        + self._ws_alert_connections
                        + self._ws_diagnostic_connections
                        + self._ws_topic_hz_connections
                        + self._ws_topic_echo_connections
                    ),
                },
                "process": {
                    "pid": os.getpid(),
                    "rss_mb": round((mem_info.rss + children_rss) / 1024 / 1024, 1),
                    "vms_mb": round(mem_info.vms / 1024 / 1024, 1),
                    "cpu_percent": self._last_cpu_percent,
                    "children": children_count,
                    "threads": self._proc.num_threads(),
                },
            }


# Singleton instance
metrics = Metrics()
