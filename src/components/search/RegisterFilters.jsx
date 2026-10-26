import React, { useId, useState } from 'react';
import { Check, ChevronDown, RotateCcw, SlidersHorizontal, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { REGISTER_FILTERS, REGISTER_COLORS, displayCount, displayDate } from '@/lib/registerUi';
import { activeFilterCount, invalidFilterArea } from '@/lib/propertyFilters';
import DocumentTypeIcon from '@/components/DocumentTypeIcon';
import DocumentPeriods from './DocumentPeriods';
import './RegisterFilters.css';

const EMPTY_FILTERS = { searchTerms: [], searchMatch: 'all', recordTypes: [], match: 'any', district: '', descriptionTag: '', dateFrom: '', dateTo: '', hasAddress: false, areaMin: '', areaMax: '', cadastreDistricts: [], cadastrePurposes: [], cadastreUses: [], cadastrePropertyTypes: [] };
const DOCUMENT_ORDER = ['building_permits', 'projecting_visas', 'exploitation_certificates'];
const DOCUMENT_TYPES = REGISTER_FILTERS.filter((code) => code !== 'all' && code !== 'no_records').sort((a, b) => DOCUMENT_ORDER.indexOf(a) - DOCUMENT_ORDER.indexOf(b));
const CADASTRAL_FACETS = [
  { field: 'cadastreDistricts', options: 'districts', label: 'filter.cadastreDistrict' },
  { field: 'cadastrePurposes', options: 'purposes', label: 'filter.cadastrePurpose' },
  { field: 'cadastreUses', options: 'uses', label: 'filter.cadastreUse' },
  { field: 'cadastrePropertyTypes', options: 'property_types', label: 'filter.cadastrePropertyType' },
];
const emptyDocumentDates = () => Object.fromEntries(DOCUMENT_TYPES.map((type) => [type, { from: '', to: '' }]));

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
  const { t, lang, pick } = useI18n();
  const id = useId();
  const filters = { ...EMPTY_FILTERS, ...value, ...Object.fromEntries(CADASTRAL_FACETS.map(({ field }) => [field, Array.isArray(value?.[field]) ? value[field] : []])), recordTypes: Array.isArray(value?.recordTypes) ? value.recordTypes : [], documentDates: Object.fromEntries(DOCUMENT_TYPES.map((type) => [type, { from: '', to: '', ...value?.documentDates?.[type] }])) };
  const hasAreaRange = filters.areaMin !== '' || filters.areaMax !== '';
  const noRecords = filters.recordTypes.includes('no_records');
  const selectedTypes = filters.recordTypes.filter((code) => code !== 'no_records');
  const advancedCount = Number(Boolean(filters.district)) + Number(Boolean(filters.descriptionTag)) + Number(Boolean(filters.dateFrom || filters.dateTo)) + Number(filters.hasAddress);
  const cadastralCount = CADASTRAL_FACETS.filter(({ field }) => filters[field].length > 0).length;
  const activeCount = activeFilterCount(filters);
  const cadastralOptions = options?.cadastre;
  const cadastralAvailable = cadastralOptions?.available === true;
  const advancedAvailable = options?.available === true;
  const scopedDatesAvailable = options?.scoped_dates_available === true;
  const advancedDisabled = noRecords || !advancedAvailable;
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
      onChange({ ...EMPTY_FILTERS, searchTerms: filters.searchTerms, searchMatch: filters.searchMatch, recordTypes: noRecords ? [] : ['no_records'], documentDates: emptyDocumentDates(), areaMin: filters.areaMin, areaMax: filters.areaMax, ...Object.fromEntries(CADASTRAL_FACETS.map(({ field }) => [field, filters[field]])) });
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
      <span className="filter-symbol" style={{ color: REGISTER_COLORS[code] || '#173b42' }} aria-hidden="true"><DocumentTypeIcon type={code} size={18} /></span>
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
    <section className="register-filters filter-workbench" aria-labelledby={id + '-heading'}>
      <div className="filter-heading-row">
        <div className="section-heading"><SlidersHorizontal size={16} /><h2 id={id + '-heading'}>{t('filter.title')}</h2>{activeCount > 0 && <span className="filter-active-count" aria-label={t('filter.activeCount', { n: activeCount })}>{activeCount}</span>}</div>
        {activeCount > 0 && <button type="button" className="filter-clear" onClick={reset}><RotateCcw size={13} />{t('filter.clearAll')}</button>}
      </div>
      <p className="filter-workbench-intro">{pick('Избирайте няколко условия. Картата се обновява веднага.', 'Combine conditions. The map updates as you choose.')}</p>
      {chips.length > 0 ? <div className="filter-current-selection" aria-label={t('filter.activeFilters')}>
        <div className="filter-current-heading"><strong>{pick('Избрани условия', 'Selected conditions')}</strong><span>{pick('Натиснете, за да премахнете', 'Select to remove')}</span></div>
        <div className="filter-active-list">{chips.map((chip) => <button type="button" key={chip.key} className="filter-active-chip" onClick={chip.remove} aria-label={t('filter.remove', { filter: chip.label })}><span>{chip.label}</span><X size={13} aria-hidden="true" /></button>)}</div>
      </div> : <p className="filter-workbench-empty">{pick('Няма допълнителни филтри за имотите.', 'No additional plot filters selected.')}</p>}
      <fieldset className="filter-types">
        <legend>{t('filter.documentTypes')}</legend>
        <div className="filter-options">{DOCUMENT_TYPES.map(typeOption)}</div>
        <div className="filter-no-records-wrap">{typeOption('no_records')}</div>
        {noRecords && <p className="filter-selection-help">{pick('Кадастралните условия и площта се запазват. Документните условия са изключени.', 'Cadastral conditions and area are retained. Document conditions are cleared.')}</p>}
      </fieldset>
      {selectedTypes.length > 1 && <div className="filter-match">
        <span id={id + '-match-label'}>{t('filter.matchLabel')}</span>
        <div className="filter-match-options" role="radiogroup" aria-labelledby={id + '-match-label'}>
          {['any', 'all'].map((match) => <label key={match} className={filters.match === match ? 'is-active' : ''}><input type="radio" name={id + '-match'} checked={filters.match === match} onChange={() => update({ match })} /><span>{t('filter.match.' + match)}</span></label>)}
        </div>
        <p>{t('filter.matchHelp.' + filters.match)}</p>
      </div>}
      <DocumentPeriods filters={filters} options={options} disabled={advancedDisabled || !scopedDatesAvailable} onChange={updateDocumentDates} />
      <section className="filter-parcel-area-section filter-primary-area" aria-labelledby={id + '-area-heading'}>
        <div className="filter-document-date-heading"><h3 id={id + '-area-heading'}>{pick('Площ на терена · м²', 'Land parcel area · m²')}</h3>{hasAreaRange && <button type="button" className="filter-document-date-clear" onClick={() => update({ areaMin: '', areaMax: '' })}>{t('filter.clearArea')}</button>}</div>
        {!areaAvailable && <p className="filter-selection-help">{options ? t('filter.parcelAreaUnavailable') : t('filter.parcelAreaLoading')}</p>}
        <fieldset disabled={!areaAvailable} className="filter-parcel-area-fields">
          <legend className="sr-only">{t('filter.parcelArea')}</legend>
          <div className="filter-date-fields">
            <label className="filter-field" htmlFor={id + '-area-min'}><span>{t('filter.areaMin')}</span><input id={id + '-area-min'} type="number" min="0" max={filters.areaMax || '1000000000'} step="any" inputMode="decimal" placeholder={pick('Без минимум', 'No minimum')} value={filters.areaMin} aria-invalid={areaRangeError || undefined} aria-describedby={areaRangeError ? id + '-area-error' : id + '-area-help'} onChange={(event) => update({ areaMin: event.target.value })} /></label>
            <label className="filter-field" htmlFor={id + '-area-max'}><span>{t('filter.areaMax')}</span><input id={id + '-area-max'} type="number" min={filters.areaMin || '0'} max="1000000000" step="any" inputMode="decimal" placeholder={pick('Без максимум', 'No maximum')} value={filters.areaMax} aria-invalid={areaRangeError || undefined} aria-describedby={areaRangeError ? id + '-area-error' : id + '-area-help'} onChange={(event) => update({ areaMax: event.target.value })} /></label>
          </div>
        </fieldset>
        {areaRangeError && <p id={id + '-area-error'} className="filter-field-error" role="alert">{t('filter.areaRangeError')}</p>}
        <p id={id + '-area-help'} className="filter-area-caption">{pick('Кадастрална геометрична площ на терена, без РЗП на сградите.', 'Cadastral geometric land area, separate from building floor area.')}</p>
        <details className="filter-help-details"><summary>{pick('Източник и обхват на площта', 'Area source and coverage')}<ChevronDown size={14} aria-hidden="true" /></summary><div>
          <p>{t('filter.parcelAreaHelp')}</p>
          {areaAvailable && <p>{t('filter.parcelAreaCoverage', { n: displayCount(areaOptions.parcel_count, lang) })}{areaOptions.min_m2 != null && areaOptions.max_m2 != null && <span>{t('filter.parcelAreaAvailableRange', { from: areaNumber(areaOptions.min_m2), to: areaNumber(areaOptions.max_m2) })}</span>}</p>}
          {Number(areaOptions?.ambiguous_parcel_count) > 0 && <p>{t('filter.parcelAreaAmbiguous', { n: displayCount(areaOptions.ambiguous_parcel_count, lang) })}</p>}
          {areaAvailable && areaOptions.source_url && <a className="filter-area-source" href={areaOptions.source_url} target="_blank" rel="noreferrer">{t('filter.parcelAreaSource')}</a>}
        </div></details>
      </section>
      <details className="filter-disclosure filter-cadastre-disclosure">
        <summary className="filter-disclosure-heading"><span><strong>{pick('Кадастрални характеристики', 'Cadastral attributes')}</strong><small>{pick('Район, предназначение, начин на ползване и вид собственост', 'District, purpose, use and property category')}</small></span>{cadastralCount > 0 && <span className="filter-active-count">{cadastralCount}</span>}<ChevronDown size={17} aria-hidden="true" /></summary>
        <section className="cadastre-filters" aria-label={t('filter.cadastreTitle')}>
        {!cadastralAvailable && <p className="filter-selection-help">{options ? t('filter.cadastreUnavailable') : t('filter.cadastreLoading')}</p>}
        <div className="cadastre-filter-controls">{CADASTRAL_FACETS.map((facet) => <CadastralFacetSelect key={facet.field} id={id + '-' + facet.field} label={t(facet.label)} selected={filters[facet.field]} options={Array.isArray(cadastralOptions?.[facet.options]) ? cadastralOptions[facet.options] : []} available={cadastralAvailable} onChange={(selected) => update({ [facet.field]: selected })} t={t} lang={lang} />)}</div>
        <p className="filter-field-help">{pick('Няколко стойности в едно поле са алтернативи.', 'Multiple values within one field are alternatives.')}</p>
        <details className="filter-help-details"><summary>{pick('Как се комбинират тези условия?', 'How do these conditions combine?')}<ChevronDown size={14} aria-hidden="true" /></summary><div><p>{t('filter.cadastreCombineHelp')}</p><p>{t('filter.cadastreEvidenceHelp')}</p></div></details>
        {cadastralAvailable && cadastralOptions.source_url && <a className="filter-area-source" href={cadastralOptions.source_url} target="_blank" rel="noreferrer">{t('filter.parcelAreaSource')}</a>}
        </section>
      </details>
      <details className="filter-disclosure filter-document-disclosure">
        <summary className="filter-disclosure-heading"><span><strong>{pick('Подробности за документите', 'Document details')}</strong><small>{pick('Район на документа, описание и посочен адрес', 'Document district, description and stated address')}</small></span>{advancedCount > 0 && <span className="filter-active-count">{advancedCount}</span>}<ChevronDown size={17} aria-hidden="true" /></summary>
        <div className="filter-advanced-body">
          {advancedDisabled && <p className="filter-selection-help">{noRecords ? t('filter.advancedNeedsRecords') : options ? t('filter.advancedUnavailable') : t('filter.advancedLoading')}</p>}
          <fieldset disabled={advancedDisabled} className="filter-advanced-fields">
            <legend className="sr-only">{t('filter.more')}</legend>
            <label className="filter-field" htmlFor={id + '-district'}><span>{t('filter.district')}</span><select id={id + '-district'} value={filters.district} onChange={(event) => update({ district: event.target.value })}><option value="">{t('filter.allDistricts')}</option>{districts.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label className="filter-field" htmlFor={id + '-description'}><span>{t('filter.descriptionTag')}</span><select id={id + '-description'} value={filters.descriptionTag} onChange={(event) => update({ descriptionTag: event.target.value })}><option value="">{t('filter.anyDescription')}</option>{descriptions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select><small>{t('filter.descriptionTagHelp')}</small></label>
            <label className="filter-address-option"><input type="checkbox" checked={filters.hasAddress} onChange={(event) => update({ hasAddress: event.target.checked })} /><span>{t('filter.hasAddress')}<small>{t('filter.addressHelp')}</small></span></label>
          </fieldset>
          {!advancedDisabled && <p className="filter-selection-help">{t('filter.combineHelp')}</p>}
        </div>
      </details>
      <details className="filter-help-details filter-method-help"><summary>{pick('Как да четем резултатите?', 'How should results be interpreted?')}<ChevronDown size={14} aria-hidden="true" /></summary><div><p>{t('filter.note')}</p><p>{t('filter.noRecordsHelp')}</p></div></details>
    </section>
  );
}

