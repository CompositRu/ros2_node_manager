/**
 * useAlerts - hook for connecting to the alerts WebSocket
 *
 * Automatically connects on mount, reconnects on disconnect
 * using exponential backoff + jitter via createReconnectingSocket.
 */

import { useEffect, useRef } from 'react';
import { useNotifications } from './useNotifications';
import { createReconnectingSocket } from '../services/reconnectingSocket';

export function useAlerts(enabled = true) {
  const { addNotification } = useNotifications();
  const socketRef = useRef(null);
  const addNotificationRef = useRef(addNotification);

  // Keep ref in sync to avoid re-creating the socket when addNotification changes
  useEffect(() => {
    addNotificationRef.current = addNotification;
  }, [addNotification]);

  useEffect(() => {
    if (!enabled) return;

    // Build WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const port = window.location.port || (protocol === 'wss:' ? '443' : '80');

    // In development, backend is on port 8080
    const wsPort = import.meta.env.DEV ? '8080' : port;
    const url = `${protocol}//${host}:${wsPort}/ws/alerts`;

    const socket = createReconnectingSocket(url, {
      onMessage: (data) => {
        if (data.type === 'alert') {
          addNotificationRef.current({
            severity: data.severity,
            title: data.title,
            message: data.message,
            alertType: data.alert_type,
            details: data.details,
          });
        } else if (data.type === 'error') {
          console.error('Alert service error:', data.message);
        }
      },
      onConnected: () => {
        console.log('Alerts WebSocket connected');
      },
      onError: (err) => {
        console.error('Alerts WebSocket error:', err);
      },
    });

    socketRef.current = socket;

    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [enabled]);

  return {
    get isConnected() {
      return socketRef.current?.readyState === WebSocket.OPEN;
    },
  };
}
