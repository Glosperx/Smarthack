interface MenuButtonProps {
  onClick: () => void;
  disabled?: boolean;
}

/**
 * Floating three-line hamburger menu button placed in the top right.
 */
export function MenuButton({ onClick, disabled = false }: MenuButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label="Open park list"
      className="absolute top-4 right-4 z-20 p-3 rounded-xl bg-slate-900/90 text-slate-100 border border-slate-700/80 shadow-lg hover:bg-slate-800 hover:border-slate-600 focus:outline-none focus:ring-2 focus:ring-emerald-400 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <svg
        className="w-6 h-6"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth="2"
        stroke="currentColor"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
      </svg>
    </button>
  );
}
