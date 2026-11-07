import { useState } from 'react';
import { formatChange, type ResourceSite, type ResourceSummary } from './api';

interface WindResourcePanelProps {
  enabled: boolean;
  onToggle: () => void;
  summary: ResourceSummary | undefined;
  sites: ResourceSite[];
  isLoading: boolean;
  error: unknown;
  focusedRank: number | null;
  onFocusSite: (rank: number) => void;
}

/** Readable names of the forecasting methods the backtest compares. */
const ESTIMATOR_LABELS: Record<string, string> = {
  persistence: 'Last year (persistence)',
  climatology_all: 'Mean of all years',
  climatology_10y: 'Mean of last 10 years',
  climatology_5y: 'Mean of last 5 years',
  exp_weighted_8y: 'Exponentially weighted mean',
  linear_trend_15y: '15-year linear trend',
  learned_blend: 'Learned blend (ridge)',
};

/**
 * Horizontal colour bar with its end values.
 */
function Legend({ summary }: { summary: ResourceSummary }) {
  const { vmin, vmax, colors } = summary.legend;
  const mid = (vmin + vmax) / 2;
  return (
    <div>
      <div className="flex items-baseline justify-between text-[11px] text-slate-300">
        <span>Forecast mean wind at 100 m</span>
        <span className="text-slate-400">m/s</span>
      </div>
      <div
        className="mt-1 h-2.5 w-full rounded-sm"
        style={{ backgroundImage: `linear-gradient(to right, ${colors.join(', ')})` }}
      />
      <div className="mt-0.5 flex justify-between font-mono text-[11px] text-slate-300">
        <span>≤{vmin.toFixed(1)}</span>
        <span>{mid.toFixed(1)}</span>
        <span>≥{vmax.toFixed(1)}</span>
      </div>
    </div>
  );
}

/**
 * Backtest table: how each method did on years it never saw.
 */
function MethodCard({ summary }: { summary: ResourceSummary }) {
  return (
    <div className="space-y-2 text-[11px] leading-snug text-slate-300">
      <p>
        Wind {summary.target_years[0]}–{summary.target_years[1]} = Global Wind Atlas 250 m terrain
        detail ({summary.reference_years[0]}–{summary.reference_years[1]}) × forecast change from
        NASA POWER 1981–{summary.data_until}. Method chosen on {summary.validation_years[0]}–
        {summary.validation_years[1]}, scored on held-out {summary.test_years[0]}–
        {summary.test_years[1]}.
      </p>
      <table className="w-full font-mono">
        <thead>
          <tr className="text-slate-400">
            <th className="text-left font-normal">Method</th>
            <th className="text-right font-normal">Test MAE</th>
          </tr>
        </thead>
        <tbody>
          {summary.backtest.map((row) => (
            <tr key={row.estimator} className={row.selected ? 'text-white font-semibold' : ''}>
              <td className="py-0.5 pr-2 font-sans">
                {row.selected ? '▸ ' : ''}
                {ESTIMATOR_LABELS[row.estimator] ?? row.estimator}
              </td>
              <td className="text-right">
                {row.mae_test.toFixed(2)} m/s ({(row.mape_test * 100).toFixed(1)}%)
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        80% band {formatChange(summary.band_low_pct)} / {formatChange(summary.band_high_pct)}: held
        true {(summary.band_coverage_test * 100).toFixed(0)}% of the time on the test years. Area
        ranking stability (Spearman) {summary.rank_correlation_test.toFixed(3)}.
      </p>
      <p className="text-slate-400">
        Hills {summary.elevation_band_m[0]}–{summary.elevation_band_m[1]} m:{' '}
        {Math.round(summary.hill_area_km2).toLocaleString()} km², of which{' '}
        {Math.round(summary.buildable_area_km2).toLocaleString()} km² with slope ≤{' '}
        {summary.max_slope_deg}°.
      </p>
      <ul className="space-y-0.5 text-slate-400">
        {summary.sources.map((s) => (
          <li key={s.name}>
            <a href={s.url} target="_blank" rel="noreferrer" className="underline hover:text-white">
              {s.name}
            </a>{' '}
            · {s.license}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Floating panel (bottom-left) that toggles the hill wind atlas and lists the best sites.
 */
export function WindResourcePanel({
  enabled,
  onToggle,
  summary,
  sites,
  isLoading,
  error,
  focusedRank,
  onFocusSite,
}: WindResourcePanelProps) {
  const [showMethod, setShowMethod] = useState(false);

  return (
    <div className="absolute bottom-6 left-4 z-20 w-[min(22rem,calc(100vw-2rem))] max-h-[calc(100vh-7rem)] flex flex-col rounded-xl border border-slate-700/80 bg-slate-900/95 text-slate-100 shadow-2xl backdrop-blur-md">
      <button
        onClick={onToggle}
        aria-pressed={enabled}
        className="flex items-center justify-between gap-3 px-4 py-3 text-left cursor-pointer rounded-xl hover:bg-slate-800/60 focus:outline-none focus:ring-2 focus:ring-sky-400"
      >
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Site finder
          </div>
          <div className="text-sm font-semibold">
            Best hill wind{' '}
            {summary ? `${summary.target_years[0]}–${summary.target_years[1]}` : 'next 2 years'}
          </div>
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
        <div className="overflow-y-auto px-4 pb-4 space-y-3">
          {isLoading && <p className="text-xs text-slate-400">Loading the wind atlas…</p>}
          {Boolean(error) && (
            <p className="text-xs text-rose-300">
              {error instanceof Error ? error.message : 'Could not load the wind atlas.'}
            </p>
          )}
          {summary && (
            <>
              <Legend summary={summary} />
              <p className="text-[11px] text-slate-400">
                Colour shows hills between {summary.elevation_band_m[0]} and{' '}
                {summary.elevation_band_m[1]} m. Click anywhere for the local forecast.
              </p>
              <ol className="space-y-1">
                {sites.map((site) => (
                  <li key={site.rank}>
                    <button
                      onClick={() => onFocusSite(site.rank)}
                      className={`w-full flex items-center gap-3 rounded-lg px-2 py-1.5 text-left cursor-pointer transition-colors ${
                        site.rank === focusedRank ? 'bg-slate-700' : 'hover:bg-slate-800'
                      }`}
                    >
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-bold text-slate-900">
                        {site.rank}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium">
                          {site.name ?? `${site.latitude.toFixed(2)}, ${site.longitude.toFixed(2)}`}
                        </span>
                        <span className="block text-[11px] text-slate-400">
                          {site.elevation_m.toFixed(0)} m · top {(100 - site.percentile).toFixed(1)}%
                          of hills
                        </span>
                      </span>
                      <span className="text-right font-mono">
                        <span className="block text-sm font-semibold">
                          {site.wind_p50.toFixed(1)}
                        </span>
                        <span className="block text-[10px] text-slate-400">m/s</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
              <button
                onClick={() => setShowMethod((v) => !v)}
                className="text-[11px] font-semibold text-sky-300 hover:text-sky-200 cursor-pointer"
              >
                {showMethod ? 'Hide method & backtest' : 'How is this forecast made?'}
              </button>
              {showMethod && <MethodCard summary={summary} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}
