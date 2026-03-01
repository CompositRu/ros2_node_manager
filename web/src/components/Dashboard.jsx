import { useDashboard } from '../hooks/useDashboard';

// ─── Status logic ───────────────────────────────────────────────

function getAutopilotStatus(connected, data) {
  if (!connected || !data || !data.docker?.running) {
    return { level: 'offline', label: 'OFFLINE', color: 'gray' };
  }
  const { active, inactive, total } = data.nodes;
  if (total > 0 && active === 0) {
    return { level: 'critical', label: 'CRITICAL', color: 'red' };
  }
  if (inactive > 0) {
    return { level: 'warning', label: 'WARNINGS', color: 'yellow' };
  }
  return { level: 'running', label: 'AUTOPILOT RUNNING', color: 'green' };
}

const STATUS_STYLES = {
  green:  { bg: 'bg-green-900/40',  border: 'border-green-500/50', text: 'text-green-400',  dot: 'bg-green-400'  },
  yellow: { bg: 'bg-yellow-900/40', border: 'border-yellow-500/50', text: 'text-yellow-400', dot: 'bg-yellow-400' },
  red:    { bg: 'bg-red-900/40',    border: 'border-red-500/50',    text: 'text-red-400',    dot: 'bg-red-400'    },
  gray:   { bg: 'bg-gray-800/60',   border: 'border-gray-600/50',   text: 'text-gray-400',   dot: 'bg-gray-500'   },
};

// ─── Helpers ────────────────────────────────────────────────────

function formatUptime(seconds) {
  if (seconds == null) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}

// ─── Sub-components ─────────────────────────────────────────────

function StatusBanner({ status, data }) {
  const s = STATUS_STYLES[status.color];
  const { active, total } = data?.nodes || { active: 0, total: 0 };

  return (
    <div className={`${s.bg} ${s.border} border rounded-lg p-6 flex items-center justify-between`}>
      <div className="flex items-center gap-4">
        <div className={`w-4 h-4 rounded-full ${s.dot} animate-pulse`} />
        <span className={`text-2xl font-bold ${s.text}`}>{status.label}</span>
      </div>
      {data?.docker?.running && (
        <span className="text-gray-300 text-lg">{active} / {total} nodes active</span>
      )}
    </div>
  );
}

function ProgressBar({ label, value, max, unit, color = 'blue' }) {
  const percent = max ? Math.min(100, (value / max) * 100) : 0;
  const display = value != null ? `${value}${unit || ''}` : '—';

  const barColor = percent > 90 ? 'bg-red-500' : percent > 70 ? 'bg-yellow-500' : `bg-${color}-500`;

  return (
    <div className="flex items-center gap-3">
      <span className="text-gray-400 text-sm w-10 flex-shrink-0">{label}</span>
      <div className="flex-1 bg-gray-700 rounded-full h-3 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="text-gray-300 text-sm w-16 text-right flex-shrink-0">{display}</span>
    </div>
  );
}

function ResourcesCard({ resources }) {
  if (!resources) return null;

  const cpuVal = resources.cpu_percent;
  const memVal = resources.memory_used_gb;
  const memMax = resources.memory_limit_gb;
  const gpuVal = resources.gpu_percent;

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-5">
      <h3 className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-4">Resources</h3>
      <div className="space-y-3">
        <ProgressBar label="CPU" value={cpuVal} max={100} unit="%" />
        <ProgressBar label="GPU" value={gpuVal} max={100} unit="%" />
        <ProgressBar
          label="RAM"
          value={memVal}
          max={memMax}
          unit={memVal != null ? 'G' : ''}
        />
      </div>
      {resources.gpu_name && (
        <div className="mt-3 text-gray-500 text-xs">{resources.gpu_name}</div>
      )}
    </div>
  );
}

function QuickStatsCard({ data }) {
  const stats = [
    { label: 'Nodes', value: data?.nodes?.active != null ? `${data.nodes.active} active` : '—' },
    { label: 'Topics', value: data?.topics_count ?? '—' },
    { label: 'Services', value: data?.services_count ?? '—' },
    { label: 'Uptime', value: formatUptime(data?.docker?.uptime_seconds) },
  ];

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-5">
      <h3 className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-4">Quick Stats</h3>
      <div className="space-y-3">
        {stats.map((s) => (
          <div key={s.label} className="flex justify-between items-center">
            <span className="text-gray-400 text-sm">{s.label}</span>
            <span className="text-gray-200 text-sm font-medium">{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const SEVERITY_STYLES = {
  critical: { dot: 'bg-red-400', text: 'text-red-400' },
  error: { dot: 'bg-red-400', text: 'text-red-400' },
  warning: { dot: 'bg-yellow-400', text: 'text-yellow-400' },
  info: { dot: 'bg-green-400', text: 'text-green-400' },
};

function RecentAlertsCard({ alerts, onViewAll }) {
  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-5">
      <h3 className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-4">Recent Alerts</h3>
      {alerts.length === 0 ? (
        <div className="text-gray-500 text-sm py-2">No recent alerts</div>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert) => {
            const sev = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.info;
            return (
              <div key={alert.id} className="flex items-start gap-2 text-sm">
                <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${sev.dot}`} />
                <span className="text-gray-500 flex-shrink-0">{formatTimestamp(alert.timestamp)}</span>
                <span className="text-gray-300 truncate">{alert.title}: {alert.message}</span>
              </div>
            );
          })}
        </div>
      )}
      <button
        onClick={onViewAll}
        className="mt-3 text-blue-400 text-xs hover:text-blue-300 transition-colors"
      >
        View all alerts &rarr;
      </button>
    </div>
  );
}

function QuickAccessCard({ onNavigate }) {
  const links = [
    { id: 'diagnostics', label: 'Diagnostics', icon: '♡' },
    { id: 'logs', label: 'Logs', icon: '☰' },
    { id: 'nodes', label: 'Nodes', icon: '⊞' },
    { id: 'topics', label: 'Topics', icon: '⇄' },
  ];

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-5">
      <h3 className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-4">Quick Access</h3>
      <div className="flex flex-wrap gap-2">
        {links.map((link) => (
          <button
            key={link.id}
            onClick={() => onNavigate(link.id)}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white rounded-lg text-sm transition-colors"
          >
            {link.icon} {link.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────

export function Dashboard({ connected, onSectionChange }) {
  const { data, alerts, loading } = useDashboard(connected);
  const status = getAutopilotStatus(connected, data);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* System Status Banner */}
          <StatusBanner status={status} data={data} />

          {/* Resources + Quick Stats */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ResourcesCard resources={data?.resources} />
            <QuickStatsCard data={data} />
          </div>

          {/* Recent Alerts */}
          <RecentAlertsCard
            alerts={alerts}
            onViewAll={() => onSectionChange('history')}
          />

          {/* Quick Access */}
          <QuickAccessCard onNavigate={onSectionChange} />

          {/* Loading indicator */}
          {loading && !data && (
            <div className="text-center text-gray-500 py-8">Loading dashboard...</div>
          )}
        </div>
      </div>
    </div>
  );
}
