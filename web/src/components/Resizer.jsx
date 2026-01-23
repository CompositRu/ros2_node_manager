import { useCallback, useEffect, useState } from 'react';

/**
 * Horizontal resizer (changes width of left panel)
 */
export function HorizontalResizer({ onResize }) {
  const [isDragging, setIsDragging] = useState(false);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => {
      onResize(e.clientX);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, onResize]);

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`w-1 cursor-col-resize hover:bg-blue-500 transition-colors flex-shrink-0 ${
        isDragging ? 'bg-blue-500' : 'bg-gray-700 hover:bg-gray-500'
      }`}
      style={{ touchAction: 'none' }}
    />
  );
}

/**
 * Vertical resizer (changes height of bottom panel)
 */
export function VerticalResizer({ onResize }) {
  const [isDragging, setIsDragging] = useState(false);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => {
      onResize(window.innerHeight - e.clientY);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, onResize]);

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`h-1 cursor-row-resize hover:bg-blue-500 transition-colors flex-shrink-0 ${
        isDragging ? 'bg-blue-500' : 'bg-gray-700 hover:bg-gray-500'
      }`}
      style={{ touchAction: 'none' }}
    />
  );
}