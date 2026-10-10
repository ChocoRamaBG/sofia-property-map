import React from 'react';
import { ArrowUpRight, FileCheck2, MapPin } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { pointType, REGISTER_COLORS } from '@/lib/registerUi';

export default function SearchResults({ results, onSelect, query }) {
  const { t } = useI18n();
  if (!query) return null;
  return (
    <div className="search-results" aria-live="polite">
      <div className="search-results-title"><span>{t('search.results')}</span><span>{t('search.matches', { n: results.length })}</span></div>
      {results.length === 0 ? <p className="search-empty">{t('search.noResults')}</p> : (
        <ul>{results.map((result) => <li key={result.cadastral_id}>
          <button type="button" onClick={() => onSelect(result)}>
            <span className="result-icon" style={{ color: REGISTER_COLORS[pointType(result)] }}>{result.has_exploitation_certificate ? <FileCheck2 size={18} /> : <MapPin size={18} />}</span>
            <span className="min-w-0"><strong>{result.cadastral_id}</strong><small>{result.has_exploitation_certificate ? t('certificate.foundShort') : result.secondary}</small></span>
            <ArrowUpRight size={15} className="ml-auto shrink-0 text-slate-400" />
          </button>
        </li>)}</ul>
      )}
    </div>
  );
}
