import React, { useId, useRef, useState } from 'react';
import { AlertCircle, Info, Loader2, RefreshCw, SlidersHorizontal, X } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useI18n } from '@/lib/i18n';
import { REGISTER_COLORS } from '@/lib/registerUi';
import './MapLegend.css';

export default function MapLegend({ count, empty, loading, truncated, apiError, filterError, onEdit, onRetry }) {
  const { t, pick } = useI18n();
  const [open, setOpen] = useState(false);
  const id = useId();
  const openingFilters = useRef(false);
  const problem = Boolean(apiError || filterError);
  function editFilters() {
    openingFilters.current = open;
    setOpen(false);
    onEdit?.();
  }
  return <div className={`map-status-dock${problem ? ' has-problem' : ''}`}>
    <div className="map-status-pill">
      <div className="map-status-count" role="status" aria-live="polite" aria-atomic="true" aria-busy={loading}>
        {problem ? <><AlertCircle size={15} aria-hidden="true" /><span>{filterError ? pick('Провери филтрите', 'Check filters') : pick('Проблем с данните', 'Data unavailable')}</span></> : loading ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" /><span>{pick('Зареждане', 'Loading')}</span></> : <><strong>{count}</strong><span>{pick(String(count) === '1' ? 'имот' : 'имота', String(count) === '1' ? 'plot' : 'plots')}</span><span className="sr-only">{pick('в текущия изглед', 'in the current view')}</span></>}
      </div>
      {apiError && !filterError && <button type="button" className="map-status-action" title={t('map.retry')} aria-label={t('map.retry')} onClick={onRetry} disabled={loading || !onRetry}><RefreshCw size={16} aria-hidden="true" /></button>}
      {filterError && <button type="button" className="map-status-action" title={t('filter.edit')} aria-label={t('filter.edit')} onClick={editFilters}><SlidersHorizontal size={16} aria-hidden="true" /></button>}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild><button type="button" className="map-status-info" aria-label={pick('Легенда и информация за картата', 'Map legend and information')} title={pick('Легенда и информация', 'Legend and information')}><Info size={16} aria-hidden="true" />{truncated && !problem && <i className="map-status-notice-dot" aria-hidden="true" />}</button></PopoverTrigger>
        <PopoverContent side="top" align="start" sideOffset={9} collisionPadding={12} className="map-status-popover" aria-labelledby={id} style={{ zIndex: 1001 }} onCloseAutoFocus={(event) => { if (openingFilters.current) { event.preventDefault(); openingFilters.current = false; } }}>
          <div className="map-status-heading"><h2 id={id}>{t('legend.title')}</h2><button type="button" aria-label={pick('Затвори легендата', 'Close legend')} onClick={() => setOpen(false)}><X size={16} aria-hidden="true" /></button></div>
          <p className="map-status-context">{t('map.pointsInView')}: <strong>{problem || loading ? '—' : count}</strong></p>
          {!loading && empty && !problem && <p className="map-status-note">{t('filter.noMatchesView')}</p>}
          {apiError && !filterError && <p className="map-status-error">{t('map.apiError')}</p>}
          {filterError && <p className="map-status-error">{t(filterError)}</p>}
          <div className="map-status-colors">{Object.entries(REGISTER_COLORS).map(([code, color]) => <span key={code}><i style={{ backgroundColor: color }} />{t(`legend.${code}`)}</span>)}<span><i className="map-status-cluster">3</i>{t('legend.cluster')}</span></div>
          <p className="map-status-note">{pick('Точките служат за ориентация и не очертават граници на парцели.', 'Points guide location and do not outline parcel boundaries.')}</p>
          {truncated && <p className="map-status-warning">{t('map.truncated')}</p>}
        </PopoverContent>
      </Popover>
    </div>
  </div>;
}
