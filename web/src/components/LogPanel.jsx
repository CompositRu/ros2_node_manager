import { useState, useEffect, useRef } from 'react';
import { createLogsSocket } from '../services/websocket';

export function LogPanel({ nodeName, onClose, height = 256 }) {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('connecting'); // 'connecting' | 'connected' | 'error'
  const [errorMsg, setErrorMsg] = useState(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  
  const logsEndRef = useRef(null);
  const wsRef = useRef(null);
  const pausedLogsRef = useRef([]);

  useEffect(() => {
    if (!nodeName) return;
    
    // Reset state for new node
    setLogs([]);
    setStatus('connecting');
    setErrorMsg(null);
    pausedLogsRef.current = [];
    
    // Close previous WebSocket
    if (wsRef.current) {
      wsRef.current.close();
    }
    
    const ws = createLogsSocket(
      nodeName,
      (msg) => {
        // Clear error on successful message
        if (status === 'error') {
          setStatus('connected');
          setErrorMsg(null);
        }
        
        if (paused) {
          pausedLogsRef.current.push(msg);
        } else {
          setLogs(prev => [...prev.slice(-999), msg]);
        }
      },
      (err) => {
        // Only set error if we haven't connected yet
        if (status === 'connecting') {
          setStatus('error');
          setErrorMsg(err);
        }
      },
      () => {
        setStatus('connected');
        setErrorMsg(null);
      }
    );
    
    wsRef.current = ws;
    
    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    };
  }, [nodeName]);

  useEffect(() => {
    if (!paused && pausedLogsRef.current.length > 0) {
      setLogs(prev => [...prev, ...pausedLogsRef.current].slice(-1000));
      pausedLogsRef.current = [];
    }
  }, [paused]);

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  if (!nodeName) return null;

  const clearLogs = () => {
    setLogs([]);
    pausedLogsRef.current = [];
  };

  const getLevelClass = (level) => {
    switch (level?.toUpperCase()) {
      case 'DEBUG': return 'log-debug';
      case 'INFO': return 'log-info';
      case 'WARN': return 'log-warn';
      case 'ERROR': return 'log-error';
      case 'FATAL': return 'log-fatal';
      default: return 'text-gray-300';
    }
  };

  const formatTimestamp = (ts) => {
    try {
      const date = new Date(ts);
      return date.toLocaleTimeString('en-US', { hour12: false });
    } catch {
      return ts;
    }
  };

  const getStatusIndicator = () => {
    switch (status) {
      case 'connecting':
        return <span className="text-yellow-400 text-xs">● Connecting...</span>;
      case 'connected':
        return <span className="text-green-400 text-xs">● Connected</span>;
      case 'error':
        return <span className="text-red-400 text-xs">● Error: {errorMsg}</span>;
      default:
        return null;
    }
  };

  return (
    <div 
      className="flex flex-col border-t border-gray-700 bg-gray-900"
      style={{ height }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700 bg-gray-800">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="text-gray-300 font-medium flex-shrink-0">Logs:</span>
          <span className="text-blue-400 text-sm truncate" title={nodeName}>
            {nodeName}
          </span>
          {getStatusIndicator()}
        </div>
        
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => setPaused(!paused)}
            className={`px-2 py-1 text-xs rounded ${
              paused ? 'bg-yellow-600 text-white' : 'bg-gray-600 text-gray-300 hover:bg-gray-500'
            }`}
          >
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          
          <button
            onClick={clearLogs}
            className="px-2 py-1 text-xs bg-gray-600 text-gray-300 hover:bg-gray-500 rounded"
          >
            Clear
          </button>
          
          <label className="flex items-center gap-1 text-xs text-gray-400">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded"
            />
            Auto-scroll
          </label>
          
          <button
            onClick={onClose}
            className="px-2 py-1 text-gray-400 hover:text-white"
          >
            ✕
          </button>
        </div>
      </div>
      
      {/* Logs */}
      <div className="flex-1 overflow-auto p-2 font-mono text-xs">
        {logs.length === 0 && (
          <div className="text-gray-500 text-center py-4">
            {status === 'connecting' ? 'Connecting...' : 
             status === 'connected' ? 'Waiting for logs...' : 
             'Connection failed'}
          </div>
        )}
        
        {logs.map((log, idx) => (
          <div key={idx} className="flex gap-2 hover:bg-gray-800/50 px-1">
            <span className="text-gray-500 flex-shrink-0">
              [{formatTimestamp(log.timestamp)}]
            </span>
            <span className={`flex-shrink-0 w-12 ${getLevelClass(log.level)}`}>
              {log.level}
            </span>
            <span className="text-gray-300 break-all">
              {log.message}
            </span>
          </div>
        ))}
        
        <div ref={logsEndRef} />
      </div>
      
      {paused && pausedLogsRef.current.length > 0 && (
        <div className="px-4 py-1 bg-yellow-900/50 text-yellow-300 text-xs">
          ⏸ Paused - {pausedLogsRef.current.length} new messages buffered
        </div>
      )}
    </div>
  );
}