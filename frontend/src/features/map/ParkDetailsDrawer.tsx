import { Drawer } from './Drawer';
import { useParkTurbines } from '../../api/hooks';
import type { Park } from '../../api/hooks';
import { TurbineRow } from './TurbineRow';

interface ParkDetailsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  selectedPark: Park | null;
}

/**
 * Slide-out details drawer showing selected wind park info and today's turbine diagnostics.
 */
export function ParkDetailsDrawer({ isOpen, onClose, selectedPark }: ParkDetailsDrawerProps) {
  const parkId = isOpen && selectedPark ? selectedPark.id : null;
  const { data, isLoading, isFetching, isError, error, refetch } = useParkTurbines(parkId);

  // If park changed and query is still fetching the new park's data
  const isDataForCurrentPark = data?.park_id === selectedPark?.id;
  const showSkeleton = isLoading || (!isDataForCurrentPark && isFetching);

  const turbines = (isDataForCurrentPark ? data?.turbines : []) ?? [];

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={selectedPark ? selectedPark.name : 'Park Details'}
    >
      {selectedPark ? (
        <div className="space-y-5">
          {/* Subtitle Card: Coordinates & Evaluation Date */}
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-xl p-3.5 space-y-2">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400">
              <span className="flex items-center gap-1.5">
                <span className="text-slate-500">ID:</span>
                <span className="text-slate-300 font-semibold">#{selectedPark.id}</span>
              </span>
              <span>
                {selectedPark.latitude.toFixed(5)}°, {selectedPark.longitude.toFixed(5)}°
              </span>
            </div>
            {data?.date && (
              <div className="text-[11px] font-mono text-emerald-400/90 pt-1.5 border-t border-slate-700/50 flex items-center justify-between">
                <span>Evaluation Window</span>
                <span>Predictions for {data.date}</span>
              </div>
            )}
          </div>

          {/* Turbines Section */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Turbines & Health Status
              </h3>
              {!showSkeleton && !isError && isDataForCurrentPark && (
                <span className="text-xs font-mono text-slate-400">
                  {turbines.length} {turbines.length === 1 ? 'turbine' : 'turbines'}
                </span>
              )}
            </div>

            {/* Loading Skeleton */}
            {showSkeleton && (
              <div className="space-y-2.5">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="animate-pulse bg-slate-800/40 border border-slate-700/40 rounded-xl p-3.5 flex items-center justify-between"
                  >
                    <div className="space-y-2 flex-1">
                      <div className="h-3.5 bg-slate-700/60 rounded-md w-3/4" />
                      <div className="h-2.5 bg-slate-700/40 rounded-md w-1/2" />
                    </div>
                    <div className="h-5 w-12 bg-slate-700/50 rounded-md ml-3" />
                  </div>
                ))}
              </div>
            )}

            {/* Error Banner with Retry */}
            {!showSkeleton && isError && (
              <div className="bg-rose-950/60 border border-rose-800/80 rounded-xl p-4 text-center space-y-3">
                <p className="text-xs text-rose-200">
                  {error instanceof Error ? error.message : 'Could not load turbine diagnostics'}
                </p>
                <button
                  onClick={() => refetch()}
                  className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold transition-colors cursor-pointer"
                >
                  Retry
                </button>
              </div>
            )}

            {/* Empty State */}
            {!showSkeleton && !isError && isDataForCurrentPark && turbines.length === 0 && (
              <div className="border border-dashed border-slate-700/80 rounded-xl p-6 text-center bg-slate-800/20">
                <p className="text-xs text-slate-400 font-medium">No turbines registered for this park.</p>
              </div>
            )}

            {/* Turbines List */}
            {!showSkeleton && !isError && isDataForCurrentPark && turbines.length > 0 && (
              <div className="space-y-2 max-h-[calc(100vh-280px)] overflow-y-auto pr-1">
                {turbines.map((turbine) => (
                  <TurbineRow key={turbine.id} turbine={turbine} />
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-500">No park selected.</p>
      )}
    </Drawer>
  );
}
