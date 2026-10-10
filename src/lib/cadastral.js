// Client-side display helpers for cadastral records.

export const GROUP_KEYS = ['identification', 'property', 'planning', 'geometry'];

export function geoJsonToLatLngs(geometry) {
  if (!geometry || geometry.type !== 'Polygon') return [];
  const rings = geometry.coordinates || [];
  return rings.map((ring) => ring.map(([lng, lat]) => [lat, lng]));
}

export function hasValue(v) {
  return !(v === undefined || v === null || v === '');
}

export function formatNumber(value, lang) {
  if (!hasValue(value)) return null;
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return new Intl.NumberFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', {
    maximumFractionDigits: 2,
  }).format(num);
}

export function formatArea(value, lang) {
  const n = formatNumber(value, lang);
  return n === null ? null : `${n} ${lang === 'bg' ? 'м²' : 'm²'}`;
}

export function formatDate(value, lang) {
  if (!hasValue(value)) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(d);
}

export function formatDateTime(value, lang) {
  if (!hasValue(value)) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(d);
}

export function daysSince(value) {
  if (!hasValue(value)) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86400000));
}

export function formatDuration(ms) {
  if (!Number.isFinite(ms)) return null;
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;
}

export const OWNERSHIP_KEYS = {
  private: { bg: 'Частна собственост', en: 'Private' },
  public_state: { bg: 'Държавна публична собственост', en: 'State public property' },
  public_municipal: { bg: 'Общинска публична собственост', en: 'Municipal public property' },
  co_owned: { bg: 'Съсобственост', en: 'Co-owned' },
  unknown: { bg: 'Не е указано в източника', en: 'Not specified in the source' },
};

export const FIELD_LABEL_KEYS = {
  cadastral_id: 'field.cadastral_id',
  ekatte: 'field.ekatte',
  municipality: 'field.municipality',
  locality: 'field.locality',
  address: 'field.address',
  area_sqm: 'field.area',
  land_use: 'field.land_use',
  purpose: 'field.purpose',
  ownership_type: 'field.ownership',
  zoning: 'field.zoning',
  planning_status: 'field.planning_status',
  max_building_height_m: 'field.max_height',
  protected_area: 'field.protected_area',
  geometry_json: 'field.geometry',
};

// Leaflet needs literal colors, so these are design constants rather than tokens.
export const PARCEL_STYLE = {
  color: '#1e3a8a',
  weight: 1,
  fillColor: '#3b82f6',
  fillOpacity: 0.14,
};
export const PARCEL_HOVER_STYLE = {
  color: '#0f172a',
  weight: 2,
  fillColor: '#2563eb',
  fillOpacity: 0.3,
};
export const PARCEL_SELECTED_STYLE = {
  color: '#b45309',
  weight: 3,
  fillColor: '#f59e0b',
  fillOpacity: 0.4,
};