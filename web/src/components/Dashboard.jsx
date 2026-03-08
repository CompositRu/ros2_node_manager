import { useDashboard } from '../hooks/useDashboard';

// ─── Status logic ───────────────────────────────────────────────

function getAutopilotStatus(connected, data) {
  if (!connected || !data || !data.docker?.running) {
    return { level: 'offline', label: 'Не запущен контейнер', color: 'gray' };
  }
  const { active, total } = data.nodes;
  if (total === 0 || active === 0) {
    return { level: 'critical', label: 'Не запущен автопилот', color: 'red' };
  }
  if (active >= 100) {
    return { level: 'running', label: 'Автопилот запущен', color: 'green' };
  }
  return { level: 'warning', label: 'Автопилот запущен частично', color: 'yellow' };
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

function StatusBanner({ status }) {
  const s = STATUS_STYLES[status.color];

  return (
    <div className={`${s.bg} ${s.border} border rounded-lg p-6 flex items-center justify-between`}>
      <div className="flex items-center gap-4">
        <div className={`w-4 h-4 rounded-full ${s.dot} animate-pulse`} />
        <span className={`text-2xl font-bold ${s.text}`}>{status.label}</span>
      </div>
    </div>
  );
}

const MRM_STATE_STYLES = {
  NORMAL:        { bg: 'bg-green-900/30', border: 'border-green-600/50', text: 'text-green-400', dot: 'bg-green-400' },
  MRM_OPERATING: { bg: 'bg-red-900/30',   border: 'border-red-600/50',   text: 'text-red-400',   dot: 'bg-red-400' },
  MRM_SUCCEEDED: { bg: 'bg-red-900/30',   border: 'border-red-600/50',   text: 'text-red-400',   dot: 'bg-red-400' },
  MRM_FAILED:    { bg: 'bg-red-900/30',   border: 'border-red-600/50',   text: 'text-red-400',   dot: 'bg-red-400' },
};

const MRM_STATE_LABELS = {
  NORMAL: 'Маневр минимального риска: норма',
  MRM_OPERATING: 'Выполняется маневр минимального риска',
  MRM_SUCCEEDED: 'Маневр минимального риска завершён успешно',
  MRM_FAILED: 'Маневр минимального риска не удался',
};

const MRM_BEHAVIOR_LABELS = {
  NONE: null,
  EMERGENCY_STOP: 'Режим: экстренная остановка',
  COMFORTABLE_STOP: 'Режим: плавная остановка',
};

function MrmStateCard({ mrmState }) {
  if (!mrmState) return null;

  const s = MRM_STATE_STYLES[mrmState.state_label] ?? MRM_STATE_STYLES.MRM_FAILED;
  const label = MRM_STATE_LABELS[mrmState.state_label] ?? mrmState.state_label;
  const behaviorLabel = MRM_BEHAVIOR_LABELS[mrmState.behavior_label];
  const isNormal = mrmState.state_label === 'NORMAL';

  return (
    <div className={`${s.bg} ${s.border} border rounded-lg p-5 flex flex-col justify-center`}>
      <div className="flex items-center gap-2 mb-1">
        <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${s.dot} ${!isNormal ? 'animate-pulse' : ''}`} />
        <span className={`text-sm font-semibold ${s.text}`}>{label}</span>
      </div>
      {behaviorLabel && (
        <div className="text-xs text-gray-400">{behaviorLabel}</div>
      )}
    </div>
  );
}

function SpeedCard({ speed, status }) {
  const display = (status.level === 'critical' || speed == null) ? '—' : speed;

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-5 flex items-center justify-center">
      <span className="text-5xl font-bold text-white tabular-nums">
        {display}
      </span>
      <span className="text-lg text-gray-400 ml-2">km/h</span>
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
    </div>
  );
}

function QuickStatsCard({ data }) {
  const stats = [
    { label: 'Nodes', value: data?.nodes?.active != null ? `${data.nodes.active}/${data.nodes.total} active` : '—' },
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
  const iconClass = "w-4 h-4 inline-block";
  const links = [
    { id: 'diagnostics', label: 'Diagnostics', icon: <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" /></svg> },
    { id: 'logs', label: 'Logs', icon: <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" /></svg> },
    { id: 'nodes', label: 'Nodes', icon: <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25a2.25 2.25 0 01-2.25-2.25v-2.25z" /></svg> },
    { id: 'topics', label: 'Topics', icon: <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" /></svg> },
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
    <div className="h-full flex flex-col overflow-hidden select-text">
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* Logo */}
          <div className="flex justify-center">
            <img src="/logo2.png" alt="TMS" className="h-24" />
          </div>

          {/* System Status Banner */}
          <StatusBanner status={status} />

          {/* Speed + MRM State */}
          {status.level !== 'offline' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <SpeedCard speed={data?.speed_kmh} status={status} />
              <MrmStateCard mrmState={data?.mrm_state} />
            </div>
          )}

          {/* Resources + Quick Stats */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ResourcesCard resources={data?.resources} />
            <QuickStatsCard data={data} />
          </div>

          {/* Recent Alerts */}
          <RecentAlertsCard
            alerts={alerts}
            onViewAll={() => onSectionChange('history', { tab: 'alerts' })}
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
