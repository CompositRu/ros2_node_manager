#!/usr/bin/env python3
"""E2E test suite for monitoring_agent integration.

Tests the full stack at 4 levels:
  - rpc:   Direct WebSocket JSON-RPC to monitoring_agent
  - api:   HTTP REST endpoints through FastAPI
  - ws:    WebSocket streaming through FastAPI
  - infra: Infrastructure (connect, health, debug)

Usage:
    # All levels (needs both agent + FastAPI running)
    python tests/e2e_agent.py

    # RPC only (just needs agent)
    python tests/e2e_agent.py --level rpc

    # Specific test
    python tests/e2e_agent.py --test rpc.graph.nodes -v

    # Save JSON report
    python tests/e2e_agent.py --json-report results.json
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import httpx
import websockets


# ─── Test Result ────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    level: str  # rpc | api | ws | infra
    passed: bool
    latency_ms: float = 0.0
    error: Optional[str] = None
    details: dict = field(default_factory=dict)
    skipped: bool = False
    no_data: bool = False  # test ran but received no data — inconclusive


# ─── Test Registry ──────────────────────────────────────────────────────────

_tests: list[tuple[str, str, bool, callable]] = []  # (name, level, destructive, func)


def test(level: str, name: str, destructive: bool = False):
    """Register an e2e test function."""
    def decorator(func):
        _tests.append((name, level, destructive, func))
        return func
    return decorator


# ─── Agent RPC Client ──────────────────────────────────────────────────────

class AgentRPCClient:
    """Thin WebSocket JSON-RPC 2.0 client for direct agent testing."""

    def __init__(self):
        self._ws = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._subscription_queues: dict[str, asyncio.Queue] = {}
        self._reader_task: Optional[asyncio.Task] = None

    async def connect(self, url: str, timeout: float = 10.0):
        self._ws = await asyncio.wait_for(
            websockets.connect(url, max_size=2 * 1024 * 1024, ping_interval=10, ping_timeout=30),
            timeout=timeout,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def close(self):
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        self._subscription_queues.clear()

    async def call(self, method: str, params: dict = None, timeout: float = 30.0):
        self._request_id += 1
        req_id = self._request_id
        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": req_id,
        })
        await self._ws.send(msg)
        return await asyncio.wait_for(future, timeout=timeout)

    async def subscribe(self, channel: str, params: dict = None, timeout: float = 10.0) -> str:
        result = await self.call("subscribe", {"channel": channel, "params": params or {}}, timeout=timeout)
        sub_id = result["subscription"]
        self._subscription_queues[sub_id] = asyncio.Queue(maxsize=500)
        return sub_id

    async def unsubscribe(self, sub_id: str):
        try:
            await self.call("unsubscribe", {"subscription": sub_id}, timeout=5.0)
        except Exception:
            pass
        self._subscription_queues.pop(sub_id, None)

    async def read_events(self, sub_id: str, count: int, timeout: float) -> list:
        """Read up to `count` events within `timeout` seconds."""
        queue = self._subscription_queues.get(sub_id)
        if not queue:
            return []
        events = []
        deadline = time.monotonic() + timeout
        while len(events) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                data = await asyncio.wait_for(queue.get(), timeout=remaining)
                events.append(data)
            except asyncio.TimeoutError:
                break
        return events

    async def _reader_loop(self):
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "id" in msg and msg["id"] is not None:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            err = msg["error"]
                            fut.set_exception(
                                RuntimeError(f"Agent error {err.get('code')}: {err.get('message')}")
                            )
                        else:
                            fut.set_result(msg.get("result"))
                elif msg.get("method") == "event":
                    params = msg.get("params", {})
                    sub_id = params.get("subscription", "")
                    queue = self._subscription_queues.get(sub_id)
                    if queue:
                        try:
                            queue.put_nowait(params.get("data"))
                        except asyncio.QueueFull:
                            pass
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass


# ─── Discovery Context ─────────────────────────────────────────────────────

@dataclass
class DiscoveryContext:
    """Dynamic discovery of available ROS2 entities."""
    nodes: list[str] = field(default_factory=list)
    topics: list = field(default_factory=list)       # list of dicts or [name, [types]]
    services: list = field(default_factory=list)
    services_typed: list = field(default_factory=list)
    sample_node: str = ""
    sample_topic: str = ""
    sample_topic_type: str = ""
    sample_service: str = ""
    sample_service_type: str = ""
    has_diagnostics: bool = False
    has_lifecycle_node: str = ""  # name of first lifecycle node found


# ─── Test Runner ────────────────────────────────────────────────────────────

class E2ERunner:
    def __init__(self, args):
        self.args = args
        self.agent: Optional[AgentRPCClient] = None
        self.http: Optional[httpx.AsyncClient] = None
        self.ctx = DiscoveryContext()
        self.results: list[TestResult] = []
        self.timeout_mult: float = args.timeout_mult

    def t(self, base: float) -> float:
        """Apply timeout multiplier."""
        return base * self.timeout_mult

    async def setup(self):
        """Connect clients and run discovery."""
        # Agent connection
        if self.args.agent_url:
            self.agent = AgentRPCClient()
            try:
                await self.agent.connect(self.args.agent_url, timeout=self.t(10))
                print(f"  Agent connected: {self.args.agent_url}")
            except Exception as e:
                print(f"  Agent connection FAILED: {e}")
                self.agent = None

        # HTTP client
        if self.args.api_url:
            self.http = httpx.AsyncClient(base_url=self.args.api_url, timeout=self.t(30))
            try:
                r = await self.http.get("/health")
                print(f"  API connected: {self.args.api_url} (status={r.status_code})")
            except Exception as e:
                print(f"  API connection FAILED: {e}")
                await self.http.aclose()
                self.http = None

        # Discovery via agent RPC (primary) or API (fallback)
        await self._discover()

    async def _discover(self):
        """Discover available nodes, topics, services."""
        if self.agent:
            try:
                self.ctx.nodes = await self.agent.call("graph.nodes", timeout=self.t(10))
                self.ctx.topics = await self.agent.call("graph.topics", timeout=self.t(10))
                self.ctx.services = await self.agent.call("graph.services", timeout=self.t(10))
                self.ctx.services_typed = await self.agent.call("graph.services_typed", timeout=self.t(10))
            except Exception as e:
                print(f"  Discovery via agent failed: {e}")

        if not self.ctx.nodes and self.http:
            try:
                r = await self.http.get("/api/nodes", params={"refresh": "true"})
                if r.status_code == 200:
                    data = r.json()
                    self.ctx.nodes = [n["name"] for n in data.get("nodes", [])]
            except Exception:
                pass
            try:
                r = await self.http.get("/api/topics/list")
                if r.status_code == 200:
                    self.ctx.topics = r.json().get("topics", [])
            except Exception:
                pass
            try:
                r = await self.http.get("/api/services/list", params={"include_technical": "true"})
                if r.status_code == 200:
                    self.ctx.services_typed = r.json().get("services", [])
                    self.ctx.services = [s["name"] for s in self.ctx.services_typed]
            except Exception:
                pass

        # Pick samples
        if self.ctx.nodes:
            self.ctx.sample_node = self.ctx.nodes[0]
        if self.ctx.topics:
            t = self.ctx.topics[0]
            if isinstance(t, dict):
                self.ctx.sample_topic = t.get("name", "")
                self.ctx.sample_topic_type = t.get("type", "")
            elif isinstance(t, list) and len(t) >= 2:
                self.ctx.sample_topic = t[0]
                self.ctx.sample_topic_type = t[1][0] if isinstance(t[1], list) and t[1] else str(t[1])

        # Check for /diagnostics topic
        for t in self.ctx.topics:
            name = t.get("name", "") if isinstance(t, dict) else (t[0] if isinstance(t, list) else "")
            if name == "/diagnostics":
                self.ctx.has_diagnostics = True
                break

        if self.ctx.services_typed:
            s = self.ctx.services_typed[0]
            if isinstance(s, dict):
                self.ctx.sample_service = s.get("name", "")
                self.ctx.sample_service_type = s.get("type", "")
        elif self.ctx.services:
            self.ctx.sample_service = self.ctx.services[0]

        # Find a lifecycle node (try first few)
        if self.agent and self.ctx.nodes:
            for node in self.ctx.nodes[:10]:
                try:
                    result = await self.agent.call("lifecycle.is_lifecycle", {"node": node}, timeout=self.t(5))
                    if result.get("is_lifecycle"):
                        self.ctx.has_lifecycle_node = node
                        break
                except Exception:
                    continue

        n_nodes = len(self.ctx.nodes)
        n_topics = len(self.ctx.topics)
        n_services = len(self.ctx.services) or len(self.ctx.services_typed)
        print(f"  Discovery: {n_nodes} nodes, {n_topics} topics, {n_services} services")
        if self.ctx.sample_node:
            print(f"  Sample node: {self.ctx.sample_node}")
        if self.ctx.has_lifecycle_node:
            print(f"  Lifecycle node: {self.ctx.has_lifecycle_node}")

    async def run(self):
        """Run selected tests."""
        levels = set(self.args.level.split(",")) if self.args.level else {"rpc", "api", "ws", "infra"}
        specific = self.args.test

        for name, level, destructive, func in _tests:
            full_name = f"{level}.{name}"
            # Filter
            if specific and full_name != specific and name != specific:
                continue
            if level not in levels:
                continue
            if destructive and not self.args.destructive:
                self.results.append(TestResult(name=full_name, level=level, passed=False, skipped=True,
                                               error="skipped: destructive (use --destructive)"))
                continue

            # Check prerequisites
            if level == "rpc" and not self.agent:
                self.results.append(TestResult(name=full_name, level=level, passed=False, skipped=True,
                                               error="skipped: no agent connection"))
                continue
            if level in ("api", "ws", "infra") and not self.http:
                self.results.append(TestResult(name=full_name, level=level, passed=False, skipped=True,
                                               error="skipped: no api connection"))
                continue

            # Execute
            if self.args.verbose:
                print(f"  Running {full_name}...", end=" ", flush=True)
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(func(self), timeout=self.t(60))
                result.latency_ms = (time.monotonic() - t0) * 1000
                result.name = full_name
                result.level = level
            except asyncio.TimeoutError:
                result = TestResult(name=full_name, level=level, passed=False,
                                    latency_ms=(time.monotonic() - t0) * 1000,
                                    error="timeout (60s)")
            except Exception as e:
                result = TestResult(name=full_name, level=level, passed=False,
                                    latency_ms=(time.monotonic() - t0) * 1000,
                                    error=str(e))

            self.results.append(result)
            if self.args.verbose:
                if result.no_data:
                    sym = "?"
                elif result.passed:
                    sym = "✓"
                elif result.skipped:
                    sym = "○"
                else:
                    sym = "✗"
                print(f"{sym} {result.latency_ms:.0f}ms" + (f" — {result.error}" if result.error else ""))

    async def teardown(self):
        if self.agent:
            await self.agent.close()
        if self.http:
            await self.http.aclose()

    def print_report(self):
        passed = sum(1 for r in self.results if r.passed and not r.no_data)
        failed = sum(1 for r in self.results if not r.passed and not r.skipped and not r.no_data)
        skipped = sum(1 for r in self.results if r.skipped)
        no_data = sum(1 for r in self.results if r.no_data)
        total = passed + failed

        print()
        print("═" * 80)
        print("  E2E Test Results — monitoring_agent")
        print("═" * 80)
        print(f"  {'Level':<8} {'Test':<36} {'Status':<8} {'Latency':<10} {'Details'}")
        print(f"  {'─' * 6}  {'─' * 34}  {'─' * 6}  {'─' * 8}  {'─' * 16}")

        for r in self.results:
            if r.skipped:
                sym = "○"
                lat = "—"
            elif r.no_data:
                sym = "?"
                lat = f"{r.latency_ms:.0f}ms"
            elif r.passed:
                sym = "✓"
                lat = f"{r.latency_ms:.0f}ms"
            else:
                sym = "✗"
                lat = f"{r.latency_ms:.0f}ms" if r.latency_ms > 0 else "—"

            detail = ""
            if r.error:
                detail = r.error
            elif r.details:
                parts = [f"{k}={v}" for k, v in list(r.details.items())[:3]]
                detail = ", ".join(parts)

            # Truncate detail
            if len(detail) > 40:
                detail = detail[:37] + "..."

            print(f"  {r.level:<8} {r.name:<36} {sym:<8} {lat:<10} {detail}")

        print(f"  {'─' * 6}  {'─' * 34}  {'─' * 6}  {'─' * 8}  {'─' * 16}")
        summary = f"  Total: {passed} passed, {failed} failed"
        if no_data:
            summary += f", {no_data} no data"
        if skipped:
            summary += f", {skipped} skipped"
        summary += f" (of {total + no_data + skipped})"
        print(summary)
        print("═" * 80)

    def save_json_report(self, path: str):
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_url": self.args.agent_url,
            "api_url": self.args.api_url,
            "levels": self.args.level,
            "timeout_mult": self.args.timeout_mult,
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.passed and not r.no_data),
                "failed": sum(1 for r in self.results if not r.passed and not r.skipped and not r.no_data),
                "no_data": sum(1 for r in self.results if r.no_data),
                "skipped": sum(1 for r in self.results if r.skipped),
            },
            "results": [asdict(r) for r in self.results],
        }
        with open(path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nJSON report saved to {path}")


# ═══════════════════════════════════════════════════════════════════════════
# Level 1: RPC Tests (direct agent WebSocket)
# ═══════════════════════════════════════════════════════════════════════════

@test(level="rpc", name="graph.nodes")
async def test_rpc_graph_nodes(r: E2ERunner) -> TestResult:
    result = await r.agent.call("graph.nodes", timeout=r.t(10))
    assert isinstance(result, list), f"expected list, got {type(result)}"
    assert len(result) > 0, "empty node list"
    assert all(isinstance(n, str) and n.startswith("/") for n in result), "nodes must be /prefixed strings"
    return TestResult(name="", level="", passed=True, details={"count": len(result)})


@test(level="rpc", name="graph.node_info")
async def test_rpc_graph_node_info(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no nodes discovered")
    result = await r.agent.call("graph.node_info", {"node": r.ctx.sample_node}, timeout=r.t(10))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    for key in ("subscribers", "publishers", "services"):
        assert key in result, f"missing key: {key}"
    n_pub = len(result.get("publishers", []))
    n_sub = len(result.get("subscribers", []))
    n_srv = len(result.get("services", []))
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.sample_node, "pubs": n_pub, "subs": n_sub, "srvs": n_srv})


@test(level="rpc", name="graph.topics")
async def test_rpc_graph_topics(r: E2ERunner) -> TestResult:
    result = await r.agent.call("graph.topics", timeout=r.t(10))
    assert isinstance(result, list), f"expected list, got {type(result)}"
    assert len(result) > 0, "empty topic list"
    # Each element should have name and type
    first = result[0]
    if isinstance(first, dict):
        assert "name" in first, "topic dict missing 'name'"
    elif isinstance(first, list):
        assert len(first) >= 2, "topic list item too short"
    return TestResult(name="", level="", passed=True, details={"count": len(result)})


@test(level="rpc", name="graph.topic_info")
async def test_rpc_graph_topic_info(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_topic:
        return TestResult(name="", level="", passed=False, skipped=True, error="no topics discovered")
    result = await r.agent.call("graph.topic_info", {"topic": r.ctx.sample_topic}, timeout=r.t(10))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    assert "type" in result or "publishers" in result, f"missing expected keys, got: {list(result.keys())}"
    return TestResult(name="", level="", passed=True,
                      details={"topic": r.ctx.sample_topic, "type": result.get("type", "?")})


@test(level="rpc", name="graph.services")
async def test_rpc_graph_services(r: E2ERunner) -> TestResult:
    result = await r.agent.call("graph.services", timeout=r.t(10))
    assert isinstance(result, list), f"expected list, got {type(result)}"
    assert len(result) > 0, "empty service list"
    return TestResult(name="", level="", passed=True, details={"count": len(result)})


@test(level="rpc", name="graph.services_typed")
async def test_rpc_graph_services_typed(r: E2ERunner) -> TestResult:
    result = await r.agent.call("graph.services_typed", timeout=r.t(10))
    assert isinstance(result, list), f"expected list, got {type(result)}"
    assert len(result) > 0, "empty typed service list"
    first = result[0]
    if isinstance(first, dict):
        assert "name" in first, "service dict missing 'name'"
        assert "type" in first, "service dict missing 'type'"
    return TestResult(name="", level="", passed=True, details={"count": len(result)})


@test(level="rpc", name="graph.interface_show")
async def test_rpc_graph_interface_show(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_service_type:
        return TestResult(name="", level="", passed=False, skipped=True, error="no service type discovered")
    result = await r.agent.call("graph.interface_show", {"type": r.ctx.sample_service_type}, timeout=r.t(10))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    definition = result.get("definition", "")
    assert isinstance(definition, str) and len(definition) > 0, "empty interface definition"
    return TestResult(name="", level="", passed=True,
                      details={"type": r.ctx.sample_service_type, "len": len(definition)})


@test(level="rpc", name="params.dump")
async def test_rpc_params_dump(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no nodes discovered")
    result = await r.agent.call("params.dump", {"node": r.ctx.sample_node}, timeout=r.t(10))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.sample_node, "params": len(result)})


@test(level="rpc", name="lifecycle.is_lifecycle")
async def test_rpc_lifecycle_is_lifecycle(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no nodes discovered")
    result = await r.agent.call("lifecycle.is_lifecycle", {"node": r.ctx.sample_node}, timeout=r.t(10))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    assert "is_lifecycle" in result, "missing 'is_lifecycle' key"
    assert isinstance(result["is_lifecycle"], bool), "is_lifecycle must be bool"
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.sample_node, "is_lifecycle": result["is_lifecycle"]})


@test(level="rpc", name="lifecycle.get_state")
async def test_rpc_lifecycle_get_state(r: E2ERunner) -> TestResult:
    if not r.ctx.has_lifecycle_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no lifecycle node found")
    result = await r.agent.call("lifecycle.get_state", {"node": r.ctx.has_lifecycle_node}, timeout=r.t(10))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    state = result.get("state")
    assert state is not None, "missing 'state' key"
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.has_lifecycle_node, "state": state})


@test(level="rpc", name="sub.topic.echo")
async def test_rpc_sub_topic_echo(r: E2ERunner) -> TestResult:
    # Use /rosout as it's always active
    topic = "/rosout"
    sub_id = await r.agent.subscribe("topic.echo", {"topic": topic}, timeout=r.t(10))
    try:
        events = await r.agent.read_events(sub_id, count=1, timeout=r.t(10))
        if not events:
            # /rosout might be quiet; try sample_topic
            await r.agent.unsubscribe(sub_id)
            if r.ctx.sample_topic and r.ctx.sample_topic != "/rosout":
                topic = r.ctx.sample_topic
                sub_id = await r.agent.subscribe("topic.echo", {"topic": topic}, timeout=r.t(10))
                events = await r.agent.read_events(sub_id, count=1, timeout=r.t(10))
            else:
                return TestResult(name="", level="", passed=True,
                                  details={"topic": topic, "msgs": 0, "note": "no msgs (quiet topic)"})
        assert len(events) >= 1, f"expected ≥1 messages, got {len(events)}"
        return TestResult(name="", level="", passed=True,
                          details={"topic": topic, "msgs": len(events)})
    finally:
        await r.agent.unsubscribe(sub_id)


@test(level="rpc", name="sub.topic.hz")
async def test_rpc_sub_topic_hz(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_topic:
        return TestResult(name="", level="", passed=False, skipped=True, error="no topics discovered")
    sub_id = await r.agent.subscribe("topic.hz", {"topic": r.ctx.sample_topic}, timeout=r.t(10))
    try:
        events = await r.agent.read_events(sub_id, count=1, timeout=r.t(10))
        if not events:
            return TestResult(name="", level="", passed=True,
                              details={"topic": r.ctx.sample_topic, "note": "no hz data (low-freq topic)"})
        hz = events[0].get("hz", 0) if isinstance(events[0], dict) else 0
        return TestResult(name="", level="", passed=True,
                          details={"topic": r.ctx.sample_topic, "hz": round(hz, 1)})
    finally:
        await r.agent.unsubscribe(sub_id)


@test(level="rpc", name="sub.logs")
async def test_rpc_sub_logs(r: E2ERunner) -> TestResult:
    sub_id = await r.agent.subscribe("logs", timeout=r.t(10))
    try:
        events = await r.agent.read_events(sub_id, count=1, timeout=r.t(10))
        if not events:
            return TestResult(name="", level="", passed=False, no_data=True,
                              details={"note": "no logs received (quiet system)"})
        ev = events[0]
        if isinstance(ev, dict):
            assert "message" in ev or "msg" in ev or "node" in ev, f"unexpected log format: {list(ev.keys())}"
        return TestResult(name="", level="", passed=True, details={"msgs": len(events)})
    finally:
        await r.agent.unsubscribe(sub_id)


@test(level="rpc", name="sub.diagnostics")
async def test_rpc_sub_diagnostics(r: E2ERunner) -> TestResult:
    if not r.ctx.has_diagnostics:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="no /diagnostics topic found")
    sub_id = await r.agent.subscribe("diagnostics", timeout=r.t(10))
    try:
        events = await r.agent.read_events(sub_id, count=1, timeout=r.t(10))
        if not events:
            return TestResult(name="", level="", passed=False, no_data=True,
                              details={"note": "no diagnostics received"})
        return TestResult(name="", level="", passed=True, details={"msgs": len(events)})
    finally:
        await r.agent.unsubscribe(sub_id)


# Destructive RPC tests
@test(level="rpc", name="lifecycle.set_state", destructive=True)
async def test_rpc_lifecycle_set_state(r: E2ERunner) -> TestResult:
    if not r.ctx.has_lifecycle_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no lifecycle node found")
    # Deactivate then re-activate
    result = await r.agent.call("lifecycle.set_state",
                                {"node": r.ctx.has_lifecycle_node, "transition": "deactivate"}, timeout=r.t(10))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    # Re-activate
    await r.agent.call("lifecycle.set_state",
                       {"node": r.ctx.has_lifecycle_node, "transition": "activate"}, timeout=r.t(10))
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.has_lifecycle_node})


@test(level="rpc", name="service.call")
async def test_rpc_service_call(r: E2ERunner) -> TestResult:
    # Find a list_parameters service (safe, read-only)
    target = None
    target_type = "rcl_interfaces/srv/ListParameters"
    for svc in (r.ctx.services_typed or []):
        if isinstance(svc, dict):
            if svc.get("type") == target_type:
                target = svc["name"]
                break
    if not target and r.ctx.sample_node:
        target = f"{r.ctx.sample_node}/list_parameters"
    if not target:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="no list_parameters service found")
    result = await r.agent.call("service.call", {
        "service": target,
        "type": target_type,
        "request": {},
    }, timeout=r.t(15))
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    return TestResult(name="", level="", passed=True,
                      details={"service": target})


# ═══════════════════════════════════════════════════════════════════════════
# Level 2: API Tests (HTTP REST through FastAPI)
# ═══════════════════════════════════════════════════════════════════════════

@test(level="api", name="GET /api/nodes")
async def test_api_nodes(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/nodes", params={"refresh": "true"})
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "nodes" in data, f"missing 'nodes' key, got: {list(data.keys())}"
    assert "total" in data, "missing 'total' key"
    return TestResult(name="", level="", passed=True,
                      details={"total": data.get("total", 0), "active": data.get("active", 0)})


@test(level="api", name="GET /api/nodes/{name}")
async def test_api_node_detail(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no nodes discovered")
    node = r.ctx.sample_node.lstrip("/")
    resp = await r.http.get(f"/api/nodes/{node}", params={"refresh": "true"})
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "node" in data, f"missing 'node' key"
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.sample_node})


@test(level="api", name="GET /api/nodes/{name}/params")
async def test_api_node_params(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no nodes discovered")
    node = r.ctx.sample_node.lstrip("/")
    resp = await r.http.get(f"/api/nodes/{node}/params")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "parameters" in data, f"missing 'parameters' key"
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.sample_node, "params": len(data.get("parameters", {}))})


@test(level="api", name="GET /api/topics/list")
async def test_api_topics_list(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/topics/list")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "topics" in data, "missing 'topics' key"
    assert "count" in data, "missing 'count' key"
    return TestResult(name="", level="", passed=True, details={"count": data["count"]})


@test(level="api", name="GET /api/topics/info/{topic}")
async def test_api_topic_info(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_topic:
        return TestResult(name="", level="", passed=False, skipped=True, error="no topics discovered")
    topic = r.ctx.sample_topic.lstrip("/")
    resp = await r.http.get(f"/api/topics/info/{topic}")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "topic" in data, "missing 'topic' key"
    return TestResult(name="", level="", passed=True,
                      details={"topic": r.ctx.sample_topic, "type": data.get("type", "?")})


@test(level="api", name="GET /api/topics/groups")
async def test_api_topic_groups(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/topics/groups")
    if resp.status_code == 503:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="topic monitoring not active")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "groups" in data, "missing 'groups' key"
    return TestResult(name="", level="", passed=True,
                      details={"groups": len(data["groups"])})


@test(level="api", name="GET /api/services/list")
async def test_api_services_list(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/services/list")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "services" in data, "missing 'services' key"
    assert "count" in data, "missing 'count' key"
    return TestResult(name="", level="", passed=True, details={"count": data["count"]})


@test(level="api", name="GET /api/services/interface/{type}")
async def test_api_service_interface(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_service_type:
        return TestResult(name="", level="", passed=False, skipped=True, error="no service type discovered")
    itype = r.ctx.sample_service_type
    resp = await r.http.get(f"/api/services/interface/{itype}")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "type" in data, "missing 'type' key"
    assert "raw" in data, "missing 'raw' key"
    return TestResult(name="", level="", passed=True,
                      details={"type": itype, "has_raw": bool(data.get("raw"))})


@test(level="api", name="POST /api/services/call")
async def test_api_service_call(r: E2ERunner) -> TestResult:
    # Find list_parameters service
    target = None
    target_type = "rcl_interfaces/srv/ListParameters"
    if r.ctx.services_typed:
        for svc in r.ctx.services_typed:
            if isinstance(svc, dict) and svc.get("type") == target_type:
                target = svc["name"]
                break
    if not target and r.ctx.sample_node:
        target = f"{r.ctx.sample_node}/list_parameters"
    if not target:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="no list_parameters service found")
    svc_name = target.lstrip("/")
    resp = await r.http.post(f"/api/services/call/{svc_name}", json={
        "service_type": target_type,
        "request_yaml": "{}",
    })
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "success" in data, "missing 'success' key"
    return TestResult(name="", level="", passed=True,
                      details={"service": target, "success": data.get("success")})


@test(level="api", name="GET /api/history/logs")
async def test_api_history_logs(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/history/logs", params={"limit": 10})
    if resp.status_code == 503:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="history store not available")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert isinstance(data, (dict, list)), f"unexpected type: {type(data)}"
    return TestResult(name="", level="", passed=True, details={"type": type(data).__name__})


@test(level="api", name="GET /api/history/alerts")
async def test_api_history_alerts(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/history/alerts", params={"limit": 10})
    if resp.status_code == 503:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="history store not available")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert isinstance(data, (dict, list)), f"unexpected type: {type(data)}"
    return TestResult(name="", level="", passed=True, details={"type": type(data).__name__})


@test(level="api", name="GET /api/history/logs/export")
async def test_api_history_export(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/history/logs/export", params={"format": "json"})
    if resp.status_code == 503:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="history store not available")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    return TestResult(name="", level="", passed=True,
                      details={"content_type": resp.headers.get("content-type", "?")})


@test(level="api", name="GET /api/history/stats")
async def test_api_history_stats(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/history/stats")
    if resp.status_code == 503:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="history store not available")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert isinstance(data, dict), f"expected dict, got {type(data)}"
    return TestResult(name="", level="", passed=True, details=data)


# Destructive API tests
@test(level="api", name="POST /api/nodes/{name}/lifecycle", destructive=True)
async def test_api_lifecycle(r: E2ERunner) -> TestResult:
    if not r.ctx.has_lifecycle_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no lifecycle node found")
    node = r.ctx.has_lifecycle_node.lstrip("/")
    resp = await r.http.post(f"/api/nodes/{node}/lifecycle", json={"transition": "deactivate"})
    assert resp.status_code == 200, f"status {resp.status_code}"
    # Re-activate
    await r.http.post(f"/api/nodes/{node}/lifecycle", json={"transition": "activate"})
    return TestResult(name="", level="", passed=True, details={"node": r.ctx.has_lifecycle_node})


# ═══════════════════════════════════════════════════════════════════════════
# Level 3: WebSocket Tests (FastAPI WS endpoints)
# ═══════════════════════════════════════════════════════════════════════════

async def _ws_receive_messages(url: str, count: int, timeout: float) -> list[dict]:
    """Connect to a FastAPI WS endpoint and collect messages."""
    messages = []
    try:
        async with websockets.connect(url, max_size=2 * 1024 * 1024) as ws:
            deadline = time.monotonic() + timeout
            while len(messages) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    messages.append(msg)
                except asyncio.TimeoutError:
                    break
    except Exception as e:
        if not messages:
            raise
    return messages


def _ws_url(api_url: str, path: str) -> str:
    """Convert http://host:port to ws://host:port/path."""
    return api_url.replace("http://", "ws://").replace("https://", "wss://") + path


@test(level="ws", name="WS /ws/nodes/status")
async def test_ws_nodes_status(r: E2ERunner) -> TestResult:
    url = _ws_url(r.args.api_url, "/ws/nodes/status")
    msgs = await _ws_receive_messages(url, count=1, timeout=r.t(15))
    assert len(msgs) >= 1, "no messages received within timeout"
    msg = msgs[0]
    assert isinstance(msg, dict), f"expected dict, got {type(msg)}"
    assert "type" in msg, f"missing 'type' key, got: {list(msg.keys())}"
    return TestResult(name="", level="", passed=True,
                      details={"type": msg.get("type"), "nodes": msg.get("total", "?")})


@test(level="ws", name="WS /ws/logs/all")
async def test_ws_logs_all(r: E2ERunner) -> TestResult:
    url = _ws_url(r.args.api_url, "/ws/logs/all")
    msgs = await _ws_receive_messages(url, count=2, timeout=r.t(15))
    assert len(msgs) >= 1, "no messages received within timeout"
    # First message should be history
    first = msgs[0]
    assert isinstance(first, dict), f"expected dict, got {type(first)}"
    has_history = first.get("type") == "history"
    return TestResult(name="", level="", passed=True,
                      details={"msgs": len(msgs), "has_history": has_history})


@test(level="ws", name="WS /ws/logs/{node}")
async def test_ws_logs_node(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_node:
        return TestResult(name="", level="", passed=False, skipped=True, error="no nodes discovered")
    node = r.ctx.sample_node.lstrip("/")
    url = _ws_url(r.args.api_url, f"/ws/logs/{node}")
    msgs = await _ws_receive_messages(url, count=1, timeout=r.t(10))
    # Even if no messages, connection itself is valid
    return TestResult(name="", level="", passed=True,
                      details={"node": r.ctx.sample_node, "msgs": len(msgs)})


@test(level="ws", name="WS /ws/topics/hz")
async def test_ws_topics_hz(r: E2ERunner) -> TestResult:
    url = _ws_url(r.args.api_url, "/ws/topics/hz")
    msgs = await _ws_receive_messages(url, count=1, timeout=r.t(10))
    if not msgs:
        return TestResult(name="", level="", passed=True,
                          details={"note": "no hz data (no active groups)"})
    msg = msgs[0]
    assert isinstance(msg, dict), f"expected dict, got {type(msg)}"
    return TestResult(name="", level="", passed=True,
                      details={"type": msg.get("type", "?")})


@test(level="ws", name="WS /ws/topics/echo-single/{topic}")
async def test_ws_topics_echo_single(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_topic:
        return TestResult(name="", level="", passed=False, skipped=True, error="no topics discovered")
    topic = r.ctx.sample_topic.lstrip("/")
    url = _ws_url(r.args.api_url, f"/ws/topics/echo-single/{topic}")
    msgs = await _ws_receive_messages(url, count=1, timeout=r.t(10))
    return TestResult(name="", level="", passed=True,
                      details={"topic": r.ctx.sample_topic, "msgs": len(msgs)})


@test(level="ws", name="WS /ws/topics/hz-single/{topic}")
async def test_ws_topics_hz_single(r: E2ERunner) -> TestResult:
    if not r.ctx.sample_topic:
        return TestResult(name="", level="", passed=False, skipped=True, error="no topics discovered")
    topic = r.ctx.sample_topic.lstrip("/")
    url = _ws_url(r.args.api_url, f"/ws/topics/hz-single/{topic}")
    msgs = await _ws_receive_messages(url, count=1, timeout=r.t(10))
    return TestResult(name="", level="", passed=True,
                      details={"topic": r.ctx.sample_topic, "msgs": len(msgs)})


@test(level="ws", name="WS /ws/diagnostics")
async def test_ws_diagnostics(r: E2ERunner) -> TestResult:
    if not r.ctx.has_diagnostics:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="no /diagnostics topic found")
    url = _ws_url(r.args.api_url, "/ws/diagnostics")
    msgs = await _ws_receive_messages(url, count=1, timeout=r.t(15))
    return TestResult(name="", level="", passed=True,
                      details={"msgs": len(msgs)})


@test(level="ws", name="WS /ws/alerts")
async def test_ws_alerts(r: E2ERunner) -> TestResult:
    url = _ws_url(r.args.api_url, "/ws/alerts")
    # Alerts may be rare, just verify connection works
    try:
        async with websockets.connect(url, max_size=2 * 1024 * 1024) as ws:
            # Try to receive for a short time — alerts may not fire
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=r.t(3))
                msg = json.loads(raw)
                return TestResult(name="", level="", passed=True,
                                  details={"type": msg.get("type", "?")})
            except asyncio.TimeoutError:
                return TestResult(name="", level="", passed=False, no_data=True,
                                  details={"note": "connected OK, no alerts received"})
    except Exception as e:
        return TestResult(name="", level="", passed=False, error=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Level 4: Infrastructure Tests
# ═══════════════════════════════════════════════════════════════════════════

@test(level="infra", name="GET /health")
async def test_infra_health(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/health")
    assert resp.status_code == 200, f"status {resp.status_code}"
    data = resp.json()
    assert "status" in data, "missing 'status' key"
    assert data["status"] == "ok", f"status is '{data['status']}', expected 'ok'"
    return TestResult(name="", level="", passed=True,
                      details={"connected": data.get("connected"), "server": data.get("server")})


@test(level="infra", name="GET /api/debug/stats")
async def test_infra_debug_stats(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/debug/stats")
    assert resp.status_code == 200, f"status {resp.status_code}"
    data = resp.json()
    assert isinstance(data, dict), f"expected dict, got {type(data)}"
    return TestResult(name="", level="", passed=True,
                      details={k: v for k, v in list(data.items())[:3]})


@test(level="infra", name="GET /api/dashboard")
async def test_infra_dashboard(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/dashboard")
    if resp.status_code == 503:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="not connected")
    assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert isinstance(data, dict), f"expected dict"
    return TestResult(name="", level="", passed=True,
                      details={"keys": list(data.keys())[:5]})


@test(level="infra", name="GET /api/servers")
async def test_infra_servers_list(r: E2ERunner) -> TestResult:
    resp = await r.http.get("/api/servers")
    assert resp.status_code == 200, f"status {resp.status_code}"
    data = resp.json()
    assert isinstance(data, list), f"expected list, got {type(data)}"
    return TestResult(name="", level="", passed=True,
                      details={"servers": len(data)})


@test(level="infra", name="connect-disconnect")
async def test_infra_connect_disconnect(r: E2ERunner) -> TestResult:
    """Test disconnect + reconnect cycle."""
    # Get current server
    resp = await r.http.get("/api/servers/current")
    if resp.status_code != 200:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="cannot get current server")
    current = resp.json()
    if not current.get("connected"):
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="not currently connected")
    server_id = current.get("server", {}).get("id")
    if not server_id:
        return TestResult(name="", level="", passed=False, skipped=True,
                          error="no server id in current")

    # Disconnect
    resp = await r.http.post("/api/servers/disconnect")
    assert resp.status_code == 200, f"disconnect failed: {resp.status_code}"

    # Reconnect
    resp = await r.http.post("/api/servers/connect", json={"server_id": server_id})
    assert resp.status_code == 200, f"reconnect failed: {resp.status_code}"

    # Verify connected
    await asyncio.sleep(1)
    resp = await r.http.get("/health")
    data = resp.json()
    assert data.get("connected"), "not connected after reconnect"

    # Re-discover since connection was reset
    await r._discover()

    return TestResult(name="", level="", passed=True,
                      details={"server_id": server_id})


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="E2E test suite for monitoring_agent")
    p.add_argument("--agent-url", default="ws://localhost:9090",
                   help="WebSocket URL of monitoring_agent (default: ws://localhost:9090)")
    p.add_argument("--api-url", default="http://localhost:8080",
                   help="HTTP URL of FastAPI backend (default: http://localhost:8080)")
    p.add_argument("--level", default="rpc,api,ws,infra",
                   help="Comma-separated levels to run: rpc,api,ws,infra (default: all)")
    p.add_argument("--test", default=None,
                   help="Run specific test by name (e.g. rpc.graph.nodes)")
    p.add_argument("--timeout-mult", type=float, default=1.0,
                   help="Timeout multiplier (default: 1.0)")
    p.add_argument("--json-report", default=None,
                   help="Save JSON report to file")
    p.add_argument("--destructive", action="store_true",
                   help="Include destructive tests (lifecycle transitions, kill)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Verbose output during test execution")
    p.add_argument("--no-agent", action="store_true",
                   help="Skip agent connection (only test API/WS/infra)")
    p.add_argument("--no-api", action="store_true",
                   help="Skip API connection (only test RPC)")
    return p.parse_args()


async def main():
    args = parse_args()

    if args.no_agent:
        args.agent_url = None
    if args.no_api:
        args.api_url = None

    print("═" * 60)
    print("  E2E Test Suite — monitoring_agent")
    print("═" * 60)
    print(f"  Agent: {args.agent_url or '(disabled)'}")
    print(f"  API:   {args.api_url or '(disabled)'}")
    print(f"  Levels: {args.level}")
    print(f"  Timeout mult: {args.timeout_mult}x")
    if args.test:
        print(f"  Filter: {args.test}")
    if args.destructive:
        print(f"  Destructive: YES")
    print()

    runner = E2ERunner(args)

    print("Setup:")
    await runner.setup()
    print()

    print("Running tests:")
    t0 = time.monotonic()
    await runner.run()
    duration = time.monotonic() - t0

    await runner.teardown()

    runner.print_report()
    print(f"\n  Duration: {duration:.1f}s")

    if args.json_report:
        runner.save_json_report(args.json_report)

    # Exit code: fail if any tests failed or had no data (inconclusive)
    failed = sum(1 for r in runner.results if not r.passed and not r.skipped and not r.no_data)
    no_data = sum(1 for r in runner.results if r.no_data)
    sys.exit(1 if (failed > 0 or no_data > 0) else 0)


if __name__ == "__main__":
    asyncio.run(main())
