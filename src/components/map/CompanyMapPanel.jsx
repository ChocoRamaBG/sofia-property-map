import React, { useId } from 'react';
import { AlertCircle, Building2, ChevronDown, Info, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayCount } from '@/lib/registerUi';
import './CompanyMapPanel.css';

export default function CompanyMapPanel({ panelRef, draft, onDraftChange, query, onApply, onShowAll, data, loading, error, onRetry, level = 'all', onLevelChange }) {
  const { pick, lang } = useI18n();
  const id = useId();
  const length = Array.from(draft.trim()).length;
  const counts = data?.coverage?.counts || {};
  const denominator = Number.isSafeInteger(counts.sofia_candidates) && counts.sofia_candidates > 0 ? counts.sofia_candidates : null;
  const located = counts.located_companies ?? counts.mapped_companies;
  const percentage = (number) => denominator && Number.isSafeInteger(number) ? new Intl.NumberFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: 1 }).format(number / denominator * 100) + '%' : null;
  const metrics = [
    ['cadastre', pick('Точен кадастрален адрес', 'Exact cadastral address'), counts.exact_cadastral_address_companies ?? counts.matched_companies],
    ['municipal', pick('Общински адрес → парцел', 'Municipal address → parcel'), counts.municipal_parcel_companies ?? 0],
    ['address', pick('Само официален адрес', 'Official address only'), counts.address_only_companies ?? 0],
  ];
  return <section className="company-map-panel" ref={panelRef}>
    <h1><Building2 size={22} aria-hidden="true" />{pick('Фирмени адреси', 'Registered company addresses')}</h1>
    <p>{pick('Търсете по име или ЕИК. Отворете пин за фирмите на този адрес.', 'Search by name or UIC. Open a pin to see its registered companies.')}</p>
    <form onSubmit={(event) => { event.preventDefault(); if (length >= 2 && length <= 120) onApply(draft.trim()); }}>
      <label htmlFor={id}>{pick('Име на фирма или ЕИК', 'Company name or UIC')}</label>
      <div className="company-map-input"><Search size={17} aria-hidden="true" /><input id={id} value={draft} onChange={(event) => onDraftChange(event.target.value)} placeholder={pick('Филтрирай фирмите на картата…', 'Filter companies on the map…')} aria-invalid={length > 120 || undefined} />{draft && <button type="button" onClick={() => onDraftChange('')} aria-label={pick('Изчисти текста', 'Clear text')}><X size={16} /></button>}</div>
      <button className="company-map-submit" type="submit" disabled={length < 2 || length > 120}>{pick('Покажи съвпаденията на картата', 'Show matches on the map')}</button>
    </form>
    <div className="company-map-levels" role="group" aria-label={pick('Точност на фирменото местоположение', 'Company location evidence')}>
      {[['all', pick('Всички', 'All')], ['parcel', pick('С парцел', 'With parcel')], ['address', pick('Само адрес', 'Address only')]].map(([value, label]) => <button type="button" key={value} aria-pressed={level === value} onClick={() => onLevelChange?.(value)}>{label}</button>)}
    </div>
    <div className="company-map-point-types"><span><i />{pick('С установен парцел', 'Parcel established')}</span><span><i className="is-address" />{pick('Само официален адрес', 'Official address only')}</span></div>
    {length > 120 && <p role="status">{pick('Използвайте до 120 знака.', 'Use up to 120 characters.')}</p>}
    {query && <div className="company-map-query"><span>{query}</span><button type="button" onClick={onShowAll} aria-label={pick('Премахни фирмения филтър', 'Remove the company filter')}><X size={15} /></button></div>}
    <div className="company-map-summary" role="status" aria-live="polite" aria-busy={loading}>
      {error ? <><AlertCircle size={17} /><p>{pick('Фирменият слой временно не е достъпен.', 'The company layer is temporarily unavailable.')}</p><button type="button" onClick={onRetry}>{pick('Опитай отново', 'Try again')}</button></> : loading && !data ? <><Loader2 size={17} className="animate-spin" /><p>{pick('Зареждане на адресите…', 'Loading addresses…')}</p></> : data ? <><strong>{displayCount(data.total, lang)} {pick('местоположения', 'locations')} · {displayCount(data.company_total, lang)} {pick('фирми', 'companies')}</strong><p>{pick('в текущия изглед', 'in the current view')}{loading ? ' · …' : ''}</p>{data.total === 0 && <p>{pick('Няма съвпадения в този изглед. Покажете всички адреси или променете търсенето.', 'No matches in this view. Show all addresses or change the search.')}</p>}</> : null}
    </div>
    {Number.isSafeInteger(located) && <details className="company-map-coverage">
      <summary><span><strong>{pick('Покритие на извлечението', 'Extract coverage')}</strong><small>{displayCount(located, lang)} {pick('фирми с местоположение', 'located companies')}</small></span>{percentage(located) && <b>{percentage(located)}</b>}<ChevronDown size={16} aria-hidden="true" /></summary>
      <div className="company-map-coverage-body" aria-label={pick('Три нива на съпоставяне', 'Three matching methods')}>
      {metrics.map(([key, label, value]) => Number.isSafeInteger(value) && <div key={key}><span>{label}</span><strong>{displayCount(value, lang)} {pick('фирми', 'companies')}</strong>{denominator && <small>{new Intl.NumberFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: 1 }).format(value / denominator * 100)}% · {displayCount(value, lang)} / {displayCount(denominator, lang)}</small>}</div>)}
      {denominator && <p>{pick('Дял от фирмите с адрес в София в предоставеното извлечение, а не от всички съществуващи фирми.', 'Share of Sofia-address companies in the supplied extract, not all existing companies.')}</p>}
      </div>
    </details>}
    <details className="company-map-method"><summary><Info size={15} />{pick('Какво показва пинът?', 'What does a pin show?')}</summary><p>{pick('Синият пин е фирмен адрес с установен парцел; позицията е вътрешна точка на официалния полигон, а не входът на офиса. Оранжевият пин е официален адрес на Столична община, за който парцелът не е установен еднозначно. Точният метод е показан при отваряне. Адресът не доказва собственост или дейност на място.', 'A blue pin is a registered address linked to a parcel; its position is an interior point of the official polygon, not an office entrance. An orange pin is an official Sofia Municipality address whose parcel has not been established unambiguously. Opening it shows the matching method. An address proves neither ownership nor activity at the location.')}</p><a href="./about.html">{pick('Източници и метод', 'Sources and method')} ↗</a></details>
    <p className="company-map-filter-note">{pick('Строителните филтри са запазени в „Имоти“. Тук търсенето ограничава фирмения слой.', 'Construction filters are preserved under “Properties”. Search here filters the company layer.')}</p>
  </section>;
}

export function BusinessMapStatus({ total, loading, error, onEdit, onRetry }) {
  const { pick, lang } = useI18n();
  return <div className="map-status-dock"><div className="map-status-pill">
    <div className="map-status-count" role="status" aria-live="polite">{error ? <><AlertCircle size={15} /><span>{pick('Проблем с данните', 'Data unavailable')}</span></> : loading ? <><Loader2 size={14} className="animate-spin" /><span>{pick('Зареждане', 'Loading')}</span></> : <><strong>{displayCount(total, lang)}</strong><span>{pick('местоположения', 'locations')}</span></>}</div>
    {error && <button className="map-status-action" type="button" onClick={onRetry} aria-label={pick('Опитай отново', 'Try again')}><RefreshCw size={16} /></button>}
    <button className="map-status-info" type="button" onClick={onEdit} aria-label={pick('Информация за фирмения слой', 'Company layer information')}><Info size={16} /></button>
  </div></div>;
}
