import { propertyFilterParams } from '@/lib/propertyFilters';

const API_URL = import.meta.env.VITE_API_URL || './api.php';

async function request(action, params = {}, signal) {
  const url = new URL(API_URL, window.location.href);
  url.searchParams.set('action', action);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  });
  const response = await fetch(url, { headers: { Accept: 'application/json' }, signal });
  const payload = await response.json().catch(() => {
    throw new Error('The data service returned an invalid response.');
  });
  if (!response.ok || payload.error) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

export const realEstateApi = {
  meta: () => request('meta'),
  viewport: (bounds, filters = {}, signal) => request('viewport', { ...bounds, ...propertyFilterParams(filters) }, signal),
  boundaries: (bounds, filters = {}, signal) => request('boundaries', { ...bounds, ...propertyFilterParams(filters) }, signal),
  search: (query, filters = {}, signal) => {
    const params = propertyFilterParams(filters);
    return request('search', { ...(!params.search_terms && query ? { q: query } : {}), ...params }, signal);
  },
  plot: (id) => request('plot', { id }),
};
