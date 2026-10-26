import React from 'react';
import { CircleDot, Crosshair, Layers, Minus, Pentagon, Plus, RotateCcw } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { cn } from '@/lib/utils';
import './ParcelGeometryLayer.css';

function ToolButton({ label, onClick, active, children }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={typeof active === 'boolean' ? active : undefined}
      onClick={onClick}
      className={cn(
        'map-tool-button',
        active && 'bg-primary text-primary-foreground hover:bg-primary'
      )}
    >
      {children}
    </button>
  );
}

export default function MapToolbar({ onZoomIn, onZoomOut, onLocate, onReset, baseLayer, onBaseLayerChange, parcelMode = 'points', onParcelModeChange }) {
  const { t, pick } = useI18n();
  return (
    <div className="map-toolbar">
      {onParcelModeChange && <div className="map-parcel-mode" role="group" aria-label={pick('Показване на имотите', 'Parcel display')}>
        <button type="button" aria-pressed={parcelMode === 'points'} title={pick('Покажи кадастралните координатни точки', 'Show cadastral coordinate points')} onClick={() => onParcelModeChange('points')}><CircleDot size={16} aria-hidden="true" /><span>{pick('Точки', 'Points')}</span></button>
        <button type="button" aria-pressed={parcelMode === 'boundaries'} title={pick('Покажи границите от кадастралните отворени данни; приближете картата за отделни имоти', 'Show boundaries from cadastral open data; zoom in for individual plots')} onClick={() => onParcelModeChange('boundaries')}><Pentagon size={16} aria-hidden="true" /><span>{pick('Граници', 'Boundaries')}</span></button>
      </div>}
      <ToolButton label={t('map.zoomIn')} onClick={onZoomIn}>
        <Plus className="h-4 w-4" aria-hidden="true" />
      </ToolButton>
      <ToolButton label={t('map.zoomOut')} onClick={onZoomOut}>
        <Minus className="h-4 w-4" aria-hidden="true" />
      </ToolButton>
      <ToolButton label={t('map.locate')} onClick={onLocate}>
        <Crosshair className="h-4 w-4" aria-hidden="true" />
      </ToolButton>
      <ToolButton label={t('map.reset')} onClick={onReset}>
        <RotateCcw className="h-4 w-4" aria-hidden="true" />
      </ToolButton>
      <ToolButton
        label={baseLayer === 'standard' ? t('map.satellite') : t('map.standard')}
        onClick={() => onBaseLayerChange(baseLayer === 'standard' ? 'satellite' : 'standard')}
        active={baseLayer === 'satellite'}
      >
        <Layers className="h-4 w-4" aria-hidden="true" />
      </ToolButton>
    </div>
  );
}
