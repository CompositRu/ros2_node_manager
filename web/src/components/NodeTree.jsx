import { useState, useMemo } from 'react';
import { ContextMenu } from './ContextMenu';
import { ConfirmModal } from './ConfirmModal';
import * as api from '../services/api';

/**
 * Build tree structure from flat node list
 */
function buildTree(nodes) {
  const root = { children: {}, nodes: [], count: 0, activeCount: 0, lifecycleCount: 0 };
  
  for (const node of nodes) {
    const parts = node.name.split('/').filter(Boolean);
    let current = root;
    
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!current.children[part]) {
        current.children[part] = { children: {}, nodes: [], count: 0, activeCount: 0, lifecycleCount: 0 };
      }
      current = current.children[part];
    }
    
    current.nodes.push(node);
  }
  
  function calcCounts(node) {
    let count = node.nodes.length;
    let activeCount = node.nodes.filter(n => n.status === 'active').length;
    let lifecycleCount = node.nodes.filter(n => n.type === 'lifecycle' && n.status === 'active').length;
    
    for (const child of Object.values(node.children)) {
      calcCounts(child);
      count += child.count;
      activeCount += child.activeCount;
      lifecycleCount += child.lifecycleCount;
    }
    
    node.count = count;
    node.activeCount = activeCount;
    node.lifecycleCount = lifecycleCount;
  }
  calcCounts(root);
  
  return root;
}

function StatusIndicator({ status, type }) {
  let statusColor = 'text-gray-500';
  let statusSymbol = '○';
  
  if (status === 'active') {
    statusColor = 'text-green-400';
    statusSymbol = '●';
  }
  
  let typeIndicator = '';
  if (type === 'lifecycle') {
    typeIndicator = '◐';
  } else if (type === 'unknown') {
    typeIndicator = '?';
  }
  
  return (
    <span className="flex items-center gap-1">
      <span className={statusColor}>{statusSymbol}</span>
      {typeIndicator && (
        <span className={type === 'lifecycle' ? 'text-purple-400 text-xs' : 'text-yellow-400 text-xs'}>
          {typeIndicator}
        </span>
      )}
    </span>
  );
}

function TreeNode({ 
  name, 
  data, 
  path, 
  level, 
  selectedNode, 
  onSelectNode, 
  expandedPaths, 
  onTogglePath,
  onContextMenu 
}) {
  const fullPath = path ? `${path}/${name}` : `/${name}`;
  const isExpanded = expandedPaths.has(fullPath);
  const hasChildren = Object.keys(data.children).length > 0 || data.nodes.length > 0;

  const handleContextMenu = (e) => {
    e.preventDefault();
    e.stopPropagation();
    onContextMenu(e, fullPath, data);
  };

  const toggleExpand = (e) => {
    e.stopPropagation();
    onTogglePath(fullPath);
  };

  return (
    <div className="select-none">
      <div
        className="flex items-center gap-1 py-0.5 px-1 hover:bg-gray-700 rounded cursor-pointer"
        onClick={toggleExpand}
        onContextMenu={handleContextMenu}
        style={{ paddingLeft: `${level * 12}px` }}
      >
        {hasChildren && (
          <span className="text-gray-500 w-4 text-center">
            {isExpanded ? '▼' : '▶'}
          </span>
        )}
        {!hasChildren && <span className="w-4" />}
        
        <span className="text-blue-400">/{name}</span>
        <span className="text-gray-500 text-xs">
          ({data.activeCount}/{data.count})
        </span>
      </div>
      
      {isExpanded && (
        <div>
          {Object.entries(data.children)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([childName, childData]) => (
              <TreeNode
                key={childName}
                name={childName}
                data={childData}
                path={fullPath}
                level={level + 1}
                selectedNode={selectedNode}
                onSelectNode={onSelectNode}
                expandedPaths={expandedPaths}
                onTogglePath={onTogglePath}
                onContextMenu={onContextMenu}
              />
            ))}
          
          {data.nodes
            .sort((a, b) => a.name.localeCompare(b.name))
            .map(node => {
              const nodeName = node.name.split('/').pop();
              const isSelected = selectedNode === node.name;
              
              return (
                <div
                  key={node.name}
                  className={`flex items-center gap-2 py-0.5 px-1 rounded cursor-pointer ${
                    isSelected ? 'bg-blue-900 hover:bg-blue-800' : 'hover:bg-gray-700'
                  }`}
                  style={{ paddingLeft: `${(level + 1) * 12 + 16}px` }}
                  onClick={() => onSelectNode(node.name)}
                >
                  <StatusIndicator status={node.status} type={node.type} />
                  <span className={node.status === 'active' ? 'text-white' : 'text-gray-500'}>
                    {nodeName}
                  </span>
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}

export function NodeTree({ nodes, selectedNode, onSelectNode }) {
  const [expandedPaths, setExpandedPaths] = useState(new Set(['/']));
  const [contextMenu, setContextMenu] = useState(null);
  const [confirmModal, setConfirmModal] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionResults, setActionResults] = useState(null);
  
  const tree = useMemo(() => buildTree(nodes), [nodes]);
  
  const togglePath = (path) => {
    setExpandedPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  const handleContextMenu = (e, path, data) => {
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      path,
      data
    });
  };

  const closeContextMenu = () => {
    setContextMenu(null);
  };

  const handleGroupShutdown = async () => {
    if (!confirmModal) return;
    
    setActionLoading(true);
    setActionResults(null);
    
    try {
      const result = await api.groupAction(confirmModal.path, 'shutdown', false);
      setActionResults(result.results);
    } catch (err) {
      setActionResults([{ node: 'Error', success: false, message: err.message }]);
    } finally {
      setActionLoading(false);
    }
  };

  const handleGroupKill = async () => {
    if (!confirmModal) return;
    
    setActionLoading(true);
    setActionResults(null);
    
    try {
      const result = await api.groupAction(confirmModal.path, 'kill', true);
      setActionResults(result.results);
    } catch (err) {
      setActionResults([{ node: 'Error', success: false, message: err.message }]);
    } finally {
      setActionLoading(false);
    }
  };

  const closeModal = () => {
    setConfirmModal(null);
    setActionResults(null);
  };

  const expandAll = () => {
    const paths = new Set(['/']);
    const addPaths = (data, path) => {
      for (const [name, child] of Object.entries(data.children)) {
        const fullPath = `${path}/${name}`;
        paths.add(fullPath);
        addPaths(child, fullPath);
      }
    };
    addPaths(tree, '');
    setExpandedPaths(paths);
  };

  const collapseAll = () => {
    setExpandedPaths(new Set(['/']));
  };

  const getContextMenuItems = () => {
    if (!contextMenu) return [];
    
    const { data, path } = contextMenu;
    
    return [
      {
        label: `Shutdown lifecycle nodes`,
        icon: '⏹',
        count: data.lifecycleCount,
        disabled: data.lifecycleCount === 0,
        onClick: () => setConfirmModal({
          type: 'shutdown',
          path,
          count: data.lifecycleCount,
          title: '⏹ Shutdown Lifecycle Nodes',
          message: `This will shutdown ${data.lifecycleCount} lifecycle node(s) in:\n${path}\n\nThis action uses 'ros2 lifecycle set shutdown'.`
        })
      },
      {
        label: `Kill all nodes`,
        icon: '💀',
        count: data.activeCount,
        disabled: data.activeCount === 0,
        danger: true,
        onClick: () => setConfirmModal({
          type: 'kill',
          path,
          count: data.activeCount,
          title: '💀 Kill All Nodes',
          message: `⚠️ WARNING: This will forcefully KILL ${data.activeCount} node(s) in:\n${path}\n\nThis may cause issues if nodes don't restart properly!`
        })
      },
      { separator: true },
      {
        label: 'Expand all',
        icon: '📂',
        onClick: expandAll
      },
      {
        label: 'Collapse all', 
        icon: '📁',
        onClick: collapseAll
      }
    ];
  };

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 p-2 border-b border-gray-700">
        <span className="text-gray-400 text-sm font-medium">Node Tree</span>
        <div className="flex-1" />
        <button
          onClick={expandAll}
          className="text-xs text-gray-400 hover:text-white px-2 py-1"
        >
          Expand All
        </button>
        <button
          onClick={collapseAll}
          className="text-xs text-gray-400 hover:text-white px-2 py-1"
        >
          Collapse All
        </button>
      </div>
      
      {/* Tree */}
      <div className="flex-1 overflow-auto p-2 text-sm font-mono">
        {Object.entries(tree.children)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([name, data]) => (
            <TreeNode
              key={name}
              name={name}
              data={data}
              path=""
              level={0}
              selectedNode={selectedNode}
              onSelectNode={onSelectNode}
              expandedPaths={expandedPaths}
              onTogglePath={togglePath}
              onContextMenu={handleContextMenu}
            />
          ))}
        
        {tree.nodes.map(node => (
          <div
            key={node.name}
            className={`flex items-center gap-2 py-0.5 px-1 rounded cursor-pointer ${
              selectedNode === node.name ? 'bg-blue-900' : 'hover:bg-gray-700'
            }`}
            onClick={() => onSelectNode(node.name)}
          >
            <StatusIndicator status={node.status} type={node.type} />
            <span>{node.name}</span>
          </div>
        ))}
        
        {nodes.length === 0 && (
          <div className="text-gray-500 text-center py-8">
            No nodes found
          </div>
        )}
      </div>
      
      {/* Legend */}
      <div className="p-2 border-t border-gray-700 text-xs text-gray-500">
        <div className="flex items-center gap-4">
          <span><span className="text-green-400">●</span> Active</span>
          <span><span className="text-gray-500">○</span> Inactive</span>
          <span><span className="text-purple-400">◐</span> Lifecycle</span>
          <span className="text-gray-600">Right-click for actions</span>
        </div>
      </div>

      {/* Context Menu */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={getContextMenuItems()}
          onClose={closeContextMenu}
        />
      )}

      {/* Confirm Modal */}
      {confirmModal && (
        <ConfirmModal
          title={confirmModal.title}
          message={confirmModal.message}
          confirmText={confirmModal.type === 'kill' ? 'Kill All' : 'Shutdown All'}
          danger={confirmModal.type === 'kill'}
          loading={actionLoading}
          results={actionResults}
          onConfirm={confirmModal.type === 'kill' ? handleGroupKill : handleGroupShutdown}
          onCancel={closeModal}
        />
      )}
    </div>
  );
}