/**
 * NotificationContext - управление toast-уведомлениями
 * 
 * Особенности:
 * - Максимум 5 уведомлений одновременно
 * - Автоматическое закрытие через 7 секунд
 * - Новые вытесняют старые при переполнении
 */

import { createContext, useState, useCallback, useRef, useEffect } from 'react';

const MAX_NOTIFICATIONS = 5;
const AUTO_DISMISS_MS = 7000;

export const NotificationContext = createContext(null);

export function NotificationProvider({ children }) {
  const [notifications, setNotifications] = useState([]);
  const timersRef = useRef(new Map());

  // Remove notification by ID
  const removeNotification = useCallback((id) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }

    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  // Add notification
  const addNotification = useCallback((notification) => {
    const id = crypto.randomUUID();
    const timestamp = Date.now();
    
    const newNotification = {
      ...notification,
      id,
      timestamp,
      severity: notification.severity || 'error'
    };

    setNotifications(prev => {
      let updated = [...prev];

      // Вытесняем старые если очередь полна
      while (updated.length >= MAX_NOTIFICATIONS) {
        const oldest = updated[0];
        const timer = timersRef.current.get(oldest.id);
        if (timer) {
          clearTimeout(timer);
          timersRef.current.delete(oldest.id);
        }
        updated = updated.slice(1);
      }

      return [...updated, newNotification];
    });

    // Auto-dismiss timer
    const timer = setTimeout(() => {
      removeNotification(id);
    }, AUTO_DISMISS_MS);
    timersRef.current.set(id, timer);

    return id;
  }, [removeNotification]);

  // Clear all notifications
  const clearAll = useCallback(() => {
    timersRef.current.forEach(timer => clearTimeout(timer));
    timersRef.current.clear();
    setNotifications([]);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      timersRef.current.forEach(timer => clearTimeout(timer));
    };
  }, []);

  const value = {
    notifications,
    addNotification,
    removeNotification,
    clearAll
  };

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}