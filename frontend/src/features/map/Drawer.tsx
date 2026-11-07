import type { ReactNode } from 'react';

interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

/**
 * Generic slide-out panel extending from the right edge.
 */
export function Drawer({ isOpen, onClose, title, children }: DrawerProps) {
  return (
    <aside
      role="dialog"
      aria-label={title}
      aria-hidden={!isOpen}
      className={`fixed inset-y-0 right-0 z-30 w-full sm:w-96 bg-slate-900/95 backdrop-blur-md border-l border-slate-800 shadow-2xl transition-transform duration-300 ease-in-out flex flex-col ${
        isOpen ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      {/* Drawer Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
        <h2 className="text-lg font-semibold text-slate-100 tracking-tight">{title}</h2>
        <button
          onClick={onClose}
          aria-label="Close drawer"
          className="p-2 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800/80 transition-colors cursor-pointer"
        >
          <svg
            className="w-5 h-5"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth="2"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Drawer Body */}
      <div className="flex-1 overflow-y-auto p-6">{children}</div>
    </aside>
  );
}
