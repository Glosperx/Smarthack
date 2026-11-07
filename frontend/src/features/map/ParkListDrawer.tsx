import { useState, useMemo } from 'react';
import { Drawer } from './Drawer';
import type { Park } from '../../api/hooks';

interface ParkListDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  parks: Park[];
  selectedId: number | null;
  onSelectPark: (id: number) => void;
}

/**
 * Slide-out list drawer displaying all wind parks.
 */
export function ParkListDrawer({
  isOpen,
  onClose,
  parks,
  selectedId,
  onSelectPark,
}: ParkListDrawerProps) {
  const [filterText, setFilterText] = useState('');

  const filteredParks = useMemo(() => {
    if (!filterText.trim()) return parks;
    const query = filterText.toLowerCase();
    return parks.filter((p) => `park #${p.id}`.includes(query) || `${p.id}`.includes(query));
  }, [parks, filterText]);

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title="Wind Parks">
      {/* Search Filter */}
      <div className="mb-4">
        <input
          type="text"
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          placeholder="Filter parks..."
          className="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
        />
      </div>

      {/* Count label */}
      <div className="text-xs text-slate-400 mb-3 font-mono">
        Showing {filteredParks.length} of {parks.length} parks
      </div>

      {/* Scrollable park items */}
      <div className="space-y-2">
        {filteredParks.map((park) => {
          const isSelected = park.id === selectedId;
          return (
            <button
              key={park.id}
              onClick={() => onSelectPark(park.id)}
              className={`w-full text-left p-3.5 rounded-xl border transition-all cursor-pointer flex items-center justify-between ${
                isSelected
                  ? 'bg-blue-600/20 border-blue-500/80 text-blue-200'
                  : 'bg-slate-800/50 border-slate-700/60 hover:bg-slate-800 hover:border-slate-600 text-slate-200'
              }`}
            >
              <div>
                <div className="font-semibold text-sm">Park #{park.id}</div>
                <div className="text-xs font-mono text-slate-400 mt-0.5">
                  {park.latitude.toFixed(4)}, {park.longitude.toFixed(4)}
                </div>
              </div>
              <svg
                className="w-4 h-4 text-slate-500"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth="2"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          );
        })}

        {filteredParks.length === 0 && (
          <p className="text-center text-sm text-slate-500 py-8">No parks found.</p>
        )}
      </div>
    </Drawer>
  );
}
