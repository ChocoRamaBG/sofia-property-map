import React, { useId, useRef, useState } from 'react';
import { AlertCircle, Info, Loader2, RefreshCw, SlidersHorizontal, X, ZoomIn } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useI18n } from '@/lib/i18n';
import { displayCount, displayDate, REGISTER_COLORS } from '@/lib/registerUi';
import './MapLegend.css';

export default function MapLegend({ count, empty, loading, truncated, apiError, filterError, onEdit, onRetry, parcelMode = 'points', boundaryStatus = null, onZoomIn }) {
  const { t, pick, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const id = useId();
  const openingFilters = useRef(false);
  const boundaries = parcelMode === 'boundaries';
  const boundaryReady = boundaries && boundaryStatus?.status === 'ready';
  const problem = Boolean(filterError || (apiError && !boundaryReady));
  const boundaryZoom = boundaries && ['zoom_in', 'dense'].includes(boundaryStatus?.status);
  const boundaryIssue = boundaries && ['error', 'unavailable'].includes(boundaryStatus?.status);
  const busy = (loading && !boundaryReady) || (boundaries && boundaryStatus?.status === 'loading');
  const shownCount = boundaryReady && Number.isFinite(boundaryStatus.total) ? displayCount(boundaryStatus.total, lang) : count;
  function editFilters() {
    openingFilters.current = open;
    setOpen(false);
    onEdit?.();
  }
  return <div className={`map-status-dock${problem ? ' has-problem' : ''}`}>
    <div className="map-status-pill">
      <div className="map-status-count" role="status" aria-live="polite" aria-atomic="true" aria-busy={busy}>
        {problem ? <><AlertCircle size={15} aria-hidden="true" /><span>{filterError ? pick('Провери филтрите', 'Check filters') : pick('Проблем с данните', 'Data unavailable')}</span></> : busy ? <><Loader2 size={14} className="animate-spin" aria-hidden="true" /><span>{pick('Зареждане', 'Loading')}</span></> : boundaryZoom ? <span>{pick('Приближи за граници', 'Zoom in for boundaries')}</span> : <><strong>{shownCount}</strong><span>{boundaryIssue ? pick('точки', 'points') : pick(String(shownCount) === '1' ? 'имот' : 'имота', String(shownCount) === '1' ? 'plot' : 'plots')}</span><span className="sr-only">{pick('в текущия изглед', 'in the current view')}</span></>}
      </div>
      {((apiError && !boundaryReady) || boundaryIssue) && !filterError && <button type="button" className="map-status-action" title={t('map.retry')} aria-label={t('map.retry')} onClick={onRetry} disabled={busy || !onRetry}><RefreshCw size={16} aria-hidden="true" /></button>}
      {boundaryZoom && !problem && <button type="button" className="map-status-action" title={pick('Приближи за кадастрални граници', 'Zoom in for parcel boundaries')} aria-label={pick('Приближи за кадастрални граници', 'Zoom in for parcel boundaries')} onClick={onZoomIn}><ZoomIn size={16} aria-hidden="true" /></button>}
      {filterError && <button type="button" className="map-status-action" title={t('filter.edit')} aria-label={t('filter.edit')} onClick={editFilters}><SlidersHorizontal size={16} aria-hidden="true" /></button>}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild><button type="button" className="map-status-info" aria-label={pick('Легенда и информация за картата', 'Map legend and information')} title={pick('Легенда и информация', 'Legend and information')}><Info size={16} aria-hidden="true" />{(truncated || boundaryIssue) && !problem && <i className="map-status-notice-dot" aria-hidden="true" />}</button></PopoverTrigger>
        <PopoverContent side="top" align="start" sideOffset={9} collisionPadding={12} className="map-status-popover" aria-labelledby={id} style={{ zIndex: 1001 }} onCloseAutoFocus={(event) => { if (openingFilters.current) { event.preventDefault(); openingFilters.current = false; } }}>
          <div className="map-status-heading"><h2 id={id}>{t('legend.title')}</h2><button type="button" aria-label={pick('Затвори легендата', 'Close legend')} onClick={() => setOpen(false)}><X size={16} aria-hidden="true" /></button></div>
          <p className="map-status-context">{t('map.pointsInView')}: <strong>{problem || busy ? '—' : shownCount}</strong></p>
          {!busy && (boundaryReady ? boundaryStatus.total === 0 : empty) && !problem && <p className="map-status-note">{t('filter.noMatchesView')}</p>}
          {apiError && !boundaryReady && !filterError && <p className="map-status-error">{t('map.apiError')}</p>}
          {filterError && <p className="map-status-error">{t(filterError)}</p>}
          <div className="map-status-colors">{Object.entries(REGISTER_COLORS).map(([code, color]) => <span key={code}><i style={{ backgroundColor: color }} />{t(`legend.${code}`)}</span>)}<span><i className="map-status-cluster">3</i>{t('legend.cluster')}</span></div>
          {boundaries ? <div className="map-boundary-evidence">
            <strong>{pick('Кадастрални граници', 'Cadastral boundaries')}</strong>
            {boundaryZoom && <p>{pick('Приближете картата. При широк или прекалено гъст изглед се запазват всички групирани точки.', 'Zoom in. Wide or very dense views retain all grouped points.')}</p>}
            {boundaryIssue && <p>{pick('Слоят с границите временно не е достъпен. Показаните точки не очертават парцелите.', 'The boundary layer is temporarily unavailable. The displayed points do not outline parcels.')}</p>}
            {boundaryReady && <p>{displayCount(boundaryStatus.geometry_count || 0, lang)} {pick('публикувани очертания', 'published outlines')}{boundaryStatus.missing_count > 0 && <> · {displayCount(boundaryStatus.missing_count, lang)} {pick('точки без налична използваема геометрия', 'points without usable geometry')}</>}</p>}
            <a href="https://kais.cadastre.bg/bg/OpenData" target="_blank" rel="noreferrer">{pick('Източник: АГКК · КАИС, Отворени данни', 'Source: AGCC · KAIS Open Data')}</a>
            {boundaryStatus?.captured_at && <p>{pick('Извлечено:', 'Captured:')} {displayDate(boundaryStatus.captured_at, lang)}</p>}
            <p>{pick('Публикувана геометрия, преобразувана за картата. Площта и периметърът са стойностите на източника; слоят не е заверена скица или геодезическо измерване.', 'Published geometry transformed for this map. Area and perimeter retain source values; this layer is not a certified cadastral sketch or field survey.')}</p>
          </div> : <p className="map-status-note">{pick('Точките служат за ориентация и не очертават граници на парцели.', 'Points guide location and do not outline parcel boundaries.')}</p>}
          {truncated && <p className="map-status-warning">{t('map.truncated')}</p>}
        </PopoverContent>
      </Popover>
    </div>
  </div>;
}
