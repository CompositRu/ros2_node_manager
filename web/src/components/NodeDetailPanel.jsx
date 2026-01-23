import { useState, useEffect } from 'react';
import * as api from '../services/api';

// Loading spinner component
const Spinner = () => (
  <svg className="animate-spin h-4 w-4 text-blue-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
  </svg>
);

/**
 * Panel showing node details
 */
export function NodeDetailPanel({ nodeName, onShowLogs }) {
  const [node, setNode] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [cache, setCache] = useState({});

  useEffect(() => {
    if (!nodeName) {
      setNode(null);
      return;
    }

    const cached = cache[nodeName];
    if (cached) {
      setNode(cached);
    } else {
      setNode({
        name: nodeName,
        status: 'active',
        type: 'unknown',
        parameters: {},
        subscribers: [],
        publishers: [],
        services: []
      });
    }

    const fetchDetail = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getNodeDetail(nodeName);
        setNode(data.node);
        setCache(prev => ({ ...prev, [nodeName]: data.node }));
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchDetail();
  }, [nodeName]);

  const refresh = async () => {
    if (!nodeName) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getNodeDetail(nodeName);
      setNode(data.node);
      setCache(prev => ({ ...prev, [nodeName]: data.node }));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (!nodeName) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        Select a node to view details
      </div>
    );
  }

  const handleShutdown = async (force = false) => {
    setActionLoading(true);
    setActionError(null);
    setShowConfirm(false);
    try {
      const result = await api.shutdownNode(nodeName, force);
      if (!result.success) {
        setActionError(result.message);
      }
      refresh();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const statusColor = node?.status === 'active' ? 'text-green-400' : 'text-gray-500';
  const typeColor = node?.type === 'lifecycle' ? 'text-purple-400' :
                    node?.type === 'regular' ? 'text-blue-400' : 'text-yellow-400';

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-white truncate flex-1" title={nodeName}>
            {nodeName.split('/').pop()}
          </h2>
          {loading && <Spinner />}
        </div>
        <p className="text-xs text-gray-500 truncate" title={nodeName}>
          {nodeName}
        </p>
      </div>

      {error && (
        <div className="px-4 py-2 bg-red-900/50 text-red-300 text-sm">
          {error}
        </div>
      )}

      {node && (
        <>
          {/* Status */}
          <div className="p-4 border-b border-gray-700 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Status:</span>
              <span className={`font-medium ${statusColor}`}>
                {node.status === 'active' ? '● Active' : '○ Inactive'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Type:</span>
              <span className={`font-medium ${typeColor}`}>
                {node.type === 'lifecycle' ? '◐ Lifecycle' :
                 node.type === 'regular' ? '● Regular' : '? Unknown'}
              </span>
            </div>
            {node.type === 'lifecycle' && node.lifecycle_state && (
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Lifecycle State:</span>
                <span className="text-purple-300">{node.lifecycle_state}</span>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="p-4 border-b border-gray-700 flex gap-2 flex-wrap">
            {node.status === 'active' && node.type !== 'unknown' && (
              node.type === 'lifecycle' ? (
                <button
                  onClick={() => handleShutdown(false)}
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded disabled:opacity-50"
                >
                  {actionLoading ? 'Shutting down...' : 'Shutdown'}
                </button>
              ) : (
                <button
                  onClick={() => setShowConfirm(true)}
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-orange-600 hover:bg-orange-700 text-white text-sm rounded disabled:opacity-50"
                >
                  Kill Process
                </button>
              )
            )}
            <button
              onClick={() => onShowLogs(nodeName)}
              className="px-3 py-1.5 bg-gray-600 hover:bg-gray-700 text-white text-sm rounded"
            >
              View Logs
            </button>
            <button
              onClick={refresh}
              disabled={loading}
              className="px-3 py-1.5 bg-gray-600 hover:bg-gray-700 text-white text-sm rounded disabled:opacity-50 flex items-center gap-1"
            >
              {loading ? <Spinner /> : '↻'} Refresh
            </button>
          </div>

          {actionError && (
            <div className="px-4 py-2 bg-red-900/50 text-red-300 text-sm">
              {actionError}
            </div>
          )}

          {showConfirm && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
              <div className="bg-gray-800 p-4 rounded-lg shadow-xl max-w-md">
                <h3 className="text-white font-semibold mb-2">⚠️ Warning</h3>
                <p className="text-gray-300 text-sm mb-4">
                  This will forcefully kill the process. The node may not restart properly. Are you sure?
                </p>
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={() => setShowConfirm(false)}
                    className="px-3 py-1.5 bg-gray-600 hover:bg-gray-700 text-white text-sm rounded"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => handleShutdown(true)}
                    className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded"
                  >
                    Kill
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Content */}
          <div className="flex-1 overflow-auto p-4 space-y-4">
            <Section title="Parameters" loading={loading && Object.keys(node.parameters || {}).length === 0} defaultOpen={true}>
              {Object.keys(node.parameters || {}).length > 0 ? (
                <div className="space-y-1 text-sm font-mono max-h-64 overflow-auto">
                  {Object.entries(node.parameters).map(([key, value]) => (
                    <div key={key} className="flex">
                      <span className="text-blue-300 mr-2">{key}:</span>
                      <span className="text-gray-300">{formatValue(value)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="text-gray-500 text-sm flex items-center gap-2">
                  {loading ? <><Spinner /> Loading...</> : 'No parameters'}
                </span>
              )}
            </Section>

            <Section title={`Subscribers (${node.subscribers?.length || 0})`} loading={loading && (node.subscribers?.length || 0) === 0}>
              {(node.subscribers?.length || 0) > 0 ? (
                <ul className="text-sm font-mono space-y-0.5 max-h-48 overflow-auto">
                  {node.subscribers.map(sub => (
                    <li key={sub} className="text-cyan-300">{sub}</li>
                  ))}
                </ul>
              ) : (
                <span className="text-gray-500 text-sm flex items-center gap-2">
                  {loading ? <><Spinner /> Loading...</> : 'None'}
                </span>
              )}
            </Section>

            <Section title={`Publishers (${node.publishers?.length || 0})`} loading={loading && (node.publishers?.length || 0) === 0}>
              {(node.publishers?.length || 0) > 0 ? (
                <ul className="text-sm font-mono space-y-0.5 max-h-48 overflow-auto">
                  {node.publishers.map(pub => (
                    <li key={pub} className="text-green-300">{pub}</li>
                  ))}
                </ul>
              ) : (
                <span className="text-gray-500 text-sm flex items-center gap-2">
                  {loading ? <><Spinner /> Loading...</> : 'None'}
                </span>
              )}
            </Section>

            <Section title={`Services (${node.services?.length || 0})`} loading={loading && (node.services?.length || 0) === 0}>
              {(node.services?.length || 0) > 0 ? (
                <ul className="text-sm font-mono space-y-0.5 max-h-48 overflow-auto">
                  {node.services.map(srv => (
                    <li key={srv} className="text-yellow-300">{srv}</li>
                  ))}
                </ul>
              ) : (
                <span className="text-gray-500 text-sm flex items-center gap-2">
                  {loading ? <><Spinner /> Loading...</> : 'None'}
                </span>
              )}
            </Section>
          </div>
        </>
      )}
    </div>
  );
}

function Section({ title, children, defaultOpen = false, loading = false }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border border-gray-700 rounded">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-2 hover:bg-gray-700/50"
      >
        <span className="text-gray-300 font-medium text-sm">{title}</span>
        <span className="text-gray-500">{isOpen ? '▼' : '▶'}</span>
      </button>
      {isOpen && (
        <div className="p-2 border-t border-gray-700">
          {children}
        </div>
      )}
    </div>
  );
}

function formatValue(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}