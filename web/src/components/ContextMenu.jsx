import { useEffect, useRef } from 'react';

export function ContextMenu({ x, y, items, onClose }) {
  const menuRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        onClose();
      }
    };

    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  // Adjust position to keep menu in viewport
  const adjustedX = Math.min(x, window.innerWidth - 200);
  const adjustedY = Math.min(y, window.innerHeight - items.length * 40);

  return (
    <div
      ref={menuRef}
      className="fixed bg-gray-800 border border-gray-600 rounded shadow-xl py-1 z-50 min-w-48"
      style={{ left: adjustedX, top: adjustedY }}
    >
      {items.map((item, idx) => (
        item.separator ? (
          <div key={idx} className="border-t border-gray-600 my-1" />
        ) : (
          <button
            key={idx}
            onClick={() => {
              item.onClick();
              onClose();
            }}
            disabled={item.disabled}
            className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed ${
              item.danger ? 'text-red-400 hover:bg-red-900/50' : 'text-gray-200'
            }`}
          >
            {item.icon && <span className="mr-2">{item.icon}</span>}
            {item.label}
            {item.count !== undefined && (
              <span className="ml-2 text-gray-500">({item.count})</span>
            )}
          </button>
        )
      ))}
    </div>
  );
}