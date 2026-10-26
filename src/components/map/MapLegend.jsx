import React from 'react';
import { ChevronDown, Loader2, RefreshCw } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { REGISTER_COLORS } from '@/lib/registerUi';

export default function MapLegend({ count, empty, loading, truncated, apiError, filterError, activeCount, onClear, onEdit, onRetry }) {
  const { t, pick } = useI18n();
  return (
    <div className="map-legend">
      <div className="map-count" role="status">{loading ? <><Loader2 size={14} className="animate-spin" />{t('map.loading')}</> : <><span className="map-count-number">{count}</span><span>{t('map.pointsInView')}</span></>}</div>
      {!loading && empty && !apiError && !filterError && <p className="map-legend-empty">{t('filter.noMatchesView')}</p>}
      {activeCount > 0 && <div className="map-legend-actions"><button onClick={onEdit}>{t('filter.edit')}</button><button onClick={onClear}>{t('filter.clearAll')}</button></div>}
      <details className="legend-colors"><summary>{t('legend.title')}<ChevronDown size={13} /></summary><div>{Object.entries(REGISTER_COLORS).map(([code, color]) => <span key={code}><i style={{ background: color }} />{t(`legend.${code}`)}</span>)}<span><i className="legend-cluster-sample">3</i>{t('legend.cluster')}</span></div></details>
      <p className="map-point-note">{pick('Точките служат за ориентация и не очертават граници.', 'Points guide location and do not outline parcel boundaries.')}</p>
      {truncated && <p className="legend-warning">{t('map.truncated')}</p>}
      {apiError && !filterError && <div><p role="alert" className="legend-error">{t('map.apiError')}</p><div className="map-legend-actions"><button type="button" onClick={onRetry} disabled={loading || !onRetry}>{loading ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}{t(loading ? 'map.retrying' : 'map.retry')}</button></div></div>}
      {filterError && <p role="alert" className="legend-error">{t(filterError)}</p>}
    </div>
  );
}
