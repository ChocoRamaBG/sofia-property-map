import React, { useId, useState } from 'react';
import { Check, ChevronDown, FileCheck2, RotateCcw, SlidersHorizontal, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { REGISTER_FILTERS, REGISTER_COLORS, displayCount, displayDate } from '@/lib/registerUi';
import { invalidFilterArea } from '@/lib/propertyFilters';

const EMPTY_FILTERS = { recordTypes: [], match: 'any', district: '', descriptionTag: '', dateFrom: '', dateTo: '', hasAddress: false, areaMin: '', areaMax: '', cadastreDistricts: [], cadastrePurposes: [], cadastreUses: [], cadastrePropertyTypes: [] };
const DOCUMENT_TYPES = REGISTER_FILTERS.filter((code) => code !== 'all' && code !== 'no_records');
const CADASTRAL_FACETS = [
  { field: 'cadastreDistricts', options: 'districts', label: 'filter.cadastreDistrict' },
  { field: 'cadastrePurposes', options: 'purposes', label: 'filter.cadastrePurpose' },
  { field: 'cadastreUses', options: 'uses', label: 'filter.cadastreUse' },
  { field: 'cadastrePropertyTypes', options: 'property_types', label: 'filter.cadastrePropertyType' },
];
const emptyDocumentDates = () => Object.fromEntries(DOCUMENT_TYPES.map((type) => [type, { from: '', to: '' }]));

function inputDate(date) {
  return String(date.getFullYear()) + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
}

function cadastralOptionLabel(option) {
  return String(option?.label_bg || option?.label || option?.key || '');
}

function cadastralChipValue(option, key, t) {
  const label = cadastralOptionLabel(option) || t('filter.cadastreValueUnavailable');
  return option?.code !== null && option?.code !== undefined && String(option.code) !== '' ? t('filter.cadastreValueWithCode', { label, code: option.code }) : label;
}

function CadastralFacetSelect({ id, label, selected, options, available, onChange, t, lang }) {
  const [search, setSearch] = useState('');
  const query = search.trim().toLocaleLowerCase('bg-BG');
  const visible = [...options].sort((left, right) => cadastralOptionLabel(left).localeCompare(cadastralOptionLabel(right), 'bg-BG', { numeric: true })
    || String(left.code ?? '').localeCompare(String(right.code ?? ''), 'bg-BG', { numeric: true })
    || String(left.key).localeCompare(String(right.key), 'bg-BG', { numeric: true }))
    .filter((option) => !query || `${cadastralOptionLabel(option)} ${option.code ?? ''} ${option.key}`.toLocaleLowerCase('bg-BG').includes(query));
  const limitReached = selected.length >= 100;
  const toggle = (key) => onChange(selected.includes(key) ? selected.filter((item) => item !== key) : limitReached ? selected : [...selected, key]);
  return <details className={'cadastre-filter-select ' + (selected.length ? 'is-active ' : '') + (!available ? 'is-unavailable' : '')} onToggle={(event) => { if (!event.currentTarget.open) setSearch(''); }}>
    <summary id={id + '-heading'} className="cadastre-filter-summary" aria-disabled={!available || undefined} onClick={(event) => { if (!available) event.preventDefault(); }}><span>{label}</span><small>{selected.length ? t('filter.cadastreSelected', { n: selected.length }) : t('filter.cadastreAny')}</small><ChevronDown size={15} aria-hidden="true" /></summary>
    <div className="cadastre-filter-panel">
      <label className="cadastre-filter-search" htmlFor={id + '-search'}><span className="sr-only">{t('filter.cadastreSearch', { field: label })}</span><input id={id + '-search'} type="search" autoComplete="off" placeholder={t('filter.cadastreSearchPlaceholder')} value={search} disabled={!available} onChange={(event) => setSearch(event.target.value)} /></label>
      {selected.length > 0 && <button type="button" className="cadastre-filter-clear" onClick={() => onChange([])} aria-label={t('filter.cadastreClearField', { field: label })}>{t('filter.cadastreClearSelection')}</button>}
      {limitReached && <p className="filter-field-help">{t('filter.cadastreSelectionLimit')}</p>}
      <div className="cadastre-filter-options" role="group" aria-labelledby={id + '-heading'}>{visible.map((option) => <label className={'cadastre-filter-option ' + (selected.includes(String(option.key)) ? 'is-active' : '')} key={option.key}>
        <input type="checkbox" checked={selected.includes(String(option.key))} disabled={!available || (limitReached && !selected.includes(String(option.key)))} onChange={() => toggle(String(option.key))} />
        <span className="cadastre-filter-option-label"><span>{cadastralOptionLabel(option)}</span>{option.code !== null && option.code !== undefined && String(option.code) !== '' && <small>{t('filter.cadastreCode', { code: option.code })}</small>}</span>
        {option.count != null && <span className="filter-count" title={t('filter.cadastreCountHint')}>{displayCount(option.count, lang)}</span>}
      </label>)}</div>
      {visible.length === 0 && <p className="cadastre-filter-empty">{t('filter.cadastreNoOptions')}</p>}
    </div>
  </details>;
}

export default function RegisterFilters({ value, onChange, counts, options }) {
  const { t, lang } = useI18n();
  const id = useId();
  const filters = { ...EMPTY_FILTERS, ...value, ...Object.fromEntries(CADASTRAL_FACETS.map(({ field }) => [field, Array.isArray(value?.[field]) ? value[field] : []])), recordTypes: Array.isArray(value?.recordTypes) ? value.recordTypes : [], documentDates: Object.fromEntries(DOCUMENT_TYPES.map((type) => [type, { from: '', to: '', ...value?.documentDates?.[type] }])) };
  const scopedDateCount = DOCUMENT_TYPES.filter((type) => filters.documentDates[type].from || filters.documentDates[type].to).length;
  const hasAreaRange = filters.areaMin !== '' || filters.areaMax !== '';
  const [expanded, setExpanded] = useState(Boolean(filters.district || filters.descriptionTag || filters.dateFrom || filters.dateTo || filters.hasAddress || scopedDateCount || hasAreaRange));
  const noRecords = filters.recordTypes.includes('no_records');
  const selectedTypes = filters.recordTypes.filter((code) => code !== 'no_records');
  const advancedCount = Number(Boolean(filters.district)) + Number(Boolean(filters.descriptionTag)) + Number(Boolean(filters.dateFrom || filters.dateTo)) + Number(filters.hasAddress) + scopedDateCount + Number(hasAreaRange);
  const cadastralCount = CADASTRAL_FACETS.filter(({ field }) => filters[field].length > 0).length;
  const activeCount = filters.recordTypes.length + advancedCount + cadastralCount;
  const cadastralOptions = options?.cadastre;
  const cadastralAvailable = cadastralOptions?.available === true;
  const advancedAvailable = options?.available === true;
  const scopedDatesAvailable = options?.scoped_dates_available === true;
  const advancedDisabled = noRecords || !advancedAvailable;
  const dateRangeError = Boolean(filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo);
  const areaRangeError = invalidFilterArea(filters);
  const areaOptions = options?.parcel_area;
  const areaAvailable = areaOptions?.available === true;
  const areaNumber = (number) => Number.isFinite(Number(number)) ? Number(number).toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: 8 }) : String(number);
  const districts = (options?.districts || []).map((item) => typeof item === 'string' ? { key: item, label: item } : { ...item, key: item.key ?? item.value, label: item.label ?? item.key ?? item.value });
  const descriptions = (options?.description_tags || []).map((item) => ({ ...item, label: lang === 'bg' ? item.label_bg || item.label_en || item.key : item.label_en || item.label_bg || item.key }));
  const reset = () => onChange({ ...EMPTY_FILTERS, recordTypes: [], documentDates: emptyDocumentDates() });
  const update = (patch) => onChange({ ...filters, ...patch });
  const updateDocumentDates = (type, patch) => {
    const range = { ...filters.documentDates[type], ...patch };
    update({
      documentDates: { ...filters.documentDates, [type]: range },
      recordTypes: range.from || range.to ? [...new Set([...selectedTypes, type])] : selectedTypes,
      dateFrom: '', dateTo: '',
    });
  };
  const toggleType = (code) => {
    if (code === 'no_records') {
      onChange({ ...EMPTY_FILTERS, recordTypes: noRecords ? [] : ['no_records'], documentDates: emptyDocumentDates(), areaMin: filters.areaMin, areaMax: filters.areaMax, ...Object.fromEntries(CADASTRAL_FACETS.map(({ field }) => [field, filters[field]])) });
      return;
    }
    const next = selectedTypes.includes(code) ? selectedTypes.filter((type) => type !== code) : [...selectedTypes, code];
    update({ recordTypes: next, match: next.length < 2 ? 'any' : filters.match, documentDates: selectedTypes.includes(code) ? { ...filters.documentDates, [code]: { from: '', to: '' } } : filters.documentDates });
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
    ...CADASTRAL_FACETS.flatMap((facet) => filters[facet.field].map((key) => ({ key: facet.field + '-' + key, label: t('filter.cadastreChip', { field: t(facet.label), value: cadastralChipValue(cadastralOptions?.[facet.options]?.find((option) => String(option.key) === key), key, t) }), remove: () => update({ [facet.field]: filters[facet.field].filter((item) => item !== key) }) }))),
    ...filters.recordTypes.map((code) => ({ key: code, label: t('filter.chip.' + code), remove: () => toggleType(code) })),
    ...(filters.district ? [{ key: 'district', label: t('filter.districtChip', { district: districts.find((item) => item.key === filters.district)?.label || filters.district }), remove: () => update({ district: '' }) }] : []),
    ...(filters.descriptionTag ? [{ key: 'description', label: descriptions.find((item) => item.key === filters.descriptionTag)?.label || filters.descriptionTag, remove: () => update({ descriptionTag: '' }) }] : []),
    ...DOCUMENT_TYPES.flatMap((type) => {
      const range = filters.documentDates[type];
      if (!range.from && !range.to) return [];
      const period = range.from && range.to ? displayDate(range.from, lang) + ' – ' + displayDate(range.to, lang) : range.from ? t('filter.fromChip', { date: displayDate(range.from, lang) }) : t('filter.toChip', { date: displayDate(range.to, lang) });
      return [{ key: 'dates-' + type, label: t('filter.documentDateChip', { document: t('filter.chip.' + type), period }), remove: () => updateDocumentDates(type, { from: '', to: '' }) }];
    }),
    ...(filters.dateFrom || filters.dateTo ? [{ key: 'dates', label: t('filter.legacyDateChip', { period: filters.dateFrom && filters.dateTo ? displayDate(filters.dateFrom, lang) + ' – ' + displayDate(filters.dateTo, lang) : filters.dateFrom ? t('filter.fromChip', { date: displayDate(filters.dateFrom, lang) }) : t('filter.toChip', { date: displayDate(filters.dateTo, lang) }) }), remove: () => update({ dateFrom: '', dateTo: '' }) }] : []),
    ...(filters.hasAddress ? [{ key: 'address', label: t('filter.addressChip'), remove: () => update({ hasAddress: false }) }] : []),
    ...(hasAreaRange ? [{ key: 'area', label: filters.areaMin !== '' && filters.areaMax !== '' ? t('filter.areaChip', { from: areaNumber(filters.areaMin), to: areaNumber(filters.areaMax) }) : filters.areaMin !== '' ? t('filter.areaMinChip', { area: areaNumber(filters.areaMin) }) : t('filter.areaMaxChip', { area: areaNumber(filters.areaMax) }), remove: () => update({ areaMin: '', areaMax: '' }) }] : []),
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
      <section className="cadastre-filters" aria-labelledby={id + '-cadastre-heading'}>
        <div className="cadastre-filters-heading"><h3 id={id + '-cadastre-heading'}>{t('filter.cadastreTitle')}</h3>{cadastralCount > 0 && <span className="filter-active-count">{cadastralCount}</span>}</div>
        {!cadastralAvailable && <p className="filter-selection-help">{options ? t('filter.cadastreUnavailable') : t('filter.cadastreLoading')}</p>}
        <div className="cadastre-filter-controls">{CADASTRAL_FACETS.map((facet) => <CadastralFacetSelect key={facet.field} id={id + '-' + facet.field} label={t(facet.label)} selected={filters[facet.field]} options={Array.isArray(cadastralOptions?.[facet.options]) ? cadastralOptions[facet.options] : []} available={cadastralAvailable} onChange={(selected) => update({ [facet.field]: selected })} t={t} lang={lang} />)}</div>
        <p className="filter-field-help">{t('filter.cadastreCombineHelp')}</p>
        <p className="filter-field-help">{t('filter.cadastreEvidenceHelp')}</p>
        {cadastralAvailable && cadastralOptions.source_url && <a className="filter-area-source" href={cadastralOptions.source_url} target="_blank" rel="noreferrer">{t('filter.parcelAreaSource')}</a>}
      </section>
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
      <div className="filter-advanced">
        <button type="button" className="filter-advanced-toggle" aria-expanded={expanded} aria-controls={id + '-advanced'} onClick={() => setExpanded((open) => !open)}>
          <span><strong>{t('filter.more')}</strong><small>{t('filter.moreSummary')}</small></span>{advancedCount > 0 && <span className="filter-active-count">{advancedCount}</span>}<ChevronDown size={17} className={expanded ? 'is-open' : ''} aria-hidden="true" />
        </button>
        {expanded && <div id={id + '-advanced'} className="filter-advanced-body">
          <div className="filter-parcel-area-section">
            <div className="filter-document-date-heading"><strong>{t('filter.parcelArea')}</strong>{hasAreaRange && <button type="button" className="filter-document-date-clear" onClick={() => update({ areaMin: '', areaMax: '' })}>{t('filter.clearArea')}</button>}</div>
            {!areaAvailable && <p className="filter-selection-help">{options ? t('filter.parcelAreaUnavailable') : t('filter.parcelAreaLoading')}</p>}
            <fieldset disabled={!areaAvailable} className="filter-parcel-area-fields">
              <legend className="sr-only">{t('filter.parcelArea')}</legend>
              <div className="filter-date-fields">
                <label className="filter-field" htmlFor={id + '-area-min'}><span>{t('filter.areaMin')}</span><input id={id + '-area-min'} type="number" min="0" max={filters.areaMax || '1000000000'} step="any" inputMode="decimal" value={filters.areaMin} aria-invalid={areaRangeError || undefined} aria-describedby={areaRangeError ? id + '-area-error' : id + '-area-help'} onChange={(event) => update({ areaMin: event.target.value })} /></label>
                <label className="filter-field" htmlFor={id + '-area-max'}><span>{t('filter.areaMax')}</span><input id={id + '-area-max'} type="number" min={filters.areaMin || '0'} max="1000000000" step="any" inputMode="decimal" value={filters.areaMax} aria-invalid={areaRangeError || undefined} aria-describedby={areaRangeError ? id + '-area-error' : id + '-area-help'} onChange={(event) => update({ areaMax: event.target.value })} /></label>
              </div>
            </fieldset>
            {areaRangeError && <p id={id + '-area-error'} className="filter-field-error" role="alert">{t('filter.areaRangeError')}</p>}
            <p id={id + '-area-help'} className="filter-field-help">{t('filter.parcelAreaHelp')}</p>
            {areaAvailable && <p className="filter-field-help">{t('filter.parcelAreaCoverage', { n: displayCount(areaOptions.parcel_count, lang) })}{areaOptions.min_m2 != null && areaOptions.max_m2 != null && <span>{t('filter.parcelAreaAvailableRange', { from: areaNumber(areaOptions.min_m2), to: areaNumber(areaOptions.max_m2) })}</span>}</p>}
            {Number(areaOptions?.ambiguous_parcel_count) > 0 && <p className="filter-field-help">{t('filter.parcelAreaAmbiguous', { n: displayCount(areaOptions.ambiguous_parcel_count, lang) })}</p>}
            {areaAvailable && areaOptions.source_url && <a className="filter-area-source" href={areaOptions.source_url} target="_blank" rel="noreferrer">{t('filter.parcelAreaSource')}</a>}
          </div>
          {advancedDisabled && <p className="filter-selection-help">{noRecords ? t('filter.advancedNeedsRecords') : options ? t('filter.advancedUnavailable') : t('filter.advancedLoading')}</p>}
          <fieldset disabled={advancedDisabled} className="filter-advanced-fields">
            <legend className="sr-only">{t('filter.more')}</legend>
            <label className="filter-field" htmlFor={id + '-district'}><span>{t('filter.district')}</span><select id={id + '-district'} value={filters.district} onChange={(event) => update({ district: event.target.value })}><option value="">{t('filter.allDistricts')}</option>{districts.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label className="filter-field" htmlFor={id + '-description'}><span>{t('filter.descriptionTag')}</span><select id={id + '-description'} value={filters.descriptionTag} onChange={(event) => update({ descriptionTag: event.target.value })}><option value="">{t('filter.anyDescription')}</option>{descriptions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select><small>{t('filter.descriptionTagHelp')}</small></label>
            <div className="filter-date-section filter-document-date-section">
              <span className="filter-field-heading">{t('filter.documentDates')}</span>
              <p className="filter-field-help">{t('filter.documentDatesHelp')}</p>
              {advancedAvailable && !scopedDatesAvailable && <p className="filter-selection-help">{t('filter.documentDatesUnavailable')}</p>}
              {(filters.dateFrom || filters.dateTo) && <div className="filter-legacy-date-block">
                <div className="filter-document-date-heading"><strong>{t('filter.legacyDateTitle')}</strong><button type="button" className="filter-document-date-clear" onClick={() => update({ dateFrom: '', dateTo: '' })}>{t('filter.clearPeriod')}</button></div>
                <p>{filters.dateFrom && filters.dateTo ? displayDate(filters.dateFrom, lang) + ' – ' + displayDate(filters.dateTo, lang) : filters.dateFrom ? t('filter.fromChip', { date: displayDate(filters.dateFrom, lang) }) : t('filter.toChip', { date: displayDate(filters.dateTo, lang) })}</p>
                <p className="filter-field-help">{t('filter.legacyDateHelp')}</p>
                {dateRangeError && <p className="filter-field-error" role="alert">{t('filter.dateRangeError')}</p>}
              </div>}
              <div className="filter-document-date-list">{DOCUMENT_TYPES.map((type) => {
                const range = filters.documentDates[type];
                const rangeError = Boolean(range.from && range.to && range.from > range.to);
                const typeId = id + '-dates-' + type;
                const available = options?.document_date_ranges?.[type];
                const document = t('filter.' + type);
                return <fieldset key={type} disabled={!scopedDatesAvailable} className={'filter-document-date-card ' + (range.from || range.to ? 'is-active' : '')}>
                  <legend>{document}</legend>
                  {(range.from || range.to) && <div className="filter-document-date-heading"><span>{t('filter.periodSelected')}</span><button type="button" className="filter-document-date-clear" aria-label={t('filter.clearDocumentPeriod', { document })} onClick={() => updateDocumentDates(type, { from: '', to: '' })}>{t('filter.clearPeriod')}</button></div>}
                  <div className="filter-date-fields">
                    <label className="filter-field" htmlFor={typeId + '-from'}><span>{t('filter.dateFrom')}</span><input id={typeId + '-from'} type="date" value={range.from} max={range.to || undefined} aria-label={t('filter.documentDateFrom', { document })} aria-invalid={rangeError || undefined} aria-describedby={rangeError ? typeId + '-error' : undefined} onChange={(event) => updateDocumentDates(type, { from: event.target.value })} /></label>
                    <label className="filter-field" htmlFor={typeId + '-to'}><span>{t('filter.dateTo')}</span><input id={typeId + '-to'} type="date" value={range.to} min={range.from || undefined} aria-label={t('filter.documentDateTo', { document })} aria-invalid={rangeError || undefined} aria-describedby={rangeError ? typeId + '-error' : undefined} onChange={(event) => updateDocumentDates(type, { to: event.target.value })} /></label>
                  </div>
                  {rangeError && <p id={typeId + '-error'} className="filter-field-error" role="alert">{t('filter.dateRangeError')}</p>}
                  <div className="filter-date-presets">
                    <button type="button" aria-label={t('filter.documentDatePreset', { document, period: t('filter.thisYear') })} onClick={() => { const today = new Date(); updateDocumentDates(type, { from: today.getFullYear() + '-01-01', to: inputDate(today) }); }}>{t('filter.thisYear')}</button>
                    <button type="button" aria-label={t('filter.documentDatePreset', { document, period: t('filter.lastYear') })} onClick={() => { const today = new Date(); updateDocumentDates(type, { from: inputDate(new Date(today.getFullYear() - 1, today.getMonth(), today.getDate())), to: inputDate(today) }); }}>{t('filter.lastYear')}</button>
                  </div>
                  {available?.date_min && available?.date_max && <p className="filter-field-help">{t('filter.dateRange', { from: displayDate(available.date_min, lang), to: displayDate(available.date_max, lang) })}</p>}
                </fieldset>;
              })}</div>
              <p className="filter-field-help">{t('filter.dateHelp')}</p>
            </div>
            <label className="filter-address-option"><input type="checkbox" checked={filters.hasAddress} onChange={(event) => update({ hasAddress: event.target.checked })} /><span>{t('filter.hasAddress')}<small>{t('filter.addressHelp')}</small></span></label>
          </fieldset>
          {!advancedDisabled && <p className="filter-selection-help">{t('filter.combineHelp')}</p>}
        </div>}
      </div>

      {chips.length > 0 && <div className="filter-active-list" aria-label={t('filter.activeFilters')}>{chips.map((chip) => <button type="button" key={chip.key} className="filter-active-chip" onClick={chip.remove} aria-label={t('filter.remove', { filter: chip.label })}><span>{chip.label}</span><X size={13} aria-hidden="true" /></button>)}</div>}
      <p className="filter-footnote">{t('filter.note')}</p>
    </section>
  );
}

