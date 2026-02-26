import { useState, useRef, useCallback } from 'react';
import { createTopicEchoSocket } from '../services/websocket';

const MAX_MESSAGES = 500;

export function useTopicEcho() {
  const [messages, setMessages] = useState([]);
  const [echoGroupId, setEchoGroupId] = useState(null);
  const [echoGroupName, setEchoGroupName] = useState(null);
  const [echoStatus, setEchoStatus] = useState('disconnected');
  const [paused, setPaused] = useState(false);
  const wsRef = useRef(null);
  const pausedRef = useRef(false);

  const startEcho = useCallback((groupId, groupName) => {
    // Close previous connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setMessages([]);
    setEchoGroupId(groupId);
    setEchoGroupName(groupName);
    setPaused(false);
    pausedRef.current = false;
    setEchoStatus('connecting');

    const ws = createTopicEchoSocket(
      groupId,
      (msg) => {
        if (pausedRef.current) return;
        setMessages((prev) => {
          const next = [...prev, msg];
          return next.length > MAX_MESSAGES ? next.slice(-MAX_MESSAGES) : next;
        });
      },
      (err) => {
        console.error('Topic Echo error:', err);
        setEchoStatus('error');
      },
      () => {
        setEchoStatus('connected');
      }
    );

    wsRef.current = ws;
  }, []);

  const stopEcho = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setEchoGroupId(null);
    setEchoGroupName(null);
    setEchoStatus('disconnected');
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  const togglePause = useCallback(() => {
    setPaused((prev) => {
      pausedRef.current = !prev;
      return !prev;
    });
  }, []);

  return {
    messages,
    echoGroupId,
    echoGroupName,
    echoStatus,
    paused,
    startEcho,
    stopEcho,
    clearMessages,
    togglePause,
  };
}
