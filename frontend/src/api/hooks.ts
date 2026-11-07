import { useQuery } from '@tanstack/react-query';
import { apiFetch } from './client';
import type { components, operations } from '../types/api';

export type HealthResponse =
  operations['health_check_api_health_get']['responses'][200]['content']['application/json'];

export type ExampleResult = components['schemas']['ExampleResult'];

/**
 * Query hook for application health check.
 */
export function useHealthQuery() {
  return useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => apiFetch<HealthResponse>('/api/health'),
  });
}

/**
 * Query hook for the example upstream search endpoint.
 */
export function useExampleQuery(query: string) {
  return useQuery<ExampleResult>({
    queryKey: ['example', query],
    queryFn: () =>
      apiFetch<ExampleResult>(`/api/example?q=${encodeURIComponent(query)}`),
    enabled: Boolean(query.trim()),
  });
}
