export const DOCUMENT_FILTERS = ['exploitation_certificates', 'building_permits', 'projecting_visas', 'no_records'];
const DESCRIPTION_TAGS = ['housing', 'business', 'infrastructure', 'public', 'parking'];
const FILTER_QUERY_KEYS = ['record_type', 'record_types', 'match', 'district', 'date_from', 'date_to', 'has_address', 'description_tag'];

export function normalizePropertyFilters(value = {}) {
  if (typeof value === 'string') value = { recordTypes: value === 'all' ? [] : [value] };
  const recordTypes = DOCUMENT_FILTERS.filter((type) => value.recordTypes?.includes(type));
  const noRecords = recordTypes.includes('no_records');
  const date = (input) => /^\d{4}-\d{2}-\d{2}$/.test(input || '') ? input : '';
  return {
    recordTypes: noRecords ? ['no_records'] : recordTypes,
    match: value.match === 'all' ? 'all' : 'any',
    district: noRecords ? '' : String(value.district || '').trim(),
    dateFrom: noRecords ? '' : date(value.dateFrom),
    dateTo: noRecords ? '' : date(value.dateTo),
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
    ...(filters.hasAddress ? { has_address: '1' } : {}),
    ...(filters.descriptionTag ? { description_tag: filters.descriptionTag } : {}),
  };
}

export function activeFilterCount(value) {
  const filters = normalizePropertyFilters(value);
  return filters.recordTypes.length + Number(Boolean(filters.district)) + Number(Boolean(filters.dateFrom || filters.dateTo)) + Number(filters.hasAddress) + Number(Boolean(filters.descriptionTag));
}

export function invalidFilterDates(value) {
  return Boolean(value.dateFrom && value.dateTo && value.dateFrom > value.dateTo);
}

export function readPropertyFilters() {
  const params = new URLSearchParams(window.location.search);
  const types = params.get('record_types') || params.get('record_type') || '';
  return normalizePropertyFilters({
    recordTypes: types.split(','), match: params.get('match'), district: params.get('district'),
    dateFrom: params.get('date_from'), dateTo: params.get('date_to'),
    hasAddress: params.get('has_address') === '1', descriptionTag: params.get('description_tag'),
  });
}

export function writePropertyFilters(value) {
  const url = new URL(window.location.href);
  FILTER_QUERY_KEYS.forEach((key) => url.searchParams.delete(key));
  Object.entries(propertyFilterParams(value)).forEach(([key, param]) => url.searchParams.set(key, param));
  window.history.replaceState(window.history.state, '', url);
}
