import React, { useEffect } from 'react';
import { CircleMarker, MapContainer, Marker, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { divIcon } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useI18n } from '@/lib/i18n';
import { displayCount, pointType, REGISTER_COLORS } from '@/lib/registerUi';

const TILES = {
  standard: {
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  },
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri',
    maxZoom: 19,
  },
};

const ADDRESS_ICON = divIcon({
  className: 'address-location-icon', iconSize: [34, 42], iconAnchor: [17, 40], popupAnchor: [0, -34],
  html: '<svg viewBox="0 0 34 42" width="34" height="42" aria-hidden="true"><path d="M17 40C12 32 2 25 2 17a15 15 0 0 1 30 0c0 8-10 15-15 23Z" fill="#c86624" stroke="white" stroke-width="3"/><circle cx="17" cy="17" r="5" fill="white"/></svg>',
});

function MapBridge({ onMapReady }) {
  const map = useMap();
  useEffect(() => { onMapReady(map); }, [map, onMapReady]);
  useEffect(() => {
    let frame;
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => map.invalidateSize({ pan: false }));
    });
    observer.observe(map.getContainer());
    return () => { observer.disconnect(); window.cancelAnimationFrame(frame); };
  }, [map]);
  return null;
}

function emitBounds(map, onChange) {
  const bounds = map.getBounds();
  onChange({ north: bounds.getNorth(), south: bounds.getSouth(), east: bounds.getEast(), west: bounds.getWest(), zoom: map.getZoom() });
}

function BoundsWatcher({ onChange }) {
  const map = useMapEvents({
    moveend() { emitBounds(map, onChange); },
    zoomend() { emitBounds(map, onChange); },
  });
  useEffect(() => { emitBounds(map, onChange); }, [map, onChange]);
  return null;
}

export default function MapView({
  parcels = [], selectedParcel, selectedKey, hoveredKey, baseLayer = 'standard', userLocation, addressLocation,
  onSelect, onHover, onBoundsChange, onMapReady, onClusterClick,
}) {
  const { t, lang } = useI18n();
  const tiles = TILES[baseLayer] || TILES.standard;
  const selectedInView = parcels.some((item) => item.cadastral_id === selectedKey);
  const selectedOutside = !selectedInView && selectedParcel?.lat != null && selectedParcel?.lng != null ? selectedParcel : null;

  return (
    <MapContainer center={[42.684, 23.333]} zoom={13} zoomControl={false} preferCanvas className="h-full w-full" scrollWheelZoom>
      <TileLayer url={tiles.url} attribution={tiles.attribution} maxZoom={tiles.maxZoom} />
      {parcels.map((item, index) => {
        const cluster = item.kind === 'cluster';
        const selected = item.cadastral_id === selectedKey;
        const hovered = item.cadastral_id === hoveredKey;
        const type = pointType(item);
        const radius = selected ? 9 : hovered ? 8 : type === 'no_records' ? 4 : 6;
        const color = selected ? '#163f47' : REGISTER_COLORS[type];
        const position = [Number(item.lat), Number(item.lng)];
        if (!Number.isFinite(position[0]) || !Number.isFinite(position[1])) return null;
        if (cluster) {
          const count = Number(item.count);
          if (!Number.isFinite(count) || count < 1) return null;
          const certificateCount = Number(item.certificate_count) || 0;
          const scale = count >= 1000 ? 'xlarge' : count >= 100 ? 'large' : count >= 10 ? 'medium' : 'small';
          const size = { small: 44, medium: 56, large: 68, xlarge: 80 }[scale];
          const clusterLabel = t(count === 1 ? 'map.clusterSingle' : 'map.cluster', { n: displayCount(count, lang) });
          const certificateLabel = certificateCount > 0 ? t('map.clusterCertificates', { n: displayCount(certificateCount, lang) }) : '';
          const clusterZoom = Number.isFinite(Number(item.zoom)) ? Number(item.zoom) : 13;
          const icon = divIcon({
            className: 'plot-cluster-icon', iconSize: [size, size], iconAnchor: [size / 2, size / 2],
            html: `<span class="plot-cluster plot-cluster-${scale} ${certificateCount ? 'has-certificate' : ''}" style="width:${size}px;height:${size}px"><span class="cluster-count">${displayCount(count, lang)}</span>${count >= 10 ? `<span class="cluster-count-label">${t('map.clusterPlots')}</span>` : ''}${certificateCount ? '<span class="cluster-certificate-dot" aria-hidden="true"></span>' : ''}</span>`,
          });
          return <Marker key={`cluster-${item.cell_key || index}`} position={position} icon={icon} title={[clusterLabel, certificateLabel].filter(Boolean).join(' ')} keyboard zIndexOffset={size} eventHandlers={{ click: () => onClusterClick(position, Math.min(19, clusterZoom + 2), item.bounds, count) }}>
            <Tooltip direction="top" offset={[0, -(size / 2) + 5]}><span>{clusterLabel}</span>{certificateCount > 0 && <span className="cluster-tooltip-certificate">{certificateLabel}</span>}</Tooltip>
          </Marker>;
        }
        return (
          <CircleMarker key={item.cadastral_id} center={position} radius={radius}
            pathOptions={{ color: selected ? '#fff' : color, weight: selected ? 3 : 1, fillColor: color, fillOpacity: type === 'no_records' && !selected ? 0.58 : 0.94 }}
            eventHandlers={{
              click: () => onSelect(item),
              mouseover: () => onHover(item.cadastral_id),
              mouseout: () => onHover(null),
            }}>
            <Tooltip direction="top" offset={[0, -4]}><strong>{item.cadastral_id}</strong><span className="point-tooltip-status">{t(`legend.${type}`)}</span></Tooltip>
          </CircleMarker>
        );
      })}
      {selectedOutside ? (
        <CircleMarker center={[Number(selectedOutside.lat), Number(selectedOutside.lng)]} radius={8}
          pathOptions={{ color: '#fff', weight: 3, fillColor: '#163f47', fillOpacity: 1 }}>
          <Tooltip>{selectedOutside.cadastral_id}</Tooltip>
        </CircleMarker>
      ) : null}
      {userLocation ? (
        <CircleMarker center={[userLocation.lat, userLocation.lng]} radius={7}
          pathOptions={{ color: '#fff', weight: 2, fillColor: '#2563eb', fillOpacity: 1 }}>
          <Tooltip>{t('map.you')}</Tooltip>
        </CircleMarker>
      ) : null}
      {addressLocation && <Marker position={[addressLocation.lat, addressLocation.lng]} icon={ADDRESS_ICON} zIndexOffset={1200} title={addressLocation.label}>
        <Tooltip>{lang === 'bg' ? 'Адресно местоположение' : 'Address location'} · {addressLocation.label}</Tooltip>
        <Popup><strong>{addressLocation.label}</strong><p>{lang === 'bg' ? 'Приблизително местоположение от OpenStreetMap. Изберете кадастрална точка отделно за официалните сведения.' : 'Approximate OpenStreetMap location. Select a cadastral point separately for official records.'}</p><a href={addressLocation.source_url} target="_blank" rel="noopener noreferrer">OpenStreetMap ↗</a></Popup>
      </Marker>}
      <BoundsWatcher onChange={onBoundsChange} />
      <MapBridge onMapReady={onMapReady} />
    </MapContainer>
  );
}
