import { useState, useEffect, useCallback } from 'react';
import * as api from '../services/api';

/**
 * Hook for managing server connection
 */
export function useServer() {
  const [servers, setServers] = useState([]);
  const [currentServer, setCurrentServer] = useState(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Fetch servers list
  const fetchServers = useCallback(async () => {
    try {
      const data = await api.getServers();
      setServers(data);
    } catch (err) {
      console.error('Failed to fetch servers:', err);
    }
  }, []);
  
  // Fetch current connection status
  const fetchCurrentServer = useCallback(async () => {
    try {
      const data = await api.getCurrentServer();
      setConnected(data.connected);
      setCurrentServer(data.server);
    } catch (err) {
      console.error('Failed to fetch current server:', err);
      setConnected(false);
      setCurrentServer(null);
    }
  }, []);
  
  // Initial fetch
  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await Promise.all([fetchServers(), fetchCurrentServer()]);
      setLoading(false);
    };
    init();
  }, [fetchServers, fetchCurrentServer]);
  
  // Connect to server
  const connect = useCallback(async (serverId, password = null) => {
    try {
      setLoading(true);
      setError(null);
      const result = await api.connectToServer(serverId, password);
      setConnected(true);
      setCurrentServer(result.server);
      await fetchServers();
      return result;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [fetchServers]);
  
  // Disconnect
  const disconnect = useCallback(async () => {
    try {
      setLoading(true);
      await api.disconnectFromServer();
      setConnected(false);
      setCurrentServer(null);
      await fetchServers();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [fetchServers]);
  
  return {
    servers,
    currentServer,
    connected,
    loading,
    error,
    connect,
    disconnect,
    refresh: fetchServers,
  };
}
