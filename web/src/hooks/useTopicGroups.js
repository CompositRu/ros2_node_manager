import { useState, useEffect, useRef, useCallback } from 'react';
import { createTopicHzSocket } from '../services/websocket';

export function useTopicGroups(enabled = true) {
  const [groups, setGroups] = useState([]);
  const [status, setStatus] = useState('disconnected');
  const wsRef = useRef(null);

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

    const ws = createTopicHzSocket(
      (msg) => {
        if (msg.groups && Array.isArray(msg.groups)) {
          setGroups(msg.groups);
        }
      },
      (err) => {
        console.error('Topic Hz error:', err);
        setStatus('error');
      },
      () => {
        setStatus('connected');
      }
    );

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [enabled]);

  const toggleGroupActive = useCallback((groupId) => {
    setGroups(prev => prev.map(g =>
      g.id === groupId ? { ...g, active: !g.active } : g
    ));
  }, []);

  return { groups, status, toggleGroupActive };
}
