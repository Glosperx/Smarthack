import { useState } from 'react';
import { useParks } from '../../api/hooks';
import { useDrawerFlow } from './useDrawerFlow';
import { ParkMap } from './ParkMap';
import { MenuButton } from './MenuButton';
import { ParkListDrawer } from './ParkListDrawer';
import { ParkDetailsDrawer } from './ParkDetailsDrawer';
import { usePlainSites, useResourceSites, useResourceSummary } from '../resource/api';
import { WindResourceLayer } from '../resource/WindResourceLayer';
import { WindResourcePanel } from '../resource/WindResourcePanel';
import { VERDICT, useTransportNetwork, useTransportSummary } from '../transport/api';
import { TransportLayer } from '../transport/TransportLayer';
import { TransportPanel } from '../transport/TransportPanel';

/**
 * Top-level Wind Park Map screen.
 */
export function MapPage() {
  const { data: parks = [], isLoading, isError, error, refetch } = useParks();
  const { open, selectedId, toggleList, selectPark, close } = useDrawerFlow();
  const [resourceOn, setResourceOn] = useState(false);
  const [focusedSite, setFocusedSite] = useState<number | null>(null);
  const [plainOn, setPlainOn] = useState(true);
  const [focusedPlain, setFocusedPlain] = useState<number | null>(null);
  const plainSites = usePlainSites(resourceOn);
  const resourceSummary = useResourceSummary(resourceOn);
  const resourceSites = useResourceSites(resourceOn);
  const [transportOn, setTransportOn] = useState(false);
  const [verdictsShown, setVerdictsShown] = useState<Set<number>>(
    () => new Set([VERDICT.viable, VERDICT.check, VERDICT.blocked, VERDICT.isolated])
  );
  const [showCounty, setShowCounty] = useState(true);
  const transportSummary = useTransportSummary(transportOn);
  const transportNetwork = useTransportNetwork(transportOn);
  const toggleVerdict = (code: number) =>
    setVerdictsShown((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const selectedPark = parks.find((p) => p.id === selectedId) || null;

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-slate-950 font-sans">
      {/* Top Right Hamburger Menu Button */}
      <MenuButton onClick={toggleList} disabled={isLoading} />

      {/* Bottom Left Hill Wind Site Finder */}
      <WindResourcePanel
        enabled={resourceOn}
        onToggle={() => setResourceOn((v) => !v)}
        summary={resourceSummary.data}
        sites={resourceSites.data ?? []}
        isLoading={resourceSummary.isLoading || resourceSites.isLoading}
        error={resourceSummary.error ?? resourceSites.error}
        focusedRank={focusedSite}
        onFocusSite={(rank) => {
          setFocusedSite(rank);
          setFocusedPlain(null);
        }}
        plainOn={plainOn}
        onTogglePlain={() => setPlainOn((v) => !v)}
        plainSites={plainSites.data ?? []}
        focusedPlain={focusedPlain}
        onFocusPlain={(rank) => {
          setFocusedPlain(rank);
          setFocusedSite(null);
        }}
      />

      {/* Bottom Right Oversize Transport Network */}
      <TransportPanel
        enabled={transportOn}
        onToggle={() => setTransportOn((v) => !v)}
        summary={transportSummary.data}
        isLoading={transportSummary.isLoading || transportNetwork.isLoading}
        error={transportSummary.error ?? transportNetwork.error}
        visible={verdictsShown}
        onToggleVerdict={toggleVerdict}
        showCounty={showCounty}
        onToggleCounty={() => setShowCounty((v) => !v)}
      />

      {/* Main Map View */}
      <main className="w-full h-full">
        <ParkMap
          parks={parks}
          selectedId={selectedId}
          onSelectPark={selectPark}
          onBackgroundClick={close}
        >
          {resourceOn && resourceSummary.data && (
            <WindResourceLayer
              summary={resourceSummary.data}
              sites={resourceSites.data ?? []}
              focusedRank={focusedSite}
              showPlain={plainOn && resourceSummary.data.plain_legend != null}
              plainSites={plainOn ? (plainSites.data ?? []) : []}
              focusedPlain={focusedPlain}
            />
          )}
          {transportOn && transportSummary.data && transportNetwork.data && (
            <TransportLayer
              network={transportNetwork.data}
              summary={transportSummary.data}
              visible={verdictsShown}
              showCounty={showCounty}
            />
          )}
        </ParkMap>
      </main>

      {/* Loading Overlay */}
      {isLoading && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-950/60 backdrop-blur-xs">
          <div className="flex items-center gap-3 bg-slate-900/90 border border-slate-800 px-5 py-3 rounded-2xl shadow-2xl">
            <div className="w-5 h-5 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm font-medium text-slate-200">Loading wind parks...</span>
          </div>
        </div>
      )}

      {/* Error Banner with Retry */}
      {isError && (
        <div className="absolute top-6 left-1/2 -translate-x-1/2 z-30 max-w-md w-full px-4">
          <div className="bg-rose-950/90 border border-rose-700 text-rose-200 p-4 rounded-xl shadow-2xl backdrop-blur-md flex items-center justify-between gap-4">
            <div className="text-sm">
              <span className="font-semibold block text-rose-100">Failed to load parks</span>
              <span className="text-xs text-rose-300">
                {error instanceof Error ? error.message : 'Unknown upstream error occurred'}
              </span>
            </div>
            <button
              onClick={() => refetch()}
              className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold transition-colors cursor-pointer"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* Empty State Badge */}
      {!isLoading && !isError && parks.length === 0 && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 bg-slate-900/90 border border-slate-800 px-4 py-2 rounded-xl text-xs text-slate-400 shadow-md">
          No wind parks registered in database.
        </div>
      )}

      {/* Slide-out List Drawer */}
      <ParkListDrawer
        isOpen={open === 'list'}
        onClose={close}
        parks={parks}
        selectedId={selectedId}
        onSelectPark={selectPark}
      />

      {/* Slide-out Details Drawer */}
      <ParkDetailsDrawer
        isOpen={open === 'details'}
        onClose={close}
        selectedPark={selectedPark}
      />
    </div>
  );
}
