import { useState, useEffect, useRef, useCallback } from 'react';
import { createUnifiedLogsSocket } from '../services/websocket';

const MAX_LOGS = 1000;

export function useUnifiedLogs(enabled = true) {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('disconnected');
  const wsRef = useRef(null);

  const clearLogs = useCallback(() => {
    setLogs([]);
  }, []);

  useEffect(() => {
    if (!enabled) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setStatus('disconnected');
      return;
    }

    setStatus('connecting');
    let lastHistoryTs = null;

    const ws = createUnifiedLogsSocket(
      (msg) => {
        // Deduplicate: skip messages already covered by history
        if (lastHistoryTs && msg.timestamp <= lastHistoryTs) {
          return;
        }
        setLogs(prev => {
          const next = [...prev, msg];
          return next.length > MAX_LOGS ? next.slice(-MAX_LOGS) : next;
        });
      },
      (err) => {
        console.error('Unified logs error:', err);
        setStatus('error');
      },
      () => {
        setStatus('connected');
      },
      (historyLogs) => {
        if (historyLogs.length > 0) {
          lastHistoryTs = historyLogs[historyLogs.length - 1].timestamp;
          setLogs(historyLogs.slice(-MAX_LOGS));
        }
      }
    );

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [enabled]);

  return { logs, status, clearLogs };
}
