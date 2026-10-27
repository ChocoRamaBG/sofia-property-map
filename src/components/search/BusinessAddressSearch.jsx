import React, { useEffect, useId, useRef, useState } from 'react';
import { ArrowUpRight, Building2, ChevronDown, Loader2, MapPin, Search, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import './BusinessAddressSearch.css';

export function createBusinessSearchState() {
  return { query: '', submitted: '', data: null, error: false, open: false };
}

async function readBusinessData(action, params, signal) {
  const url = new URL('./business-data.php', window.location.href);
  url.searchParams.set('action', action);
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, String(value)));
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error('Business address data unavailable');
  return payload;
}

export default function BusinessAddressSearch({ onSelect, lang: language, state: controlledState, onStateChange }) {
  const i18n = useI18n();
  const lang = language || i18n.lang;
  const pick = (bg, en) => lang === 'bg' ? bg : en;
  const [localState, setLocalState] = useState(createBusinessSearchState);
  const state = controlledState || localState;
  const setState = onStateChange || setLocalState;
  const [loading, setLoading] = useState(false);
  const [metadata, setMetadata] = useState(null);
  const [opening, setOpening] = useState(null);
  const [navigationError, setNavigationError] = useState(false);
  const requestRef = useRef(null);
  const mountedRef = useRef(false);
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const length = Array.from((state.query || '').trim()).length;
  const canSubmit = length >= 2 && length <= 120 && !loading;
  const countLabel = (number) => Number(number).toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB');

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; requestRef.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!state.open || metadata) return undefined;
    const controller = new AbortController();
    readBusinessData('meta', {}, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setMetadata(data); })
      .catch(() => { /* A manual search shows service failures without blocking the main property search. */ });
    return () => controller.abort();
  }, [state.open, metadata]);

  async function submit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const query = state.query.trim();
    setLoading(true);
    setNavigationError(false);
    setState((previous) => ({ ...previous, submitted: query, data: null, error: false }));
    try {
      const data = await readBusinessData('search', { q: query }, controller.signal);
      if (controller.signal.aborted) return;
      if (!Array.isArray(data.results) || !Number.isSafeInteger(data.total) || data.total < data.results.length) throw new Error('Invalid search response');
      setState((previous) => ({ ...previous, submitted: query, data, error: false }));
    } catch {
      if (!controller.signal.aborted) setState((previous) => ({ ...previous, submitted: query, data: null, error: true }));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  function clear() {
    requestRef.current?.abort();
    setLoading(false);
    setNavigationError(false);
    setState((previous) => ({ ...previous, query: '', submitted: '', data: null, error: false }));
  }

  async function select(result) {
    const targetId = result.cadastral_id || result.address_id;
    if (opening || !onSelect || !/^(?:68134\.\d{1,6}\.\d{1,6}|address-[a-f0-9]{24})$/.test(targetId || '')) return;
    setOpening(result.uic);
    setNavigationError(false);
    try {
      await onSelect(targetId, result);
    } catch {
      if (mountedRef.current) setNavigationError(true);
    } finally {
      if (mountedRef.current) setOpening(null);
    }
  }

  const data = state.data;
  const coverage = data?.coverage || metadata?.coverage || metadata || {};
  const counts = coverage.counts || {};
  const candidates = counts.sofia_candidates;
  const matched = counts.located_companies ?? counts.matched_companies;
  const matchedParcels = counts.matched_parcels;
  const results = Array.isArray(data?.results) ? data.results.slice(0, 40) : [];
  return (
    <details className="business-address-search" open={Boolean(state.open)} onToggle={(event) => {
      const open = event.currentTarget.open;
      if (open !== Boolean(state.open)) setState((previous) => ({ ...previous, open }));
    }}>
      <summary><Building2 size={17} aria-hidden="true" /><span>{pick('Намерете фирмен адрес на картата', 'Find a registered business address')}<small>{pick('По име на фирма или ЕИК', 'By company name or UIC')}</small></span><ChevronDown size={16} aria-hidden="true" /></summary>
      <div className="business-address-search-body">
        <p id={hintId}>{pick('Търси фирми с установен регистриран адрес. Резултатът отваря парцела или официалната адресна точка; строителните филтри се запазват.', 'Find companies with an established registered address. A result opens its parcel or official address point; construction filters are retained.')}</p>
        <form onSubmit={submit}>
          <label htmlFor={inputId}>{pick('Фирма или ЕИК', 'Company name or UIC')}</label>
          <div className="business-address-search-input"><Search size={16} aria-hidden="true" /><input id={inputId} value={state.query || ''} onChange={(event) => setState((previous) => ({ ...previous, query: event.target.value }))} placeholder={pick('Име или 9-цифрен ЕИК…', 'Name or 9-digit UIC…')} aria-describedby={hintId} aria-invalid={length > 120 || undefined} />{(state.query || state.submitted) && <button type="button" onClick={clear} aria-label={pick('Изчисти фирменото търсене', 'Clear the business search')}><X size={15} aria-hidden="true" /></button>}</div>
          <button className="business-address-search-submit" type="submit" disabled={!canSubmit}>{loading ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <MapPin size={15} aria-hidden="true" />}{pick(loading ? 'Търсене…' : 'Намери адреса', loading ? 'Searching…' : 'Find the address')}</button>
        </form>
        {length > 120 && <p role="status">{pick('Използвайте до 120 знака.', 'Use up to 120 characters.')}</p>}
        <div className="business-address-search-results" aria-live="polite" aria-busy={loading}>
          {loading ? <p role="status">{pick('Проверка на фирмените адреси…', 'Checking registered addresses…')}</p> : state.error ? <p role="status">{pick('Фирмените адреси временно не са достъпни. Опитайте отново.', 'Business addresses are temporarily unavailable. Please try again.')}</p> : data && <>
            <div className="business-address-search-count"><strong>{countLabel(data.total)} {pick('фирми', 'companies')}</strong><span>{state.submitted}</span></div>
            {results.length === 0 ? <p>{pick('Няма еднозначно свързан адрес за това търсене. Фирмата може да липсва от извлечението или адресът ѝ да е непълен/нееднозначен.', 'No unambiguous address match was found. The company may be absent from the extract or its address may be incomplete or ambiguous.')}</p> : <>
              {(data.truncated || data.total > results.length) && <p>{pick(`Показани са първите ${results.length} от ${countLabel(data.total)} фирми. Уточнете името за по-тесен резултат.`, `Showing the first ${results.length} of ${countLabel(data.total)} companies. Refine the name to narrow the results.`)}</p>}
              <ul>{results.map((result) => <li key={result.uic}><button type="button" data-business-result-id={result.cadastral_id || result.address_id} onClick={() => select(result)} disabled={Boolean(opening)}><Building2 size={16} aria-hidden="true" /><span><strong>{result.name}</strong><small>{pick('ЕИК', 'UIC')} {result.uic}</small><small>{result.registered_address}</small><small>{result.cadastral_id ? `${pick('Имот', 'Plot')} ${result.cadastral_id}` : pick('Официален адрес · парцелът не е установен', 'Official address · parcel not established')}</small></span>{opening === result.uic ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <ArrowUpRight size={15} aria-hidden="true" />}</button></li>)}</ul>
            </>}
          </>}
          {navigationError && <p role="status">{pick('Имотът не се отвори. Опитайте отново.', 'The plot could not be opened. Please try again.')}</p>}
        </div>
        {Number.isSafeInteger(matched) && <p className="business-address-search-coverage">{pick('Покритие:', 'Coverage:')} {countLabel(matched)} {pick('фирми с установено местоположение', 'companies with an established location')}{Number.isSafeInteger(candidates) ? ` / ${countLabel(candidates)} ${pick('фирми с адрес в София в извлечението', 'Sofia address candidates in the extract')}` : ''}{Number.isSafeInteger(matchedParcels) ? ` · ${countLabel(matchedParcels)} ${pick('имота', 'plots')}` : ''}.</p>}
        <p className="business-address-search-note">{pick('Регистриран фирмен адрес ≠ собственик на имота. Непълните и нееднозначните адреси не се поставят приблизително на картата. Източници: Търговски регистър (предоставени извлечения) и АГКК.', 'A company’s registered address does not establish property ownership. Incomplete and ambiguous addresses are not placed approximately on the map. Sources: supplied Commercial Register extracts and AGKK.')}</p>
      </div>
    </details>
  );
}
