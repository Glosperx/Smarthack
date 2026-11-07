/**
 * Typed HTTP fetch wrapper for FastAPI backend requests.
 * Throws an Error with backend response details on non-2xx status codes.
 */
export async function apiFetch<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const response = await fetch(endpoint, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorJson = await response.json();
      if (errorJson?.detail) {
        detail = typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch {
      // Fallback to response.statusText if json body is missing or unparseable
    }
    throw new Error(`API ${response.status}: ${detail}`);
  }

  return response.json() as Promise<T>;
}
