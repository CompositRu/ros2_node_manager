import { useState } from 'react';
import { useLogHistory } from '../hooks/useLogHistory';
import { getLogExportUrl } from '../services/api';

const LOG_LEVELS = ['All', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'];

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

const formatDate = (ts) => {
  try {
    const d = new Date(ts);
    return `${d.toLocaleDateString('ru-RU')} ${d.toLocaleTimeString('en-US', { hour12: false })}`;
  } catch {
    return ts;
  }
};

export function LogHistory() {
  const {
    logs, total, loading, error, filters, offset, pageSize,
    updateFilters, nextPage, prevPage, fetchLogs,
  } = useLogHistory();

  const [searchInput, setSearchInput] = useState('');

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    updateFilters({ search: searchInput });
  };

  const handleExport = (format) => {
    const url = getLogExportUrl({ ...filters, format });
    window.open(url, '_blank');
  };

  const currentPage = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700 bg-gray-800 flex-shrink-0 flex-wrap">
        <select
          value={filters.level || 'All'}
          onChange={(e) => updateFilters({ level: e.target.value === 'All' ? null : e.target.value })}
          className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
        >
          {LOG_LEVELS.map((level) => (
            <option key={level} value={level}>{level}</option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Filter by node..."
          value={filters.node_name}
          onChange={(e) => updateFilters({ node_name: e.target.value })}
          className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 w-36 focus:outline-none focus:border-blue-500"
        />

        <form onSubmit={handleSearchSubmit} className="flex items-center gap-1">
          <input
            type="text"
            placeholder="Search message..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded border border-gray-600 w-44 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Search
          </button>
        </form>

        <div className="flex-1" />

        <button
          onClick={() => fetchLogs(0)}
          disabled={loading}
          className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>

        <div className="relative group">
          <button
            className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded"
          >
            Export
          </button>
          <div className="absolute right-0 top-full mt-1 bg-gray-700 border border-gray-600 rounded shadow-lg hidden group-hover:block z-10">
            <button
              onClick={() => handleExport('json')}
              className="block w-full px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-600 text-left"
            >
              JSON
            </button>
            <button
              onClick={() => handleExport('text')}
              className="block w-full px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-600 text-left"
            >
              Text
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-2 bg-red-900/30 text-red-400 text-xs border-b border-gray-700">
          Error: {error}
        </div>
      )}

      {/* Log table */}
      <div className="flex-1 overflow-auto p-2 font-mono text-xs select-text">
        {logs.length === 0 && !loading && (
          <div className="text-gray-500 text-center py-8">
            {total === 0 ? 'No logs in history yet' : 'No logs match filters'}
          </div>
        )}

        {loading && logs.length === 0 && (
          <div className="text-gray-500 text-center py-8">Loading...</div>
        )}

        {logs.map((log) => (
          <div key={log.id} className="flex gap-2 hover:bg-gray-800/50 px-1 leading-5">
            <span className="text-gray-500 flex-shrink-0">
              {formatDate(log.timestamp)}
            </span>
            <span className={`flex-shrink-0 w-12 text-right ${getLevelClass(log.level)}`}>
              {log.level}
            </span>
            <span className="text-purple-300 flex-shrink-0 whitespace-nowrap">
              [{log.node_name}]
            </span>
            <span className="text-gray-300 break-all">
              {log.message}
            </span>
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
