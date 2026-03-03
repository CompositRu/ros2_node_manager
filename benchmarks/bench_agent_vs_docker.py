#!/usr/bin/env python3
"""Benchmark: monitoring_agent (WebSocket) vs docker exec.

Measures latency, throughput, CPU, and memory for all core operations.
Requires:
  - Docker container 'tram_autoware' running with ROS2 nodes
  - monitoring_agent node running inside the container (for agent mode)

Usage:
    # Both modes (requires agent running)
    python benchmarks/bench_agent_vs_docker.py

    # Docker exec only
    python benchmarks/bench_agent_vs_docker.py --mode docker

    # Agent only
    python benchmarks/bench_agent_vs_docker.py --mode agent

    # Custom iterations
    python benchmarks/bench_agent_vs_docker.py --iterations 50

    # With load generator running inside Docker:
    #   docker exec tram_autoware ros2 run monitoring_agent load_generator \
    #       --ros-args -p node_count:=200 -p topics_per_node:=3 -p publish_hz:=30
"""

import argparse
import asyncio
import json
import os
import resource
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class BenchmarkResult:
    """Result of a single benchmark operation."""
    operation: str
    mode: str  # 'docker' or 'agent'
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0

    @property
    def count(self) -> int:
        return len(self.latencies_ms)

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0

    @property
    def p95_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_l = sorted(self.latencies_ms)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]

    @property
    def min_ms(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0

    @property
    def max_ms(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0


@dataclass
class SystemMetrics:
    """System resource usage snapshot."""
    timestamp: float
    cpu_percent: float = 0.0
    rss_mb: float = 0.0
    docker_exec_count: int = 0
    process_count: int = 0


# ===================== Docker exec benchmarks =====================

CONTAINER = 'tram_autoware'
ENV_CACHE = '/tmp/.ros2nm_env_cache'


def _docker_cmd(cmd: str) -> str:
    """Build docker exec command with cached ROS env."""
    escaped = cmd.replace("'", "'\"'\"'")
    return (
        f"docker exec {CONTAINER} bash -c "
        f"'source {ENV_CACHE} 2>/dev/null && {escaped}'"
    )


async def _bench_docker_exec(cmd: str, iterations: int) -> BenchmarkResult:
    """Benchmark a single docker exec command."""
    result = BenchmarkResult(operation=cmd[:60], mode='docker')
    full_cmd = _docker_cmd(cmd)

    for _ in range(iterations):
        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            elapsed = (time.perf_counter() - start) * 1000
            if proc.returncode == 0:
                result.latencies_ms.append(elapsed)
            else:
                result.errors += 1
        except Exception:
            result.errors += 1

    return result


# ===================== Agent (WebSocket) benchmarks =====================

async def _bench_agent_rpc(ws, method: str, params: dict,
                           iterations: int) -> BenchmarkResult:
    """Benchmark a single agent JSON-RPC call."""
    import websockets

    result = BenchmarkResult(operation=f'{method}', mode='agent')

    for i in range(iterations):
        msg = json.dumps({
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': i + 1,
        })
        start = time.perf_counter()
        try:
            await ws.send(msg)
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            elapsed = (time.perf_counter() - start) * 1000
            resp = json.loads(raw)
            if 'error' in resp:
                result.errors += 1
            else:
                result.latencies_ms.append(elapsed)
        except Exception:
            result.errors += 1

    return result


async def _bench_agent_subscription(ws, channel: str, params: dict,
                                    duration: float = 5.0) -> dict:
    """Benchmark subscription throughput."""
    import websockets

    # Subscribe
    sub_msg = json.dumps({
        'jsonrpc': '2.0',
        'method': 'subscribe',
        'params': {'channel': channel, 'params': params},
        'id': 9999,
    })
    await ws.send(sub_msg)
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    resp = json.loads(raw)
    sub_id = resp.get('result', {}).get('subscription', '')

    # Collect messages for duration
    msg_count = 0
    start = time.perf_counter()
    try:
        while time.perf_counter() - start < duration:
            raw = await asyncio.wait_for(ws.recv(), timeout=duration + 1)
            msg = json.loads(raw)
            if msg.get('method') == 'event':
                msg_count += 1
    except asyncio.TimeoutError:
        pass

    elapsed = time.perf_counter() - start

    # Unsubscribe
    unsub = json.dumps({
        'jsonrpc': '2.0',
        'method': 'unsubscribe',
        'params': {'subscription': sub_id},
        'id': 9998,
    })
    await ws.send(unsub)
    try:
        await asyncio.wait_for(ws.recv(), timeout=2)
    except Exception:
        pass

    return {
        'channel': channel,
        'messages': msg_count,
        'duration_s': round(elapsed, 2),
        'throughput_msg_s': round(msg_count / elapsed, 2) if elapsed > 0 else 0,
    }


# ===================== System metrics =====================

def get_system_metrics() -> SystemMetrics:
    """Collect current system resource usage."""
    metrics = SystemMetrics(timestamp=time.time())

    # Count docker exec processes
    try:
        result = subprocess.run(
            ['pgrep', '-c', '-f', f'docker exec {CONTAINER}'],
            capture_output=True, text=True, timeout=5,
        )
        metrics.docker_exec_count = int(result.stdout.strip() or '0')
    except Exception:
        pass

    # Count total processes
    try:
        result = subprocess.run(
            ['sh', '-c', 'ps aux | wc -l'],
            capture_output=True, text=True, timeout=5,
        )
        metrics.process_count = int(result.stdout.strip() or '0')
    except Exception:
        pass

    # RSS of current process
    ru = resource.getrusage(resource.RUSAGE_SELF)
    metrics.rss_mb = ru.ru_maxrss / 1024  # Linux: KB -> MB

    return metrics


# ===================== Main benchmark runner =====================

async def run_docker_benchmarks(iterations: int) -> list[BenchmarkResult]:
    """Run all docker exec benchmarks."""
    print('\n=== Docker Exec Benchmarks ===\n')

    commands = [
        ('ros2 node list', 'node_list'),
        ('ros2 topic list -t', 'topic_list'),
        ('ros2 service list', 'service_list'),
    ]

    results = []
    for cmd, label in commands:
        print(f'  {label}: ', end='', flush=True)
        r = await _bench_docker_exec(cmd, iterations)
        r.operation = label
        results.append(r)
        print(f'{r.avg_ms:.1f}ms avg, {r.median_ms:.1f}ms median, '
              f'{r.p95_ms:.1f}ms p95, {r.errors} errors')

    # node info — pick first node from list
    node_list_r = await _bench_docker_exec('ros2 node list', 1)
    if node_list_r.latencies_ms:
        full_cmd = _docker_cmd('ros2 node list')
        proc = await asyncio.create_subprocess_shell(
            full_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        nodes = [l.strip() for l in stdout.decode().split('\n') if l.strip().startswith('/')]
        if nodes:
            test_node = nodes[0]
            print(f'  node_info ({test_node}): ', end='', flush=True)
            r = await _bench_docker_exec(f'ros2 node info {test_node}', iterations)
            r.operation = 'node_info'
            results.append(r)
            print(f'{r.avg_ms:.1f}ms avg, {r.median_ms:.1f}ms median, '
                  f'{r.p95_ms:.1f}ms p95')

    return results


async def run_agent_benchmarks(agent_url: str,
                               iterations: int) -> list[BenchmarkResult]:
    """Run all agent WebSocket benchmarks."""
    import websockets

    print('\n=== Agent (WebSocket) Benchmarks ===\n')

    try:
        ws = await websockets.connect(agent_url, max_size=2 * 1024 * 1024)
    except Exception as e:
        print(f'  ERROR: Cannot connect to agent at {agent_url}: {e}')
        return []

    results = []

    rpc_tests = [
        ('graph.nodes', {}, 'node_list'),
        ('graph.topics', {}, 'topic_list'),
        ('graph.services', {}, 'service_list'),
    ]

    for method, params, label in rpc_tests:
        print(f'  {label}: ', end='', flush=True)
        r = await _bench_agent_rpc(ws, method, params, iterations)
        r.operation = label
        results.append(r)
        print(f'{r.avg_ms:.1f}ms avg, {r.median_ms:.1f}ms median, '
              f'{r.p95_ms:.1f}ms p95, {r.errors} errors')

    # node_info — pick first node
    nodes_r = await _bench_agent_rpc(ws, 'graph.nodes', {}, 1)
    if nodes_r.latencies_ms:
        msg = json.dumps({'jsonrpc': '2.0', 'method': 'graph.nodes', 'params': {}, 'id': 0})
        await ws.send(msg)
        raw = await ws.recv()
        nodes = json.loads(raw).get('result', [])
        if nodes:
            test_node = nodes[0]
            print(f'  node_info ({test_node}): ', end='', flush=True)
            r = await _bench_agent_rpc(ws, 'graph.node_info', {'node': test_node}, iterations)
            r.operation = 'node_info'
            results.append(r)
            print(f'{r.avg_ms:.1f}ms avg, {r.median_ms:.1f}ms median, '
                  f'{r.p95_ms:.1f}ms p95')

    # Subscription throughput test
    print(f'\n  Subscription throughput (5s):')
    # Find a topic with publishers
    msg = json.dumps({'jsonrpc': '2.0', 'method': 'graph.topics', 'params': {}, 'id': 0})
    await ws.send(msg)
    raw = await ws.recv()
    topics = json.loads(raw).get('result', [])
    rosout = [t for t in topics if t.get('name') == '/rosout']
    if rosout:
        print(f'    /rosout echo: ', end='', flush=True)
        st = await _bench_agent_subscription(ws, 'topic.echo', {'topic': '/rosout'}, 5.0)
        print(f'{st["throughput_msg_s"]} msg/s ({st["messages"]} msgs in {st["duration_s"]}s)')

    await ws.close()
    return results


def print_comparison(docker_results: list[BenchmarkResult],
                     agent_results: list[BenchmarkResult]):
    """Print side-by-side comparison table."""
    print('\n' + '=' * 78)
    print('COMPARISON: Docker Exec vs Agent (WebSocket)')
    print('=' * 78)
    print(f'{"Operation":<15} {"Docker avg":>12} {"Agent avg":>12} '
          f'{"Speedup":>10} {"Docker p95":>12} {"Agent p95":>12}')
    print('-' * 78)

    docker_map = {r.operation: r for r in docker_results}
    agent_map = {r.operation: r for r in agent_results}

    for op in ['node_list', 'topic_list', 'service_list', 'node_info']:
        d = docker_map.get(op)
        a = agent_map.get(op)
        if not d or not a:
            continue
        speedup = d.avg_ms / a.avg_ms if a.avg_ms > 0 else float('inf')
        print(f'{op:<15} {d.avg_ms:>10.1f}ms {a.avg_ms:>10.1f}ms '
              f'{speedup:>9.1f}x {d.p95_ms:>10.1f}ms {a.p95_ms:>10.1f}ms')

    print('-' * 78)


def save_results(docker_results: list, agent_results: list, filepath: str):
    """Save raw benchmark results to JSON."""
    data = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'system': get_system_metrics().__dict__,
        'docker_results': [
            {
                'operation': r.operation,
                'mode': r.mode,
                'count': r.count,
                'avg_ms': round(r.avg_ms, 2),
                'median_ms': round(r.median_ms, 2),
                'p95_ms': round(r.p95_ms, 2),
                'min_ms': round(r.min_ms, 2),
                'max_ms': round(r.max_ms, 2),
                'errors': r.errors,
            }
            for r in docker_results
        ],
        'agent_results': [
            {
                'operation': r.operation,
                'mode': r.mode,
                'count': r.count,
                'avg_ms': round(r.avg_ms, 2),
                'median_ms': round(r.median_ms, 2),
                'p95_ms': round(r.p95_ms, 2),
                'min_ms': round(r.min_ms, 2),
                'max_ms': round(r.max_ms, 2),
                'errors': r.errors,
            }
            for r in agent_results
        ],
    }
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    print(f'\nResults saved to {filepath}')


async def main():
    parser = argparse.ArgumentParser(description='Benchmark: agent vs docker exec')
    parser.add_argument('--mode', choices=['both', 'docker', 'agent'], default='both')
    parser.add_argument('--iterations', type=int, default=20,
                        help='Number of iterations per operation')
    parser.add_argument('--agent-url', default='ws://localhost:9090',
                        help='Agent WebSocket URL')
    parser.add_argument('--container', default='tram_autoware',
                        help='Docker container name')
    parser.add_argument('--output', default='benchmarks/results.json',
                        help='Output file for raw results')
    args = parser.parse_args()

    global CONTAINER
    CONTAINER = args.container

    print(f'Benchmark: monitoring_agent vs docker exec')
    print(f'Iterations: {args.iterations}, Mode: {args.mode}')
    print(f'Container: {CONTAINER}, Agent: {args.agent_url}')

    # Collect initial system metrics
    metrics_before = get_system_metrics()
    print(f'\nSystem: {metrics_before.process_count} processes, '
          f'{metrics_before.docker_exec_count} docker exec running')

    docker_results = []
    agent_results = []

    if args.mode in ('both', 'docker'):
        docker_results = await run_docker_benchmarks(args.iterations)

    if args.mode in ('both', 'agent'):
        agent_results = await run_agent_benchmarks(args.agent_url, args.iterations)

    if docker_results and agent_results:
        print_comparison(docker_results, agent_results)

    # Final metrics
    metrics_after = get_system_metrics()
    print(f'\nSystem after: {metrics_after.process_count} processes, '
          f'{metrics_after.docker_exec_count} docker exec running, '
          f'{metrics_after.rss_mb:.1f} MB RSS')

    # Save results
    save_results(docker_results, agent_results, args.output)


if __name__ == '__main__':
    asyncio.run(main())
