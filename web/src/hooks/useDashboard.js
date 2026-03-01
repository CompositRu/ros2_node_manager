import { useState, useEffect, useRef, useCallback } from 'react';
import { getDashboard, getAlertHistory } from '../services/api';

const POLL_INTERVAL = 5000;

export function useDashboard(enabled = true) {
  const [data, setData] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const [dashboardData, alertsData] = await Promise.all([
        getDashboard(),
        getAlertHistory({ limit: 5 }),
      ]);
      setData(dashboardData);
      setAlerts(alertsData.items || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }

    fetchData();
    timerRef.current = setInterval(fetchData, POLL_INTERVAL);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, fetchData]);

  return { data, alerts, loading, error, refresh: fetchData };
}
