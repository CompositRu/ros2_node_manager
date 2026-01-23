import { useState } from 'react';

/**
 * Server selector dropdown
 */
export function ServerSelector({ servers, currentServer, connected, onConnect, onDisconnect, loading }) {
  const [selectedId, setSelectedId] = useState(currentServer?.id || '');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  
  const handleConnect = async () => {
    if (!selectedId) return;
    try {
      await onConnect(selectedId, password || null);
      setPassword('');
      setShowPassword(false);
    } catch (err) {
      // Error handled in parent
    }
  };
  
  return (
    <div className="flex items-center gap-3">
      <label className="text-gray-400 text-sm">Server:</label>
      
      <select
        value={selectedId}
        onChange={(e) => setSelectedId(e.target.value)}
        disabled={loading}
        className="bg-gray-700 text-white px-3 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
      >
        <option value="">Select server...</option>
        {servers.map(srv => (
          <option key={srv.id} value={srv.id}>
            {srv.name} {srv.connected ? '✓' : ''}
          </option>
        ))}
      </select>
      
      {/* Password input for SSH servers */}
      {selectedId && servers.find(s => s.id === selectedId)?.type === 'ssh' && (
        <div className="flex items-center gap-2">
          <input
            type={showPassword ? 'text' : 'password'}
            placeholder="Password (optional)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="bg-gray-700 text-white px-3 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500 w-40"
          />
          <button
            onClick={() => setShowPassword(!showPassword)}
            className="text-gray-400 hover:text-white"
          >
            {showPassword ? '👁️' : '👁️‍🗨️'}
          </button>
        </div>
      )}
      
      {connected ? (
        <button
          onClick={onDisconnect}
          disabled={loading}
          className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded disabled:opacity-50"
        >
          Disconnect
        </button>
      ) : (
        <button
          onClick={handleConnect}
          disabled={loading || !selectedId}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-50"
        >
          {loading ? 'Connecting...' : 'Connect'}
        </button>
      )}
      
      {connected && currentServer && (
        <span className="text-green-400 text-sm">
          ● Connected to {currentServer.name}
        </span>
      )}
    </div>
  );
}
