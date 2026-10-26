const API_URL = import.meta.env.VITE_API_URL || './api.php';

export const developmentApi = {
  async activity(params = {}, signal) {
    const url = new URL(API_URL, window.location.href);
    url.searchParams.set('action', 'development');
    const savedIds = params.saved_ids;
    Object.entries(params).forEach(([key, value]) => {
      if (key === 'saved_ids') return;
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, Array.isArray(value) ? value.join(',') : String(value));
    });
    // A shortlist can contain 200 identifiers. Keep that read-only lookup out
    // of request-line limits without sending any other fields in the body.
    const request = savedIds ? { method: 'POST', body: new URLSearchParams({ saved_ids: Array.isArray(savedIds) ? savedIds.join(',') : String(savedIds) }) } : {};
    const response = await fetch(url, { ...request, headers: { Accept: 'application/json' }, signal });
    const payload = await response.json().catch(() => { throw new Error('Invalid construction activity response.'); });
    if (!response.ok || payload?.error) throw new Error(payload?.error || `Construction activity request failed (${response.status}).`);
    return payload;
  },
  async housingContext(signal) {
    const response = await fetch(new URL('./data/housing-context.json', window.location.href), { headers: { Accept: 'application/json' }, cache: 'no-cache', signal });
    if (!response.ok) throw new Error('Housing context is temporarily unavailable.');
    return response.json();
  },
};
