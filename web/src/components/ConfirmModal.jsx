export function ConfirmModal({ 
  title, 
  message, 
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  danger = false,
  onConfirm, 
  onCancel,
  loading = false,
  results = null
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl max-w-lg w-full mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-700">
          <h3 className="text-lg font-semibold text-white">{title}</h3>
        </div>
        
        {/* Content */}
        <div className="px-4 py-4">
          <p className="text-gray-300 text-sm whitespace-pre-line">{message}</p>
          
          {/* Results */}
          {results && (
            <div className="mt-4 max-h-48 overflow-auto">
              <div className="text-sm space-y-1">
                {results.map((r, idx) => (
                  <div 
                    key={idx}
                    className={`flex items-center gap-2 px-2 py-1 rounded ${
                      r.success ? 'bg-green-900/30' : 'bg-red-900/30'
                    }`}
                  >
                    <span>{r.success ? '✓' : '✗'}</span>
                    <span className="text-gray-400 truncate flex-1">{r.node}</span>
                    {!r.success && (
                      <span className="text-red-400 text-xs">{r.message}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        
        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-700 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded disabled:opacity-50"
          >
            {results ? 'Close' : cancelText}
          </button>
          {!results && (
            <button
              onClick={onConfirm}
              disabled={loading}
              className={`px-4 py-2 text-white text-sm rounded disabled:opacity-50 ${
                danger 
                  ? 'bg-red-600 hover:bg-red-500' 
                  : 'bg-blue-600 hover:bg-blue-500'
              }`}
            >
              {loading ? 'Processing...' : confirmText}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}