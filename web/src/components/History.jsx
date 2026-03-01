import { useState, useEffect } from 'react';
import { LogHistory } from './LogHistory';
import { AlertHistory } from './AlertHistory';

const SUB_TABS = [
  { id: 'logs', label: 'Log History' },
  { id: 'alerts', label: 'Alert History' },
];

export function History({ connected, initialTab }) {
  const [subTab, setSubTab] = useState(initialTab || 'logs');

  useEffect(() => {
    if (initialTab) setSubTab(initialTab);
  }, [initialTab]);

  if (!connected) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        <div className="text-center">
          <p className="mb-2">Not connected</p>
          <p className="text-sm">Connect to a server to view history</p>
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
              px-4 py-2.5 text-sm font-medium border-b-2 transition-colors
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
        {subTab === 'logs' && <LogHistory />}
        {subTab === 'alerts' && <AlertHistory />}
      </div>
    </div>
  );
}
