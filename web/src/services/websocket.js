/**
 * WebSocket client for real-time updates
 */

export function createNodesStatusSocket(onMessage, onError) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const url = `${protocol}//${host}/ws/nodes/status`;
  
  const ws = new WebSocket(url);
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (e) {
      console.error('Failed to parse WebSocket message:', e);
    }
  };
  
  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
    if (onError) onError(error);
  };
  
  ws.onclose = () => {
    console.log('Nodes status WebSocket closed');
  };
  
  return ws;
}

export function createLogsSocket(nodeName, onMessage, onError, onConnected) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const path = nodeName.startsWith('/') ? nodeName.slice(1) : nodeName;
  const url = `${protocol}//${host}/ws/logs/${path}`;
  
  const ws = new WebSocket(url);
  
  ws.onopen = () => {
    console.log(`Logs WebSocket connected for ${nodeName}`);
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      
      if (data.type === 'connected' && onConnected) {
        onConnected(data.message);
      } else if (data.type === 'log') {
        onMessage(data);
      } else if (data.type === 'error' && onError) {
        onError(data.message);
      }
    } catch (e) {
      console.error('Failed to parse log message:', e);
    }
  };
  
  ws.onerror = (error) => {
    console.error('Logs WebSocket error:', error);
    if (onError) onError(error.message || 'WebSocket error');
  };
  
  ws.onclose = () => {
    console.log(`Logs WebSocket closed for ${nodeName}`);
  };

  return ws;
}

export function createUnifiedLogsSocket(onMessage, onError, onConnected) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const url = `${protocol}//${host}/ws/logs/all`;

  const ws = new WebSocket(url);

  ws.onopen = () => {
    console.log('Unified logs WebSocket connected');
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'connected' && onConnected) {
        onConnected(data.message);
      } else if (data.type === 'log') {
        onMessage(data);
      } else if (data.type === 'error' && onError) {
        onError(data.message);
      }
    } catch (e) {
      console.error('Failed to parse unified log message:', e);
    }
  };

  ws.onerror = (error) => {
    console.error('Unified logs WebSocket error:', error);
    if (onError) onError(error.message || 'WebSocket error');
  };

  ws.onclose = () => {
    console.log('Unified logs WebSocket closed');
  };

  return ws;
}

export function createDiagnosticsSocket(onMessage, onError, onConnected) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const url = `${protocol}//${host}/ws/diagnostics`;

  const ws = new WebSocket(url);

  ws.onopen = () => {
    console.log('Diagnostics WebSocket connected');
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'connected' && onConnected) {
        onConnected(data.message);
      } else if (data.type === 'diagnostics') {
        onMessage(data);
      } else if (data.type === 'error' && onError) {
        onError(data.message);
      }
    } catch (e) {
      console.error('Failed to parse diagnostics message:', e);
    }
  };

  ws.onerror = (error) => {
    console.error('Diagnostics WebSocket error:', error);
    if (onError) onError(error.message || 'WebSocket error');
  };

  ws.onclose = () => {
    console.log('Diagnostics WebSocket closed');
  };

  return ws;
}

export function createTopicHzSocket(onMessage, onError, onConnected) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const url = `${protocol}//${host}/ws/topics/hz`;

  const ws = new WebSocket(url);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'connected' && onConnected) {
        onConnected(data.message);
      } else if (data.type === 'hz_update') {
        onMessage(data);
      } else if (data.type === 'error' && onError) {
        onError(data.message);
      }
    } catch (e) {
      console.error('Failed to parse topic Hz message:', e);
    }
  };

  ws.onerror = (error) => {
    console.error('Topic Hz WebSocket error:', error);
    if (onError) onError(error.message || 'WebSocket error');
  };

  ws.onclose = () => {
    console.log('Topic Hz WebSocket closed');
  };

  return ws;
}

export function createTopicEchoSocket(groupId, onMessage, onError, onConnected) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const url = `${protocol}//${host}/ws/topics/echo/${groupId}`;

  const ws = new WebSocket(url);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'connected' && onConnected) {
        onConnected(data);
      } else if (data.type === 'echo') {
        onMessage(data);
      } else if (data.type === 'error' && onError) {
        onError(data.message);
      }
    } catch (e) {
      console.error('Failed to parse topic echo message:', e);
    }
  };

  ws.onerror = (error) => {
    console.error('Topic Echo WebSocket error:', error);
    if (onError) onError(error.message || 'WebSocket error');
  };

  ws.onclose = () => {
    console.log(`Topic Echo WebSocket closed for group ${groupId}`);
  };

  return ws;
}
