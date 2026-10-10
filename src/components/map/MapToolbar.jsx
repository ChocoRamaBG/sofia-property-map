import React from 'react';
import { Crosshair, Layers, Minus, Plus, RotateCcw } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { cn } from '@/lib/utils';

function ToolButton({ label, onClick, active, children }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
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

export default function MapToolbar({ onZoomIn, onZoomOut, onLocate, onReset, baseLayer, onBaseLayerChange }) {
  const { t } = useI18n();
  return (
    <div className="map-toolbar">
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
