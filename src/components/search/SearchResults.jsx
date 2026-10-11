import React from 'react';
import { ArrowUpRight, FileCheck2, Loader2, MapPin } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { pointType, REGISTER_COLORS } from '@/lib/registerUi';

export default function SearchResults({ results = [], onSelect, query, total, mappedTotal, unmappedTotal, truncated = false, loading = false, error }) {
  const { t, lang } = useI18n();
  if (!query || (Array.isArray(query) && query.length === 0)) return null;
  const previews = results.slice(0, 40);
  const knownTotal = Number.isSafeInteger(total) && total >= 0 ? total : null;
  const countText = knownTotal === null
    ? t('search.previewCount', { n: previews.length })
    : t('search.matches', { n: knownTotal.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB') });
  const isPreview = truncated || (knownTotal !== null && knownTotal > previews.length);
  const hasUnmapped = Number.isSafeInteger(unmappedTotal) && unmappedTotal > 0;
  return (
    <div className="search-results" aria-live="polite" aria-busy={loading}>
      <div className="search-results-title"><span>{t('search.results')}</span>{!loading && !error && <span>{countText}</span>}</div>
      {loading ? <p className="search-status" role="status"><Loader2 size={14} className="animate-spin" aria-hidden="true" />{t('search.loadingMap')}</p> : error ? <p className="search-status search-error" role="alert">{t('search.error')}</p> : previews.length === 0 ? <p className="search-empty">{t('search.noResults')}</p> : (
        <>
        {hasUnmapped && <p className="search-preview-note">{Number.isSafeInteger(mappedTotal) && mappedTotal >= 0 ? t('search.mappingCounts', { mapped: mappedTotal.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB'), unmapped: unmappedTotal.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB') }) : t('search.unmappedCount', { unmapped: unmappedTotal.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB') })}</p>}
        {isPreview && <p className="search-preview-note">{knownTotal === null ? t('search.previewUnknown', { n: previews.length }) : t('search.previewOfTotal', { n: previews.length, total: knownTotal.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB') })}</p>}
        <ul>{previews.map((result) => <li key={result.cadastral_id}>
          <button type="button" onClick={() => onSelect(result)}>
            <span className="result-icon" style={{ color: REGISTER_COLORS[pointType(result)] }}>{result.has_exploitation_certificate ? <FileCheck2 size={18} /> : <MapPin size={18} />}</span>
            <span className="min-w-0"><strong>{result.cadastral_id}</strong><small>{result.has_exploitation_certificate ? t('certificate.foundShort') : result.secondary}</small>{(result.lat === null || result.lng === null) && <small className="search-result-unmapped">{t('search.withoutCoordinates')}</small>}</span>
            <ArrowUpRight size={15} className="ml-auto shrink-0 text-slate-400" />
          </button>
        </li>)}</ul>
        </>
      )}
    </div>
  );
}
