/**
 * ToastContainer - контейнер для toast-уведомлений
 * 
 * Позиционируется в правом нижнем углу.
 * Показывает до 5 уведомлений с анимацией.
 */

import { useNotifications } from '../hooks/useNotifications';

// Иконки для разных уровней severity
const SeverityIcon = ({ severity }) => {
  switch (severity) {
    case 'critical':
      return (
        <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      );
    case 'error':
      return (
        <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
            d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      );
    case 'warning':
      return (
        <svg className="w-5 h-5 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      );
    case 'info':
    default:
      return (
        <svg className="w-5 h-5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
            d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      );
  }
};

// Цвета фона для разных уровней severity
const getSeverityStyles = (severity) => {
  switch (severity) {
    case 'critical':
      return 'bg-red-900/90 border-red-500';
    case 'error':
      return 'bg-red-800/90 border-red-600';
    case 'warning':
      return 'bg-yellow-800/90 border-yellow-600';
    case 'info':
    default:
      return 'bg-blue-800/90 border-blue-600';
  }
};

// Форматирование времени
const formatTime = (timestamp) => {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('ru-RU', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit'
  });
};

// Одно уведомление
function Toast({ notification, onClose }) {
  const severityStyles = getSeverityStyles(notification.severity);

  return (
    <div 
      className={`
        ${severityStyles}
        border-l-4 rounded-lg shadow-lg p-4 mb-3
        animate-slide-in
        max-w-sm w-full
        backdrop-blur-sm
      `}
    >
      <div className="flex items-start gap-3">
        <SeverityIcon severity={notification.severity} />
        
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-white truncate">
              {notification.title}
            </h4>
            <button
              onClick={() => onClose(notification.id)}
              className="text-gray-400 hover:text-white transition-colors flex-shrink-0"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          <p className="text-sm text-gray-300 mt-1 break-words">
            {notification.message}
          </p>
          
          <span className="text-xs text-gray-500 mt-1 block">
            {formatTime(notification.timestamp)}
          </span>
        </div>
      </div>
    </div>
  );
}

// Контейнер для всех уведомлений
export function ToastContainer() {
  const { notifications, removeNotification } = useNotifications();

  if (notifications.length === 0) {
    return null;
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col-reverse">
      {notifications.map(notification => (
        <Toast
          key={notification.id}
          notification={notification}
          onClose={removeNotification}
        />
      ))}
    </div>
  );
}
