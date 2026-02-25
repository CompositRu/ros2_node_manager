import { useState, useEffect, useRef, useMemo } from 'react';
import { useSystemStats } from '../hooks/useSystemStats';
import { useUnifiedLogs } from '../hooks/useUnifiedLogs';

function formatUptime(seconds) {
  if (!seconds) return '--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function StatCard({ label, value, unit }) {
  return (
    <div className="bg-gray-800 rounded px-3 py-2 flex flex-col min-w-0">
      <span className="text-gray-400 text-xs uppercase tracking-wide">{label}</span>
      <span className="text-white text-lg font-semibold truncate">
        {value ?? '--'}{unit && <span className="text-gray-400 text-sm ml-1">{unit}</span>}
      </span>
    </div>
  );
}

const LOG_LEVELS = ['All', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'];

export function SystemMonitor({ connected }) {
  const { stats } = useSystemStats(true);
  const { logs, status: logsStatus, clearLogs } = useUnifiedLogs(connected);

  const [levelFilter, setLevelFilter] = useState('All');
  const [nodeFilter, setNodeFilter] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const logsEndRef = useRef(null);
  const pausedLogsRef = useRef([]);
  const [displayLogs, setDisplayLogs] = useState([]);

  // Handle pause/resume
  useEffect(() => {
    if (paused) {
      pausedLogsRef.current = [...logs];
    } else {
      setDisplayLogs([]);
      pausedLogsRef.current = [];
    }
  }, [paused]);

  const currentLogs = paused ? pausedLogsRef.current : logs;

  const filteredLogs = useMemo(() => {
    return currentLogs.filter((log) => {
      if (levelFilter !== 'All' && log.level !== levelFilter) return false;
      if (nodeFilter && !log.node_name?.toLowerCase().includes(nodeFilter.toLowerCase())) return false;
      return true;
    });
  }, [currentLogs, levelFilter, nodeFilter]);

  useEffect(() => {
    if (autoScroll && !paused && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [filteredLogs, autoScroll, paused]);

  const getLevelClass = (level) => {
    switch (level?.toUpperCase()) {
      case 'DEBUG': return 'log-debug';
      case 'INFO': return 'log-info';
      case 'WARN': return 'log-warn';
      case 'ERROR': return 'log-error';
      case 'FATAL': return 'log-fatal';
      default: return 'text-gray-300';
    }
  };

  const formatTimestamp = (ts) => {
    try {
      return new Date(ts).toLocaleTimeString('en-US', { hour12: false });
    } catch {
      return ts;
    }
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Stats Grid */}
      <div className="p-4 border-b border-gray-700 flex-shrink-0">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
          System Monitor
        </h2>
        <div className="grid grid-cols-4 gap-3">
          <StatCard label="CPU" value={stats?.process?.cpu_percent?.toFixed(1)} unit="%" />
          <StatCard label="RSS" value={stats?.process?.rss_mb?.toFixed(0)} unit="MB" />
          <StatCard label="Exec" value={stats?.subprocesses?.active_exec} />
          <StatCard label="Streams" value={stats?.subprocesses?.active_streams} />
          <StatCard label="WebSockets" value={stats?.websockets?.total} />
          <StatCard label="Uptime" value={formatUptime(stats?.uptime_seconds)} />
          <StatCard label="Commands" value={stats?.subprocesses?.total_commands} />
          <StatCard label="Threads" value={stats?.process?.threads} />
        </div>
      </div>

      {/* Unified Log Stream */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Log toolbar */}
        <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700 bg-gray-800 flex-shrink-0">
          <span className="text-gray-300 font-medium text-sm flex-shrink-0">All Logs</span>

          {logsStatus === 'connecting' && <span className="text-yellow-400 text-xs flex-shrink-0">● Connecting...</span>}
          {logsStatus === 'connected' && <span className="text-green-400 text-xs flex-shrink-0">● Connected</span>}
          {logsStatus === 'error' && <span className="text-red-400 text-xs flex-shrink-0">● Error</span>}
          {logsStatus === 'disconnected' && !connected && <span className="text-gray-500 text-xs flex-shrink-0">● Not connected</span>}

          <div className="flex-1" />

          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value)}
            className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
          >
            {LOG_LEVELS.map((level) => (
              <option key={level} value={level}>{level}</option>
            ))}
          </select>

          <input
            type="text"
            placeholder="Filter by node..."
            value={nodeFilter}
            onChange={(e) => setNodeFilter(e.target.value)}
            className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 w-40 focus:outline-none focus:border-blue-500"
          />

          <button
            onClick={() => setPaused(!paused)}
            className={`px-2 py-1 text-xs rounded ${
              paused ? 'bg-yellow-600 text-white' : 'bg-gray-600 text-gray-300 hover:bg-gray-500'
            }`}
          >
            {paused ? 'Resume' : 'Pause'}
          </button>

          <button
            onClick={clearLogs}
            className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded"
          >
            Clear
          </button>

          <label className="flex items-center gap-1 text-xs text-gray-400 flex-shrink-0">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded"
            />
            Auto-scroll
          </label>
        </div>

        {/* Log content */}
        <div className="flex-1 overflow-auto p-2 font-mono text-xs">
          {filteredLogs.length === 0 && (
            <div className="text-gray-500 text-center py-8">
              {logsStatus === 'connecting' ? 'Connecting to log stream...' :
               logsStatus === 'connected' ? 'Waiting for logs...' :
               !connected ? 'Connect to a server to view logs' :
               'No logs yet'}
            </div>
          )}

          {filteredLogs.map((log, idx) => (
            <div key={idx} className="flex gap-2 hover:bg-gray-800/50 px-1 leading-5">
              <span className="text-gray-500 flex-shrink-0">
                {formatTimestamp(log.timestamp)}
              </span>
              <span className={`flex-shrink-0 w-12 text-right ${getLevelClass(log.level)}`}>
                {log.level}
              </span>
              <span className="text-purple-300 flex-shrink-0 truncate max-w-[200px]" title={log.node_name}>
                [{log.node_name}]
              </span>
              <span className="text-gray-300 break-all">
                {log.message}
              </span>
            </div>
          ))}

          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
}
