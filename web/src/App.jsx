import { useState, useCallback, useEffect, useRef } from 'react';
import { useServer } from './hooks/useServer';
import { useNodes } from './hooks/useNodes';
import { StatusBar } from './components/StatusBar';
import { NodeTree } from './components/NodeTree';
import { NodeDetailPanel } from './components/NodeDetailPanel';
import { LogPanel } from './components/LogPanel';
import { HorizontalResizer, VerticalResizer } from './components/Resizer';
import { useAlerts } from './hooks/useAlerts';
import { ToastContainer } from './components/ToastContainer';
import { ActivityBar } from './components/ActivityBar';
import { SystemMonitor } from './components/SystemMonitor';

// Min/max constraints
const MIN_TREE_WIDTH = 200;
const MAX_TREE_WIDTH = 600;
const MIN_LOG_HEIGHT = 100;
const MAX_LOG_HEIGHT = 500;
const DEFAULT_TREE_WIDTH = 320;
const DEFAULT_LOG_HEIGHT = 256;
const ACTIVITY_BAR_WIDTH = 48;

function App() {
  const server = useServer();
  const nodes = useNodes({ onDisconnect: server.handleServerDisconnected });

  useAlerts(server.connected);

  // Refresh nodes when server connection changes to connected
  const wasConnected = useRef(server.connected);
  useEffect(() => {
    if (server.connected && !wasConnected.current) {
      nodes.refresh();
    }
    wasConnected.current = server.connected;
  }, [server.connected, nodes.refresh]);

  const [activeSection, setActiveSection] = useState('nodes');
  const [selectedNode, setSelectedNode] = useState(null);
  const [logNode, setLogNode] = useState(null);

  // Panel sizes
  const [treeWidth, setTreeWidth] = useState(DEFAULT_TREE_WIDTH);
  const [logHeight, setLogHeight] = useState(DEFAULT_LOG_HEIGHT);

  const handleShowLogs = (nodeName) => {
    setLogNode(nodeName);
  };

  const handleCloseLogs = () => {
    setLogNode(null);
  };

  const handleTreeResize = useCallback((clientX) => {
    const newWidth = clientX - ACTIVITY_BAR_WIDTH;
    setTreeWidth(Math.min(MAX_TREE_WIDTH, Math.max(MIN_TREE_WIDTH, newWidth)));
  }, []);

  const handleLogResize = useCallback((newHeight) => {
    setLogHeight(Math.min(MAX_LOG_HEIGHT, Math.max(MIN_LOG_HEIGHT, newHeight)));
  }, []);

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white select-none">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-700 bg-gray-800 flex-shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-bold text-blue-400">ROS2 Node Manager</h1>

          {server.connected && server.currentServer && (
            <>
              <span className="text-green-400 text-sm">● {server.currentServer.name}</span>
              <button
                onClick={server.disconnect}
                disabled={server.loading}
                className="px-2 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded disabled:opacity-50"
              >
                Disconnect
              </button>
            </>
          )}
          {!server.connected && !server.loading && (
            <>
              <span className="text-red-400 text-sm">● Not connected</span>
              <button
                onClick={() => server.servers[0] && server.connect(server.servers[0].id)}
                disabled={!server.servers.length}
                className="px-2 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded disabled:opacity-50"
              >
                Connect
              </button>
            </>
          )}
          {server.loading && (
            <span className="text-yellow-400 text-sm">● Connecting...</span>
          )}
        </div>

        <div className="flex items-center gap-4">
          {activeSection === 'nodes' && (
            <>
              <StatusBar
                total={nodes.counts.total}
                active={nodes.counts.active}
                inactive={nodes.counts.inactive}
              />

              <button
                onClick={() => nodes.refresh()}
                disabled={nodes.loading}
                className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white rounded text-sm disabled:opacity-50"
              >
                {nodes.loading ? 'Loading...' : 'Refresh'}
              </button>
            </>
          )}
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Activity Bar */}
        <ActivityBar
          activeSection={activeSection}
          onSectionChange={setActiveSection}
        />

        {/* Nodes Section */}
        {activeSection === 'nodes' && (
          <>
            {/* Node Tree */}
            <div
              className="flex flex-col border-r border-gray-700"
              style={{ width: treeWidth }}
            >
              {server.connected ? (
                <NodeTree
                  nodes={nodes.nodes}
                  selectedNode={selectedNode}
                  onSelectNode={setSelectedNode}
                />
              ) : (
                <div className="flex-1 flex items-center justify-center text-gray-500">
                  <div className="text-center">
                    <p className="mb-2">Not connected</p>
                    <p className="text-sm">Select a server to connect</p>
                  </div>
                </div>
              )}
            </div>

            {/* Horizontal Resizer */}
            <HorizontalResizer onResize={handleTreeResize} />

            {/* Detail Panel + Logs */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Detail Panel */}
              <div className="flex-1 overflow-hidden">
                {server.connected ? (
                  <NodeDetailPanel
                    nodeName={selectedNode}
                    onShowLogs={handleShowLogs}
                    onNodeChanged={() => nodes.refresh()}
                  />
                ) : (
                  <div className="h-full flex items-center justify-center text-gray-500">
                    Connect to a server to view nodes
                  </div>
                )}
              </div>

              {/* Log Panel with Resizer */}
              {logNode && (
                <>
                  <VerticalResizer onResize={handleLogResize} />
                  <LogPanel
                    nodeName={logNode}
                    onClose={handleCloseLogs}
                    height={logHeight}
                  />
                </>
              )}
            </div>
          </>
        )}

        {/* System Section */}
        {activeSection === 'system' && (
          <div className="flex-1 overflow-hidden">
            <SystemMonitor connected={server.connected} />
          </div>
        )}
      </div>

      {/* Footer */}
      <footer className="px-4 py-2 border-t border-gray-700 bg-gray-800 text-xs text-gray-500 flex-shrink-0">
        <div className="flex items-center justify-between">
          <span>ROS2 Node Manager v0.2.0</span>
          {server.error && (
            <span className="text-red-400">Error: {server.error}</span>
          )}
          {nodes.error && (
            <span className="text-red-400">Nodes Error: {nodes.error}</span>
          )}
        </div>
      </footer>
      <ToastContainer />
    </div>
  );
}

export default App;
