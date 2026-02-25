import { useState, useEffect, useCallback, useRef } from 'react';
import * as api from '../services/api';

const POLL_INTERVAL = 5000;

export function useSystemStats(enabled = true) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  const fetchStats = useCallback(async () => {
    try {
      const data = await api.getStats();
      setStats(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setStats(null);
      setLoading(false);
      return;
    }

    fetchStats();
    intervalRef.current = setInterval(fetchStats, POLL_INTERVAL);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled, fetchStats]);

  return { stats, loading, error, refresh: fetchStats };
}
