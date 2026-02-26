import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { getTopicList } from '../services/api';
import { createSingleTopicEchoSocket, createSingleTopicHzSocket } from '../services/websocket';

const MAX_ECHO_MESSAGES = 500;

function HzBadge({ hz }) {
  if (hz === null || hz === undefined) return null;
  const color = hz > 0 ? 'text-green-400' : 'text-red-400';
  return <span className={`${color} text-xs font-mono`}>{hz.toFixed(1)} Hz</span>;
}

function buildTopicTree(topics) {
  const root = { children: {}, topics: [], count: 0 };

  for (const topic of topics) {
    const parts = topic.name.split('/').filter(Boolean);
    let current = root;

    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!current.children[part]) {
        current.children[part] = { children: {}, topics: [], count: 0 };
      }
      current = current.children[part];
    }

    current.topics.push(topic);
  }

  function calcCounts(node) {
    let count = node.topics.length;
    for (const child of Object.values(node.children)) {
      calcCounts(child);
      count += child.count;
    }
    node.count = count;
  }
  calcCounts(root);

  return root;
}

function collectAllPaths(node, path = '') {
  const paths = [];
  for (const [name, child] of Object.entries(node.children)) {
    const fullPath = path ? `${path}/${name}` : `/${name}`;
    paths.push(fullPath);
    paths.push(...collectAllPaths(child, fullPath));
  }
  return paths;
}

function TopicTreeNode({ name, data, path, level, expandedPaths, onTogglePath,
  selectedTopic, onSelectTopic, echoTopic, hzTopic, hzValues, onEcho, onHz }) {
  const fullPath = path ? `${path}/${name}` : `/${name}`;
  const isExpanded = expandedPaths.has(fullPath);
  const hasChildren = Object.keys(data.children).length > 0 || data.topics.length > 0;

  return (
    <div className="select-none">
      <div
        className="flex items-center gap-1 py-0.5 px-1 hover:bg-gray-700 rounded cursor-pointer"
        onClick={() => onTogglePath(fullPath)}
        style={{ paddingLeft: `${level * 12}px` }}
      >
        {hasChildren ? (
          <span className="text-gray-500 w-4 text-center text-[10px]">
            {isExpanded ? '\u25BC' : '\u25B6'}
          </span>
        ) : (
          <span className="w-4" />
        )}
        <span className="text-blue-400 text-sm font-mono">/{name}</span>
        <span className="text-gray-500 text-xs">({data.count})</span>
      </div>

      {isExpanded && (
        <div>
          {Object.entries(data.children)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([childName, childData]) => (
              <TopicTreeNode
                key={childName}
                name={childName}
                data={childData}
                path={fullPath}
                level={level + 1}
                expandedPaths={expandedPaths}
                onTogglePath={onTogglePath}
                selectedTopic={selectedTopic}
                onSelectTopic={onSelectTopic}
                echoTopic={echoTopic}
                hzTopic={hzTopic}
                hzValues={hzValues}
                onEcho={onEcho}
                onHz={onHz}
              />
            ))}

          {data.topics
            .sort((a, b) => a.name.localeCompare(b.name))
            .map(topic => {
              const leafName = topic.name.split('/').pop();
              const isSelected = selectedTopic === topic.name;
              const hzValue = hzValues[topic.name];
              return (
                <div
                  key={topic.name}
                  className={`flex items-center gap-2 py-0.5 px-1 rounded cursor-pointer ${
                    isSelected ? 'bg-blue-900 hover:bg-blue-800' : 'hover:bg-gray-700'
                  }`}
                  style={{ paddingLeft: `${(level + 1) * 12 + 16}px` }}
                  onClick={() => onSelectTopic(isSelected ? null : topic.name)}
                  title={topic.name}
                >
                  <span className="text-green-400 text-xs font-mono">#</span>
                  <span className="text-gray-200 text-sm font-mono truncate">{leafName}</span>
                  <div className="ml-auto flex items-center gap-1.5 flex-shrink-0">
                    {hzValue !== undefined && <HzBadge hz={hzValue} />}
                    {isSelected && (
                      <>
                        <button
                          onClick={(e) => { e.stopPropagation(); onHz(topic.name); }}
                          className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                            hzTopic === topic.name
                              ? 'bg-blue-600 hover:bg-blue-700 text-white'
                              : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                          }`}
                        >
                          Hz
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); onEcho(topic.name); }}
                          className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                            echoTopic === topic.name
                              ? 'bg-red-600 hover:bg-red-700 text-white'
                              : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                          }`}
                        >
                          {echoTopic === topic.name ? 'Stop' : 'Echo'}
                        </button>
                      </>
                    )}
                    {!isSelected && hzValue === undefined && topic.type && (
                      <span className="text-gray-500 text-xs truncate max-w-[220px] flex-shrink-0" title={topic.type}>
                        {topic.type}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}

function EchoPanel({ topicName, messages, paused, onTogglePause, onClear, onClose }) {
  const listRef = useRef(null);
  const autoScrollRef = useRef(true);
  const [height, setHeight] = useState(300);
  const draggingRef = useRef(false);
  const startYRef = useRef(0);
  const startHeightRef = useRef(0);

  useEffect(() => {
    if (autoScrollRef.current && listRef.current && !paused) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, paused]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    autoScrollRef.current = scrollHeight - scrollTop - clientHeight < 40;
  };

  const handleDragStart = (e) => {
    e.preventDefault();
    draggingRef.current = true;
    startYRef.current = e.clientY;
    startHeightRef.current = height;

    const onMove = (ev) => {
      if (!draggingRef.current) return;
      const delta = startYRef.current - ev.clientY;
      setHeight(Math.max(120, Math.min(800, startHeightRef.current + delta)));
    };
    const onUp = () => {
      draggingRef.current = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  return (
    <div className="bg-gray-800 border-t border-gray-700 flex flex-col" style={{ height }}>
      <div
        onMouseDown={handleDragStart}
        className="h-1.5 cursor-row-resize bg-gray-700 hover:bg-blue-500 transition-colors flex-shrink-0"
      />
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700 flex-shrink-0">
        <span className="text-sm text-gray-300">
          Echo: <span className="text-blue-400 font-mono">{topicName}</span>
          <span className="text-gray-500 ml-2">({messages.length})</span>
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onTogglePause}
            className={`px-2 py-0.5 text-xs rounded ${
              paused
                ? 'bg-green-600 hover:bg-green-700 text-white'
                : 'bg-yellow-600 hover:bg-yellow-700 text-white'
            }`}
          >
            {paused ? 'Resume' : 'Pause'}
          </button>
          <button
            onClick={onClear}
            className="px-2 py-0.5 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            Clear
          </button>
          <button
            onClick={onClose}
            className="px-2 py-0.5 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            Close
          </button>
        </div>
      </div>

      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-2 font-mono text-xs select-text"
      >
        {messages.length === 0 && (
          <div className="text-gray-500 text-center py-8">Waiting for messages...</div>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} className="mb-2">
            <pre className="text-gray-300 whitespace-pre-wrap leading-tight">{msg.data}</pre>
            {idx < messages.length - 1 && (
              <div className="text-gray-600 mt-0.5">---</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function TopicTree({ connected }) {
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedPaths, setExpandedPaths] = useState(new Set(['/']));
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [filter, setFilter] = useState('');

  // Echo state
  const [echoTopic, setEchoTopic] = useState(null);
  const [echoMessages, setEchoMessages] = useState([]);
  const [echoPaused, setEchoPaused] = useState(false);
  const echoWsRef = useRef(null);
  const echoPausedRef = useRef(false);

  // Hz state
  const [hzTopic, setHzTopic] = useState(null);
  const [hzValues, setHzValues] = useState({});
  const hzWsRef = useRef(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (echoWsRef.current) echoWsRef.current.close();
      if (hzWsRef.current) hzWsRef.current.close();
    };
  }, []);

  const fetchTopics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTopicList();
      setTopics(data.topics || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (connected) fetchTopics();
  }, [connected, fetchTopics]);

  const filteredTopics = useMemo(() => {
    if (!filter) return topics;
    const lower = filter.toLowerCase();
    return topics.filter(t =>
      t.name.toLowerCase().includes(lower) ||
      t.type.toLowerCase().includes(lower)
    );
  }, [topics, filter]);

  const tree = useMemo(() => buildTopicTree(filteredTopics), [filteredTopics]);

  const togglePath = useCallback((path) => {
    setExpandedPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    const allPaths = collectAllPaths(tree);
    setExpandedPaths(new Set(['/', ...allPaths]));
  }, [tree]);

  const collapseAll = useCallback(() => {
    setExpandedPaths(new Set());
  }, []);

  // Echo handlers
  const handleEcho = useCallback((topicName) => {
    if (echoTopic === topicName) {
      if (echoWsRef.current) {
        echoWsRef.current.close();
        echoWsRef.current = null;
      }
      setEchoTopic(null);
      return;
    }

    if (echoWsRef.current) {
      echoWsRef.current.close();
    }

    setEchoMessages([]);
    setEchoTopic(topicName);
    setEchoPaused(false);
    echoPausedRef.current = false;

    const ws = createSingleTopicEchoSocket(
      topicName,
      (msg) => {
        if (echoPausedRef.current) return;
        setEchoMessages(prev => {
          const next = [...prev, msg];
          return next.length > MAX_ECHO_MESSAGES ? next.slice(-MAX_ECHO_MESSAGES) : next;
        });
      },
      (err) => console.error('Single topic echo error:', err),
      () => {}
    );

    echoWsRef.current = ws;
  }, [echoTopic]);

  const stopEcho = useCallback(() => {
    if (echoWsRef.current) {
      echoWsRef.current.close();
      echoWsRef.current = null;
    }
    setEchoTopic(null);
  }, []);

  const clearEchoMessages = useCallback(() => {
    setEchoMessages([]);
  }, []);

  const toggleEchoPause = useCallback(() => {
    setEchoPaused(prev => {
      echoPausedRef.current = !prev;
      return !prev;
    });
  }, []);

  // Hz handlers
  const handleHz = useCallback((topicName) => {
    if (hzTopic === topicName) {
      if (hzWsRef.current) {
        hzWsRef.current.close();
        hzWsRef.current = null;
      }
      setHzTopic(null);
      setHzValues(prev => {
        const next = { ...prev };
        delete next[topicName];
        return next;
      });
      return;
    }

    if (hzWsRef.current) {
      hzWsRef.current.close();
    }

    setHzValues({});
    setHzTopic(topicName);

    const ws = createSingleTopicHzSocket(
      topicName,
      (msg) => {
        setHzValues({ [msg.topic]: msg.hz });
      },
      (err) => console.error('Single topic Hz error:', err),
      () => {}
    );

    hzWsRef.current = ws;
  }, [hzTopic]);

  if (!connected) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        <div className="text-center">
          <p className="mb-2">Not connected</p>
          <p className="text-sm">Connect to a server to view topics</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-700 flex-shrink-0">
        <span className="text-sm font-medium text-gray-300">Topics</span>
        <span className="text-xs text-gray-500">({filteredTopics.length}{filter ? `/${topics.length}` : ''})</span>
        <div className="flex-1" />
        <button
          onClick={fetchTopics}
          disabled={loading}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700 transition-colors disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
        <button
          onClick={expandAll}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700 transition-colors"
        >
          Expand
        </button>
        <button
          onClick={collapseAll}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700 transition-colors"
        >
          Collapse
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-1.5 border-b border-gray-700 flex-shrink-0">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter topics or types..."
          className="w-full bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:border-blue-400 focus:outline-none placeholder-gray-500"
        />
      </div>

      {/* Error */}
      {error && (
        <div className="px-3 py-2 text-red-400 text-sm bg-red-900/20 border-b border-gray-700">
          {error}
        </div>
      )}

      {/* Tree */}
      <div className="flex-1 overflow-y-auto p-2 font-mono text-sm">
        {loading && topics.length === 0 && (
          <div className="text-gray-500 text-center py-8">Loading topics...</div>
        )}
        {!loading && topics.length === 0 && (
          <div className="text-gray-500 text-center py-8">No topics found</div>
        )}
        {filteredTopics.length === 0 && topics.length > 0 && filter && (
          <div className="text-gray-500 text-center py-8">No topics matching "{filter}"</div>
        )}
        {Object.entries(tree.children)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([name, data]) => (
            <TopicTreeNode
              key={name}
              name={name}
              data={data}
              path=""
              level={0}
              expandedPaths={expandedPaths}
              onTogglePath={togglePath}
              selectedTopic={selectedTopic}
              onSelectTopic={setSelectedTopic}
              echoTopic={echoTopic}
              hzTopic={hzTopic}
              hzValues={hzValues}
              onEcho={handleEcho}
              onHz={handleHz}
            />
          ))}
        {/* Root-level topics (unlikely but handle) */}
        {tree.topics.map(topic => (
          <div
            key={topic.name}
            className={`flex items-center gap-2 py-0.5 px-1 rounded cursor-pointer ${
              selectedTopic === topic.name ? 'bg-blue-900' : 'hover:bg-gray-700'
            }`}
            onClick={() => setSelectedTopic(selectedTopic === topic.name ? null : topic.name)}
          >
            <span className="text-green-400 text-xs">#</span>
            <span className="text-gray-200 truncate">{topic.name}</span>
            {topic.type && (
              <span className="text-gray-500 text-xs ml-auto truncate max-w-[220px]">{topic.type}</span>
            )}
          </div>
        ))}
      </div>

      {/* Echo Panel */}
      {echoTopic && (
        <EchoPanel
          topicName={echoTopic}
          messages={echoMessages}
          paused={echoPaused}
          onTogglePause={toggleEchoPause}
          onClear={clearEchoMessages}
          onClose={stopEcho}
        />
      )}
    </div>
  );
}
