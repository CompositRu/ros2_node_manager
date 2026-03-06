import { useState, useEffect, useRef, useCallback } from 'react';
import { createDiagnosticsSocket } from '../services/websocket';

const MAX_HISTORY = 50;

export function useDiagnostics(enabled = true) {
  const [diagnostics, setDiagnostics] = useState({});
  const [status, setStatus] = useState('disconnected');
  const wsRef = useRef(null);

  const clearDiagnostics = useCallback(() => {
    setDiagnostics({});
  }, []);

  useEffect(() => {
    if (!enabled) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setStatus('disconnected');
      setDiagnostics({});
      return;
    }

    setStatus('connecting');

    const ws = createDiagnosticsSocket(
      (msg) => {
        if (!msg.items || !Array.isArray(msg.items)) return;

        setDiagnostics((prev) => {
          const next = { ...prev };
          for (const item of msg.items) {
            const existing = next[item.name];
            const historyEntry = {
              level: item.level,
              message: item.message,
              timestamp: item.timestamp,
            };

            if (existing) {
              const history = [...existing.history, historyEntry];
              next[item.name] = {
                ...item,
                history: history.length > MAX_HISTORY
                  ? history.slice(-MAX_HISTORY)
                  : history,
              };
            } else {
              next[item.name] = {
                ...item,
                history: [historyEntry],
              };
            }
          }
          return next;
        });
      },
      (err) => {
        console.error('Diagnostics error:', err);
        setStatus('error');
      },
      () => {
        setStatus('connected');
      },
      () => {
        setStatus('disconnected');
        setDiagnostics({});
      }
    );

    wsRef.current = ws;

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    };
  }, [enabled]);

  return { diagnostics, status, clearDiagnostics };
}
