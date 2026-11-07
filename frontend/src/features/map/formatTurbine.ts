import type { TurbineToday } from '../../api/hooks';

/**
 * Formats a turbine and its prediction into the required display sentence:
 * `Turbine {id}, status {status}, {daily_fault_probability}% for {suspected_subsystem}`
 * or `Turbine {id}, no prediction for today`.
 */
export function formatTurbine(t: TurbineToday): string {
  const p = t.prediction;
  if (!p) return `Turbine ${t.id}, no prediction for today`;
  const pct = (p.daily_fault_probability * 100).toFixed(1);
  if (!p.suspected_subsystem || p.suspected_subsystem.toLowerCase() === 'none') {
    return `Turbine ${t.id}, status ${p.status}, ${pct}%`;
  }
  return `Turbine ${t.id}, status ${p.status}, ${pct}% for ${p.suspected_subsystem}`;
}

const STATUS_DOT: Record<string, string> = {
  ok: 'bg-emerald-500',
  healthy: 'bg-emerald-500',
  normal: 'bg-emerald-500',
  warning: 'bg-amber-500',
  watch: 'bg-amber-500',
  critical: 'bg-rose-500',
  fault: 'bg-rose-500',
  alarm: 'bg-rose-500',
};

/**
 * Returns Tailwind background color class corresponding to diagnostic health status.
 */
export const statusDot = (status?: string | null): string =>
  STATUS_DOT[status?.toLowerCase() ?? ''] ?? 'bg-slate-400';
