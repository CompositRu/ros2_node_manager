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

    const ws = createUnifiedLogsSocket(
      (msg) => {
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
      }
    );

    wsRef.current = ws;

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    };
  }, [enabled]);

  return { logs, status, clearLogs };
}
