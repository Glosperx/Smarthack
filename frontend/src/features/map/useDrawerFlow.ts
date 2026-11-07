import { useState, useRef, useEffect, useCallback } from 'react';

export type OpenDrawer = 'list' | 'details' | null;
export const DRAWER_ANIM_MS = 300;

/**
 * State machine managing the open drawer, selected park,
 * and the "close first, then open" transition delay.
 */
export function useDrawerFlow() {
  const [open, setOpen] = useState<OpenDrawer>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const afterClose = useCallback((fn: () => void) => {
    if (timer.current !== undefined) {
      clearTimeout(timer.current);
    }
    timer.current = setTimeout(fn, DRAWER_ANIM_MS);
  }, []);

  const close = useCallback(() => {
    if (timer.current !== undefined) {
      clearTimeout(timer.current);
    }
    setOpen(null);
  }, []);

  const toggleList = useCallback(() => {
    if (open === 'list') {
      close();
    } else if (open === 'details') {
      setOpen(null);
      afterClose(() => setOpen('list'));
    } else {
      setOpen('list');
    }
  }, [open, close, afterClose]);

  const selectPark = useCallback((id: number) => {
    if (open === 'list') {
      setOpen(null);
      afterClose(() => {
        setSelectedId(id);
        setOpen('details');
      });
    } else {
      setSelectedId(id);
      setOpen('details');
    }
  }, [open, afterClose]);

  // Clean up any pending timer on unmount
  useEffect(() => {
    return () => {
      if (timer.current !== undefined) {
        clearTimeout(timer.current);
      }
    };
  }, []);

  // Close drawer on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [close]);

  return {
    open,
    selectedId,
    toggleList,
    selectPark,
    close,
  };
}
