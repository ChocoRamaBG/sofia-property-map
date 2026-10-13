import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Loader2, MapPin, Search, X } from 'lucide-react';
import { addressApi } from '@/api/addressApi';
import { useI18n } from '@/lib/i18n';

function streetOnlyQuery(value) {
  // Offer a user-controlled fallback only for a simple street + house number.
  // Block numbers, entrances, floors and apartment numbers are not street numbers.
  if (/(?:^|\s)(?:бл\.?|блок|ж\.?\s*к\.?|кв\.?|квартал|вх\.?|вход|ет\.?|етаж|ап\.?|апартамент)(?:\s|\.|$)/iu.test(value)) return null;
  const city = value.match(/(?:,\s*|\s+)(?:София|Sofia)(?:\s*,\s*(?:България|Bulgaria))?\s*$/iu);
  const suffix = city ? value.slice(city.index) : '';
  const street = (city ? value.slice(0, city.index) : value).trim();
  if (street.includes(',')) return null;
  let withoutNumber = street.replace(/(?:\s+|\s*№\s*)[0-9]{1,4}(?:\s*[a-zа-я])?\s*$/iu, '').trim();
  if (withoutNumber === street) withoutNumber = street.replace(/^[0-9]{1,4}[a-zа-я]?\s+(?=\p{L})/iu, '').trim();
  if (withoutNumber === street || Array.from(withoutNumber).length < 3) return null;
  return `${withoutNumber}${suffix}`;
}

/** Location lookup only. Selecting an OSM address never links a cadastral record. */
export default function AddressSearch({ onSelectLocation, selectedLocation = null, onClearLocation, externalRequest, isRequestCurrent, onRequestHandled, onLookupStart, onProviderChange }) {
  const { lang, pick } = useI18n();
  const helpId = useId();
  const [query, setQuery] = useState(() => selectedLocation?.query || '');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [provider, setProvider] = useState(null);
  const [providerError, setProviderError] = useState(false);
  const [providerRevision, setProviderRevision] = useState(0);
  const requestRef = useRef(null);
  const externalRequestRef = useRef(null);
  const queryLength = Array.from(query.trim()).length;
  const tooLong = queryLength > 160;
  const canSubmit = provider?.enabled && !loading && queryLength >= 3 && !tooLong;

  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setProviderError(false);
    addressApi.meta(controller.signal).then((next) => {
      if (!controller.signal.aborted) setProvider(next);
    }).catch(() => {
      if (!controller.signal.aborted) setProviderError(true);
    });
    return () => controller.abort();
  }, [providerRevision]);
  useEffect(() => { if (provider) onProviderChange?.(provider); }, [provider, onProviderChange]);

  const lookup = useCallback(async (nextQuery) => {
    if (!provider?.enabled) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const navigation = onLookupStart?.();
    setSubmittedQuery(nextQuery.trim());
    setLoading(true);
    setResults([]);
    setError(null);
    try {
      const response = await addressApi.search(nextQuery, lang, controller.signal);
      if (!controller.signal.aborted) {
        setResults(response.results);
        setProvider(response.provider);
        // Multiple names at exactly the same location can describe one address.
        // Distinct locations retain the chooser instead of selecting a guess.
        const locationKeys = new Set(response.results.map((result) => [result.lat, result.lng, result.precision,
          ...['south', 'north', 'west', 'east'].map((key) => result.bounds?.[key] ?? '')].map((value) => typeof value === 'number' ? value.toFixed(6) : value).join('|')));
        if (response.results.length > 0 && locationKeys.size === 1) onSelectLocation?.({ ...response.results[0], query: nextQuery.trim() }, navigation);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure.code || 'unavailable');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [provider?.enabled, lang, onLookupStart, onSelectLocation]);

  useEffect(() => {
    if (!externalRequest || externalRequestRef.current === externalRequest.id) return;
    if (isRequestCurrent && !isRequestCurrent(externalRequest)) { externalRequestRef.current = externalRequest.id; onRequestHandled?.(externalRequest.id); return; }
    const nextQuery = externalRequest.query.trim();
    setQuery(nextQuery);
    requestRef.current?.abort();
    setLoading(false);
    setResults([]);
    setError(null);
    setSubmittedQuery('');
    if (!provider && !providerError) return;
    externalRequestRef.current = externalRequest.id;
    onRequestHandled?.(externalRequest.id);
    if (provider?.enabled) lookup(nextQuery);
    else { setSubmittedQuery(nextQuery); setError('unavailable'); }
  }, [externalRequest, isRequestCurrent, provider, providerError, lookup, onRequestHandled]);

  const submit = (event) => {
    event.preventDefault();
    if (canSubmit) lookup(query.trim());
  };

  const clear = () => {
    if (externalRequest) { externalRequestRef.current = externalRequest.id; onRequestHandled?.(externalRequest.id); }
    requestRef.current?.abort();
    requestRef.current = null;
    setQuery('');
    setSubmittedQuery('');
    setResults([]);
    setLoading(false);
    setError(null);
    onClearLocation?.();
  };

  const errorText = error === 'busy' || error === 'rate_limited'
    ? pick('Търсенето е натоварено. Опитайте отново след малко.', 'Address search is busy. Please try again shortly.')
    : error === 'invalid_query'
      ? pick('Въведете адрес с 3 до 160 знака.', 'Enter an address using 3 to 160 characters.')
      : pick('Търсенето по адрес временно не е достъпно. Опитайте отново по-късно.', 'Address search is temporarily unavailable. Please try again later.');
  const streetFallback = !loading && !error && submittedQuery && results.length === 0 ? streetOnlyQuery(submittedQuery) : null;

  return (
    <section className="address-search rounded-xl border border-emerald-100 bg-emerald-50/40 p-4" aria-label={pick('Намери адрес на картата', 'Find an address on the map')}>
      <div className="mb-2 flex items-center gap-2 text-emerald-800">
        <MapPin size={17} aria-hidden="true" />
        <h2 className="text-sm font-semibold">{pick('Намери адрес', 'Find an address')}</h2>
      </div>
      <p className="mb-3 text-xs leading-relaxed text-slate-600">{pick('Въведете улица и номер в София, за да се придвижите до мястото.', 'Enter a Sofia street and house number to move the map to that location.')}</p>
      <form onSubmit={submit}>
        <label className="search-input-wrap">
          <Search size={17} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={pick('Напр. ул. Алабин 20, София', 'e.g. 20 Alabin Street, Sofia')} aria-label={pick('Адрес в София', 'Address in Sofia')} aria-describedby={helpId} aria-invalid={tooLong || undefined} autoComplete="off" />
          {query && <button type="button" onClick={clear} aria-label={pick('Изчисти адреса', 'Clear address')}><X size={15} aria-hidden="true" /></button>}
        </label>
        <button type="submit" className="search-submit" disabled={!canSubmit}>
          {loading ? <Loader2 size={17} className="animate-spin" aria-hidden="true" /> : <MapPin size={17} aria-hidden="true" />}
          {loading ? pick('Търсене на адрес…', 'Finding address…') : pick('Намери на картата', 'Find on map')}
          {!loading && <ArrowRight size={16} className="ml-auto" aria-hidden="true" />}
        </button>
      </form>
      <p id={helpId} className="mt-2 text-[10px] leading-relaxed text-slate-500">{provider && <>{pick('При натискане на „Намери“ адресът се изпраща към ', 'When you press Find, the address is sent to ')}<strong className="font-medium">{provider.label}</strong>. </>}</p>
      {providerError || provider?.enabled === false ? <div className="mt-2 text-xs leading-relaxed text-slate-600" role="status"><p>{pick('Търсенето по адрес временно не е достъпно.', 'Address search is temporarily unavailable.')}</p><button type="button" className="min-h-11 text-emerald-800 underline underline-offset-2" onClick={() => setProviderRevision((value) => value + 1)}>{pick('Опитай отново', 'Retry')}</button></div> : !provider && <p className="mt-2 text-xs text-slate-500" role="status">{pick('Подготовка на търсенето по адрес…', 'Preparing address search…')}</p>}
      {tooLong && <p className="mt-2 text-xs text-red-700" role="status">{pick('Адресът може да съдържа до 160 знака.', 'The address can contain up to 160 characters.')}</p>}
      {submittedQuery && <div className="mt-3" aria-live="polite" aria-busy={loading}>
        {loading ? <p className="flex items-center gap-2 text-xs text-emerald-800" role="status"><Loader2 size={14} className="animate-spin" aria-hidden="true" />{pick('Търсене на адрес в София…', 'Looking up a Sofia address…')}</p>
          : error ? <p className="text-xs leading-relaxed text-red-700" role="alert">{errorText}</p>
            : results.length === 0 ? <>
              <p className="text-xs leading-relaxed text-slate-600">{pick('Не е намерен адрес. Опитайте с пълно име на улицата и номер. Някои адреси липсват в OpenStreetMap.', 'No address found. Try the full street name and house number. Some addresses are missing from OpenStreetMap.')}</p>
              {streetFallback && <div className="mt-2 rounded-lg border border-emerald-200 bg-white p-3">
                <p className="text-[10px] leading-relaxed text-slate-600">{pick('Можете да потърсите улицата без номера. Резултатът ще показва улица, а не точния адрес.', 'You can look up the street without the house number. The result will locate the street, not the exact address.')}</p>
                <button type="button" className="mt-1 flex min-h-11 items-center gap-2 text-xs font-medium text-emerald-800 underline underline-offset-2" onClick={() => lookup(streetFallback)}><MapPin size={14} aria-hidden="true" />{pick('Намери само улицата', 'Find street only')}</button>
                <p className="text-[10px] leading-relaxed text-slate-500">{streetFallback}</p>
              </div>}
            </>
              : <>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-emerald-800">{pick('Изберете място', 'Choose a location')}</p>
                <ul className="space-y-2">{results.map((result) => <li key={result.id}>
                  <button type="button" onClick={() => onSelectLocation?.({ ...result, query: submittedQuery })} className={`flex min-h-12 w-full items-start gap-2 rounded-lg border p-3 text-left transition-colors hover:border-emerald-400 focus-visible:outline-emerald-600 ${selectedLocation?.id === result.id ? 'border-emerald-400 bg-emerald-100/70' : 'border-emerald-100 bg-white'}`}>
                    <MapPin size={17} className="mt-0.5 shrink-0 text-emerald-700" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <strong className="block text-xs font-medium leading-relaxed text-slate-800">{result.label}</strong>
                      <small className="mt-1 block text-[10px] leading-relaxed text-slate-500">{result.precision === 'address' ? pick('Адресна точка · приблизително местоположение', 'Address point · approximate location') : result.precision === 'street' ? pick('Улица · номерът не е потвърден', 'Street · house number is not confirmed') : pick('Район или населено място · приблизително местоположение', 'Area or settlement · approximate location')}</small>
                    </span>
                    <ArrowUpRight size={14} className="mt-1 shrink-0 text-slate-400" aria-hidden="true" />
                  </button>
                </li>)}</ul>
              </>}
      </div>}
      {selectedLocation && <div className="mt-3 rounded-lg border border-emerald-200 bg-white p-3">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-800">{pick('Показано на картата', 'Shown on map')}</p>
        <p className="mt-1 text-xs leading-relaxed text-slate-700">{selectedLocation.label}</p>
        <button type="button" className="mt-1 inline-flex min-h-11 items-center gap-1 text-xs text-emerald-800 underline underline-offset-2" onClick={() => onClearLocation?.()}><X size={13} aria-hidden="true" />{pick('Премахни адресния маркер', 'Remove address marker')}</button>
      </div>}
      <p className="mt-3 text-[10px] leading-relaxed text-slate-600">{pick('Адресният маркер служи за ориентация. Изберете отделно кадастрална точка за официалните данни; адресът не доказва връзка с имот.', 'The address marker helps you navigate. Select a cadastral point separately for official records; an address does not establish a parcel match.')}</p>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
        <a className="underline underline-offset-2" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors · ODbL</a>
        {provider && <>
          <a className="underline underline-offset-2" href={provider.policy_url} target="_blank" rel="noopener noreferrer">{pick('Условия на услугата', 'Service usage policy')}</a>
          <a className="underline underline-offset-2" href={provider.privacy_url} target="_blank" rel="noopener noreferrer">{pick('Поверителност на услугата', 'Service privacy policy')}</a>
        </>}
      </div>
    </section>
  );
}
