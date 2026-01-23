/**
 * Status bar showing node counts
 */
export function StatusBar({ total, active, inactive }) {
  return (
    <div className="flex items-center gap-4 text-sm">
      <span className="text-gray-300">
        Nodes: <span className="font-semibold text-white">{total}</span> total
      </span>
      <span className="text-gray-300">|</span>
      <span className="text-green-400">
        <span className="font-semibold">{active}</span> active
      </span>
      <span className="text-gray-300">|</span>
      <span className="text-gray-500">
        <span className="font-semibold">{inactive}</span> inactive
      </span>
    </div>
  );
}
