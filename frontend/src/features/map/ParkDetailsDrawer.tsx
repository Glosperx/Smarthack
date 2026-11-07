import { Drawer } from './Drawer';
import type { Park } from '../../api/hooks';

interface ParkDetailsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  selectedPark: Park | null;
}

/**
 * Slide-out details drawer showing selected wind park coordinates.
 */
export function ParkDetailsDrawer({ isOpen, onClose, selectedPark }: ParkDetailsDrawerProps) {
  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={selectedPark ? `Park #${selectedPark.id}` : 'Park Details'}
    >
      {selectedPark ? (
        <div className="space-y-6">
          {/* Geographic Coordinates Card */}
          <div className="bg-slate-800/60 border border-slate-700/80 rounded-xl p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
              Geographic Coordinates
            </h3>
            <div className="space-y-3 font-mono text-sm">
              <div className="flex justify-between items-center py-1.5 border-b border-slate-700/50">
                <span className="text-slate-400">Latitude</span>
                <span className="text-emerald-400 font-medium">
                  {selectedPark.latitude.toFixed(6)}°
                </span>
              </div>
              <div className="flex justify-between items-center py-1.5">
                <span className="text-slate-400">Longitude</span>
                <span className="text-emerald-400 font-medium">
                  {selectedPark.longitude.toFixed(6)}°
                </span>
              </div>
            </div>
          </div>

          {/* Reserved slot for future details */}
          <div className="border border-dashed border-slate-700/80 rounded-xl p-5 text-center bg-slate-800/20">
            <svg
              className="w-8 h-8 text-slate-600 mx-auto mb-2"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth="1.5"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
              />
            </svg>
            <p className="text-xs text-slate-400 font-medium">Turbine Specifications & Output</p>
            <p className="text-xs text-slate-500 mt-1">
              Detailed metrics, capacity, and active weather forecasts will appear here.
            </p>
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-500">No park selected.</p>
      )}
    </Drawer>
  );
}
