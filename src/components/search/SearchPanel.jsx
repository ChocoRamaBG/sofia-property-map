import React, { useId } from 'react';
import { ArrowRight, Loader2, Search, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import SearchResults from '@/components/search/SearchResults';

export default function SearchPanel({
  query = '', onQueryChange, onSubmit, onClear, loading, results = [], resultQuery, onSelectResult,
  searchTerms = [], searchMatch = 'all', onRemoveTerm, onClearTerms, onSearchMatchChange,
  resultTotal, resultMappedTotal, resultUnmappedTotal, resultsTruncated, searchError,
}) {
  const { t } = useI18n();
  const matchGroup = useId();
  const termTooLong = Array.from(query.trim()).length > 120;
  const canSubmit = !loading && query.trim().length > 0 && searchTerms.length < 8;
  return (
    <section className="search-panel">
      <p className="eyebrow">{t('search.eyebrow')}</p>
      <h1>{t('search.heading')}</h1>
      <p className="search-description">{t('search.description')}</p>
      <form onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(); }}>
        <label className="search-input-wrap">
          <Search size={18} aria-hidden="true" />
          <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={t('search.placeholder')} aria-label={t('search.title')} aria-invalid={termTooLong || undefined} aria-describedby={termTooLong ? `${matchGroup}-hint ${matchGroup}-limit` : `${matchGroup}-hint`} />
          {query && <button type="button" onClick={onClear} aria-label={t('search.clearDraft')}><X size={15} aria-hidden="true" /></button>}
        </label>
        <button className="search-submit" type="submit" disabled={!canSubmit}>
          {loading ? <Loader2 size={17} className="animate-spin" aria-hidden="true" /> : <Search size={17} aria-hidden="true" />} {loading ? t('search.searching') : t('search.addTerm')} {!loading && <ArrowRight size={16} className="ml-auto" aria-hidden="true" />}
        </button>
      </form>
      <p className="search-hint" id={`${matchGroup}-hint`}>{t('search.hint')}</p>
      {termTooLong && <p className="search-term-limit" id={`${matchGroup}-limit`} role="status">{t('search.termTooLong')}</p>}
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
              <p>{t(`search.matchHelp.${searchMatch === 'any' ? 'any' : 'all'}`)}</p>
            </fieldset>
          )}
          <p className="search-map-help">{t('search.mapHelp')}</p>
        </div>
      )}
      <SearchResults results={results} onSelect={onSelectResult} query={resultQuery} total={resultTotal} mappedTotal={resultMappedTotal} unmappedTotal={resultUnmappedTotal} truncated={resultsTruncated} loading={loading} error={searchError} />
    </section>
  );
}
