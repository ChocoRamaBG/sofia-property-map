const ADDRESS_API_URL = import.meta.env.VITE_ADDRESS_API_URL || './geocode.php';

export class AddressLookupError extends Error {
  constructor(code = 'unavailable', retryAfter = null) {
    super(code);
    this.name = 'AddressLookupError';
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

export const addressApi = {
  async meta(signal) {
    const url = new URL(ADDRESS_API_URL, window.location.href);
    url.searchParams.set('action', 'meta');
    const response = await fetch(url, { headers: { Accept: 'application/json' }, signal });
    const payload = await response.json().catch(() => { throw new AddressLookupError(); });
    if (!response.ok || !payload.provider) throw new AddressLookupError();
    return payload.provider;
  },
  async search(query, lang = 'bg', signal) {
    const response = await fetch(new URL(ADDRESS_API_URL, window.location.href), {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ q: query.trim(), lang: lang === 'en' ? 'en' : 'bg' }),
      signal,
    });
    const payload = await response.json().catch(() => { throw new AddressLookupError(); });
    if (!response.ok || payload.error) throw new AddressLookupError(payload.error || 'unavailable', payload.retry_after);
    if (!Array.isArray(payload.results) || payload.results.length > 5) throw new AddressLookupError();
    return payload;
  },
};
