import { useState, useCallback, useEffect, useRef } from 'react';
import { getLogHistory } from '../services/api';

const PAGE_SIZE = 100;

export function useLogHistory() {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({
    level: null,
    node_name: '',
    search: '',
    since: null,
    until: null,
  });
  const [offset, setOffset] = useState(0);
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const fetchLogs = useCallback(async (newOffset) => {
    setLoading(true);
    setError(null);
    try {
      const currentOffset = newOffset ?? 0;
      const result = await getLogHistory({
        ...filtersRef.current,
        limit: PAGE_SIZE,
        offset: currentOffset,
      });
      setLogs(result.items);
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
      fetchLogs(newOffset);
    }
  }, [offset, total, fetchLogs]);

  const prevPage = useCallback(() => {
    const newOffset = Math.max(0, offset - PAGE_SIZE);
    fetchLogs(newOffset);
  }, [offset, fetchLogs]);

  // Re-fetch when filters change (reset to page 0)
  useEffect(() => {
    fetchLogs(0);
  }, [filters, fetchLogs]);

  return {
    logs,
    total,
    loading,
    error,
    filters,
    offset,
    pageSize: PAGE_SIZE,
    fetchLogs,
    updateFilters,
    nextPage,
    prevPage,
  };
}
