/**
 * useAlerts - хук для подключения к WebSocket алертов
 * 
 * Автоматически подключается при монтировании,
 * реконнектится при обрыве связи.
 */

import { useEffect, useRef, useCallback } from 'react';
import { useNotifications } from './useNotifications';

const WS_RECONNECT_DELAY = 5000;

export function useAlerts(enabled = true) {
  const { addNotification } = useNotifications();
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const isConnectingRef = useRef(false);

  const connect = useCallback(() => {
    // Prevent multiple simultaneous connections
    if (isConnectingRef.current || !enabled) return;
    isConnectingRef.current = true;

    // Clear pending reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    // Build WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const port = window.location.port || (protocol === 'wss:' ? '443' : '80');
    
    // In development, backend is on port 8080
    const wsPort = import.meta.env.DEV ? '8080' : port;
    const url = `${protocol}//${host}:${wsPort}/ws/alerts`;

    console.log('Connecting to alerts WebSocket:', url);
    
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('Alerts WebSocket connected');
        isConnectingRef.current = false;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'alert') {
            addNotification({
              severity: data.severity,
              title: data.title,
              message: data.message,
              alertType: data.alert_type,
              details: data.details
            });
          } else if (data.type === 'error') {
            console.error('Alert service error:', data.message);
          }
        } catch (e) {
          console.error('Failed to parse alert message:', e);
        }
      };

      ws.onerror = (error) => {
        console.error('Alerts WebSocket error:', error);
        isConnectingRef.current = false;
      };

      ws.onclose = (event) => {
        console.log('Alerts WebSocket closed:', event.code, event.reason);
        isConnectingRef.current = false;
        wsRef.current = null;
        
        // Schedule reconnect
        if (enabled) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('Attempting to reconnect alerts WebSocket...');
            connect();
          }, WS_RECONNECT_DELAY);
        }
      };

    } catch (e) {
      console.error('Failed to create alerts WebSocket:', e);
      isConnectingRef.current = false;
      
      // Schedule reconnect
      if (enabled) {
        reconnectTimeoutRef.current = setTimeout(connect, WS_RECONNECT_DELAY);
      }
    }
  }, [enabled, addNotification]);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    if (enabled) {
      connect();
    }

    return () => {
      // Cleanup
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [enabled, connect]);

  // Return connection status (optional)
  return {
    isConnected: wsRef.current?.readyState === WebSocket.OPEN
  };
}
