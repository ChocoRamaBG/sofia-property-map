const API_URL = import.meta.env.VITE_API_URL || './api.php';

async function request(action, params = {}) {
  const url = new URL(API_URL, window.location.href);
  url.searchParams.set('action', action);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  });
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const payload = await response.json().catch(() => {
    throw new Error('The data service returned an invalid response.');
  });
  if (!response.ok || payload.error) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

export const realEstateApi = {
  meta: () => request('meta'),
  viewport: (bounds, recordType = 'all') => request('viewport', { ...bounds, record_type: recordType }),
  search: (query, recordType = 'all') => request('search', { q: query, record_type: recordType }),
  plot: (id) => request('plot', { id }),
};
