import React, { useEffect, useRef, useState } from 'react';
import { CircleDot, Crosshair, Layers, Map, Minus, Pentagon, Plus, RotateCcw } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useIsMobile } from '@/hooks/use-mobile';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import './ParcelGeometryLayer.css';
import './MapToolbar.css';

function ToolButton({ label, onClick, children }) {
  return <button type="button" title={label} aria-label={label} onClick={onClick} className="map-tool-button">{children}</button>;
}

export default function MapToolbar({ onZoomIn, onZoomOut, onLocate, onReset, baseLayer, onBaseLayerChange, parcelMode = 'points', onParcelModeChange, active = true }) {
  const { t, pick } = useI18n();
  const [open, setOpen] = useState(false);
  const isMobile = useIsMobile();
  const toolbar = useRef(null);
  useEffect(() => { if (!active) setOpen(false); }, [active]);
  const act = (callback) => { callback?.(); setOpen(false); };
  return <div className="map-toolbar" ref={toolbar} role="group" aria-label={pick('Контроли на картата', 'Map controls')}>
    <div className="map-zoom-group">
      <ToolButton label={t('map.zoomIn')} onClick={onZoomIn}><Plus size={18} aria-hidden="true" /></ToolButton>
      <ToolButton label={t('map.zoomOut')} onClick={onZoomOut}><Minus size={18} aria-hidden="true" /></ToolButton>
    </div>
    <Popover open={active && open} onOpenChange={setOpen}>
      <PopoverTrigger asChild><button type="button" className="map-tool-button map-display-trigger" title={pick('Изглед и инструменти', 'Map display and tools')} aria-label={pick('Изглед и инструменти на картата', 'Map display and tools')}><Layers size={18} aria-hidden="true" /></button></PopoverTrigger>
      <PopoverContent side={isMobile ? 'bottom' : 'left'} align={isMobile ? 'end' : 'start'} sideOffset={10} collisionPadding={12} collisionBoundary={toolbar.current?.closest('.map-stage') || undefined} className="map-display-menu" style={{ zIndex: 1001 }}>
        <h2>{pick('Изглед на картата', 'Map display')}</h2>
        <fieldset><legend>{pick('Основна карта', 'Base map')}</legend><div className="map-display-options">
          <button type="button" aria-pressed={baseLayer !== 'satellite'} onClick={() => onBaseLayerChange('standard')}><Map size={17} aria-hidden="true" />{pick('Карта', 'Map')}</button>
          <button type="button" aria-pressed={baseLayer === 'satellite'} onClick={() => onBaseLayerChange('satellite')}><Layers size={17} aria-hidden="true" />{pick('Сателит', 'Satellite')}</button>
        </div></fieldset>
        {onParcelModeChange && <fieldset><legend>{pick('Показване на имотите', 'Parcel display')}</legend><div className="map-display-options">
          <button type="button" aria-pressed={parcelMode === 'points'} onClick={() => onParcelModeChange('points')}><CircleDot size={17} aria-hidden="true" />{pick('Точки', 'Points')}</button>
          <button type="button" aria-pressed={parcelMode === 'boundaries'} onClick={() => onParcelModeChange('boundaries')}><Pentagon size={17} aria-hidden="true" />{pick('Граници', 'Boundaries')}</button>
        </div>{parcelMode === 'boundaries' && <p>{pick('Приближете за отделните кадастрални граници.', 'Zoom in to see individual cadastral boundaries.')}</p>}</fieldset>}
        <div className="map-display-actions">
          <button type="button" onClick={() => act(onLocate)}><Crosshair size={17} aria-hidden="true" />{t('map.locate')}</button>
          <button type="button" onClick={() => act(onReset)}><RotateCcw size={17} aria-hidden="true" />{t('map.reset')}</button>
        </div>
      </PopoverContent>
    </Popover>
  </div>;
}
