import { useState } from 'react';
import { VERDICT_STYLE, type TransportSummary } from './api';

interface TransportPanelProps {
  enabled: boolean;
  onToggle: () => void;
  summary: TransportSummary | undefined;
  isLoading: boolean;
  error: unknown;
  visible: Set<number>;
  onToggleVerdict: (code: number) => void;
  showCounty: boolean;
  onToggleCounty: () => void;
}

/**
 * Floating panel (bottom-right) that toggles the oversize transport network, shows its
 * legend with kilometres per verdict, and explains what the map can and cannot tell.
 */
export function TransportPanel({
  enabled,
  onToggle,
  summary,
  isLoading,
  error,
  visible,
  onToggleVerdict,
  showCounty,
  onToggleCounty,
}: TransportPanelProps) {
  const [showDetails, setShowDetails] = useState(false);
  const total = summary?.total_km ?? 0;

  return (
    <div className="absolute bottom-8 right-4 z-20 w-[min(20rem,calc(100vw-2rem))] max-h-[calc(100vh-7rem)] flex flex-col rounded-xl border border-slate-700/80 bg-slate-900/95 text-slate-100 shadow-2xl backdrop-blur-md">
      <button
        onClick={onToggle}
        aria-pressed={enabled}
        className="flex items-center justify-between gap-3 px-4 py-3 text-left cursor-pointer rounded-xl hover:bg-slate-800/60 focus:outline-none focus:ring-2 focus:ring-sky-400"
      >
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Oversize transport
          </div>
          <div className="text-sm font-semibold">Roads for turbine convoys</div>
        </div>
        <span
          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors ${
            enabled ? 'bg-sky-500' : 'bg-slate-600'
          }`}
        >
          <span
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
              enabled ? 'translate-x-4' : 'translate-x-0.5'
            }`}
          />
        </span>
      </button>

      {enabled && (
        <div className="overflow-y-auto px-4 pb-4 space-y-3 border-t border-slate-800 pt-3">
          {isLoading && <p className="text-xs text-slate-400">Loading the road network…</p>}
          {error != null && (
            <p className="text-xs text-rose-300">
              {error instanceof Error ? error.message : 'Could not load the network.'}
            </p>
          )}
          {summary && (
            <>
              <p className="text-[11px] leading-snug text-slate-300">
                Judged for a 2.4–3 MW turbine: {summary.vehicle.length_m.toFixed(0)} m long with
                the blade, {summary.vehicle.height_m} m high, {summary.vehicle.width_m} m wide,{' '}
                {summary.vehicle.gross_t.toFixed(0)} t. Reachability from{' '}
                {summary.ports.map((p) => p.name.replace('Port ', '')).join(', ')}.
              </p>

              <ul className="space-y-1">
                {[...summary.verdicts]
                  .sort((a, b) => VERDICT_STYLE[a.code].order - VERDICT_STYLE[b.code].order)
                  .map((v) => {
                    const style = VERDICT_STYLE[v.code];
                    const on = visible.has(v.code);
                    return (
                      <li key={v.code}>
                        <label className="flex items-center gap-2 cursor-pointer text-xs">
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => onToggleVerdict(v.code)}
                            className="accent-sky-500"
                          />
                          <span
                            className="h-1.5 w-5 rounded-full"
                            style={{ backgroundColor: style.color, opacity: on ? 1 : 0.35 }}
                          />
                          <span className={on ? 'text-slate-100' : 'text-slate-500'}>
                            {style.name}
                          </span>
                          <span className="ml-auto font-mono text-[11px] text-slate-400">
                            {Math.round(v.km).toLocaleString()} km
                            {total > 0 && ` · ${((v.km / total) * 100).toFixed(0)}%`}
                          </span>
                        </label>
                      </li>
                    );
                  })}
              </ul>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={showCounty}
                  onChange={onToggleCounty}
                  className="accent-sky-500"
                />
                Show county roads (DJ)
              </label>

              <p className="text-[11px] text-slate-400">
                Click a road to see why it got its colour.
              </p>

              <button
                onClick={() => setShowDetails((v) => !v)}
                className="text-[11px] font-semibold text-sky-300 hover:text-sky-200 cursor-pointer"
              >
                {showDetails ? 'Hide' : 'What drives the colours?'}
              </button>

              {showDetails && (
                <div className="space-y-2 text-[11px] leading-snug text-slate-300">
                  <table className="w-full font-mono">
                    <tbody>
                      {[...summary.reasons]
                        .filter((r) => r.km > 0)
                        .sort((a, b) => b.km - a.km)
                        .map((r) => (
                          <tr key={r.bit}>
                            <td className="py-0.5 pr-2 font-sans">
                              <span className={r.blocking ? 'text-rose-300' : 'text-amber-200'}>
                                {r.blocking ? '■ ' : '▲ '}
                              </span>
                              {r.label}
                            </td>
                            <td className="text-right whitespace-nowrap">
                              {Math.round(r.km).toLocaleString()} km
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  <ul className="list-disc pl-4 space-y-1 text-slate-400">
                    {summary.caveats.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                  <ul className="space-y-0.5 text-slate-400">
                    {summary.sources.map((s) => (
                      <li key={s.name}>
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="underline hover:text-white"
                        >
                          {s.name}
                        </a>{' '}
                        · {s.license}
                        {summary.osm_extract_date &&
                          ` · data of ${new Date(summary.osm_extract_date).toLocaleDateString()}`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
