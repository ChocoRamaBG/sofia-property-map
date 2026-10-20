const API_URL = import.meta.env.VITE_MARKET_API_URL || './market.php';

async function request(action, params = {}, signal) {
  const url = new URL(API_URL, window.location.href);
  url.searchParams.set('action', action);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  });
  const response = await fetch(url, { headers: { Accept: 'application/json' }, signal });
  const payload = await response.json().catch(() => { throw new Error('Invalid market data response.'); });
  if (!response.ok || payload?.error) throw new Error(payload?.error || `Market request failed (${response.status}).`);
  return payload;
}

export const marketApi = {
  summary: (signal) => request('summary', {}, signal),
  listings: (params = {}, signal) => request('listings', params, signal),
  viewport: (params = {}, signal) => request('viewport', params, signal),
};
