import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GeoJSON } from 'react-leaflet';
import { svg } from 'leaflet';
import { realEstateApi } from '@/api/realEstateApi';
import { invalidFilterArea, invalidFilterDates, invalidFilterSearch, propertyFilterParams } from '@/lib/propertyFilters';
import { displayDate, pointType, REGISTER_COLORS } from '@/lib/registerUi';
import { useI18n } from '@/lib/i18n';
import './ParcelGeometryLayer.css';

const MIN_ZOOM = 16;
const MAX_ITEMS = 600;
const MAX_VERTICES = 100000;
const CADASTRAL_ID = /^\d{4,6}\.\d{1,6}\.\d{1,6}$/;

function coordinate(value, limit) { return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= limit; }
function safeSource(source, lang) {
  let url = null;
  try { const parsed = new URL(source?.url); if (parsed.protocol === 'https:' && !parsed.username && !parsed.password) url = parsed.href; } catch { /* Missing provenance remains explicitly unknown. */ }
  return { source_url: url, source_name: (lang === 'bg' ? source?.label_bg : source?.label_en) || source?.label_bg || source?.label_en || null, captured_at: source?.captured_at || null };
}
function flags(properties) {
  return { ...properties, has_exploitation_certificate: Boolean(Number(properties.has_exploitation_certificate)), has_building_permit: Boolean(Number(properties.has_building_permit)), has_projecting_visa: Boolean(Number(properties.has_projecting_visa)) };
}

// Reject an incomplete response as a whole. A dropped feature would otherwise
// make the displayed shapes look like the complete filtered viewport.
function checkedCollection(payload) {
  if (!payload || payload.type !== 'FeatureCollection' || !['available', 'zoom_in', 'too_dense', 'unavailable'].includes(payload.status)) throw new Error('Invalid parcel geometry response.');
  if (payload.status !== 'available') {
    if (payload.complete === true || payload.features?.length || payload.fallback_points?.length) throw new Error('Unexpected partial parcel geometry response.');
    return payload;
  }
  if (payload.complete !== true || !Array.isArray(payload.features) || !Array.isArray(payload.fallback_points) || payload.features.length + payload.fallback_points.length > MAX_ITEMS) throw new Error('Incomplete parcel geometry response.');
  if (payload.geometry_count !== payload.features.length || payload.missing_count !== payload.fallback_points.length || payload.total !== payload.geometry_count + payload.missing_count) throw new Error('Parcel geometry counts do not reconcile.');
  const ids = new Set();
  let vertices = 0;
  function ringsValid(rings) {
    return Array.isArray(rings) && rings.length > 0 && rings.every((ring) => {
      if (!Array.isArray(ring) || ring.length < 4 || (vertices += ring.length) > MAX_VERTICES) return false;
      const first = ring[0]; const last = ring[ring.length - 1];
      if (!Array.isArray(first) || !Array.isArray(last) || first[0] !== last[0] || first[1] !== last[1]) return false;
      return ring.every((position) => Array.isArray(position) && position.length === 2 && coordinate(position[0], 180) && coordinate(position[1], 90));
    });
  }
  function uniqueId(id) { if (typeof id !== 'string' || !CADASTRAL_ID.test(id) || ids.has(id)) return false; ids.add(id); return true; }
  const features = payload.features.map((feature) => {
    const geometry = feature?.geometry;
    if (feature?.type !== 'Feature' || !uniqueId(feature.properties?.cadastral_id) || !geometry || !['Polygon', 'MultiPolygon'].includes(geometry.type)) throw new Error('Invalid parcel feature.');
    const valid = geometry.type === 'Polygon' ? ringsValid(geometry.coordinates) : Array.isArray(geometry.coordinates) && geometry.coordinates.length > 0 && geometry.coordinates.every(ringsValid);
    if (!valid) throw new Error('Invalid parcel ring.');
    return { ...feature, properties: flags(feature.properties) };
  });
  const fallback = payload.fallback_points.map((point) => {
    if (!uniqueId(point?.cadastral_id) || !coordinate(point.lat, 90) || !coordinate(point.lng, 180)) throw new Error('Invalid parcel fallback point.');
    return flags(point);
  });
  return { ...payload, features, fallback_points: fallback };
}

export function useParcelGeometry({ bounds, filters, active, parcelMode, revision = 0 }) {
  const { lang } = useI18n();
  const params = propertyFilterParams(filters || {});
  const invalidFilters = invalidFilterArea(filters) || invalidFilterDates(filters) || invalidFilterSearch(filters);
  const enabled = Boolean(active && parcelMode === 'boundaries' && bounds && Number(bounds.zoom) >= MIN_ZOOM && !invalidFilters);
  const key = JSON.stringify({ bounds: bounds ? [bounds.north, bounds.south, bounds.east, bounds.west, bounds.zoom] : null, params, revision });
  const [state, setState] = useState({ key: null, data: null, status: 'zoom_in' });
  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setState({ key, data: null, status: 'loading' });
    const timer = window.setTimeout(() => {
      realEstateApi.boundaries(bounds, filters, controller.signal).then((result) => {
        if (controller.signal.aborted) return;
        const data = checkedCollection(result);
        const status = { available: 'ready', zoom_in: 'zoom_in', too_dense: 'dense', unavailable: 'unavailable' }[data.status];
        setState({ key, data, status });
      }).catch((error) => { if (!controller.signal.aborted && error.name !== 'AbortError') setState({ key, data: null, status: 'error' }); });
    }, 120);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [enabled, key]);
  const current = enabled && state.key === key ? state : { key, data: null, status: invalidFilters ? 'unavailable' : enabled ? 'loading' : 'zoom_in' };
  const data = current.status === 'ready' ? current.data : null;
  const status = useMemo(() => ({ status: current.status, min_zoom: MIN_ZOOM, reason: current.data?.reason || null, total: data?.total ?? null, geometry_count: data?.geometry_count ?? null, missing_count: data?.missing_count ?? null, fallback_count: data?.fallback_points.length ?? null, ...safeSource(current.data?.source, lang) }), [current.status, current.data, data, lang]);
  return { data, status, key };
}

function metric(value, lang, unit) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? `${new Intl.NumberFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: 2 }).format(value)} ${unit}` : null;
}

export default function ParcelGeometryLayer({ data, dataKey, selectedKey, hoveredKey, onSelect, onHover }) {
  const { lang, t, pick } = useI18n();
  const group = useRef(null);
  const actions = useRef({ onSelect, onHover });
  actions.current = { onSelect, onHover };
  const renderer = useMemo(() => svg({ padding: 0.15, pane: 'parcel-boundaries' }), []);
  const style = useCallback((feature) => {
    const plot = feature.properties;
    const selected = plot.cadastral_id === selectedKey;
    const hovered = plot.cadastral_id === hoveredKey;
    const color = REGISTER_COLORS[pointType(plot)] || REGISTER_COLORS.no_records;
    return { color: selected ? '#173f39' : color, weight: selected ? 3.5 : hovered ? 2.5 : 1.5, opacity: 0.95, fillColor: color, fillOpacity: selected ? 0.3 : hovered ? 0.23 : 0.1, lineJoin: 'round', lineCap: 'round' };
  }, [selectedKey, hoveredKey]);
  const eachFeature = useCallback((feature, layer) => {
    const plot = feature.properties;
    const source = safeSource(plot.source || data.source, lang);
    const tooltip = document.createElement('div');
    const title = document.createElement('strong'); title.textContent = plot.cadastral_id; tooltip.appendChild(title);
    const rows = [t(`legend.${pointType(plot)}`), pick('Кадастрална граница от отворени данни', 'Cadastral boundary from open data')];
    const area = metric(plot.area_m2, lang, 'm²');
    const perimeter = metric(plot.published_perimeter_m ?? plot.perimeter_m, lang, 'm');
    if (area) rows.push(`${pick('Публикувана площ:', 'Published area:')} ${area}`);
    if (perimeter) rows.push(`${pick('Публикуван периметър:', 'Published perimeter:')} ${perimeter}`);
    rows.push(`${source.source_name || pick('Източникът не е посочен', 'Source not stated')} · ${source.captured_at ? displayDate(source.captured_at, lang) : pick('Непозната дата на извличане', 'Capture date unknown')}`);
    rows.push(pick('За официално трасиране е нужна кадастрална услуга.', 'An official cadastral service is needed for legal setting-out.'));
    for (const text of rows) { const line = document.createElement('span'); line.textContent = text; tooltip.appendChild(line); }
    layer.bindTooltip(tooltip, { sticky: true, direction: 'auto', className: 'parcel-boundary-tooltip', opacity: 1 });
    const selectedPlot = { ...plot, geometry_bounds: feature.bbox || null };
    layer.on({ click: () => actions.current.onSelect?.(selectedPlot), mouseover: () => actions.current.onHover?.(plot.cadastral_id), mouseout: () => actions.current.onHover?.(null) });
    let element;
    const keyboard = (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); actions.current.onSelect?.(selectedPlot); } };
    const focus = () => { actions.current.onHover?.(plot.cadastral_id); layer.openTooltip(); };
    const blur = () => { actions.current.onHover?.(null); layer.closeTooltip(); };
    layer.on('add', () => {
      element = layer.getElement();
      if (!element) return;
      element.setAttribute('tabindex', '0'); element.setAttribute('role', 'button');
      element.setAttribute('aria-label', `${pick('Имот', 'Plot')} ${plot.cadastral_id}. ${t(`legend.${pointType(plot)}`)}${area ? `. ${area}` : ''}`);
      element.addEventListener('keydown', keyboard); element.addEventListener('focus', focus); element.addEventListener('blur', blur);
    });
    layer.on('remove', () => { element?.removeEventListener('keydown', keyboard); element?.removeEventListener('focus', focus); element?.removeEventListener('blur', blur); });
  }, [data.source, lang, pick, t]);
  useEffect(() => {
    group.current?.eachLayer((layer) => {
      const selected = layer.feature?.properties?.cadastral_id === selectedKey;
      const element = layer.getElement();
      if (selected) { element?.setAttribute('aria-current', 'true'); layer.bringToFront(); }
      else element?.removeAttribute('aria-current');
    });
  }, [dataKey, lang, selectedKey]);
  return <GeoJSON key={`${dataKey}:${lang}`} ref={group} data={data} renderer={renderer} pane="parcel-boundaries" smoothFactor={0} className="parcel-boundary-path" style={style} onEachFeature={eachFeature} />;
}
