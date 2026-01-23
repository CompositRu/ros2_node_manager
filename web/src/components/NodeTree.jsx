import { useState, useMemo } from 'react';

/**
 * Build tree structure from flat node list
 */
function buildTree(nodes) {
  const root = { children: {}, nodes: [], count: 0 };
  
  for (const node of nodes) {
    const parts = node.name.split('/').filter(Boolean);
    let current = root;
    
    // Navigate/create path
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!current.children[part]) {
        current.children[part] = { children: {}, nodes: [], count: 0 };
      }
      current = current.children[part];
    }
    
    // Add node to final location
    current.nodes.push(node);
  }
  
  // Calculate counts
  function calcCount(node) {
    let count = node.nodes.length;
    for (const child of Object.values(node.children)) {
      count += calcCount(child);
    }
    node.count = count;
    return count;
  }
  calcCount(root);
  
  return root;
}

/**
 * Status indicator component
 */
function StatusIndicator({ status, type, lifecycleState }) {
  let statusColor = 'text-gray-500';
  let statusSymbol = '○';
  
  if (status === 'active') {
    statusColor = 'text-green-400';
    statusSymbol = '●';
  }
  
  // Add lifecycle indicator
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

/**
 * Tree node component (recursive)
 */
function TreeNode({ name, data, path, level, selectedNode, onSelectNode, expandedPaths, onTogglePath }) {
  const fullPath = path ? `${path}/${name}` : `/${name}`;
  const isExpanded = expandedPaths.has(fullPath);
  const hasChildren = Object.keys(data.children).length > 0 || data.nodes.length > 0;
  
  const toggleExpand = (e) => {
    e.stopPropagation();
    onTogglePath(fullPath);
  };
  
  return (
    <div className="select-none">
      {/* Namespace header */}
      <div
        className="flex items-center gap-1 py-0.5 px-1 hover:bg-gray-700 rounded cursor-pointer"
        onClick={toggleExpand}
        style={{ paddingLeft: `${level * 12}px` }}
      >
        {hasChildren && (
          <span className="text-gray-500 w-4 text-center">
            {isExpanded ? '▼' : '▶'}
          </span>
        )}
        {!hasChildren && <span className="w-4" />}
        
        <span className="text-blue-400">/{name}</span>
        <span className="text-gray-500 text-xs">({data.count})</span>
      </div>
      
      {/* Children */}
      {isExpanded && (
        <div>
          {/* Child namespaces */}
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
              />
            ))}
          
          {/* Nodes in this namespace */}
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
                  <StatusIndicator
                    status={node.status}
                    type={node.type}
                    lifecycleState={node.lifecycle_state}
                  />
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

/**
 * Main NodeTree component
 */
export function NodeTree({ nodes, selectedNode, onSelectNode }) {
  const [expandedPaths, setExpandedPaths] = useState(new Set(['/']));
  
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
  
  // Expand all
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
  
  // Collapse all
  const collapseAll = () => {
    setExpandedPaths(new Set(['/']));
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
            />
          ))}
        
        {/* Root level nodes (unlikely but handle it) */}
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
          <span><span className="text-yellow-400">?</span> Unknown</span>
        </div>
      </div>
    </div>
  );
}
