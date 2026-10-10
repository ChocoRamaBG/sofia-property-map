import React from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { REGISTER_COLORS } from '@/lib/registerUi';

export default function MapLegend({ count, empty, loading, truncated, apiError, filterError, activeCount, onClear, onEdit }) {
  const { t } = useI18n();
  return (
    <div className="map-legend">
      <div className="map-count" role="status">{loading ? <><Loader2 size={14} className="animate-spin" />{t('map.loading')}</> : <><span className="map-count-number">{count}</span><span>{t('map.pointsInView')}</span></>}</div>
      {activeCount > 0 && <p className="legend-active-filter">{t('filter.activeCount', { n: activeCount })}</p>}
      {!loading && empty && !apiError && !filterError && <p className="map-legend-empty">{t('filter.noMatchesView')}</p>}
      {activeCount > 0 && <div className="map-legend-actions"><button onClick={onEdit}>{t('filter.edit')}</button><button onClick={onClear}>{t('filter.clearAll')}</button></div>}
      <details className="legend-colors"><summary>{t('legend.title')}<ChevronDown size={13} /></summary><div>{Object.entries(REGISTER_COLORS).map(([code, color]) => <span key={code}><i style={{ background: color }} />{t(`legend.${code}`)}</span>)}<span><i className="legend-cluster-sample">3</i>{t('legend.cluster')}</span></div></details>
      {truncated && <p className="legend-warning">{t('map.truncated')}</p>}
      {apiError && <p role="alert" className="legend-error">{t('map.apiError')}</p>}
      {filterError && <p role="alert" className="legend-error">{t('filter.dateRangeError')}</p>}
    </div>
  );
}
