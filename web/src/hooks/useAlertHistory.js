import { useState, useCallback, useEffect, useRef } from 'react';
import { getAlertHistory } from '../services/api';

const PAGE_SIZE = 50;

export function useAlertHistory() {
  const [alerts, setAlerts] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({
    alert_type: null,
    severity: null,
    node_name: '',
    since: null,
    until: null,
  });
  const [offset, setOffset] = useState(0);
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const fetchAlerts = useCallback(async (newOffset) => {
    setLoading(true);
    setError(null);
    try {
      const currentOffset = newOffset ?? 0;
      const result = await getAlertHistory({
        ...filtersRef.current,
        limit: PAGE_SIZE,
        offset: currentOffset,
      });
      setAlerts(result.items);
      setTotal(result.total);
      setOffset(currentOffset);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const updateFilters = useCallback((newFilters) => {
    setFilters(prev => ({ ...prev, ...newFilters }));
  }, []);

  const nextPage = useCallback(() => {
    const newOffset = offset + PAGE_SIZE;
    if (newOffset < total) {
      fetchAlerts(newOffset);
    }
  }, [offset, total, fetchAlerts]);

  const prevPage = useCallback(() => {
    const newOffset = Math.max(0, offset - PAGE_SIZE);
    fetchAlerts(newOffset);
  }, [offset, fetchAlerts]);

  // Re-fetch when filters change (reset to page 0)
  useEffect(() => {
    fetchAlerts(0);
  }, [filters, fetchAlerts]);

  return {
    alerts,
    total,
    loading,
    error,
    filters,
    offset,
    pageSize: PAGE_SIZE,
    fetchAlerts,
    updateFilters,
    nextPage,
    prevPage,
  };
}
