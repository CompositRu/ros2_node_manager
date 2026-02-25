import { useState } from 'react';
import { useSystemStats } from '../hooks/useSystemStats';

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

const HELP_ITEMS = [
  { label: 'CPU', desc: 'CPU usage of the server process. Normal: < 5%' },
  { label: 'RSS', desc: 'Physical memory used by the server. Normal: 50\u2013150 MB. Constant growth = memory leak' },
  { label: 'Exec', desc: 'Active one-shot docker exec commands (ros2 node list, etc). Normal: 0\u20133' },
  { label: 'Streams', desc: 'Active streaming subprocesses (ros2 topic echo). 1 per open log stream' },
  { label: 'WebSockets', desc: 'Active browser connections. 1\u20133 per open tab (status + alerts + logs)' },
  { label: 'Uptime', desc: 'Server uptime since last restart' },
  { label: 'Commands', desc: 'Total commands executed since server start' },
  { label: 'Threads', desc: 'OS threads in the server process. Normal: 5\u201315' },
];

export function AppStats() {
  const { stats } = useSystemStats(true);
  const [showHelp, setShowHelp] = useState(false);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-4 flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
            App Stats
          </h2>
          <button
            onClick={() => setShowHelp(!showHelp)}
            className={`w-5 h-5 rounded-full text-xs flex items-center justify-center transition-colors ${
              showHelp
                ? 'bg-blue-500 text-white'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-gray-300'
            }`}
            title="Metrics help"
          >
            ?
          </button>
        </div>

        {showHelp && (
          <div className="mb-3 bg-gray-800 border border-gray-600 rounded p-3 text-xs select-text">
            <table className="w-full">
              <tbody>
                {HELP_ITEMS.map((item) => (
                  <tr key={item.label} className="border-b border-gray-700 last:border-0">
                    <td className="py-1.5 pr-3 text-blue-400 font-medium whitespace-nowrap align-top">{item.label}</td>
                    <td className="py-1.5 text-gray-300">{item.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

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
    </div>
  );
}
