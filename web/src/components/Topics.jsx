import { useRef, useEffect, useState } from 'react';
import { useTopicGroups } from '../hooks/useTopicGroups';
import { useTopicEcho } from '../hooks/useTopicEcho';
import { toggleGroupHz } from '../services/api';
import { TopicTree } from './TopicTree';
import { JsonView } from './JsonView';

function HzBadge({ hz }) {
  if (hz === null || hz === undefined) {
    return <span className="text-gray-500 text-xs font-mono">--</span>;
  }
  const color = hz > 0 ? 'text-green-400' : 'text-red-400';
  return <span className={`${color} text-xs font-mono`}>{hz.toFixed(1)} Hz</span>;
}

function shortTopicName(topic, prefix) {
  if (prefix && topic.startsWith(prefix)) {
    return topic.slice(prefix.length);
  }
  return topic;
}

function computeCommonPrefix(topics) {
  if (!topics || topics.length === 0) return '';
  const parts0 = topics[0].split('/');
  let common = 0;
  for (let i = 0; i < parts0.length - 1; i++) {
    if (topics.every(t => t.split('/')[i] === parts0[i])) {
      common = i + 1;
    } else {
      break;
    }
  }
  if (common <= 1) return ''; // just "/" — not useful
  return parts0.slice(0, common).join('/') + '/';
}

function GroupCard({ group, onHz, onEcho, isEchoing }) {
  const topicNames = group.topics.map(t => t.topic);
  const prefix = computeCommonPrefix(topicNames);

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-200">{group.name}</h3>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => onHz(group.id)}
            className={`
              px-2.5 py-1 text-xs rounded transition-colors
              ${group.active
                ? 'bg-blue-600 hover:bg-blue-700 text-white'
                : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
              }
            `}
          >
            Hz {group.active ? 'On' : 'Off'}
          </button>
          <button
            onClick={() => onEcho(group.id, group.name)}
            className={`
              px-2.5 py-1 text-xs rounded transition-colors
              ${isEchoing
                ? 'bg-red-600 hover:bg-red-700 text-white'
                : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
              }
            `}
          >
            {isEchoing ? 'Stop' : 'Echo'}
          </button>
        </div>
      </div>

      {/* Common prefix */}
      {prefix && (
        <div className="text-[10px] text-gray-500 font-mono mb-2 truncate" title={prefix}>
          {prefix}
        </div>
      )}

      {/* Topics list */}
      <div className="space-y-1.5">
        {group.topics.map(({ topic, hz }) => (
          <div key={topic} className="flex items-center justify-between gap-2">
            <span className="text-xs text-gray-400 font-mono truncate" title={topic}>
              {shortTopicName(topic, prefix)}
            </span>
            {group.active ? (
              <HzBadge hz={hz} />
            ) : (
              <span className="text-gray-600 text-xs font-mono">--</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function EchoPanel({ groupName, messages, paused, onTogglePause, onClear, onClose }) {
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
      {/* Resize handle */}
      <div
        onMouseDown={handleDragStart}
        className="h-1.5 cursor-row-resize bg-gray-700 hover:bg-blue-500 transition-colors flex-shrink-0"
      />
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700 flex-shrink-0">
        <span className="text-sm text-gray-300">
          Echo: <span className="text-blue-400">{groupName}</span>
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

      {/* Messages */}
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
            <div className="text-cyan-400 text-[10px] mb-0.5">
              [{msg.topic}]
            </div>
            {msg.format === 'json' ? (
              <div className="text-gray-300 leading-tight">
                <JsonView data={msg.data} />
              </div>
            ) : (
              <pre className="text-gray-300 whitespace-pre-wrap leading-tight">{msg.data}</pre>
            )}
            {idx < messages.length - 1 && (
              <div className="text-gray-600 mt-0.5">---</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function GroupsView({ connected }) {
  const { groups, status: hzStatus, toggleGroupActive } = useTopicGroups(connected);
  const echo = useTopicEcho();

  const handleHz = async (groupId) => {
    toggleGroupActive(groupId);
    try {
      await toggleGroupHz(groupId);
    } catch (e) {
      console.error('Failed to toggle Hz:', e);
      toggleGroupActive(groupId);
    }
  };

  const handleEcho = (groupId, groupName) => {
    if (echo.echoGroupId === groupId) {
      echo.stopEcho();
    } else {
      echo.startEcho(groupId, groupName);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-200">Topic Groups</h2>
          <span className={`text-xs ${
            hzStatus === 'connected' ? 'text-green-400' :
            hzStatus === 'connecting' ? 'text-yellow-400' :
            'text-gray-500'
          }`}>
            {hzStatus === 'connected' ? 'Live' :
             hzStatus === 'connecting' ? 'Connecting...' :
             'Disconnected'}
          </span>
        </div>

        {groups.length === 0 && hzStatus === 'connected' && (
          <div className="text-gray-500 text-center py-8">
            No topic groups configured. Edit config/topic_groups.yaml to add groups.
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {groups.map((group) => (
            <GroupCard
              key={group.id}
              group={group}
              onHz={handleHz}
              onEcho={handleEcho}
              isEchoing={echo.echoGroupId === group.id}
            />
          ))}
        </div>
      </div>

      {echo.echoGroupId && (
        <EchoPanel
          groupName={echo.echoGroupName}
          messages={echo.messages}
          paused={echo.paused}
          onTogglePause={echo.togglePause}
          onClear={echo.clearMessages}
          onClose={echo.stopEcho}
        />
      )}
    </div>
  );
}

const SUB_TABS = [
  { id: 'groups', label: 'Groups' },
  { id: 'tree', label: 'Tree' },
];

export function Topics({ connected }) {
  const [subTab, setSubTab] = useState('groups');

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
      {/* Sub-tab bar */}
      <div className="flex items-center border-b border-gray-700 px-4 flex-shrink-0">
        {SUB_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setSubTab(tab.id)}
            className={`
              px-4 py-2.5 text-sm font-medium border-b-2 transition-colors select-none
              ${subTab === tab.id
                ? 'text-blue-400 border-blue-400'
                : 'text-gray-400 border-transparent hover:text-gray-200 hover:border-gray-500'
              }
            `}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {subTab === 'groups' && <GroupsView connected={connected} />}
        {subTab === 'tree' && <TopicTree connected={connected} />}
      </div>
    </div>
  );
}
