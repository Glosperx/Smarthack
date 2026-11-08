import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import type { components } from '../../types/api';

export type TransportSummary = components['schemas']['TransportSummary'];

/** One road piece: [class, verdict, reasons bitmask, ref index (-1 = none), flat lat/lon]. */
export type PackedRoad = [number, number, number, number, number[]];

/** The compact network served by `GET /api/transport/network`. */
export interface TransportNetwork {
  classes: string[];
  refs: string[];
  roads: PackedRoad[];
}

/** Verdict codes, as written by the backend (`smarthack/transport/constants.py`). */
export const VERDICT = { viable: 0, check: 1, blocked: 2, isolated: 3 } as const;

/** Colour and short name of each verdict, in drawing order (later = on top). */
export const VERDICT_STYLE: Record<number, { color: string; name: string; order: number }> = {
  [VERDICT.viable]: { color: '#16a34a', name: 'Viable', order: 0 },
  [VERDICT.isolated]: { color: '#94a3b8', name: 'Isolated', order: 1 },
  [VERDICT.check]: { color: '#f59e0b', name: 'To check', order: 2 },
  [VERDICT.blocked]: { color: '#dc2626', name: 'Blocked', order: 3 },
};

/** Line weight per OSM road class: the bigger the road, the thicker the line. */
export const CLASS_WEIGHT: Record<string, number> = {
  motorway: 4,
  trunk: 3.5,
  primary: 3,
  secondary: 2.25,
  tertiary: 1.5,
};

/** Readable names of the OSM road classes for Romania. */
export const CLASS_LABEL: Record<string, string> = {
  motorway: 'Motorway (A)',
  trunk: 'Expressway / main national road',
  primary: 'National road (DN)',
  secondary: 'National / secondary road',
  tertiary: 'County road (DJ)',
};

/**
 * Query hook for the network summary (vehicle, ports, km per verdict and reason).
 */
export function useTransportSummary(enabled: boolean) {
  return useQuery<TransportSummary>({
    queryKey: ['transport', 'summary'],
    queryFn: () => apiFetch<TransportSummary>('/api/transport/summary'),
    enabled,
    staleTime: Infinity,
  });
}

/**
 * Query hook for the whole judged road network (a few MB, fetched once).
 */
export function useTransportNetwork(enabled: boolean) {
  return useQuery<TransportNetwork>({
    queryKey: ['transport', 'network'],
    queryFn: () => apiFetch<TransportNetwork>('/api/transport/network'),
    enabled,
    staleTime: Infinity,
  });
}

/** Labels of the reasons set in a bitmask, using the summary's reason table. */
export function reasonLabels(mask: number, summary: TransportSummary): string[] {
  return summary.reasons.filter((r) => (mask & r.bit) !== 0).map((r) => r.label);
}
