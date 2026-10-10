import React, { useId, useState } from 'react';
import { Check, ChevronDown, FileCheck2, RotateCcw, SlidersHorizontal, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { REGISTER_FILTERS, REGISTER_COLORS, displayCount, displayDate } from '@/lib/registerUi';

const EMPTY_FILTERS = { recordTypes: [], match: 'any', district: '', descriptionTag: '', dateFrom: '', dateTo: '', hasAddress: false };
const DOCUMENT_TYPES = REGISTER_FILTERS.filter((code) => code !== 'all' && code !== 'no_records');

function inputDate(date) {
  return String(date.getFullYear()) + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
}

export default function RegisterFilters({ value, onChange, counts, options }) {
  const { t, lang } = useI18n();
  const id = useId();
  const filters = { ...EMPTY_FILTERS, ...value, recordTypes: Array.isArray(value?.recordTypes) ? value.recordTypes : [] };
  const [expanded, setExpanded] = useState(Boolean(filters.district || filters.descriptionTag || filters.dateFrom || filters.dateTo || filters.hasAddress));
  const noRecords = filters.recordTypes.includes('no_records');
  const selectedTypes = filters.recordTypes.filter((code) => code !== 'no_records');
  const advancedCount = Number(Boolean(filters.district)) + Number(Boolean(filters.descriptionTag)) + Number(Boolean(filters.dateFrom || filters.dateTo)) + Number(filters.hasAddress);
  const activeCount = filters.recordTypes.length + advancedCount;
  const advancedAvailable = options?.available === true;
  const advancedDisabled = noRecords || !advancedAvailable;
  const dateRangeError = Boolean(filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo);
  const districts = (options?.districts || []).map((item) => typeof item === 'string' ? { key: item, label: item } : { ...item, key: item.key ?? item.value, label: item.label ?? item.key ?? item.value });
  const descriptions = (options?.description_tags || []).map((item) => ({ ...item, label: lang === 'bg' ? item.label_bg || item.label_en || item.key : item.label_en || item.label_bg || item.key }));
  const reset = () => onChange({ ...EMPTY_FILTERS, recordTypes: [] });
  const update = (patch) => onChange({ ...filters, ...patch });
  const toggleType = (code) => {
    if (code === 'no_records') {
      onChange({ ...EMPTY_FILTERS, recordTypes: noRecords ? [] : ['no_records'] });
      return;
    }
    const next = selectedTypes.includes(code) ? selectedTypes.filter((type) => type !== code) : [...selectedTypes, code];
    update({ recordTypes: next, match: next.length < 2 ? 'any' : filters.match });
  };
  const sourceCount = (code) => code === 'exploitation_certificates' ? counts?.plots_with_exploitation_certificate : code === 'no_records' ? counts?.plots_without_records ?? counts?.plots_by_source?.no_records : counts?.plots_by_source?.[code];
  const typeOption = (code) => (
    <label key={code} className={'filter-option ' + (filters.recordTypes.includes(code) ? 'is-active ' : '') + (code === 'no_records' ? 'filter-no-records' : '')}>
      <input type="checkbox" checked={filters.recordTypes.includes(code)} onChange={() => toggleType(code)} />
      <span className="filter-check" aria-hidden="true">{filters.recordTypes.includes(code) && <Check size={13} />}</span>
      <span className="filter-symbol" style={{ color: REGISTER_COLORS[code] || '#173b42' }} aria-hidden="true">{code === 'exploitation_certificates' ? <FileCheck2 size={18} /> : <span className="filter-dot" style={{ backgroundColor: REGISTER_COLORS[code] || '#173b42' }} />}</span>
      <span className="filter-label">{t('filter.' + code)}{code === 'exploitation_certificates' && <small>{t('filter.certificateHint')}</small>}</span>
      {sourceCount(code) !== null && sourceCount(code) !== undefined && <span className="filter-count" title={t('filter.countHint')}>{displayCount(sourceCount(code), lang)}</span>}
    </label>
  );
  const chips = [
    ...filters.recordTypes.map((code) => ({ key: code, label: t('filter.chip.' + code), remove: () => toggleType(code) })),
    ...(filters.district ? [{ key: 'district', label: t('filter.districtChip', { district: districts.find((item) => item.key === filters.district)?.label || filters.district }), remove: () => update({ district: '' }) }] : []),
    ...(filters.descriptionTag ? [{ key: 'description', label: descriptions.find((item) => item.key === filters.descriptionTag)?.label || filters.descriptionTag, remove: () => update({ descriptionTag: '' }) }] : []),
    ...(filters.dateFrom || filters.dateTo ? [{ key: 'dates', label: filters.dateFrom && filters.dateTo ? displayDate(filters.dateFrom, lang) + ' – ' + displayDate(filters.dateTo, lang) : filters.dateFrom ? t('filter.fromChip', { date: displayDate(filters.dateFrom, lang) }) : t('filter.toChip', { date: displayDate(filters.dateTo, lang) }), remove: () => update({ dateFrom: '', dateTo: '' }) }] : []),
    ...(filters.hasAddress ? [{ key: 'address', label: t('filter.addressChip'), remove: () => update({ hasAddress: false }) }] : []),
  ];

  return (
    <section className="register-filters" aria-labelledby={id + '-heading'}>
      <div className="filter-heading-row">
        <div className="section-heading"><SlidersHorizontal size={16} /><h2 id={id + '-heading'}>{t('filter.title')}</h2>{activeCount > 0 && <span className="filter-active-count" aria-label={t('filter.activeCount', { n: activeCount })}>{activeCount}</span>}</div>
        {activeCount > 0 && <button type="button" className="filter-clear" onClick={reset}><RotateCcw size={13} />{t('filter.clearAll')}</button>}
      </div>
      <p>{t('filter.description')}</p>
      <button type="button" className={'filter-all-preset ' + (activeCount === 0 ? 'is-active' : '')} onClick={reset}>
        <span>{t('filter.all')}</span>{counts?.plots != null && <span className="filter-count">{displayCount(counts.plots, lang)}</span>}{activeCount === 0 && <Check size={14} aria-hidden="true" />}
      </button>
      <div className="filter-advanced">
        <button type="button" className="filter-advanced-toggle" aria-expanded={expanded} aria-controls={id + '-advanced'} onClick={() => setExpanded((open) => !open)}>
          <span><strong>{t('filter.more')}</strong><small>{t('filter.moreSummary')}</small></span>{advancedCount > 0 && <span className="filter-active-count">{advancedCount}</span>}<ChevronDown size={17} className={expanded ? 'is-open' : ''} aria-hidden="true" />
        </button>
        {expanded && <div id={id + '-advanced'} className="filter-advanced-body">
          {advancedDisabled && <p className="filter-selection-help">{noRecords ? t('filter.advancedNeedsRecords') : options ? t('filter.advancedUnavailable') : t('filter.advancedLoading')}</p>}
          <fieldset disabled={advancedDisabled} className="filter-advanced-fields">
            <legend className="sr-only">{t('filter.more')}</legend>
            <label className="filter-field" htmlFor={id + '-district'}><span>{t('filter.district')}</span><select id={id + '-district'} value={filters.district} onChange={(event) => update({ district: event.target.value })}><option value="">{t('filter.allDistricts')}</option>{districts.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label className="filter-field" htmlFor={id + '-description'}><span>{t('filter.descriptionTag')}</span><select id={id + '-description'} value={filters.descriptionTag} onChange={(event) => update({ descriptionTag: event.target.value })}><option value="">{t('filter.anyDescription')}</option>{descriptions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select><small>{t('filter.descriptionTagHelp')}</small></label>
            <div className="filter-date-section">
              <span className="filter-field-heading">{t('filter.documentDate')}</span>
              <div className="filter-date-fields">
                <label className="filter-field" htmlFor={id + '-date-from'}><span>{t('filter.dateFrom')}</span><input id={id + '-date-from'} type="date" value={filters.dateFrom} max={filters.dateTo || undefined} aria-invalid={dateRangeError || undefined} aria-describedby={dateRangeError ? id + '-date-error' : undefined} onChange={(event) => update({ dateFrom: event.target.value })} /></label>
                <label className="filter-field" htmlFor={id + '-date-to'}><span>{t('filter.dateTo')}</span><input id={id + '-date-to'} type="date" value={filters.dateTo} min={filters.dateFrom || undefined} aria-invalid={dateRangeError || undefined} aria-describedby={dateRangeError ? id + '-date-error' : undefined} onChange={(event) => update({ dateTo: event.target.value })} /></label>
              </div>
              {dateRangeError && <p id={id + '-date-error'} className="filter-field-error" role="alert">{t('filter.dateRangeError')}</p>}
              <div className="filter-date-presets">
                <button type="button" onClick={() => { const today = new Date(); update({ dateFrom: today.getFullYear() + '-01-01', dateTo: inputDate(today) }); }}>{t('filter.thisYear')}</button>
                <button type="button" onClick={() => { const today = new Date(); update({ dateFrom: inputDate(new Date(today.getFullYear() - 1, today.getMonth(), today.getDate())), dateTo: inputDate(today) }); }}>{t('filter.lastYear')}</button>
              </div>
              <p className="filter-field-help">{t('filter.dateHelp')}{options?.date_min && options?.date_max && <span>{t('filter.dateRange', { from: displayDate(options.date_min, lang), to: displayDate(options.date_max, lang) })}</span>}</p>
            </div>
            <label className="filter-address-option"><input type="checkbox" checked={filters.hasAddress} onChange={(event) => update({ hasAddress: event.target.checked })} /><span>{t('filter.hasAddress')}<small>{t('filter.addressHelp')}</small></span></label>
          </fieldset>
          {!advancedDisabled && <p className="filter-selection-help">{t('filter.combineHelp')}</p>}
        </div>}
      </div>

      <fieldset className="filter-types">
        <legend>{t('filter.documentTypes')}</legend>
        <div className="filter-options">{DOCUMENT_TYPES.map(typeOption)}</div>
      </fieldset>
      {selectedTypes.length > 1 && <div className="filter-match">
        <span id={id + '-match-label'}>{t('filter.matchLabel')}</span>
        <div className="filter-match-options" role="radiogroup" aria-labelledby={id + '-match-label'}>
          {['any', 'all'].map((match) => <label key={match} className={filters.match === match ? 'is-active' : ''}><input type="radio" name={id + '-match'} checked={filters.match === match} onChange={() => update({ match })} /><span>{t('filter.match.' + match)}</span></label>)}
        </div>
        <p>{t('filter.matchHelp.' + filters.match)}</p>
      </div>}
      <div className="filter-no-records-wrap">{typeOption('no_records')}</div>
      {noRecords && <p className="filter-selection-help">{t('filter.noRecordsHelp')}</p>}

      {chips.length > 0 && <div className="filter-active-list" aria-label={t('filter.activeFilters')}>{chips.map((chip) => <button type="button" key={chip.key} className="filter-active-chip" onClick={chip.remove} aria-label={t('filter.remove', { filter: chip.label })}><span>{chip.label}</span><X size={13} aria-hidden="true" /></button>)}</div>}
      <p className="filter-footnote">{t('filter.note')}</p>
    </section>
  );
}

