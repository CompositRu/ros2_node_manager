import { useAlertHistory } from '../hooks/useAlertHistory';

const ALERT_TYPES = [
  { value: '', label: 'All Types' },
  { value: 'node_inactive', label: 'Node Inactive' },
  { value: 'node_recovered', label: 'Node Recovered' },
  { value: 'missing_topic', label: 'Missing Topic' },
  { value: 'topic_recovered', label: 'Topic Recovered' },
  { value: 'error_pattern', label: 'Error Pattern' },
  { value: 'topic_value', label: 'Topic Value' },
];

const SEVERITIES = [
  { value: '', label: 'All Severities' },
  { value: 'critical', label: 'Critical' },
  { value: 'error', label: 'Error' },
  { value: 'warning', label: 'Warning' },
  { value: 'info', label: 'Info' },
];

const severityBorderColor = (severity) => {
  switch (severity) {
    case 'critical': return 'border-red-500';
    case 'error': return 'border-red-400';
    case 'warning': return 'border-yellow-400';
    case 'info': return 'border-blue-400';
    default: return 'border-gray-600';
  }
};

const severityBadgeClass = (severity) => {
  switch (severity) {
    case 'critical': return 'bg-red-900/50 text-red-300';
    case 'error': return 'bg-red-900/30 text-red-400';
    case 'warning': return 'bg-yellow-900/30 text-yellow-400';
    case 'info': return 'bg-blue-900/30 text-blue-400';
    default: return 'bg-gray-700 text-gray-300';
  }
};

const typeBadgeClass = (alertType) => {
  if (alertType?.includes('recovered')) return 'bg-green-900/30 text-green-400';
  if (alertType?.includes('inactive') || alertType?.includes('missing')) return 'bg-red-900/30 text-red-400';
  return 'bg-gray-700 text-gray-300';
};

const formatTimestamp = (ts) => {
  try {
    const d = new Date(ts);
    return `${d.toLocaleDateString('ru-RU')} ${d.toLocaleTimeString('en-US', { hour12: false })}`;
  } catch {
    return ts;
  }
};

export function AlertHistory() {
  const {
    alerts, total, loading, error, filters, offset, pageSize,
    updateFilters, nextPage, prevPage, fetchAlerts,
  } = useAlertHistory();

  const currentPage = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700 bg-gray-800 flex-shrink-0 flex-wrap">
        <select
          value={filters.alert_type || ''}
          onChange={(e) => updateFilters({ alert_type: e.target.value || null })}
          className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
        >
          {ALERT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>

        <select
          value={filters.severity || ''}
          onChange={(e) => updateFilters({ severity: e.target.value || null })}
          className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
        >
          {SEVERITIES.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Filter by node..."
          value={filters.node_name}
          onChange={(e) => updateFilters({ node_name: e.target.value })}
          className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 w-36 focus:outline-none focus:border-blue-500"
        />

        <div className="flex-1" />

        <button
          onClick={() => fetchAlerts(0)}
          disabled={loading}
          className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-2 bg-red-900/30 text-red-400 text-xs border-b border-gray-700">
          Error: {error}
        </div>
      )}

      {/* Alert cards */}
      <div className="flex-1 overflow-auto p-4 space-y-2">
        {alerts.length === 0 && !loading && (
          <div className="text-gray-500 text-center py-8">
            {total === 0 ? 'No alerts in history yet' : 'No alerts match filters'}
          </div>
        )}

        {loading && alerts.length === 0 && (
          <div className="text-gray-500 text-center py-8">Loading...</div>
        )}

        {alerts.map((alert) => (
          <div
            key={alert.id}
            className={`bg-gray-800 rounded border-l-4 p-3 ${severityBorderColor(alert.severity)}`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-gray-200">{alert.title}</span>
              <span className="text-xs text-gray-500 flex-shrink-0 ml-2">
                {formatTimestamp(alert.timestamp)}
              </span>
            </div>
            <p className="text-xs text-gray-400 mb-1.5">{alert.message}</p>
            <div className="flex items-center gap-2">
              <span className={`text-xs px-1.5 py-0.5 rounded ${typeBadgeClass(alert.alert_type)}`}>
                {alert.alert_type}
              </span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${severityBadgeClass(alert.severity)}`}>
                {alert.severity}
              </span>
              {alert.node_name && (
                <span className="text-xs text-purple-300">
                  {alert.node_name}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Pagination footer */}
      <div className="px-4 py-2 border-t border-gray-700 bg-gray-800 flex items-center justify-between flex-shrink-0">
        <span className="text-xs text-gray-400">
          {total > 0
            ? `${offset + 1}–${Math.min(offset + pageSize, total)} of ${total.toLocaleString()}`
            : 'No results'}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={prevPage}
            disabled={offset === 0 || loading}
            className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded disabled:opacity-30"
          >
            Prev
          </button>
          <span className="text-xs text-gray-400">
            {totalPages > 0 ? `${currentPage} / ${totalPages}` : ''}
          </span>
          <button
            onClick={nextPage}
            disabled={offset + pageSize >= total || loading}
            className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded disabled:opacity-30"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
