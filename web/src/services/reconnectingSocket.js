/**
 * Creates a WebSocket with automatic reconnect using exponential backoff + jitter.
 *
 * @param {string} url - WebSocket URL
 * @param {Object} handlers - { onMessage, onError, onConnected, onClose }
 * @param {Object} [options] - { maxRetries: 20, baseDelay: 1000, maxDelay: 16000 }
 * @returns {{ close: () => void, readyState: number }} - call close() to permanently disconnect
 */
export function createReconnectingSocket(url, handlers, options = {}) {
  const { maxRetries = 20, baseDelay = 1000, maxDelay = 16000 } = options;
  const { onMessage, onError, onConnected, onClose } = handlers;

  let ws = null;
  let attempt = 0;
  let reconnectTimeout = null;
  let closed = false; // user called close()

  function connect() {
    if (closed) return;

    ws = new WebSocket(url);

    ws.onopen = () => {
      attempt = 0; // reset on successful connect
      if (onConnected) onConnected();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (onMessage) onMessage(data);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    ws.onerror = (error) => {
      console.error(`WebSocket error (${url}):`, error);
      if (onError) onError(error.message || 'WebSocket error');
    };

    ws.onclose = () => {
      if (closed) {
        if (onClose) onClose();
        return;
      }

      if (attempt < maxRetries) {
        // Exponential backoff with jitter (+-30%)
        const delay = Math.min(baseDelay * Math.pow(2, attempt), maxDelay);
        const jitter = delay * (0.7 + Math.random() * 0.6);
        attempt++;

        reconnectTimeout = setTimeout(connect, jitter);
      } else {
        console.error(`WebSocket ${url}: max retries (${maxRetries}) reached`);
        if (onError) onError(`Connection lost after ${maxRetries} retries`);
        if (onClose) onClose();
      }
    };
  }

  connect();

  return {
    close() {
      closed = true;
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
      }
      if (ws) {
        ws.close();
        ws = null;
      }
    },
    // Expose for debugging
    get readyState() {
      return ws ? ws.readyState : WebSocket.CLOSED;
    },
  };
}
