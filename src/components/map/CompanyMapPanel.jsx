import React, { useId } from 'react';
import { AlertCircle, Building2, Info, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayCount } from '@/lib/registerUi';
import './CompanyMapPanel.css';

export default function CompanyMapPanel({ panelRef, draft, onDraftChange, query, onApply, onShowAll, data, loading, error, onRetry }) {
  const { pick, lang } = useI18n();
  const id = useId();
  const length = Array.from(draft.trim()).length;
  const counts = data?.coverage?.counts || {};
  return <section className="company-map-panel" ref={panelRef}>
    <h1><Building2 size={22} aria-hidden="true" />{pick('Фирмени адреси', 'Registered company addresses')}</h1>
    <p>{pick('Всички еднозначно свързани фирмени адреси в София. Приближете група и отворете пин, за да видите фирмите в имота.', 'All unambiguously matched registered company addresses in Sofia. Zoom into a group and open a pin to see its companies.')}</p>
    <form onSubmit={(event) => { event.preventDefault(); if (length >= 2 && length <= 120) onApply(draft.trim()); }}>
      <label htmlFor={id}>{pick('Име на фирма или ЕИК', 'Company name or UIC')}</label>
      <div className="company-map-input"><Search size={17} aria-hidden="true" /><input id={id} value={draft} onChange={(event) => onDraftChange(event.target.value)} placeholder={pick('Филтрирай фирмите на картата…', 'Filter companies on the map…')} aria-invalid={length > 120 || undefined} />{draft && <button type="button" onClick={() => onDraftChange('')} aria-label={pick('Изчисти текста', 'Clear text')}><X size={16} /></button>}</div>
      <button className="company-map-submit" type="submit" disabled={length < 2 || length > 120}>{pick('Покажи съвпаденията на картата', 'Show matches on the map')}</button>
    </form>
    {length > 120 && <p role="status">{pick('Използвайте до 120 знака.', 'Use up to 120 characters.')}</p>}
    <button className="company-map-show-all" type="button" onClick={onShowAll}>{pick('Покажи всички фирмени адреси', 'Show all registered company addresses')}</button>
    {query && <div className="company-map-query"><span>{query}</span><button type="button" onClick={onShowAll} aria-label={pick('Премахни фирмения филтър', 'Remove the company filter')}><X size={15} /></button></div>}
    <div className="company-map-summary" role="status" aria-live="polite" aria-busy={loading}>
      {error ? <><AlertCircle size={17} /><p>{pick('Фирменият слой временно не е достъпен.', 'The company layer is temporarily unavailable.')}</p><button type="button" onClick={onRetry}>{pick('Опитай отново', 'Try again')}</button></> : loading && !data ? <><Loader2 size={17} className="animate-spin" /><p>{pick('Зареждане на адресите…', 'Loading addresses…')}</p></> : data ? <><strong>{displayCount(data.total, lang)} {pick('имота', 'plots')} · {displayCount(data.company_total, lang)} {pick('фирми', 'companies')}</strong><p>{pick('в текущия изглед', 'in the current view')}{loading ? ' · …' : ''}</p>{data.total === 0 && <p>{pick('Няма съвпадения в този изглед. Покажете всички адреси или променете търсенето.', 'No matches in this view. Show all addresses or change the search.')}</p>}</> : null}
    </div>
    {Number.isSafeInteger(counts.mapped_business_parcels) && <p className="company-map-coverage">{pick('Общо на картата:', 'Total on the map:')} <strong>{displayCount(counts.mapped_business_parcels, lang)} {pick('имота', 'plots')}</strong> · {displayCount(counts.mapped_companies, lang)} {pick('фирми', 'companies')}.{counts.unmapped_business_parcels > 0 && <> {displayCount(counts.unmapped_business_parcels, lang)} {pick('свързани имота нямат използваема геометрия и не са поставени приблизително.', 'matched plots have no usable geometry and are not placed approximately.')}</>}</p>}
    <details className="company-map-method"><summary><Info size={15} />{pick('Какво показва пинът?', 'What does a pin show?')}</summary><p>{pick('Един пин обозначава кадастрален имот с регистрирани фирмени адреси. Позицията е вътрешна точка от официалния полигон, а не входът на офиса. Вписаният адрес не доказва собственост или дейност на място. Споделени и непълни адреси остават несвързани.', 'One pin represents a cadastral plot with registered company addresses. Its position is an interior point of the official polygon, not an office entrance. A registered address does not prove ownership or activity at the location. Shared and incomplete addresses remain unlinked.')}</p><a href="./about.html">{pick('Източници и метод', 'Sources and method')} ↗</a></details>
    <p className="company-map-filter-note">{pick('Строителните филтри са запазени в „Имоти“. Тук търсенето ограничава фирмения слой.', 'Construction filters are preserved under “Properties”. Search here filters the company layer.')}</p>
  </section>;
}

export function BusinessMapStatus({ total, loading, error, onEdit, onRetry }) {
  const { pick, lang } = useI18n();
  return <div className="map-status-dock"><div className="map-status-pill">
    <div className="map-status-count" role="status" aria-live="polite">{error ? <><AlertCircle size={15} /><span>{pick('Проблем с данните', 'Data unavailable')}</span></> : loading ? <><Loader2 size={14} className="animate-spin" /><span>{pick('Зареждане', 'Loading')}</span></> : <><strong>{displayCount(total, lang)}</strong><span>{pick('фирмени адреса', 'business addresses')}</span></>}</div>
    {error && <button className="map-status-action" type="button" onClick={onRetry} aria-label={pick('Опитай отново', 'Try again')}><RefreshCw size={16} /></button>}
    <button className="map-status-info" type="button" onClick={onEdit} aria-label={pick('Информация за фирмения слой', 'Company layer information')}><Info size={16} /></button>
  </div></div>;
}
