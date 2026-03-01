import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { getServiceList, getServiceInterface, callService } from '../services/api';


/**
 * Convert ROS2 interface field definitions into a YAML template.
 * e.g. "bool data" -> "data: false", "string name" -> 'name: ""'
 */
function buildYamlTemplate(fieldDefs) {
  if (!fieldDefs || !fieldDefs.trim()) return '{}';

  const lines = [];
  for (const line of fieldDefs.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const parts = trimmed.split(/\s+/);
    if (parts.length >= 2) {
      const fieldType = parts[0];
      const fieldName = parts[1];
      let defaultVal = '""';

      if (fieldType.includes('bool')) defaultVal = 'false';
      else if (fieldType.includes('int') || fieldType.includes('byte')) defaultVal = '0';
      else if (fieldType.includes('float') || fieldType.includes('double')) defaultVal = '0.0';
      else if (fieldType.includes('string')) defaultVal = '""';
      else if (fieldType.endsWith('[]')) defaultVal = '[]';

      lines.push(`${fieldName}: ${defaultVal}`);
    }
  }

  return lines.length > 0 ? lines.join('\n') : '{}';
}


function buildServiceTree(services) {
  const root = { children: {}, services: [], count: 0 };

  for (const service of services) {
    const parts = service.name.split('/').filter(Boolean);
    let current = root;

    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!current.children[part]) {
        current.children[part] = { children: {}, services: [], count: 0 };
      }
      current = current.children[part];
    }

    current.services.push(service);
  }

  function calcCounts(node) {
    let count = node.services.length;
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


function ServiceTreeNode({ name, data, path, level, expandedPaths, onTogglePath,
  selectedService, onSelectService, infoService, onInfo, activeCall, onCall }) {
  const fullPath = path ? `${path}/${name}` : `/${name}`;
  const isExpanded = expandedPaths.has(fullPath);
  const hasChildren = Object.keys(data.children).length > 0 || data.services.length > 0;

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
              <ServiceTreeNode
                key={childName}
                name={childName}
                data={childData}
                path={fullPath}
                level={level + 1}
                expandedPaths={expandedPaths}
                onTogglePath={onTogglePath}
                selectedService={selectedService}
                onSelectService={onSelectService}
                infoService={infoService}
                onInfo={onInfo}
                activeCall={activeCall}
                onCall={onCall}
              />
            ))}

          {data.services
            .sort((a, b) => a.name.localeCompare(b.name))
            .map(service => {
              const leafName = service.name.split('/').pop();
              const isSelected = selectedService === service.name;
              return (
                <div
                  key={service.name}
                  className={`flex items-center gap-2 py-0.5 px-1 rounded cursor-pointer ${
                    isSelected ? 'bg-blue-900 hover:bg-blue-800' : 'hover:bg-gray-700'
                  }`}
                  style={{ paddingLeft: `${(level + 1) * 12 + 16}px` }}
                  onClick={() => onSelectService(isSelected ? null : service.name)}
                  title={service.name}
                >
                  <span className="text-orange-400 text-xs font-mono font-bold">S</span>
                  <span className="text-gray-200 text-sm font-mono truncate">{leafName}</span>
                  <div className="ml-auto flex items-center gap-1.5 flex-shrink-0">
                    {isSelected && (
                      <>
                        <button
                          onClick={(e) => { e.stopPropagation(); onInfo(service.name, service.type); }}
                          className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                            infoService === service.name
                              ? 'bg-purple-600 hover:bg-purple-700 text-white'
                              : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                          }`}
                        >
                          Info
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); onCall(service.name, service.type); }}
                          className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                            activeCall === service.name
                              ? 'bg-green-600 hover:bg-green-700 text-white'
                              : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                          }`}
                        >
                          Call
                        </button>
                      </>
                    )}
                    {!isSelected && service.type && (
                      <span className="text-gray-500 text-xs truncate max-w-[220px]" title={service.type}>
                        {service.type}
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


function ServiceInfoPanel({ serviceName, info, loading, onClose }) {
  if (loading) {
    return (
      <div className="px-3 py-2 bg-gray-800 border-b border-gray-700 text-gray-400 text-xs">
        Loading info for <span className="text-orange-400 font-mono">{serviceName}</span>...
      </div>
    );
  }

  if (!info) return null;

  return (
    <div className="px-3 py-2 bg-gray-800 border-b border-gray-700 text-xs">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-gray-300 font-medium">Service Info</span>
        <button
          onClick={onClose}
          className="px-1.5 py-0.5 text-[10px] rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
        >
          Close
        </button>
      </div>
      <div className="text-gray-400 mb-2">
        Type: <span className="text-yellow-400 font-mono">{info.type || '\u2014'}</span>
      </div>
      {info.error && (
        <div className="text-red-400 mb-2">{info.error}</div>
      )}
      <div className="flex gap-4">
        <div className="flex-1">
          <div className="text-gray-500 mb-0.5">Request</div>
          <pre className="text-green-400 font-mono text-[11px] pl-2 whitespace-pre-wrap">
            {info.request_fields || '(empty)'}
          </pre>
        </div>
        <div className="flex-1">
          <div className="text-gray-500 mb-0.5">Response</div>
          <pre className="text-blue-400 font-mono text-[11px] pl-2 whitespace-pre-wrap">
            {info.response_fields || '(empty)'}
          </pre>
        </div>
      </div>
    </div>
  );
}


function ServiceCallPanel({ serviceName, serviceType, interfaceInfo, onClose }) {
  const [requestYaml, setRequestYaml] = useState('{}');
  const [response, setResponse] = useState(null);
  const [calling, setCalling] = useState(false);
  const [error, setError] = useState(null);

  // Pre-populate request template from interface info
  useEffect(() => {
    if (interfaceInfo?.request_fields) {
      setRequestYaml(buildYamlTemplate(interfaceInfo.request_fields));
    } else {
      setRequestYaml('{}');
    }
    setResponse(null);
    setError(null);
  }, [serviceName, interfaceInfo]);

  const handleCall = useCallback(async () => {
    setCalling(true);
    setError(null);
    setResponse(null);
    try {
      const result = await callService(serviceName, serviceType, requestYaml);
      if (result.success) {
        setResponse(result.output);
      } else {
        setError(result.output);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setCalling(false);
    }
  }, [serviceName, serviceType, requestYaml]);

  return (
    <div className="bg-gray-800 border-t border-gray-700 flex flex-col" style={{ height: 280 }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700 flex-shrink-0">
        <span className="text-sm text-gray-300 truncate">
          Call: <span className="text-orange-400 font-mono">{serviceName}</span>
          <span className="text-gray-500 text-xs ml-2">[{serviceType}]</span>
        </span>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={handleCall}
            disabled={calling}
            className="px-2 py-0.5 text-xs rounded bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
          >
            {calling ? 'Calling...' : 'Call'}
          </button>
          <button
            onClick={onClose}
            className="px-2 py-0.5 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            Close
          </button>
        </div>
      </div>

      {/* Content: Request editor + Response display */}
      <div className="flex-1 flex overflow-hidden">
        {/* Request */}
        <div className="flex-1 flex flex-col border-r border-gray-700">
          <div className="px-2 py-1 text-[10px] text-gray-500 border-b border-gray-700 flex-shrink-0">Request</div>
          <textarea
            value={requestYaml}
            onChange={(e) => setRequestYaml(e.target.value)}
            className="flex-1 bg-gray-900 text-green-400 font-mono text-xs p-2 resize-none focus:outline-none"
            placeholder="YAML request data..."
            spellCheck={false}
          />
        </div>
        {/* Response */}
        <div className="flex-1 flex flex-col">
          <div className="px-2 py-1 text-[10px] text-gray-500 border-b border-gray-700 flex-shrink-0">Response</div>
          <div className="flex-1 overflow-y-auto p-2">
            {calling && (
              <div className="text-yellow-400 text-xs">Calling service...</div>
            )}
            {error && (
              <pre className="text-red-400 font-mono text-xs whitespace-pre-wrap">{error}</pre>
            )}
            {response && (
              <pre className="text-blue-400 font-mono text-xs whitespace-pre-wrap">{response}</pre>
            )}
            {!calling && !error && !response && (
              <div className="text-gray-500 text-xs text-center py-4">
                Edit request and click Call
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}


export function Services({ connected }) {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedPaths, setExpandedPaths] = useState(new Set(['/']));
  const [selectedService, setSelectedService] = useState(null);
  const [filter, setFilter] = useState('');

  // Info state
  const [infoService, setInfoService] = useState(null);
  const [serviceInfo, setServiceInfo] = useState(null);
  const [infoLoading, setInfoLoading] = useState(false);

  // Call state
  const [callServiceName, setCallServiceName] = useState(null);
  const [callServiceType, setCallServiceType] = useState(null);
  const [callInterfaceInfo, setCallInterfaceInfo] = useState(null);

  const fetchServices = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getServiceList();
      setServices(data.services || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (connected) fetchServices();
  }, [connected, fetchServices]);

  const filteredServices = useMemo(() => {
    if (!filter) return services;
    const lower = filter.toLowerCase();
    return services.filter(s =>
      s.name.toLowerCase().includes(lower) ||
      s.type.toLowerCase().includes(lower)
    );
  }, [services, filter]);

  const tree = useMemo(() => buildServiceTree(filteredServices), [filteredServices]);

  const togglePath = useCallback((path) => {
    setExpandedPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
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

  // Info handler
  const handleInfo = useCallback(async (serviceName, serviceType) => {
    if (infoService === serviceName) {
      setInfoService(null);
      setServiceInfo(null);
      return;
    }
    setInfoService(serviceName);
    setServiceInfo(null);
    setInfoLoading(true);
    try {
      const data = await getServiceInterface(serviceType);
      setServiceInfo(data);
    } catch (err) {
      setServiceInfo({ type: serviceType, request_fields: '', response_fields: '', error: err.message });
    } finally {
      setInfoLoading(false);
    }
  }, [infoService]);

  const closeInfo = useCallback(() => {
    setInfoService(null);
    setServiceInfo(null);
  }, []);

  // Call handler
  const handleCall = useCallback(async (serviceName, serviceType) => {
    if (callServiceName === serviceName) {
      setCallServiceName(null);
      setCallServiceType(null);
      setCallInterfaceInfo(null);
      return;
    }
    setCallServiceName(serviceName);
    setCallServiceType(serviceType);
    try {
      const data = await getServiceInterface(serviceType);
      setCallInterfaceInfo(data);
    } catch {
      setCallInterfaceInfo(null);
    }
  }, [callServiceName]);

  const closeCall = useCallback(() => {
    setCallServiceName(null);
    setCallServiceType(null);
    setCallInterfaceInfo(null);
  }, []);

  if (!connected) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        <div className="text-center">
          <p className="mb-2">Not connected</p>
          <p className="text-sm">Connect to a server to view services</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-700 flex-shrink-0">
        <span className="text-sm font-medium text-gray-300">Services</span>
        <span className="text-xs text-gray-500">
          ({filteredServices.length}{filter ? `/${services.length}` : ''})
        </span>
        <div className="flex-1" />
        <button onClick={fetchServices} disabled={loading}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700 transition-colors disabled:opacity-50">
          {loading ? 'Loading...' : 'Refresh'}
        </button>
        <button onClick={expandAll}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700 transition-colors">
          Expand
        </button>
        <button onClick={collapseAll}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700 transition-colors">
          Collapse
        </button>
      </div>

      {/* Filter */}
      <div className="px-3 py-1.5 border-b border-gray-700 flex-shrink-0">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter services or types..."
          className="w-full bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:border-blue-400 focus:outline-none placeholder-gray-500"
        />
      </div>

      {/* Error */}
      {error && (
        <div className="px-3 py-2 text-red-400 text-sm bg-red-900/20 border-b border-gray-700">
          {error}
        </div>
      )}

      {/* Info Panel */}
      {infoService && (
        <ServiceInfoPanel
          serviceName={infoService}
          info={serviceInfo}
          loading={infoLoading}
          onClose={closeInfo}
        />
      )}

      {/* Tree */}
      <div className="flex-1 overflow-y-auto p-2 font-mono text-sm">
        {loading && services.length === 0 && (
          <div className="text-gray-500 text-center py-8">Loading services...</div>
        )}
        {!loading && services.length === 0 && !error && (
          <div className="text-gray-500 text-center py-8">No services found</div>
        )}
        {filteredServices.length === 0 && services.length > 0 && filter && (
          <div className="text-gray-500 text-center py-8">No services matching &quot;{filter}&quot;</div>
        )}
        {Object.entries(tree.children)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([name, data]) => (
            <ServiceTreeNode
              key={name}
              name={name}
              data={data}
              path=""
              level={0}
              expandedPaths={expandedPaths}
              onTogglePath={togglePath}
              selectedService={selectedService}
              onSelectService={setSelectedService}
              infoService={infoService}
              onInfo={handleInfo}
              activeCall={callServiceName}
              onCall={handleCall}
            />
          ))}
      </div>

      {/* Call Panel */}
      {callServiceName && (
        <ServiceCallPanel
          serviceName={callServiceName}
          serviceType={callServiceType}
          interfaceInfo={callInterfaceInfo}
          onClose={closeCall}
        />
      )}
    </div>
  );
}
