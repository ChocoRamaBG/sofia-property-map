import React from 'react';
import { ArrowRight, Loader2, Search, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import SearchResults from '@/components/search/SearchResults';

export default function SearchPanel({ query, onQueryChange, onSubmit, onClear, loading, results, resultQuery, onSelectResult }) {
  const { t } = useI18n();
  return (
    <section className="search-panel">
      <p className="eyebrow">{t('search.eyebrow')}</p>
      <h1>{t('search.heading')}</h1>
      <p className="search-description">{t('search.description')}</p>
      <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <label className="search-input-wrap">
          <Search size={18} aria-hidden="true" />
          <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={t('search.placeholder')} aria-label={t('search.title')} />
          {query && <button type="button" onClick={onClear} aria-label={t('search.clear')}><X size={15} /></button>}
        </label>
        <button className="search-submit" type="submit" disabled={loading || !query.trim()}>
          {loading ? <Loader2 size={17} className="animate-spin" /> : <Search size={17} />} {loading ? t('search.searching') : t('search.button')} {!loading && <ArrowRight size={16} className="ml-auto" />}
        </button>
      </form>
      <p className="search-hint">{t('search.hint')}</p>
      <SearchResults results={results} onSelect={onSelectResult} query={resultQuery} />
    </section>
  );
}
