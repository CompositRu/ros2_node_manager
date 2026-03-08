/**
 * WebSocket client for real-time updates.
 * All factories use createReconnectingSocket for automatic reconnect
 * with exponential backoff + jitter.
 */

import { createReconnectingSocket } from './reconnectingSocket';

function wsUrl(path) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}

export function createNodesStatusSocket(onMessage, onError) {
  return createReconnectingSocket(wsUrl('/ws/nodes/status'), {
    onMessage,
    onError,
  });
}

export function createLogsSocket(nodeName, onMessage, onError, onConnected, onHistory) {
  const path = nodeName.startsWith('/') ? nodeName.slice(1) : nodeName;
  return createReconnectingSocket(wsUrl(`/ws/logs/${path}`), {
    onMessage: (data) => {
      if (data.type === 'connected' && onConnected) onConnected(data.message);
      else if (data.type === 'history' && onHistory) onHistory(data.logs);
      else if (data.type === 'log' && onMessage) onMessage(data);
      else if (data.type === 'error' && onError) onError(data.message);
    },
    onError,
  });
}

export function createUnifiedLogsSocket(onMessage, onError, onConnected, onHistory) {
  return createReconnectingSocket(wsUrl('/ws/logs/all'), {
    onMessage: (data) => {
      if (data.type === 'connected' && onConnected) onConnected(data.message);
      else if (data.type === 'history' && onHistory) onHistory(data.logs);
      else if (data.type === 'log' && onMessage) onMessage(data);
      else if (data.type === 'error' && onError) onError(data.message);
    },
    onError,
  });
}

export function createDiagnosticsSocket(onMessage, onError, onConnected, onClose) {
  return createReconnectingSocket(wsUrl('/ws/diagnostics'), {
    onMessage: (data) => {
      if (data.type === 'connected' && onConnected) onConnected(data.message);
      else if (data.type === 'diagnostics' && onMessage) onMessage(data);
      else if (data.type === 'error' && onError) onError(data.message);
    },
    onError,
    onClose,
  });
}

export function createTopicHzSocket(onMessage, onError, onConnected) {
  return createReconnectingSocket(wsUrl('/ws/topics/hz'), {
    onMessage: (data) => {
      if (data.type === 'connected' && onConnected) onConnected(data.message);
      else if (data.type === 'hz_update' && onMessage) onMessage(data);
      else if (data.type === 'error' && onError) onError(data.message);
    },
    onError,
  });
}

export function createSingleTopicEchoSocket(topicName, onMessage, onError, onConnected) {
  const path = topicName.startsWith('/') ? topicName.slice(1) : topicName;
  return createReconnectingSocket(wsUrl(`/ws/topics/echo-single/${path}`), {
    onMessage: (data) => {
      if (data.type === 'connected' && onConnected) onConnected(data);
      else if (data.type === 'echo' && onMessage) onMessage(data);
      else if (data.type === 'error' && onError) onError(data.message);
    },
    onError,
  });
}

export function createSingleTopicHzSocket(topicName, onMessage, onError, onConnected) {
  const path = topicName.startsWith('/') ? topicName.slice(1) : topicName;
  return createReconnectingSocket(wsUrl(`/ws/topics/hz-single/${path}`), {
    onMessage: (data) => {
      if (data.type === 'connected' && onConnected) onConnected(data);
      else if (data.type === 'hz' && onMessage) onMessage(data);
      else if (data.type === 'error' && onError) onError(data.message);
    },
    onError,
  });
}

export function createTopicEchoSocket(groupId, onMessage, onError, onConnected) {
  return createReconnectingSocket(wsUrl(`/ws/topics/echo/${groupId}`), {
    onMessage: (data) => {
      if (data.type === 'connected' && onConnected) onConnected(data);
      else if (data.type === 'echo' && onMessage) onMessage(data);
      else if (data.type === 'error' && onError) onError(data.message);
    },
    onError,
  });
}

// Re-export for direct use
export { createReconnectingSocket } from './reconnectingSocket';
