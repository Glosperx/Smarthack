import type { TurbineToday } from '../../api/hooks';
import { formatTurbine, statusDot } from './formatTurbine';

interface TurbineRowProps {
  turbine: TurbineToday;
}

/**
 * Single turbine diagnostic row with status indicator and formatted summary sentence.
 */
export function TurbineRow({ turbine }: TurbineRowProps) {
  const p = turbine.prediction;
  const sentence = formatTurbine(turbine);
  const dotColor = statusDot(p?.status);

  return (
    <div className="bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/60 transition-colors rounded-xl p-3.5 flex items-start gap-3">
      {/* Status Dot */}
      <div className="mt-1 flex-shrink-0 relative flex items-center justify-center">
        <span className={`w-2.5 h-2.5 rounded-full ${dotColor}`} />
        {p?.status && ['warning', 'watch', 'critical', 'fault', 'alarm'].includes(p.status.toLowerCase()) && (
          <span
            className={`absolute -inset-0.5 rounded-full opacity-75 animate-ping ${dotColor}`}
          />
        )}
      </div>

      {/* Turbine details */}
      <div className="flex-1 min-w-0">
        <div className="text-xs font-semibold text-slate-200 leading-snug break-words">
          {sentence}
        </div>
        {p && (
          <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
            <span className="font-mono">Subsystem: {p.suspected_subsystem}</span>
            <span>&bull;</span>
            <span className="font-mono">Entry #{p.entry_id}</span>
          </div>
        )}
      </div>

      {/* Probability Badge */}
      {p ? (
        <span
          className={`flex-shrink-0 text-xs font-mono font-semibold px-2 py-0.5 rounded-md ${
            p.daily_fault_probability >= 0.7
              ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
              : p.daily_fault_probability >= 0.3
              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
              : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
          }`}
        >
          {(p.daily_fault_probability * 100).toFixed(1)}%
        </span>
      ) : (
        <span className="flex-shrink-0 text-[11px] font-mono text-slate-500 px-2 py-0.5 rounded-md bg-slate-800/60 border border-slate-700/50">
          No data
        </span>
      )}
    </div>
  );
}
