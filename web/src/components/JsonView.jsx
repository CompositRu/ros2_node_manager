/**
 * Structured JSON view for ROS2 topic echo messages.
 * Renders JSON objects as a colored key-value tree.
 */
export function JsonView({ data, indent = 0 }) {
  if (data === null || data === undefined) {
    return <span className="text-gray-500">null</span>;
  }
  if (typeof data === 'number') {
    return <span className="text-green-400">{data}</span>;
  }
  if (typeof data === 'boolean') {
    return <span className="text-purple-400">{String(data)}</span>;
  }
  if (typeof data === 'string') {
    return <span className="text-amber-400">"{data}"</span>;
  }
  if (Array.isArray(data)) {
    if (data.length === 0) {
      return <span className="text-gray-500">[]</span>;
    }
    return (
      <div style={{ paddingLeft: indent > 0 ? '1rem' : 0 }}>
        {data.map((item, i) => (
          <div key={i}>
            <span className="text-gray-500">- </span>
            <JsonView data={item} indent={indent + 1} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof data === 'object') {
    const entries = Object.entries(data);
    if (entries.length === 0) {
      return <span className="text-gray-500">{'{}'}</span>;
    }
    return (
      <div style={{ paddingLeft: indent > 0 ? '1rem' : 0 }}>
        {entries.map(([key, value]) => (
          <div key={key}>
            <span className="text-blue-400">{key}: </span>
            <JsonView data={value} indent={indent + 1} />
          </div>
        ))}
      </div>
    );
  }
  return <span>{String(data)}</span>;
}

/**
 * Extract top-level keys from a JSON object.
 * @param {object} data - JSON object
 * @returns {string[]} ordered list of top-level keys
 */
export function extractJsonTopLevelKeys(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return [];
  return Object.keys(data);
}

/**
 * Filter a JSON object to only include specified top-level keys.
 * @param {object} data - JSON object
 * @param {Set<string>} activeFields - set of top-level keys to keep
 * @returns {object} filtered object
 */
export function filterJsonFields(data, activeFields) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return data;
  if (!activeFields || activeFields.size === 0) return data;
  const result = {};
  for (const key of activeFields) {
    if (key in data) {
      result[key] = data[key];
    }
  }
  return result;
}
