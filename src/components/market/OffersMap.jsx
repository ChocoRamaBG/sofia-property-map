import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Circle, MapContainer, Marker, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { divIcon } from 'leaflet';
import { Info, Loader2, MapPin, RefreshCw } from 'lucide-react';
import { marketApi } from '@/api/marketApi';
import { useI18n } from '@/lib/i18n';
import 'leaflet/dist/leaflet.css';
import './OffersMap.css';

function number(value, lang) { return Number.isFinite(value) ? value.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: 0 }) : '—'; }
function precisionLabel(value, bg) { return value === 'street' ? (bg ? 'Референтна улица' : 'Street reference') : value === 'address' ? (bg ? 'Адресен ориентир' : 'Address reference') : (bg ? 'Референтен квартал' : 'Neighborhood reference'); }
function sourceUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && url.hostname === 'kais.cadastre.bg' ? url.href : null; } catch { return null; }
}

function MapBridge({ active, onBounds }) {
  const map = useMapEvents({ moveend: () => emit(), zoomend: () => emit() });
  const emit = useCallback(() => {
    const bounds = map.getBounds();
    onBounds({ north: Math.min(85, bounds.getNorth()), south: Math.max(-85, bounds.getSouth()), west: Math.max(-180, bounds.getWest()), east: Math.min(180, bounds.getEast()), zoom: map.getZoom() });
  }, [map, onBounds]);
  useEffect(() => {
    if (!active) return undefined;
    const frame = window.requestAnimationFrame(() => { map.invalidateSize({ pan: true, animate: false }); emit(); });
    return () => window.cancelAnimationFrame(frame);
  }, [active, emit, map]);
  useEffect(() => {
    let frame;
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const container = map.getContainer();
        if (container.clientWidth && container.clientHeight) { map.invalidateSize({ pan: true, animate: false }); emit(); }
      });
    });
    observer.observe(map.getContainer());
    return () => { observer.disconnect(); window.cancelAnimationFrame(frame); };
  }, [emit, map]);
  return null;
}

function ReferenceMarkers({ items, lang, onSelectReference, onFocus }) {
  const map = useMap();
  const bg = lang === 'bg';
  return items.map((item) => {
    const reference = item.kind === 'reference';
    const location = item.location;
    const count = Number(item.count);
    if (!Number.isFinite(item.lat) || !Number.isFinite(item.lng) || !Number.isInteger(count) || count < 1) return null;
    const size = count >= 1000 ? 72 : count >= 100 ? 62 : count >= 10 ? 52 : 44;
    const icon = divIcon({ className: 'offers-reference-icon', iconSize: [size, size], iconAnchor: [size / 2, size / 2],
      html: `<span class="offers-reference-bubble ${reference && location?.precision === 'street' ? 'is-street' : ''} ${item.eligible_count > 0 ? 'has-deals' : ''}" style="width:${size}px;height:${size}px"><strong>${number(count, lang)}</strong><small>${bg ? 'обяви' : 'ads'}</small></span>` });
    const label = reference ? `${location.label_bg} · ${precisionLabel(location.precision, bg)}` : (bg ? `${number(count, lang)} обяви · група референтни зони` : `${number(count, lang)} listings · grouped reference areas`);
    const preciseBounds = item.bounds && item.bounds.north - item.bounds.south > 0.00002 && item.bounds.east - item.bounds.west > 0.00002;
    const canZoom = !reference && map.getZoom() < 17;
    const markerKey = reference ? location.key : item.key;
    return <Marker key={markerKey} position={[item.lat, item.lng]} icon={icon} title={label} keyboard eventHandlers={{
      click: () => {
        if (canZoom) {
          if (preciseBounds) map.fitBounds([[item.bounds.south, item.bounds.west], [item.bounds.north, item.bounds.east]], { padding: [45, 45], maxZoom: Math.min(17, map.getZoom() + 2) });
          else map.setView([item.lat, item.lng], Math.min(17, map.getZoom() + 2));
        }
      },
      popupopen: () => onFocus(reference ? location : null), popupclose: () => onFocus(null),
    }}>
      <Tooltip direction="top" offset={[0, -size / 2]}>{label}{item.eligible_count > 0 && <span className="offers-map-tooltip-deals">{bg ? `${number(item.eligible_count, lang)} под сравнимата медиана` : `${number(item.eligible_count, lang)} below the comparable median`}</span>}</Tooltip>
      {!canZoom && <Popup className="offers-reference-popup" maxWidth={350} minWidth={250}>
        {reference ? <>
          <span className="offers-map-precision">{precisionLabel(location.precision, bg)}</span>
          <h3>{location.label_bg}</h3>
          <p>{bg ? 'Групирани обяви с този ориентир. Кръгът показва приблизителния обхват на референтната зона; не показва адреса на отделен имот.' : 'Listings grouped by this reference. The circle shows the approximate reference area, rather than an individual property address.'}</p>
          <strong className="offers-popup-count">{number(count, lang)} {bg ? 'обяви' : 'listings'}</strong>
          {item.eligible_count > 0 && <span className="offers-popup-deals">{number(item.eligible_count, lang)} {bg ? 'с поне 20% под медианата' : 'at least 20% below median'}</span>}
          <button type="button" className="market-button is-primary" onClick={() => onSelectReference({ key: location.key, label_bg: location.label_bg })}>{bg ? 'Разгледай обявите тук' : 'Explore listings here'}</button>
          {sourceUrl(location.source_url) && <a href={sourceUrl(location.source_url)} target="_blank" rel="noreferrer">{bg ? 'Източник на ориентира: КАИС ↗' : 'Reference source: KAIS ↗'}</a>}
          {location.reference_date && <small className="offers-map-reference-date">{bg ? 'Референтни данни към' : 'Reference data captured'} {String(location.reference_date).slice(0, 10)}</small>}
        </> : <>
          <h3>{bg ? 'Референтни зони наблизо' : 'Nearby reference areas'}</h3>
          <p>{bg ? 'Няколко ориентира попадат в една група. Изберете зона, за да видите всички нейни обяви.' : 'Several references share this group. Choose an area to see all its listings.'}</p>
          <div className="offers-reference-choices">{(item.references || []).map((area) => <button type="button" key={area.key} onClick={() => onSelectReference(area)}><span>{area.label_bg}<small>{precisionLabel(area.precision, bg)}</small></span><strong>{number(area.count, lang)}</strong></button>)}</div>
        </>}
      </Popup>}
    </Marker>;
  });
}

export default function OffersMap({ summary, filters, active, onSelectReference }) {
  const { lang } = useI18n();
  const bg = lang === 'bg';
  const [bounds, setBounds] = useState(null);
  const [revision, setRevision] = useState(0);
  const [focus, setFocus] = useState(null);
  const [state, setState] = useState({ loading: true, error: false, key: '', data: null });
  const filterKey = JSON.stringify(filters);
  const dataKey = `${summary.snapshot_id}:${filterKey}`;
  const lastBounds = useRef('');
  const changeBounds = useCallback((next) => {
    const key = JSON.stringify(next);
    if (key !== lastBounds.current) { lastBounds.current = key; setBounds(next); }
  }, []);
  useEffect(() => {
    if (!active || !bounds) return undefined;
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: false, ...(previous.key === dataKey ? {} : { data: null, key: dataKey }) }));
    setFocus(null);
    const timer = window.setTimeout(() => {
      marketApi.viewport({ ...JSON.parse(filterKey), deals_only: filters.deals_only ? 1 : undefined, ...bounds }, controller.signal).then((data) => {
        if (data?.snapshot_id !== summary.snapshot_id || !Array.isArray(data.items) || data.items.length > 800 || !Number.isInteger(data.total) || !Number.isInteger(data.located_total) || !Number.isInteger(data.unlocated_total) || data.located_total + data.unlocated_total !== data.total) throw new Error('Inconsistent map snapshot.');
        if (!controller.signal.aborted) setState({ loading: false, error: false, key: dataKey, data });
      }).catch(() => { if (!controller.signal.aborted) setState((previous) => ({ ...previous, loading: false, error: true })); });
    }, 220);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [active, bounds, dataKey, filterKey, filters.deals_only, revision, summary.snapshot_id]);
  const data = state.key === dataKey ? state.data : null;
  const items = useMemo(() => data?.items || [], [data]);
  return <div className="offers-map-workspace">
    <div className="offers-map-intro"><Info size={17} /><p>{bg ? 'Картата показва приблизителни ориентири по улица или квартал, извлечени от обявите и съпоставени с референтните данни на КАИС. Балонът е група обяви, а не конкретна сграда. Изберете балон, за да разгледате обявите.' : 'The map shows approximate street or neighborhood references extracted from listings and matched to KAIS reference data. Each bubble is a group of listings. Select it to explore the ads.'}</p></div>
    <div className="offers-map-canvas">
      <MapContainer center={[42.69, 23.33]} zoom={12} minZoom={8} maxZoom={19} maxBounds={[[40.5, 21], [45, 30]]} maxBoundsViscosity={1} preferCanvas scrollWheelZoom={false} className="offers-leaflet-map">
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" maxZoom={19} />
        {focus && <Circle center={[focus.lat, focus.lng]} radius={focus.radius_m} pathOptions={{ color: '#b66c35', weight: 1.5, dashArray: '6 5', fillColor: '#dcac73', fillOpacity: 0.12, interactive: false }} />}
        <ReferenceMarkers items={items} lang={lang} onSelectReference={onSelectReference} onFocus={setFocus} />
        <MapBridge active={active} onBounds={changeBounds} />
      </MapContainer>
      {state.loading && <div className="offers-map-progress" role="status"><Loader2 className="animate-spin" size={16} />{bg ? 'Обновяване на зоните…' : 'Updating areas…'}</div>}
      {state.error && <div className="offers-map-message is-error" role="alert"><p>{bg ? 'Картата на обявите не се зареди. Опитайте отново.' : 'The listings map could not load. Please try again.'}</p><button className="market-button" type="button" onClick={() => setRevision((value) => value + 1)}><RefreshCw size={14} />{bg ? 'Опитай отново' : 'Try again'}</button></div>}
      {!state.loading && !state.error && data && items.length === 0 && <div className="offers-map-message"><MapPin size={20} /><p>{bg ? 'Няма референтни зони в този изглед с избраните условия. Намалете мащаба или променете филтрите.' : 'No reference areas match this view and these filters. Zoom out or change the filters.'}</p></div>}
    </div>
    <div className="offers-map-footer" aria-live="polite"><div className="offers-map-legend"><span><i className="is-street" />{bg ? 'Улица' : 'Street'}</span><span><i />{bg ? 'Квартал / група' : 'Neighborhood / group'}</span><span><i className="has-deals" />{bg ? 'Има оферти под медианата' : 'Includes below-median offers'}</span></div>{data && <p><strong>{number(data.viewport_total, lang)}</strong> {bg ? 'обяви в изгледа' : 'listings in view'} · {number(data.located_total, lang)} / {number(data.total, lang)} {bg ? 'с ориентир' : 'with a reference'} · <strong>{number(data.unlocated_total, lang)}</strong> {bg ? 'без достатъчно местоположение (достъпни в списъка)' : 'without enough location detail (available in the list)'}</p>}</div>
  </div>;
}
