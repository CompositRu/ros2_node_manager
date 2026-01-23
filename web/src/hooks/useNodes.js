import { useState, useEffect, useCallback } from 'react';
import * as api from '../services/api';
import { createNodesStatusSocket } from '../services/websocket';

/**
 * Hook for managing nodes state
 */
export function useNodes() {
  const [nodes, setNodes] = useState([]);
  const [counts, setCounts] = useState({ total: 0, active: 0, inactive: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Fetch nodes
  const fetchNodes = useCallback(async (refresh = true) => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getNodes(refresh);
      setNodes(data.nodes);
      setCounts({
        total: data.total,
        active: data.active,
        inactive: data.inactive,
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);
  
  // Initial fetch
  useEffect(() => {
    fetchNodes();
  }, [fetchNodes]);
  
  // WebSocket for real-time updates
  useEffect(() => {
    const ws = createNodesStatusSocket(
      (data) => {
        if (data.type === 'nodes_update') {
          setCounts({
            total: data.total,
            active: data.active,
            inactive: data.inactive,
          });
          
          // Update node statuses
          setNodes(prev => prev.map(node => ({
            ...node,
            status: data.nodes[node.name] || node.status
          })));
        }
      },
      (err) => {
        console.error('WebSocket error:', err);
      }
    );
    
    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, []);
  
  return {
    nodes,
    counts,
    loading,
    error,
    refresh: fetchNodes,
  };
}
