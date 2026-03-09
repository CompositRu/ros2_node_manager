#!/usr/bin/env python3
"""Soak test — long-running integration test for the full monitoring stack.

Connects multiple WebSocket clients to FastAPI backend and monitors:
  - Throughput (msg/sec) per channel with degradation detection
  - Fan-out consistency (all clients get similar rates)
  - Heartbeat seq tracking: gaps, duplicates, inter-arrival jitter
  - Multi-topic echo: concurrent subscriptions to N topics
  - Memory / asyncio task leaks via /api/debug/stats
  - Reconnect recovery (optional: kill agent, verify data resumes)

Prerequisites:
  1. load_generator running (ros2 run monitoring_agent load_generator)
  2. monitoring_agent running (ros2 run monitoring_agent monitoring_agent)
  3. FastAPI backend running (uvicorn server.main:app --port 8080)

Usage:
    # Basic 5-minute run
    python3 tests/soak_test.py

    # 20-minute stress with 5 parallel clients and 10 echo topics
    python3 tests/soak_test.py --duration 1200 --clients 5 --echo-topics 10

    # With reconnect cycles
    python3 tests/soak_test.py --duration 600 --reconnect-cycles 3

    # Save JSON report
    python3 tests/soak_test.py --json-report soak_results.json
"""

import argparse
import asyncio
import json
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import httpx
import websockets


# ─── Configuration ────────────────────────────────────────────────────────────

REPORT_INTERVAL = 30        # seconds between status reports
BASELINE_WINDOW = 60        # seconds to collect baseline throughput
THROUGHPUT_WINDOW = 30      # sliding window for msg/sec (wide for bursty data)
DEGRADATION_THRESHOLD = 0.3 # alert if throughput drops below 30% of baseline
LEAK_THRESHOLD = 0.30       # alert if RSS grows >30%


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class ChannelStats:
    """Per-channel throughput tracking."""
    name: str
    timestamps: deque = field(default_factory=lambda: deque(maxlen=50000))
    total_messages: int = 0
    total_dropped: int = 0
    errors: int = 0
    baseline_rate: Optional[float] = None
    last_message_time: float = 0.0

    def record(self):
        now = time.monotonic()
        self.timestamps.append(now)
        self.total_messages += 1
        self.last_message_time = now

    def record_dropped(self, count: int):
        self.total_dropped += count

    def current_rate(self, window: float = THROUGHPUT_WINDOW) -> float:
        if not self.timestamps:
            return 0.0
        now = time.monotonic()
        cutoff = now - window
        count = sum(1 for t in self.timestamps if t > cutoff)
        return count / window

    def average_rate(self, since: float) -> float:
        if not self.timestamps:
            return 0.0
        now = time.monotonic()
        elapsed = now - since
        if elapsed <= 0:
            return 0.0
        count = sum(1 for t in self.timestamps if t > since)
        return count / elapsed

    def set_baseline(self):
        rate = self.current_rate(window=BASELINE_WINDOW)
        if rate > 0:
            self.baseline_rate = rate

    def is_degraded(self) -> bool:
        if self.baseline_rate is None or self.baseline_rate == 0:
            return False
        return self.current_rate() < self.baseline_rate * DEGRADATION_THRESHOLD


@dataclass
class HeartbeatTracker:
    """Tracks heartbeat sequence numbers for gap/duplicate/jitter detection."""
    seen_seqs: list = field(default_factory=list)          # all received seq numbers
    arrival_times: list = field(default_factory=list)       # monotonic time of each arrival
    gaps: list = field(default_factory=list)                # (expected, got) tuples
    duplicates: int = 0
    out_of_order: int = 0
    max_seq: int = -1
    _seen_set: set = field(default_factory=set)

    def record(self, seq: int):
        now = time.monotonic()
        self.arrival_times.append(now)

        if seq in self._seen_set:
            self.duplicates += 1
            return
        self._seen_set.add(seq)

        if seq < self.max_seq:
            self.out_of_order += 1

        self.seen_seqs.append(seq)

        if self.max_seq >= 0 and seq > self.max_seq + 1:
            for missing in range(self.max_seq + 1, seq):
                self.gaps.append(missing)

        self.max_seq = max(self.max_seq, seq)

    def jitter_stats(self) -> dict:
        """Inter-arrival time statistics (expected 1.0s for 1Hz heartbeat)."""
        if len(self.arrival_times) < 2:
            return {}
        intervals = [
            self.arrival_times[i] - self.arrival_times[i - 1]
            for i in range(1, len(self.arrival_times))
        ]
        avg = sum(intervals) / len(intervals)
        deviations = [abs(dt - 1.0) for dt in intervals]
        return {
            "count": len(intervals),
            "avg_interval": round(avg, 3),
            "avg_jitter": round(sum(deviations) / len(deviations), 3),
            "max_jitter": round(max(deviations), 3),
            "p95_jitter": round(sorted(deviations)[int(len(deviations) * 0.95)], 3),
            "min_interval": round(min(intervals), 3),
            "max_interval": round(max(intervals), 3),
        }

    def summary(self) -> dict:
        total_expected = self.max_seq - min(self.seen_seqs) + 1 if self.seen_seqs else 0
        return {
            "received": len(self.seen_seqs),
            "expected": total_expected,
            "gaps": len(self.gaps),
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "loss_percent": round(len(self.gaps) / total_expected * 100, 2) if total_expected > 0 else 0,
            "jitter": self.jitter_stats(),
        }


@dataclass
class HealthSnapshot:
    """System health metrics at a point in time."""
    timestamp: float
    connected: bool = False
    rss_mb: Optional[float] = None
    ws_clients_total: Optional[int] = None
    ws_clients_detail: Optional[dict] = None
    agent_subscriptions: Optional[int] = None
    cpu_percent: Optional[float] = None
    threads: Optional[int] = None


@dataclass
class SoakReport:
    """Final soak test report."""
    start_time: str
    duration_seconds: float
    clients: int
    channels: dict = field(default_factory=dict)
    heartbeat: Optional[dict] = None
    echo_topics_count: int = 0
    health_samples: int = 0
    rss_start_mb: Optional[float] = None
    rss_end_mb: Optional[float] = None
    rss_peak_mb: Optional[float] = None
    reconnect_cycles: int = 0
    reconnect_recoveries: int = 0
    degradation_events: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    passed: bool = True
    failure_reasons: list = field(default_factory=list)


# ─── WebSocket Client ─────────────────────────────────────────────────────────

_HEARTBEAT_RE = re.compile(r'heartbeat_(\d+)')


class SoakClient:
    """Single WebSocket client that subscribes to a channel and counts messages."""

    def __init__(self, client_id: int, ws_url: str, channel: str):
        self.client_id = client_id
        self.channel = channel
        self.ws_url = ws_url
        self.stats = ChannelStats(name=f"client{client_id}:{channel}")
        self.heartbeat: Optional[HeartbeatTracker] = None
        if channel == "heartbeat":
            self.heartbeat = HeartbeatTracker()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.connected = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self):
        """Connect and read messages, reconnecting on failure."""
        while self._running:
            try:
                async with websockets.connect(
                    self.ws_url,
                    max_size=2 * 1024 * 1024,
                    ping_interval=10,
                    ping_timeout=30,
                    close_timeout=5,
                ) as ws:
                    self.connected = True
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        msg_type = msg.get("type", "")
                        if msg_type in ("connected", "history"):
                            continue
                        if msg_type == "dropped":
                            self.stats.record_dropped(msg.get("count", 0))
                            continue
                        if msg_type == "error":
                            self.stats.errors += 1
                            continue
                        # Data message
                        self.stats.record()
                        # Parse heartbeat seq
                        if self.heartbeat is not None:
                            self._parse_heartbeat(msg)
            except asyncio.CancelledError:
                break
            except Exception:
                self.stats.errors += 1
                self.connected = False
                if self._running:
                    await asyncio.sleep(2)

    def _parse_heartbeat(self, msg: dict):
        """Extract seq number from heartbeat echo message."""
        # Message format: {"type": "echo", "topic": "...", "data": {"data": "heartbeat_42"}, ...}
        data = msg.get("data")
        if isinstance(data, dict):
            data = data.get("data", "")
        if isinstance(data, str):
            m = _HEARTBEAT_RE.search(data)
            if m:
                self.heartbeat.record(int(m.group(1)))


# ─── Health Checker ───────────────────────────────────────────────────────────

class HealthChecker:
    """Periodically polls /api/debug/stats for system metrics."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.snapshots: list[HealthSnapshot] = []
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def check(self) -> HealthSnapshot:
        snap = HealthSnapshot(timestamp=time.monotonic())
        try:
            resp = await self._client.get("/api/debug/stats")
            if resp.status_code == 200:
                data = resp.json()
                snap.connected = data.get("connection", {}).get("connected", False)
                proc = data.get("process", {})
                snap.rss_mb = proc.get("rss_mb")
                snap.cpu_percent = proc.get("cpu_percent")
                snap.threads = proc.get("threads")
                ws = data.get("websockets", {})
                if isinstance(ws, dict):
                    snap.ws_clients_total = ws.get("total", 0)
                    snap.ws_clients_detail = {
                        k: v for k, v in ws.items() if k != "total" and v > 0
                    }
                agent = data.get("agent", {})
                if isinstance(agent, dict):
                    snap.agent_subscriptions = agent.get("subscriptions")
        except Exception:
            pass

        if snap.rss_mb is None:
            try:
                resp = await self._client.get("/api/health")
                if resp.status_code == 200:
                    data = resp.json()
                    snap.connected = data.get("connected", False)
            except Exception:
                pass

        self.snapshots.append(snap)
        return snap

    async def close(self):
        await self._client.aclose()


# ─── Soak Runner ──────────────────────────────────────────────────────────────

class SoakRunner:
    """Orchestrates the soak test."""

    # Base channels (always subscribed)
    BASE_CHANNELS = [
        ("/ws/logs/all", "logs"),
        ("/ws/diagnostics", "diagnostics"),
        ("/ws/topics/echo-single/monitoring_agent/heartbeat", "heartbeat"),
    ]

    def __init__(self, args):
        self.args = args
        self.base_url = args.backend.rstrip("/")
        self.ws_base = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self.duration = args.duration
        self.num_clients = args.clients
        self.reconnect_cycles = args.reconnect_cycles
        self.echo_topics_count = args.echo_topics

        self.clients: list[SoakClient] = []
        self.health = HealthChecker(self.base_url)
        self.report = SoakReport(
            start_time=datetime.now(timezone.utc).isoformat(),
            duration_seconds=self.duration,
            clients=self.num_clients,
        )
        self._start_time = 0.0
        self._baseline_set = False
        self._reconnect_periods: list[tuple[float, float]] = []
        self._echo_channels: list[tuple[str, str]] = []  # extra echo topics

    async def run(self) -> SoakReport:
        """Main entry point."""
        print(f"\n{'='*70}")
        print(f"  SOAK TEST — {self.duration}s, {self.num_clients} client(s)")
        print(f"  Backend: {self.base_url}")
        print(f"  Echo topics: {self.echo_topics_count}")
        print(f"  Reconnect cycles: {self.reconnect_cycles}")
        print(f"{'='*70}\n")

        # Pre-flight check
        if not await self._preflight():
            self.report.passed = False
            self.report.failure_reasons.append("Pre-flight check failed")
            return self.report

        self._start_time = time.monotonic()

        # Discover echo topics if requested
        if self.echo_topics_count > 0:
            await self._discover_echo_topics()

        # Create clients
        await self._create_clients()

        try:
            await self._main_loop()
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n[INTERRUPTED] Stopping gracefully...")
        finally:
            await self._cleanup()

        self._finalize_report()
        return self.report

    async def _preflight(self) -> bool:
        """Check that backend is reachable and connected to agent."""
        print("[PREFLIGHT] Checking backend connectivity...")
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
                resp = await client.get("/api/health")
                if resp.status_code != 200:
                    print(f"  FAIL: /api/health returned {resp.status_code}")
                    return False
                data = resp.json()
                if not data.get("connected"):
                    print("  FAIL: Backend not connected to agent")
                    return False
                print(f"  OK: connected to server '{data.get('server')}'")

                resp = await client.get("/api/debug/stats")
                if resp.status_code == 200:
                    stats = resp.json()
                    proc = stats.get("process", {})
                    rss = proc.get("rss_mb")
                    if rss:
                        print(f"  OK: backend RSS = {rss:.1f} MB")
                    agent = stats.get("agent", {})
                    if agent:
                        print(f"  OK: agent stats available (uptime={agent.get('uptime', '?')}s)")
        except Exception as e:
            print(f"  FAIL: {e}")
            return False

        print()
        return True

    async def _discover_echo_topics(self):
        """Discover topics from load_generator for multi-echo test."""
        print(f"[DISCOVER] Finding {self.echo_topics_count} topics for echo test...")
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
                resp = await client.get("/api/topics/list")
                if resp.status_code != 200:
                    print(f"  WARNING: /api/topics/list returned {resp.status_code}, skipping echo topics")
                    return
                data = resp.json()
                topics = data.get("topics", [])

                # Filter: pick topics from load_generator fake nodes (have /data_ in name)
                # Exclude technical topics, heartbeat (already covered), rosout, diagnostics
                exclude = {"/rosout", "/diagnostics", "/monitoring_agent/heartbeat",
                           "/parameter_events", "/api/fail_safe/mrm_state"}
                candidates = []
                for t in topics:
                    name = t.get("name", "") if isinstance(t, dict) else str(t)
                    if name in exclude:
                        continue
                    if name.startswith("/monitoring_agent"):
                        continue
                    # Prefer data topics from load_generator nodes
                    if "/data_" in name or "/node_" in name:
                        candidates.insert(0, name)  # prioritize
                    elif not name.startswith("/_"):
                        candidates.append(name)

                selected = candidates[:self.echo_topics_count]
                if not selected:
                    print(f"  WARNING: No suitable topics found (total: {len(topics)})")
                    return

                for topic in selected:
                    ws_path = f"/ws/topics/echo-single{topic}"
                    label = f"echo:{topic.split('/')[-1]}"
                    self._echo_channels.append((ws_path, label))

                self.report.echo_topics_count = len(selected)
                print(f"  OK: selected {len(selected)} topics:")
                for t in selected[:5]:
                    print(f"    {t}")
                if len(selected) > 5:
                    print(f"    ... and {len(selected) - 5} more")
                print()

        except Exception as e:
            print(f"  WARNING: Topic discovery failed: {e}")

    async def _create_clients(self):
        """Create and start WebSocket clients."""
        all_channels = self.BASE_CHANNELS + self._echo_channels
        for i in range(self.num_clients):
            for ws_path, label in all_channels:
                url = f"{self.ws_base}{ws_path}"
                client = SoakClient(i, url, label)
                self.clients.append(client)
                await client.start()

        n_base = len(self.BASE_CHANNELS)
        n_echo = len(self._echo_channels)
        total = len(self.clients)
        print(f"[START] Created {total} WebSocket streams "
              f"({self.num_clients} client(s) × ({n_base} base + {n_echo} echo) channels)\n")

    def _in_reconnect_period(self) -> bool:
        now = time.monotonic()
        for start, end in self._reconnect_periods:
            if start - 5 <= now <= end + 30:
                return True
        return False

    async def _main_loop(self):
        """Run for `duration` seconds, reporting periodically."""
        end_time = self._start_time + self.duration
        next_report = self._start_time + REPORT_INTERVAL
        next_health = self._start_time + 10
        baseline_time = self._start_time + BASELINE_WINDOW

        # Schedule reconnect cycles
        reconnect_times = []
        if self.reconnect_cycles > 0 and self.duration > 240:
            usable = self.duration - 180
            interval = usable / (self.reconnect_cycles + 1)
            for i in range(1, self.reconnect_cycles + 1):
                reconnect_times.append(self._start_time + 120 + interval * i)
        elif self.reconnect_cycles > 0:
            print("[WARNING] Duration too short for reconnect cycles, skipping")
        next_reconnect_idx = 0

        while time.monotonic() < end_time:
            now = time.monotonic()
            elapsed = now - self._start_time

            if not self._baseline_set and now >= baseline_time:
                self._set_baselines()

            if now >= next_health:
                await self.health.check()
                next_health = now + 30

            if now >= next_report:
                self._print_report(elapsed)
                next_report = now + REPORT_INTERVAL

            if (next_reconnect_idx < len(reconnect_times)
                    and now >= reconnect_times[next_reconnect_idx]):
                next_reconnect_idx += 1
                await self._reconnect_cycle(next_reconnect_idx)

            await asyncio.sleep(1)

        self._print_report(self.duration)

    def _set_baselines(self):
        self._baseline_set = True
        print(f"[BASELINE] Establishing baseline throughput (after {BASELINE_WINDOW}s warmup):")
        for client in self.clients:
            client.stats.set_baseline()
            rate = client.stats.baseline_rate
            if rate and rate > 0:
                print(f"  {client.stats.name}: {rate:.1f} msg/s")
            else:
                print(f"  {client.stats.name}: no data (0 msg/s)")
                self.report.errors.append(f"No data on {client.stats.name} during baseline")
        # Print heartbeat seq status
        for client in self.clients:
            if client.heartbeat and client.heartbeat.seen_seqs:
                hb = client.heartbeat
                print(f"  {client.stats.name} seq: {min(hb.seen_seqs)}-{hb.max_seq} "
                      f"(gaps={len(hb.gaps)}, dupes={hb.duplicates})")
        print()

    def _print_report(self, elapsed: float):
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        in_reconnect = self._in_reconnect_period()
        print(f"[{mins:02d}:{secs:02d}]", end="")

        all_ok = True
        channel_summaries = {}

        for client in self.clients:
            rate = client.stats.current_rate()
            name = client.stats.name
            base = client.stats.baseline_rate
            ch = client.channel

            if ch not in channel_summaries:
                channel_summaries[ch] = {"rates": [], "ok": True, "errors": 0, "dropped": 0}
            channel_summaries[ch]["rates"].append(rate)
            channel_summaries[ch]["errors"] += client.stats.errors
            channel_summaries[ch]["dropped"] += client.stats.total_dropped

            if client.stats.is_degraded() and not in_reconnect:
                all_ok = False
                channel_summaries[ch]["ok"] = False
                event = f"[{mins:02d}:{secs:02d}] {name}: {rate:.1f} msg/s (baseline: {base:.1f})"
                self.report.degradation_events.append(event)

        # Print summary per channel (aggregate echo:* into one line)
        echo_rates = []
        for ch, data in channel_summaries.items():
            avg_rate = sum(data["rates"]) / len(data["rates"]) if data["rates"] else 0
            if ch.startswith("echo:"):
                echo_rates.append(avg_rate)
                continue
            parts = [f" {ch}: {avg_rate:.1f} msg/s"]
            if data["dropped"]:
                parts.append(f"dropped={data['dropped']}")
            if data["errors"]:
                parts.append(f"errors={data['errors']}")
            if not data["ok"]:
                parts.append("[DEGRADED]")
            print(" |".join(parts), end="")

        # Single line for all echo topics
        if echo_rates:
            avg_echo = sum(echo_rates) / len(echo_rates)
            min_echo = min(echo_rates)
            max_echo = max(echo_rates)
            print(f" | echo({len(echo_rates)}): avg={avg_echo:.1f} "
                  f"min={min_echo:.1f} max={max_echo:.1f} msg/s", end="")

        # Heartbeat jitter (from first heartbeat client)
        for client in self.clients:
            if client.heartbeat and len(client.heartbeat.arrival_times) > 10:
                jitter = client.heartbeat.jitter_stats()
                hb = client.heartbeat
                print(f" | hb: gaps={len(hb.gaps)} dupes={hb.duplicates} "
                      f"jitter={jitter.get('avg_jitter', 0)*1000:.0f}ms", end="")
                break

        # Health info
        if self.health.snapshots:
            snap = self.health.snapshots[-1]
            parts = []
            if snap.rss_mb is not None:
                parts.append(f"RSS={snap.rss_mb:.0f}MB")
            if snap.ws_clients_total is not None:
                parts.append(f"ws={snap.ws_clients_total}")
            if snap.cpu_percent is not None:
                parts.append(f"cpu={snap.cpu_percent:.0f}%")
            if parts:
                print(f" | {' '.join(parts)}", end="")

        connected = sum(1 for c in self.clients if c.connected)
        print(f" | clients={connected}/{len(self.clients)}", end="")

        if in_reconnect:
            print(" | RECONNECTING")
        elif all_ok:
            print(" | OK")
        else:
            print(" | DEGRADED")

    async def _reconnect_cycle(self, cycle_num: int):
        """Kill agent process and verify recovery."""
        print(f"\n{'─'*50}")
        print(f"[RECONNECT {cycle_num}/{self.reconnect_cycles}] Starting reconnect cycle...")
        self.report.reconnect_cycles += 1
        reconnect_start = time.monotonic()

        pre_rates = {}
        for client in self.clients:
            pre_rates[client.stats.name] = client.stats.current_rate()

        print("  Killing monitoring_agent process...")
        killed = False
        for pattern in ["monitoring_agent", "monitoring_agent.main"]:
            proc = await asyncio.create_subprocess_exec(
                "pkill", "-f", pattern,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await proc.wait()
            if rc == 0:
                print(f"  Killed with pattern: {pattern}")
                killed = True
                break

        if not killed:
            print("  WARNING: pkill returned non-zero, agent may not have been killed")

        downtime = 20
        print(f"  Agent down, waiting {downtime}s...")
        await asyncio.sleep(downtime)

        snap = await self.health.check()
        if snap.connected:
            print("  WARNING: Backend still reports connected after agent kill")
        else:
            print("  OK: Backend detected disconnect")

        print("  Waiting for agent to restart (manual or systemd)...")
        print("  (If agent doesn't auto-restart, start it manually now)")

        recovery_deadline = time.monotonic() + 120
        recovered = False
        while time.monotonic() < recovery_deadline:
            snap = await self.health.check()
            if snap.connected:
                print(f"  Agent reconnected!")
                await asyncio.sleep(15)
                recovered = True
                break
            await asyncio.sleep(5)

        reconnect_end = time.monotonic()
        self._reconnect_periods.append((reconnect_start, reconnect_end))

        if not recovered:
            print(f"  TIMEOUT: Agent did not reconnect within 120s")
            self.report.errors.append(f"Reconnect cycle {cycle_num}: agent did not recover")
            print(f"{'─'*50}\n")
            return

        await asyncio.sleep(15)
        post_ok = True
        for client in self.clients:
            rate = client.stats.current_rate()
            pre = pre_rates.get(client.stats.name, 0)
            if pre > 0 and rate < pre * DEGRADATION_THRESHOLD:
                print(f"  WARNING: {client.stats.name} not recovered: {rate:.1f} msg/s (was {pre:.1f})")
                post_ok = False

        if post_ok:
            self.report.reconnect_recoveries += 1
            print(f"  Recovery OK — all channels at normal throughput")
        else:
            self.report.errors.append(f"Reconnect cycle {cycle_num}: throughput not recovered")

        print(f"{'─'*50}\n")

    async def _cleanup(self):
        for client in self.clients:
            await client.stop()
        await self.health.close()

    def _finalize_report(self):
        """Build final report and determine pass/fail."""
        # Channel stats
        for client in self.clients:
            s = client.stats
            entry = {
                "total_messages": s.total_messages,
                "total_dropped": s.total_dropped,
                "errors": s.errors,
                "baseline_rate": round(s.baseline_rate, 2) if s.baseline_rate else None,
                "average_rate": round(s.average_rate(self._start_time), 2),
                "final_rate": round(s.current_rate(), 2),
            }
            self.report.channels[s.name] = entry

        # Heartbeat analysis (aggregate across all clients)
        heartbeat_summaries = []
        for client in self.clients:
            if client.heartbeat and client.heartbeat.seen_seqs:
                heartbeat_summaries.append(client.heartbeat.summary())
        if heartbeat_summaries:
            # Use first client as reference (all should be similar due to fan-out)
            self.report.heartbeat = heartbeat_summaries[0]
            # Add per-client comparison
            if len(heartbeat_summaries) > 1:
                self.report.heartbeat["per_client"] = [
                    {"client": i, **s} for i, s in enumerate(heartbeat_summaries)
                ]

        # Health stats
        self.report.health_samples = len(self.health.snapshots)
        rss_values = [s.rss_mb for s in self.health.snapshots if s.rss_mb is not None]
        if rss_values:
            self.report.rss_start_mb = rss_values[0]
            self.report.rss_end_mb = rss_values[-1]
            self.report.rss_peak_mb = max(rss_values)
            if len(rss_values) >= 2 and rss_values[0] > 0:
                growth = (rss_values[-1] - rss_values[0]) / rss_values[0]
                if growth > LEAK_THRESHOLD:
                    self.report.failure_reasons.append(
                        f"Memory leak: RSS grew {growth*100:.0f}% "
                        f"({rss_values[0]:.0f}MB → {rss_values[-1]:.0f}MB)"
                    )

        # Check zero throughput
        for client in self.clients:
            if client.stats.total_messages == 0:
                self.report.failure_reasons.append(f"No messages on {client.stats.name}")

        # Sustained degradation
        total_reports = max(1, int(self.duration / REPORT_INTERVAL))
        degradation_per_channel: dict[str, int] = {}
        for event in self.report.degradation_events:
            parts = event.split("] ", 1)
            if len(parts) > 1:
                ch = parts[1].split(":")[1] if ":" in parts[1] else "unknown"
                degradation_per_channel[ch] = degradation_per_channel.get(ch, 0) + 1
        for ch, count in degradation_per_channel.items():
            report_count = count / max(1, self.num_clients)
            ratio = report_count / total_reports
            if ratio > 0.2:
                self.report.failure_reasons.append(
                    f"Sustained degradation on {ch}: {ratio*100:.0f}% of reports"
                )

        # Reconnect recovery
        if self.reconnect_cycles > 0:
            expected = min(self.reconnect_cycles, self.report.reconnect_cycles)
            if self.report.reconnect_recoveries < expected:
                self.report.failure_reasons.append(
                    f"Reconnect recovery: {self.report.reconnect_recoveries}/{expected}"
                )

        # Fan-out consistency
        by_channel: dict[str, list[int]] = {}
        for client in self.clients:
            ch = client.channel
            if ch not in by_channel:
                by_channel[ch] = []
            by_channel[ch].append(client.stats.total_messages)
        for ch, counts in by_channel.items():
            if counts and max(counts) > 0:
                spread = (max(counts) - min(counts)) / max(counts)
                if spread > 0.1:
                    self.report.failure_reasons.append(
                        f"Fan-out inconsistency on {ch}: {min(counts)}-{max(counts)} messages"
                    )

        # Heartbeat checks
        total_downtime = sum(end - start for start, end in self._reconnect_periods)
        effective_duration = max(1, self.duration - total_downtime)
        for client in self.clients:
            if client.channel == "heartbeat" and client.stats.total_messages > 0:
                expected_rate = client.stats.total_messages / effective_duration
                if expected_rate < 0.5:
                    self.report.failure_reasons.append(
                        f"Heartbeat too slow on {client.stats.name}: "
                        f"{expected_rate:.2f} msg/s (expected ~1.0)"
                    )
                elif expected_rate > 2.0:
                    self.report.failure_reasons.append(
                        f"Heartbeat too fast on {client.stats.name}: "
                        f"{expected_rate:.2f} msg/s (expected ~1.0, possible duplicates)"
                    )

        # Heartbeat seq integrity: gaps > 5% = fail, any duplicates = fail
        for client in self.clients:
            if client.heartbeat and client.heartbeat.seen_seqs:
                hb = client.heartbeat
                total_expected = hb.max_seq - min(hb.seen_seqs) + 1
                if total_expected > 0:
                    loss_pct = len(hb.gaps) / total_expected * 100
                    if loss_pct > 5:
                        self.report.failure_reasons.append(
                            f"Heartbeat loss {loss_pct:.1f}% on {client.stats.name} "
                            f"({len(hb.gaps)} gaps in {total_expected} expected)"
                        )
                if hb.duplicates > 0:
                    self.report.failure_reasons.append(
                        f"Heartbeat duplicates on {client.stats.name}: {hb.duplicates}"
                    )
                # Jitter: p95 > 2s = fail (heartbeat is 1 Hz)
                jitter = hb.jitter_stats()
                if jitter.get("p95_jitter", 0) > 2.0:
                    self.report.failure_reasons.append(
                        f"Heartbeat jitter too high on {client.stats.name}: "
                        f"p95={jitter['p95_jitter']:.1f}s"
                    )
                break  # check only first client (all see same fan-out)

        # Multi-echo: all echo topics should have data
        for client in self.clients:
            if client.channel.startswith("echo:") and client.client_id == 0:
                if client.stats.total_messages == 0:
                    self.report.failure_reasons.append(
                        f"Echo topic dead: {client.stats.name}"
                    )

        self.report.passed = len(self.report.failure_reasons) == 0
        self._print_summary()

    def _print_summary(self):
        print(f"\n{'='*70}")
        print(f"  SOAK TEST {'PASSED' if self.report.passed else 'FAILED'}")
        print(f"{'='*70}")

        print(f"\n  Duration: {self.report.duration_seconds:.0f}s")
        print(f"  Clients: {self.report.clients}")

        # Aggregate by channel type for cleaner output
        by_type: dict[str, list] = {}
        for name, data in self.report.channels.items():
            ch = name.split(":", 1)[1] if ":" in name else name
            # Group all echo:* together
            group = "echo" if ch.startswith("echo:") else ch
            if group not in by_type:
                by_type[group] = []
            by_type[group].append(data)

        print(f"\n  Channel summary:")
        for ch, items in by_type.items():
            if ch == "echo" and len(items) > 3:
                # Summarize echo topics
                msgs = [d['total_messages'] for d in items]
                rates = [d['average_rate'] for d in items]
                dropped = sum(d['total_dropped'] for d in items)
                errors = sum(d['errors'] for d in items)
                topics_per_client = len(items) // max(1, self.num_clients)
                print(f"    echo: {topics_per_client} topics × {self.num_clients} clients")
                print(f"      msgs: {min(msgs)}-{max(msgs)} per stream, "
                      f"avg rate: {sum(rates)/len(rates):.2f} msg/s")
                if dropped:
                    print(f"      dropped: {dropped}")
                if errors:
                    print(f"      errors: {errors}")
            else:
                msgs = [d['total_messages'] for d in items]
                dropped = sum(d['total_dropped'] for d in items)
                errors = sum(d['errors'] for d in items)
                avg_rate = sum(d['average_rate'] for d in items) / len(items)
                baseline = items[0].get('baseline_rate')

                print(f"    {ch}: {msgs[0]} msgs/client (×{len(items)})")
                print(f"      avg rate: {avg_rate:.2f} msg/s"
                      + (f", baseline: {baseline:.2f} msg/s" if baseline else ""))
                if dropped:
                    print(f"      dropped: {dropped}")
                if errors:
                    print(f"      errors: {errors}")
                if len(set(msgs)) == 1:
                    print(f"      fan-out: perfect (all clients equal)")
                else:
                    print(f"      fan-out: {min(msgs)}-{max(msgs)} msgs")

        # Heartbeat detailed stats
        if self.report.heartbeat:
            hb = self.report.heartbeat
            print(f"\n  Heartbeat integrity:")
            print(f"    received: {hb['received']}, expected: {hb['expected']}, "
                  f"loss: {hb['loss_percent']:.1f}%")
            print(f"    gaps: {hb['gaps']}, duplicates: {hb['duplicates']}, "
                  f"out_of_order: {hb['out_of_order']}")
            jitter = hb.get('jitter', {})
            if jitter:
                print(f"    jitter: avg={jitter['avg_jitter']*1000:.0f}ms, "
                      f"p95={jitter['p95_jitter']*1000:.0f}ms, "
                      f"max={jitter['max_jitter']*1000:.0f}ms")
                print(f"    interval: avg={jitter['avg_interval']:.3f}s "
                      f"[{jitter['min_interval']:.3f}-{jitter['max_interval']:.3f}]")

        if self.report.rss_start_mb:
            growth = 0
            if self.report.rss_start_mb > 0:
                growth = (self.report.rss_end_mb - self.report.rss_start_mb) / self.report.rss_start_mb * 100
            print(f"\n  Memory: {self.report.rss_start_mb:.0f}MB → "
                  f"{self.report.rss_end_mb:.0f}MB "
                  f"(peak: {self.report.rss_peak_mb:.0f}MB, growth: {growth:+.0f}%)")

        if self.report.reconnect_cycles:
            print(f"\n  Reconnects: {self.report.reconnect_recoveries}/"
                  f"{self.report.reconnect_cycles} recovered")

        if self.report.degradation_events:
            print(f"\n  Degradation events: {len(self.report.degradation_events)} "
                  f"(outside reconnect windows)")
            for ev in self.report.degradation_events[:5]:
                print(f"    {ev}")
            if len(self.report.degradation_events) > 5:
                print(f"    ... and {len(self.report.degradation_events) - 5} more")

        if not self.report.passed:
            print(f"\n  FAILURE REASONS:")
            for reason in self.report.failure_reasons:
                print(f"    - {reason}")

        if self.report.errors:
            print(f"\n  Errors ({len(self.report.errors)}):")
            for err in self.report.errors[:10]:
                print(f"    - {err}")

        print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Soak test for tram monitoring system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--duration", type=int, default=300,
        help="Test duration in seconds (default: 300 = 5min)",
    )
    parser.add_argument(
        "--clients", type=int, default=2,
        help="Number of parallel client sets (default: 2)",
    )
    parser.add_argument(
        "--echo-topics", type=int, default=0,
        help="Number of extra echo topics to subscribe (default: 0)",
    )
    parser.add_argument(
        "--reconnect-cycles", type=int, default=0,
        help="Number of agent kill/restart cycles (default: 0)",
    )
    parser.add_argument(
        "--backend", type=str, default="http://localhost:8080",
        help="Backend base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--json-report", type=str, default=None,
        help="Save JSON report to file",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    runner = SoakRunner(args)
    report = await runner.run()

    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump(asdict(report), f, indent=2, default=str)
        print(f"Report saved to {args.json_report}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
