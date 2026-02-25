import { useState, useMemo } from 'react';
import { useDiagnostics } from '../hooks/useDiagnostics';

const LEVEL_LABELS = { 0: 'OK', 1: 'WARN', 2: 'ERROR', 3: 'STALE' };

// NDT Scan Matcher thresholds from localization_diagnostics
const NDT_THRESHOLDS = {
  iteration_num: { warn: 10, error: 15 },
  skipping_publish_num: { warn: 7 },
  transform_probability: { errorBelow: 8.0 },
  nearest_voxel_transformation_likelihood: { errorBelow: 4.5 },
};

const NDT_METRIC_LABELS = {
  iteration_num: 'Iterations',
  skipping_publish_num: 'Skip pub',
  transform_probability: 'Transform prob',
  nearest_voxel_transformation_likelihood: 'Likelihood',
};

function getNdtMetricColor(key, value) {
  const num = parseFloat(value);
  if (isNaN(num)) return 'text-gray-400';
  const t = NDT_THRESHOLDS[key];
  if (!t) return 'text-gray-300';
  if (t.error !== undefined && num > t.error) return 'text-red-400';
  if (t.errorBelow !== undefined && num < t.errorBelow) return 'text-red-400';
  if (t.warn !== undefined && num > t.warn) return 'text-yellow-400';
  return 'text-green-400';
}

function isLocalizationItem(name) {
  const lower = name.toLowerCase();
  return lower.includes('ndt_scan_matcher') || lower.includes('vector_map_poser');
}

function isBagRecorderItem(name) {
  return name.includes('bag_recorder');
}

const BAG_RECORDER_MESSAGES = {
  0: 'Идёт запись бэга',
  1: 'Бэг не записывается',
  3: 'Нода не активна',
};
const LEVEL_COLORS = {
  0: 'text-green-400',
  1: 'text-yellow-400',
  2: 'text-red-400',
  3: 'text-gray-400',
};
const LEVEL_BG = {
  0: 'bg-green-900/30 border-green-700/50',
  1: 'bg-yellow-900/30 border-yellow-700/50',
  2: 'bg-red-900/30 border-red-700/50',
  3: 'bg-gray-800 border-gray-600/50',
};
const LEVEL_DOT = {
  0: 'bg-green-400',
  1: 'bg-yellow-400',
  2: 'bg-red-400',
  3: 'bg-gray-500',
};

function DiagCard({ item, onClick }) {
  const levelLabel = LEVEL_LABELS[item.level] ?? 'UNKNOWN';
  const firstValue = item.values?.[0];

  return (
    <button
      onClick={onClick}
      className={`rounded border px-3 py-2.5 text-left transition-colors hover:brightness-125 cursor-pointer ${LEVEL_BG[item.level] ?? LEVEL_BG[3]}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${LEVEL_DOT[item.level] ?? LEVEL_DOT[3]}`} />
        <span className={`text-xs font-semibold ${LEVEL_COLORS[item.level] ?? LEVEL_COLORS[3]}`}>
          {levelLabel}
        </span>
      </div>
      <div className="text-sm text-white font-medium truncate" title={item.name}>
        {item.name}
      </div>
      {item.message && (
        <div className="text-xs text-gray-400 truncate mt-0.5">{item.message}</div>
      )}
      {firstValue && (
        <div className="text-xs text-gray-500 truncate mt-1">
          {firstValue.key}: <span className="text-gray-300">{firstValue.value}</span>
        </div>
      )}
    </button>
  );
}

function LocalizationCard({ item, onClick }) {
  const levelLabel = LEVEL_LABELS[item.level] ?? 'UNKNOWN';

  // Build a map of key-value pairs for quick lookup
  const kvMap = {};
  if (item.values) {
    for (const kv of item.values) {
      kvMap[kv.key] = kv.value;
    }
  }

  const isVectorMap = item.name.toLowerCase().includes('vector_map_poser');
  const metrics = isVectorMap
    ? ['front_truck_distance', 'rear_truck_distance']
    : ['iteration_num', 'nearest_voxel_transformation_likelihood', 'transform_probability', 'skipping_publish_num'];

  return (
    <button
      onClick={onClick}
      className={`col-span-2 rounded border px-3 py-2.5 text-left transition-colors hover:brightness-125 cursor-pointer ${LEVEL_BG[item.level] ?? LEVEL_BG[3]}`}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${LEVEL_DOT[item.level] ?? LEVEL_DOT[3]}`} />
        <span className={`text-xs font-semibold ${LEVEL_COLORS[item.level] ?? LEVEL_COLORS[3]}`}>
          {levelLabel}
        </span>
        <span className="text-sm text-white font-medium truncate" title={item.name}>
          {item.name}
        </span>
      </div>
      {item.message && (
        <div className="text-xs text-gray-400 truncate mb-2">{item.message}</div>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {metrics.map((key) => {
          const val = kvMap[key];
          if (val === undefined) return null;
          return (
            <div key={key} className="flex items-center justify-between text-xs">
              <span className="text-gray-500 truncate mr-2">{NDT_METRIC_LABELS[key] || key}</span>
              <span className={`font-mono font-medium ${getNdtMetricColor(key, val)}`}>
                {val}
              </span>
            </div>
          );
        })}
      </div>
    </button>
  );
}

function BagRecorderCard({ item, onClick }) {
  const statusMsg = BAG_RECORDER_MESSAGES[item.level] ?? BAG_RECORDER_MESSAGES[1];

  return (
    <button
      onClick={onClick}
      className={`rounded border px-3 py-2.5 text-left transition-colors hover:brightness-125 cursor-pointer ${LEVEL_BG[item.level] ?? LEVEL_BG[3]}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${LEVEL_DOT[item.level] ?? LEVEL_DOT[3]}`} />
        <span className={`text-sm font-semibold ${LEVEL_COLORS[item.level] ?? LEVEL_COLORS[3]}`}>
          {statusMsg}
        </span>
      </div>
      <div className="text-xs text-gray-400">Bag Recorder</div>
    </button>
  );
}

function DetailView({ item, onBack }) {
  const levelLabel = LEVEL_LABELS[item.level] ?? 'UNKNOWN';

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700 bg-gray-800 flex-shrink-0">
        <button
          onClick={onBack}
          className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded"
        >
          &larr; Back
        </button>
        <span className={`w-2.5 h-2.5 rounded-full ${LEVEL_DOT[item.level] ?? LEVEL_DOT[3]}`} />
        <span className={`text-sm font-semibold ${LEVEL_COLORS[item.level] ?? LEVEL_COLORS[3]}`}>
          {levelLabel}
        </span>
        <span className="text-gray-500 text-xs">({item.level})</span>
        <span className="text-gray-300 font-medium text-sm truncate select-text cursor-text">{item.name}</span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 select-text">
        {/* Message */}
        {item.message && (
          <div className="mb-4">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Message</div>
            <div className="text-sm text-gray-200">{item.message}</div>
          </div>
        )}

        {/* Hardware ID */}
        {item.hardware_id && (
          <div className="mb-4">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Hardware ID</div>
            <div className="text-sm text-gray-200">{item.hardware_id}</div>
          </div>
        )}

        {/* Timestamp */}
        {item.timestamp && (
          <div className="mb-4">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Last Update</div>
            <div className="text-sm text-gray-200">
              {new Date(item.timestamp).toLocaleString()}
            </div>
          </div>
        )}

        {/* Key-Value Pairs */}
        {item.values && item.values.length > 0 && (
          <div className="mb-4">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
              Values ({item.values.length})
            </div>
            <div className="bg-gray-800 rounded border border-gray-700 overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-700">
                    <th className="text-left px-3 py-1.5 text-gray-400 font-medium">Key</th>
                    <th className="text-left px-3 py-1.5 text-gray-400 font-medium">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {item.values.map((kv, i) => {
                    const isNdt = isLocalizationItem(item.name) && NDT_THRESHOLDS[kv.key];
                    const valColor = isNdt ? getNdtMetricColor(kv.key, kv.value) : 'text-white';
                    return (
                      <tr key={i} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                        <td className="px-3 py-1.5 text-gray-300 font-mono">{kv.key}</td>
                        <td className={`px-3 py-1.5 font-mono ${valColor}`}>{kv.value}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* History */}
        {item.history && item.history.length > 1 && (
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
              Recent History ({item.history.length})
            </div>
            <div className="space-y-1">
              {[...item.history].reverse().slice(0, 20).map((h, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={`w-1.5 h-1.5 rounded-full ${LEVEL_DOT[h.level] ?? LEVEL_DOT[3]}`} />
                  <span className={LEVEL_COLORS[h.level] ?? LEVEL_COLORS[3]}>
                    {LEVEL_LABELS[h.level] ?? '?'}
                  </span>
                  <span className="text-gray-500">
                    {new Date(h.timestamp).toLocaleTimeString()}
                  </span>
                  {h.message && (
                    <span className="text-gray-400 truncate">{h.message}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function Diagnostics({ connected }) {
  const { diagnostics, status: diagStatus, clearDiagnostics } = useDiagnostics(connected);

  const [levelFilter, setLevelFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [selectedName, setSelectedName] = useState(null);

  const diagList = useMemo(() => {
    return Object.values(diagnostics);
  }, [diagnostics]);

  const filtered = useMemo(() => {
    return diagList.filter((item) => {
      if (levelFilter !== 'All' && LEVEL_LABELS[item.level] !== levelFilter) return false;
      if (search && !item.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [diagList, levelFilter, search]);

  // Counts by level
  const counts = useMemo(() => {
    const c = { total: diagList.length, ok: 0, warn: 0, error: 0, stale: 0 };
    for (const item of diagList) {
      if (item.level === 0) c.ok++;
      else if (item.level === 1) c.warn++;
      else if (item.level === 2) c.error++;
      else c.stale++;
    }
    return c;
  }, [diagList]);

  // Detail view
  const selectedItem = selectedName ? diagnostics[selectedName] : null;
  if (selectedItem) {
    return <DetailView item={selectedItem} onBack={() => setSelectedName(null)} />;
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700 bg-gray-800 flex-shrink-0">
        <span className="text-gray-300 font-medium text-sm flex-shrink-0">Diagnostics</span>

        {diagStatus === 'connecting' && <span className="text-yellow-400 text-xs flex-shrink-0">● Connecting...</span>}
        {diagStatus === 'connected' && <span className="text-green-400 text-xs flex-shrink-0">● Connected</span>}
        {diagStatus === 'error' && <span className="text-red-400 text-xs flex-shrink-0">● Error</span>}
        {diagStatus === 'disconnected' && !connected && <span className="text-gray-500 text-xs flex-shrink-0">● Not connected</span>}

        {/* Counts */}
        {counts.total > 0 && (
          <div className="flex items-center gap-2 text-xs flex-shrink-0">
            <span className="text-gray-500">|</span>
            <span className="text-green-400">{counts.ok} OK</span>
            {counts.warn > 0 && <span className="text-yellow-400">{counts.warn} WARN</span>}
            {counts.error > 0 && <span className="text-red-400">{counts.error} ERR</span>}
            {counts.stale > 0 && <span className="text-gray-400">{counts.stale} STALE</span>}
          </div>
        )}

        <div className="flex-1" />

        {/* Filter by level */}
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
        >
          <option value="All">All levels</option>
          <option value="OK">OK</option>
          <option value="WARN">WARN</option>
          <option value="ERROR">ERROR</option>
          <option value="STALE">STALE</option>
        </select>

        {/* Search */}
        <input
          type="text"
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 w-48 focus:outline-none focus:border-blue-500"
        />

        <button
          onClick={clearDiagnostics}
          className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded"
        >
          Clear
        </button>
      </div>

      {/* Card Grid */}
      <div className="flex-1 overflow-auto p-4">
        {filtered.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            {diagStatus === 'connecting'
              ? 'Connecting to diagnostics stream...'
              : diagStatus === 'connected' && counts.total === 0
                ? 'Waiting for diagnostics data...'
                : !connected
                  ? 'Connect to a server to view diagnostics'
                  : counts.total > 0
                    ? 'No diagnostics match the current filter'
                    : 'No diagnostics yet'}
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3">
            {filtered.map((item) =>
              isBagRecorderItem(item.name) ? (
                <BagRecorderCard
                  key={item.name}
                  item={item}
                  onClick={() => setSelectedName(item.name)}
                />
              ) : isLocalizationItem(item.name) ? (
                <LocalizationCard
                  key={item.name}
                  item={item}
                  onClick={() => setSelectedName(item.name)}
                />
              ) : (
                <DiagCard
                  key={item.name}
                  item={item}
                  onClick={() => setSelectedName(item.name)}
                />
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
