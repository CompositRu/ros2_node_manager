/**
 * API client for ROS2 Node Manager
 */

const API_BASE = '/api';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Request failed');
  }
  
  return response.json();
}

// === Servers API ===

export async function getServers() {
  return request('/servers');
}

export async function getCurrentServer() {
  return request('/servers/current');
}

export async function connectToServer(serverId, password = null) {
  return request('/servers/connect', {
    method: 'POST',
    body: JSON.stringify({ server_id: serverId, password }),
  });
}

export async function disconnectFromServer() {
  return request('/servers/disconnect', { method: 'POST' });
}

// === Nodes API ===

export async function getNodes(refresh = true) {
  return request(`/nodes?refresh=${refresh}`);
}

export async function getNodeDetail(nodeName) {
  // Remove leading slash for URL
  const path = nodeName.startsWith('/') ? nodeName.slice(1) : nodeName;
  return request(`/nodes/${path}`);
}

export async function shutdownNode(nodeName, force = false) {
  const path = nodeName.startsWith('/') ? nodeName.slice(1) : nodeName;
  return request(`/nodes/${path}/shutdown`, {
    method: 'POST',
    body: JSON.stringify({ force }),
  });
}

// === Health ===

export async function getHealth() {
  return request('/health');
}
