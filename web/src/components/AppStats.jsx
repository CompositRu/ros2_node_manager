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

function SectionLabel({ children }) {
  return (
    <span className="text-gray-500 text-xs uppercase tracking-wide col-span-4 mt-2 first:mt-0">
      {children}
    </span>
  );
}

export function AppStats() {
  const { stats } = useSystemStats(true);
  const agent = stats?.agent;
  const connType = stats?.connection?.type;
  const cores = agent?.container_cpu_cores;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-4 flex-shrink-0">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
          App Stats
        </h2>

        <div className="grid grid-cols-4 gap-3">
          <SectionLabel>Backend</SectionLabel>
          <StatCard label="CPU" value={stats?.process?.cpu_percent?.toFixed(1)} unit="%" />
          <StatCard label="RSS" value={stats?.process?.rss_mb?.toFixed(0)} unit="MB" />
          <StatCard label="WebSockets" value={stats?.websockets?.total} />
          <StatCard label="Uptime" value={formatUptime(stats?.uptime_seconds)} />

          {connType === 'AgentConnection' && (
            <>
              <SectionLabel>Agent (Docker)</SectionLabel>
              <StatCard label="CPU" value={agent?.cpu_percent?.toFixed(1)} unit="%" />
              <StatCard label="RSS" value={agent?.rss_mb?.toFixed(0)} unit="MB" />
              <StatCard label="Threads" value={agent?.threads} />
              <StatCard label="PID" value={agent?.pid} />

              <SectionLabel>
                Docker {cores ? `(${cores} cores)` : ''}
              </SectionLabel>
              <StatCard label="CPU" value={agent?.container_cpu_percent?.toFixed(1)} unit="%" />
              <StatCard label="RSS" value={agent?.container_rss_mb?.toFixed(0)} unit="MB" />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
