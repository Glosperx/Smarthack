import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import type { components } from '../../types/api';

export type ResourceSummary = components['schemas']['ResourceSummary'];
export type ResourceSite = components['schemas']['ResourceSite'];
export type ResourcePoint = components['schemas']['ResourcePoint'];

/** URL of the heatmap overlay image served by the backend. */
export const HEATMAP_URL = '/api/resource/heatmap.png';

/** URL of the plain (below the hill band) heatmap overlay, same placement as the hill one. */
export const PLAIN_HEATMAP_URL = '/api/resource/heatmap-plain.png';

/**
 * Query hook for the wind atlas summary (bounds, legend, backtest, sources).
 */
export function useResourceSummary(enabled: boolean) {
  return useQuery<ResourceSummary>({
    queryKey: ['resource', 'summary'],
    queryFn: () => apiFetch<ResourceSummary>('/api/resource/summary'),
    enabled,
    staleTime: Infinity,
  });
}

/**
 * Query hook for the proposed wind park sites, best first.
 */
export function useResourceSites(enabled: boolean) {
  return useQuery<ResourceSite[]>({
    queryKey: ['resource', 'sites'],
    queryFn: () => apiFetch<ResourceSite[]>('/api/resource/sites'),
    enabled,
    staleTime: Infinity,
  });
}

/**
 * Query hook for the proposed plain wind park sites, windiest first.
 */
export function usePlainSites(enabled: boolean) {
  return useQuery<ResourceSite[]>({
    queryKey: ['resource', 'sites', 'plain'],
    queryFn: () => apiFetch<ResourceSite[]>('/api/resource/sites/plain'),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
}

/**
 * Query hook for the atlas answer at a clicked point.
 */
export function useResourcePoint(point: { lat: number; lng: number } | null) {
  return useQuery<ResourcePoint>({
    queryKey: ['resource', 'point', point?.lat, point?.lng],
    queryFn: () =>
      apiFetch<ResourcePoint>(
        `/api/resource/point?lat=${point!.lat.toFixed(5)}&lon=${point!.lng.toFixed(5)}`
      ),
    enabled: point !== null,
    staleTime: Infinity,
  });
}

/** Format a relative change such as 0.014 as "+1.4%". */
export function formatChange(change: number): string {
  const pct = change * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
}
