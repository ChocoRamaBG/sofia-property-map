import React, { useId } from 'react';
import { ArrowRight, Loader2, MapPin, Search, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import SearchResults from '@/components/search/SearchResults';
import BusinessAddressSearch from './BusinessAddressSearch';

export default function SearchPanel({
  panelRef, query = '', onQueryChange, onSubmit, onClear, loading, results = [], resultQuery, onSelectResult,
  searchTerms = [], searchMatch = 'all', onRemoveTerm, onClearTerms, onSearchMatchChange,
  resultTotal, resultMappedTotal, resultUnmappedTotal, resultsTruncated, searchError,
  addressIntent = false, onFindAddress, onSubmitAsRecords, addressProviderLabel,
  businessSearchState, onBusinessSearchStateChange, onSelectBusiness,
}) {
  const { t, pick } = useI18n();
  const matchGroup = useId();
  const queryLength = Array.from(query.trim()).length;
  const termTooLong = queryLength > (addressIntent ? 160 : 120);
  const canFindAddress = queryLength >= 3 && queryLength <= 160;
  const canAddRecordTerm = !loading && queryLength > 0 && queryLength <= 120 && searchTerms.length < 8;
  const canSubmit = addressIntent ? canFindAddress : canAddRecordTerm;
  const recordLoading = !addressIntent && loading;
  return (
    <section className="search-panel" ref={panelRef}>
      <h1>{t('search.heading')}</h1>
      <p className="search-description">{pick('Адрес, кадастрален номер или име на фирма.', 'Address, cadastral ID or company name.')}</p>
      <form onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(); }}>
        <label className="search-input-wrap">
          <Search size={18} aria-hidden="true" />
          <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={t('search.placeholder')} aria-label={t('search.title')} aria-invalid={termTooLong || undefined} aria-describedby={termTooLong ? `${matchGroup}-hint ${matchGroup}-limit` : `${matchGroup}-hint`} />
          {query && <button type="button" onClick={onClear} aria-label={t('search.clearDraft')}><X size={15} aria-hidden="true" /></button>}
        </label>
        <button className="search-submit" type="submit" disabled={!canSubmit}>
          {recordLoading ? <Loader2 size={17} className="animate-spin" aria-hidden="true" /> : addressIntent ? <MapPin size={17} aria-hidden="true" /> : <Search size={17} aria-hidden="true" />} {recordLoading ? t('search.searching') : addressIntent ? t('search.findAddress') : searchTerms.length ? pick('Добави условие', 'Add condition') : pick('Търси', 'Search')} {!recordLoading && <ArrowRight size={16} className="ml-auto" aria-hidden="true" />}
        </button>
      </form>
      {queryLength > 0 && <button type="button" className="search-intent-alternative" disabled={addressIntent ? !canAddRecordTerm : !canFindAddress} onClick={addressIntent ? onSubmitAsRecords : onFindAddress}>{addressIntent ? <Search size={14} aria-hidden="true" /> : <MapPin size={14} aria-hidden="true" />}{t(addressIntent ? 'search.asRecords' : 'search.asAddress')}{!addressIntent && <small> · {addressProviderLabel || t('search.addressService')}</small>}</button>}
      <p className="search-hint" id={`${matchGroup}-hint`}>{addressIntent ? t('search.addressHint') : pick('Добавяйте и премахвайте условия, без да губите резултатите.', 'Add or remove conditions without losing your results.')}</p>
      {addressIntent && queryLength > 0 && <p className="search-provider-notice">{t('search.addressProvider', { provider: addressProviderLabel || t('search.addressService') })}</p>}
      {termTooLong && <p className="search-term-limit" id={`${matchGroup}-limit`} role="status">{t(addressIntent ? 'search.addressTooLong' : 'search.termTooLong')}</p>}
      {searchTerms.length > 0 && (
        <div className="search-active-terms">
          <div className="search-terms-heading">
            <h2>{t('search.activeTerms')}</h2>
            <span className="search-term-count">{searchTerms.length} / 8</span>
            <button type="button" onClick={onClearTerms}>{t('search.clearTerms')}</button>
          </div>
          <ul className="search-term-list" aria-label={t('search.activeTerms')}>
            {searchTerms.map((term) => (
              <li key={term}>
                <button className="search-term-chip" type="button" onClick={() => onRemoveTerm(term)} aria-label={t('search.removeTerm', { term })}>
                  <span>{term}</span><X size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
          {searchTerms.length >= 8 && <p className="search-term-limit" role="status">{t('search.termLimit')}</p>}
          {searchTerms.length >= 2 && (
            <fieldset className="search-match">
              <legend>{t('search.matchLabel')}</legend>
              <div className="search-match-options">
                {['all', 'any'].map((mode) => (
                  <label key={mode} className={searchMatch === mode ? 'is-active' : ''}>
                    <input type="radio" name={matchGroup} value={mode} checked={searchMatch === mode} onChange={() => onSearchMatchChange(mode)} />
                    <span>{t(`search.match.${mode}`)}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </div>
      )}
      <BusinessAddressSearch state={businessSearchState} onStateChange={onBusinessSearchStateChange} onSelect={onSelectBusiness} />
      <SearchResults results={results} onSelect={onSelectResult} query={resultQuery} total={resultTotal} mappedTotal={resultMappedTotal} unmappedTotal={resultUnmappedTotal} truncated={resultsTruncated} loading={loading} error={searchError} />
      <details className="search-help"><summary>{pick('Как работи търсенето?', 'How does search work?')}</summary><p>{t('search.hint')}</p><p>{t('search.mapHelp')}</p>{searchTerms.length >= 2 && <p>{t(`search.matchHelp.${searchMatch === 'any' ? 'any' : 'all'}`)}</p>}</details>
    </section>
  );
}
