export const DOCUMENT_FILTERS = ['exploitation_certificates', 'building_permits', 'projecting_visas', 'no_records'];
export const DOCUMENT_DATE_FILTERS = {
  building_permits: 'permits',
  projecting_visas: 'visas',
  exploitation_certificates: 'certificates',
};
const DESCRIPTION_TAGS = ['housing', 'business', 'infrastructure', 'public', 'parking'];
const FILTER_QUERY_KEYS = ['record_type', 'record_types', 'match', 'district', 'date_from', 'date_to', 'has_address', 'description_tag', 'area_min_m2', 'area_max_m2',
  ...Object.values(DOCUMENT_DATE_FILTERS).flatMap((prefix) => [prefix + '_date_from', prefix + '_date_to'])];

function validDate(input) {
  if (typeof input !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(input) || input.slice(0, 4) === '0000') return '';
  const parsed = new Date(input + 'T00:00:00Z');
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === input ? input : '';
}

export function normalizePropertyFilters(value = {}) {
  if (typeof value === 'string') value = { recordTypes: value === 'all' ? [] : [value] };
  const recordTypes = DOCUMENT_FILTERS.filter((type) => value.recordTypes?.includes(type));
  const noRecords = recordTypes.includes('no_records');
  const documentDates = Object.fromEntries(Object.keys(DOCUMENT_DATE_FILTERS).map((type) => [type, {
    from: noRecords ? '' : validDate(value.documentDates?.[type]?.from),
    to: noRecords ? '' : validDate(value.documentDates?.[type]?.to),
  }]));
  // A period always requires a document of its named type.
  const requiredTypes = Object.keys(documentDates).filter((type) => documentDates[type].from || documentDates[type].to);
  return {
    recordTypes: noRecords ? ['no_records'] : DOCUMENT_FILTERS.filter((type) => recordTypes.includes(type) || requiredTypes.includes(type)),
    match: value.match === 'all' ? 'all' : 'any',
    district: noRecords ? '' : String(value.district || '').trim(),
    dateFrom: noRecords ? '' : validDate(value.dateFrom),
    dateTo: noRecords ? '' : validDate(value.dateTo),
    documentDates,
    areaMin: String(value.areaMin ?? '').trim().slice(0, 40),
    areaMax: String(value.areaMax ?? '').trim().slice(0, 40),
    hasAddress: !noRecords && Boolean(value.hasAddress),
    descriptionTag: !noRecords && DESCRIPTION_TAGS.includes(value.descriptionTag) ? value.descriptionTag : '',
  };
}

export function propertyFilterParams(value) {
  const filters = normalizePropertyFilters(value);
  return {
    ...(filters.recordTypes.length ? { record_types: filters.recordTypes.join(',') } : {}),
    ...(filters.match === 'all' && filters.recordTypes.length > 1 ? { match: 'all' } : {}),
    ...(filters.district ? { district: filters.district } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
    ...Object.fromEntries(Object.entries(DOCUMENT_DATE_FILTERS).flatMap(([type, prefix]) => {
      const range = filters.documentDates[type];
      return [...(range.from ? [[prefix + '_date_from', range.from]] : []), ...(range.to ? [[prefix + '_date_to', range.to]] : [])];
    })),
    ...(filters.hasAddress ? { has_address: '1' } : {}),
    ...(filters.descriptionTag ? { description_tag: filters.descriptionTag } : {}),
    ...(filters.areaMin !== '' ? { area_min_m2: filters.areaMin } : {}),
    ...(filters.areaMax !== '' ? { area_max_m2: filters.areaMax } : {}),
  };
}

export function activeFilterCount(value) {
  const filters = normalizePropertyFilters(value);
  return filters.recordTypes.length + Number(Boolean(filters.district)) + Number(Boolean(filters.dateFrom || filters.dateTo)) + Number(filters.hasAddress) + Number(Boolean(filters.descriptionTag))
    + Object.values(filters.documentDates).filter((range) => range.from || range.to).length
    + Number(filters.areaMin !== '' || filters.areaMax !== '');
}

export function invalidFilterDates(value) {
  const filters = normalizePropertyFilters(value);
  return Boolean(filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo)
    || Object.values(filters.documentDates).some((range) => range.from && range.to && range.from > range.to);
}

export function invalidFilterArea(value) {
  const filters = normalizePropertyFilters(value);
  const validArea = (input) => /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(input) && Number.isFinite(Number(input)) && Number(input) >= 0 && Number(input) <= 1_000_000_000;
  return (filters.areaMin !== '' && !validArea(filters.areaMin)) || (filters.areaMax !== '' && !validArea(filters.areaMax))
    || (filters.areaMin !== '' && filters.areaMax !== '' && Number(filters.areaMin) > Number(filters.areaMax));
}

export function readPropertyFilters() {
  const params = new URLSearchParams(window.location.search);
  const types = params.get('record_types') || params.get('record_type') || '';
  return normalizePropertyFilters({
    recordTypes: types.split(','), match: params.get('match'), district: params.get('district'),
    dateFrom: params.get('date_from'), dateTo: params.get('date_to'),
    documentDates: Object.fromEntries(Object.entries(DOCUMENT_DATE_FILTERS).map(([type, prefix]) => [type, {
      from: params.get(prefix + '_date_from'), to: params.get(prefix + '_date_to'),
    }])),
    hasAddress: params.get('has_address') === '1', descriptionTag: params.get('description_tag'),
    areaMin: params.get('area_min_m2'), areaMax: params.get('area_max_m2'),
  });
}

export function writePropertyFilters(value) {
  const url = new URL(window.location.href);
  FILTER_QUERY_KEYS.forEach((key) => url.searchParams.delete(key));
  Object.entries(propertyFilterParams(value)).forEach(([key, param]) => url.searchParams.set(key, param));
  window.history.replaceState(window.history.state, '', url);
}
