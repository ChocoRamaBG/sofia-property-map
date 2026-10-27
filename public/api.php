<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

// Keep these v2 bounds synchronized with build_registry_snapshot.py.
const REGISTRY_MAX_INDEX_BYTES = 8 * 1024 * 1024;
const REGISTRY_MAX_DATASET_BYTES = 128 * 1024 * 1024;
const REGISTRY_MAX_DOCUMENTS = 100000;
const CADASTRE_MAX_INDEX_BYTES = 16 * 1024 * 1024;
const CADASTRE_MAX_DATASET_BYTES = 128 * 1024 * 1024;
const CADASTRE_MAX_PARCELS = 500000;
const CADASTRE_MAX_ZIP_BYTES = 64 * 1024 * 1024;
const CADASTRE_MAX_FACET_VALUES = 1000;
const CADASTRE_AREA_METHOD = 'published_AREA_BGS2005_LCC';
const CADASTRE_CATALOGUE_URL = 'https://kais.cadastre.bg/bg/OpenData';

function respond(array $body, int $status = 200): void {
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function text_length(string $text): int {
    return function_exists('mb_strlen') ? mb_strlen($text, 'UTF-8') : strlen($text);
}

function number_param(string $key, float $min, float $max): float {
    $raw = $_GET[$key] ?? null;
    if (!is_numeric($raw)) {
        throw new InvalidArgumentException('Invalid map bounds.');
    }
    $number = (float)$raw;
    if ($number < $min || $number > $max) {
        throw new InvalidArgumentException('Map bounds are out of range.');
    }
    return $number;
}

class FilterUnavailableException extends RuntimeException {}

function optional_filter_string(string $key, int $limit): ?string {
    $value = $_GET[$key] ?? null;
    if ($value === null) return null;
    if (!is_string($value) || text_length($value) > $limit) throw new InvalidArgumentException('Invalid map filter.');
    $value = trim($value);
    return $value === '' ? null : $value;
}

function document_date_range_params(string $fromKey, string $toKey): array {
    $from = optional_filter_string($fromKey, 10);
    $to = optional_filter_string($toKey, 10);
    if (!snapshot_date_valid($from) || !snapshot_date_valid($to) || ($from !== null && $to !== null && $from > $to)) {
        throw new InvalidArgumentException('Invalid document date range.');
    }
    return ['from' => $from, 'to' => $to];
}

function optional_area_param(string $key): ?float {
    $raw = optional_filter_string($key, 40);
    if ($raw === null) return null;
    if (!preg_match('/^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/', $raw)) {
        throw new InvalidArgumentException('Invalid parcel area range.');
    }
    $value = (float)$raw;
    if (!is_finite($value) || $value < 0 || $value > 1000000000) {
        throw new InvalidArgumentException('Invalid parcel area range.');
    }
    return $value;
}

function cadastre_selection_params(string $key, string $pattern): array {
    $raw = optional_filter_string($key, 4000);
    if ($raw === null) return [];
    $values = array_values(array_unique(array_map('trim', explode(',', $raw))));
    if (count($values) > 100) throw new InvalidArgumentException('Too many cadastral filter values.');
    foreach ($values as $value) {
        if (!preg_match($pattern, $value)) throw new InvalidArgumentException('Invalid cadastral attribute filter.');
    }
    return $values;
}

function keyword_search_params(): array {
    $match = optional_filter_string('search_match', 10) ?? 'all';
    if (!in_array($match, ['all', 'any'], true)) throw new InvalidArgumentException('Invalid search matching mode.');
    $raw = $_GET['search_terms'] ?? null;
    if (array_key_exists('search_terms', $_GET)) {
        if (!is_string($raw) || strlen($raw) > 4096 || !preg_match('/^\s*\[/', $raw)) throw new InvalidArgumentException('Invalid search terms.');
        try {
            $terms = json_decode($raw, true, 4, JSON_THROW_ON_ERROR);
        } catch (JsonException $error) {
            throw new InvalidArgumentException('Invalid search terms.');
        }
        if (!snapshot_list($terms) || count($terms) > 8) throw new InvalidArgumentException('Choose at most eight search terms.');
    } else {
        // Old clients send q only to search. An explicit empty array clears it.
        $legacy = $_GET['q'] ?? '';
        if (!is_string($legacy) || strlen($legacy) > 4096) throw new InvalidArgumentException('Invalid search term.');
        $terms = [$legacy];
    }
    $unique = [];
    foreach ($terms as $term) {
        if (!is_string($term) || !preg_match('//u', $term)) throw new InvalidArgumentException('Invalid search term.');
        $term = preg_replace('/^\s+|\s+$/u', '', $term);
        if ($term === '') continue;
        // Count Unicode characters even when mbstring is unavailable on the host.
        if (preg_match_all('/./us', $term) > 120) throw new InvalidArgumentException('Search terms may contain at most 120 characters.');
        $folded = cadastre_fold_text($term);
        if (!isset($unique[$folded])) $unique[$folded] = $term;
    }
    return ['search_terms' => array_values($unique), 'search_folded_terms' => array_map('strval', array_keys($unique)),
        'search_match' => $match, 'search_active' => $unique !== []];
}

function map_filter_params(): array {
    // The legacy singleton parameter remains compatible with previously cached clients.
    $raw = optional_filter_string(array_key_exists('record_types', $_GET) ? 'record_types' : 'record_type', 200) ?? 'all';
    $types = array_values(array_unique(array_map('trim', explode(',', $raw))));
    $allowed = ['all', 'exploitation_certificates', 'building_permits', 'projecting_visas', 'no_records'];
    foreach ($types as $type) {
        if (!in_array($type, $allowed, true)) throw new InvalidArgumentException('Invalid register filter.');
    }
    if ($types === ['all']) $types = [];
    elseif (in_array('all', $types, true)) throw new InvalidArgumentException('Select all records or specific register types.');
    $match = optional_filter_string('match', 10) ?? 'any';
    if (!in_array($match, ['any', 'all'], true)) throw new InvalidArgumentException('Invalid filter matching mode.');
    $district = optional_filter_string('district', 200);
    $descriptionTag = optional_filter_string('description_tag', 40);
    if ($descriptionTag !== null && !in_array($descriptionTag, ['housing', 'business', 'infrastructure', 'public', 'parking'], true)) {
        throw new InvalidArgumentException('Invalid construction description filter.');
    }
    // Keep the old shared period for existing links. New periods explicitly
    // name the document type and are required together, irrespective of any/all.
    $legacyDateRange = document_date_range_params('date_from', 'date_to');
    $documentDates = [];
    foreach (['building_permits' => 'permits', 'projecting_visas' => 'visas', 'exploitation_certificates' => 'certificates'] as $type => $prefix) {
        $range = document_date_range_params($prefix . '_date_from', $prefix . '_date_to');
        if ($range['from'] !== null || $range['to'] !== null) $documentDates[$type] = $range;
    }
    $address = optional_filter_string('has_address', 5);
    if ($address !== null && !in_array($address, ['0', '1'], true)) throw new InvalidArgumentException('Invalid address filter.');
    $areaMin = optional_area_param('area_min_m2');
    $areaMax = optional_area_param('area_max_m2');
    if ($areaMin !== null && $areaMax !== null && $areaMin > $areaMax) throw new InvalidArgumentException('Invalid parcel area range.');
    $cadastreFacets = [
        'districts' => cadastre_selection_params('cadastre_districts', '/^sofia-district-(?:0[0-9]|1[0-9]|2[0-3])$/'),
        'purposes' => cadastre_selection_params('cadastre_purposes', '/^purpose-[a-f0-9]{16}$/'),
        'uses' => cadastre_selection_params('cadastre_uses', '/^use-[a-f0-9]{16}$/'),
        'property_types' => cadastre_selection_params('cadastre_property_types', '/^property-[a-f0-9]{16}$/'),
    ];
    $cadastreAttributesActive = false;
    foreach ($cadastreFacets as $values) {
        if ($values !== []) $cadastreAttributesActive = true;
    }
    $areaActive = $areaMin !== null || $areaMax !== null;
    $advanced = $district !== null || $descriptionTag !== null || $legacyDateRange['from'] !== null || $legacyDateRange['to'] !== null || $documentDates !== [] || $address === '1';
    if (in_array('no_records', $types, true) && (count($types) !== 1 || $advanced)) {
        throw new InvalidArgumentException('Properties without linked records cannot be combined with document filters.');
    }
    return ['record_types' => $types, 'match' => $match, 'district' => $district, 'description_tag' => $descriptionTag,
        'date_from' => $legacyDateRange['from'], 'date_to' => $legacyDateRange['to'], 'document_dates' => $documentDates,
        'has_address' => $address === '1', 'advanced' => $advanced,
        'area_min_m2' => $areaMin, 'area_max_m2' => $areaMax, 'area_active' => $areaActive,
        'cadastre_facets' => $cadastreFacets, 'cadastre_attributes_active' => $cadastreAttributesActive,
        'cadastre_active' => $areaActive || $cadastreAttributesActive] + keyword_search_params();
}

function record_filter(array $filter): string {
    $types = $filter['record_types'];
    if ($types === []) return '';
    if ($types === ['no_records']) return ' AND NOT EXISTS (SELECT 1 FROM parcel_documents filter_pd WHERE filter_pd.parcel_cadastral_id = p.cadastral_id)';
    $clauses = [];
    foreach ($types as $type) {
        // All source literals are selected from the validated fixed enum above.
        $sourceCondition = $type === 'exploitation_certificates'
            ? "filter_pd.source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy')"
            : "filter_pd.source_code = '" . $type . "'";
        $clauses[] = 'EXISTS (SELECT 1 FROM parcel_documents filter_pd WHERE filter_pd.parcel_cadastral_id = p.cadastral_id AND ' . $sourceCondition . ')';
    }
    return ' AND (' . implode($filter['match'] === 'all' ? ' AND ' : ' OR ', $clauses) . ')';
}

function document_flags_join(): string {
    // Aggregate the small exact-ID link table once instead of looking up each map point.
    return " LEFT JOIN (
        SELECT parcel_cadastral_id, COUNT(*) AS document_count,
               MAX(source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy')) AS has_exploitation_certificate,
               MAX(source_code = 'building_permits') AS has_building_permit,
               MAX(source_code = 'projecting_visas') AS has_projecting_visa
        FROM parcel_documents GROUP BY parcel_cadastral_id
    ) flags ON flags.parcel_cadastral_id = p.cadastral_id ";
}

function document_flags_select(): string {
    return 'COALESCE(flags.document_count, 0) AS document_count,
            COALESCE(flags.has_exploitation_certificate, 0) AS has_exploitation_certificate,
            COALESCE(flags.has_building_permit, 0) AS has_building_permit,
            COALESCE(flags.has_projecting_visa, 0) AS has_projecting_visa';
}

function serialize_plot(array $row): array {
    return [
        'cadastral_id' => $row['cadastral_id'],
        'lat' => $row['lat'] === null ? null : (float)$row['lat'],
        'lng' => $row['lng'] === null ? null : (float)$row['lng'],
        'document_count' => (int)$row['document_count'],
        'has_exploitation_certificate' => (bool)$row['has_exploitation_certificate'],
        'has_building_permit' => (bool)$row['has_building_permit'],
        'has_projecting_visa' => (bool)$row['has_projecting_visa'],
    ];
}

function document_snapshot_date(?string $filename, ?string $fallback): ?string {
    // Keep internal workbook provenance while showing the capture date publicly.
    if ($filename !== null && preg_match('/(\d{2})\.(\d{2})\.(\d{4})/', $filename, $match)) {
        if (checkdate((int)$match[2], (int)$match[1], (int)$match[3])) {
            return sprintf('%04d-%02d-%02d', (int)$match[3], (int)$match[2], (int)$match[1]);
        }
    }
    return $fallback;
}

function snapshot_date_valid($value): bool {
    if ($value === null) return true;
    if (!is_string($value) || !preg_match('/^(\d{4})-(\d{2})-(\d{2})$/', $value, $match)) return false;
    return checkdate((int)$match[2], (int)$match[3], (int)$match[1]);
}

function snapshot_timestamp_valid($value): bool {
    if (!is_string($value) || !preg_match('/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/', $value, $match)) return false;
    if (!snapshot_date_valid($match[1]) || (int)$match[2] > 23 || (int)$match[3] > 59 || (int)$match[4] > 59) return false;
    try { new DateTimeImmutable($value); } catch (Throwable $error) { return false; }
    return true;
}

function snapshot_import_timestamp_valid($value): bool {
    if (snapshot_timestamp_valid($value)) return true;
    if (!is_string($value) || !preg_match('/^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})$/', $value, $match)) return false;
    return snapshot_date_valid($match[1]) && (int)$match[2] <= 23 && (int)$match[3] <= 59 && (int)$match[4] <= 59;
}

function snapshot_string($value, int $limit, bool $nullable = false): bool {
    return ($nullable && $value === null) || (is_string($value) && text_length($value) <= $limit);
}

function snapshot_list($value): bool {
    return is_array($value) && ($value === [] || array_keys($value) === range(0, count($value) - 1));
}

function source_is_certificate(string $code): bool {
    return in_array($code, ['exploitation_certificates', 'exploitation_certificates_legacy'], true);
}

function empty_document_flags(): array {
    return ['document_count' => 0, 'has_exploitation_certificate' => false, 'has_building_permit' => false, 'has_projecting_visa' => false];
}

function public_source(array $source): array {
    return [
        'code' => $source['code'], 'label_bg' => $source['label_bg'], 'label_en' => $source['label_en'],
        'source_url' => $source['source_url'], 'snapshot_date' => $source['snapshot_date'],
    ];
}

function registry_source_codes(): array {
    return ['coordinates', 'building_permits', 'exploitation_certificates', 'exploitation_certificates_legacy', 'projecting_visas'];
}

function validate_registry_sources($rows): array {
    if (!snapshot_list($rows) || count($rows) > 5) throw new RuntimeException('Registry sources are invalid.');
    $sources = [];
    foreach ($rows as $source) {
        if (!is_array($source) || !in_array($source['code'] ?? null, registry_source_codes(), true) || isset($sources[$source['code']])
            || !snapshot_string($source['label_bg'] ?? null, 190) || !snapshot_string($source['label_en'] ?? null, 190)
            || !array_key_exists('source_url', $source) || !snapshot_string($source['source_url'], 500, true)
            || !array_key_exists('snapshot_date', $source) || !snapshot_date_valid($source['snapshot_date'])
            || !snapshot_string($source['snapshot_file'] ?? null, 255, true)) {
            throw new RuntimeException('Registry source metadata is invalid.');
        }
        $legacyArchive = $source['code'] === 'exploitation_certificates_legacy'
            && in_array($source['source_url'], ['http://up.gis-sofia.bg/', 'https://up.gis-sofia.bg/'], true);
        if ($source['source_url'] !== null && !$legacyArchive && (!filter_var($source['source_url'], FILTER_VALIDATE_URL)
            || parse_url($source['source_url'], PHP_URL_SCHEME) !== 'https'
            || parse_url($source['source_url'], PHP_URL_HOST) !== 'nag.sofia.bg')) {
            throw new RuntimeException('Registry source URL is invalid.');
        }
        $sources[$source['code']] = $source;
    }
    foreach (['building_permits', 'exploitation_certificates', 'projecting_visas'] as $code) {
        if (!isset($sources[$code])) throw new RuntimeException('Registry snapshot is missing a register.');
    }
    return $sources;
}

function validate_registry_completion($completion): void {
    if (!is_array($completion) || ($completion['status'] ?? null) !== 'complete' || !snapshot_list($completion['sources'] ?? null)) {
        throw new RuntimeException('Registry snapshot is incomplete.');
    }
    foreach ($completion['sources'] as $code) {
        if (!in_array($code, registry_source_codes(), true)) throw new RuntimeException('Registry completion source is invalid.');
    }
    if (array_diff(['building_permits', 'exploitation_certificates', 'projecting_visas'], $completion['sources']) !== []
        || (isset($completion['start_date']) && !snapshot_date_valid($completion['start_date']))
        || (isset($completion['finished_at']) && !snapshot_timestamp_valid($completion['finished_at']))) {
        throw new RuntimeException('Registry snapshot is incomplete.');
    }
}

function validate_registry_document($document, array $sources): void {
    if (!is_array($document) || !is_string($document['source_code'] ?? null) || !isset($sources[$document['source_code']])
        || $document['source_code'] === 'coordinates'
        || !is_string($document['document_hash'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $document['document_hash'])
        || !snapshot_string($document['record_key'] ?? null, 190, true) || !is_array($document['raw_fields'] ?? null)
        || count($document['raw_fields']) > 100 || !snapshot_list($document['cadastral_ids'] ?? null)
        || count($document['cadastral_ids']) > 10000 || !snapshot_string($document['snapshot_file'] ?? null, 255, true)
        || (isset($document['snapshot_date']) && !snapshot_date_valid($document['snapshot_date']))
        || (isset($document['issued_at']) && !snapshot_date_valid($document['issued_at']))) {
        throw new RuntimeException('Registry document is invalid.');
    }
    foreach ($document['raw_fields'] as $field => $value) {
        if (!snapshot_string((string)$field, 200) || (!is_scalar($value) && $value !== null)
            || (is_string($value) && strlen($value) > 500000)) throw new RuntimeException('Registry fields are invalid.');
    }
    foreach ($document['cadastral_ids'] as $id) {
        if (!is_string($id) || !preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $id)) {
            throw new RuntimeException('Registry cadastral link is invalid.');
        }
    }
}

function public_registry_imports($rows, array $sources): array {
    if (!snapshot_list($rows) || count($rows) > 10000) throw new RuntimeException('Registry imports are invalid.');
    $imports = [];
    foreach ($rows as $import) {
        if (!is_array($import) || !is_string($import['source_code'] ?? null) || !isset($sources[$import['source_code']])
            || !snapshot_string($import['source_file'] ?? null, 255, true)
            || !snapshot_import_timestamp_valid($import['imported_at'] ?? null)
            || !is_int($import['records_loaded'] ?? null) || $import['records_loaded'] < 0
            || (isset($import['snapshot_date']) && !snapshot_date_valid($import['snapshot_date']))) {
            throw new RuntimeException('Registry import metadata is invalid.');
        }
        $source = $sources[$import['source_code']];
        $fallback = ($import['source_file'] ?? null) === ($source['snapshot_file'] ?? null) ? $source['snapshot_date'] : null;
        $imports[] = array_merge(public_source($source), [
            'source_code' => $import['source_code'], 'imported_at' => $import['imported_at'], 'records_loaded' => $import['records_loaded'],
            'snapshot_date' => array_key_exists('snapshot_date', $import) ? $import['snapshot_date'] : document_snapshot_date($import['source_file'] ?? null, $fallback),
        ]);
    }
    return $imports;
}

function bounded_registry_json(string $path, int $limit, ?int $expectedBytes = null, ?string $expectedHash = null): array {
    if (!is_file($path) || is_link($path)) throw new RuntimeException('Registry snapshot file is unavailable.');
    $bytes = filesize($path);
    if ($bytes === false || $bytes <= 0 || $bytes > $limit || ($expectedBytes !== null && $bytes !== $expectedBytes)) {
        throw new RuntimeException('Registry snapshot has an invalid size.');
    }
    $json = file_get_contents($path, false, null, 0, $limit + 1);
    if ($json === false || strlen($json) !== $bytes || ($expectedHash !== null && !hash_equals($expectedHash, hash('sha256', $json)))) {
        throw new RuntimeException('Registry snapshot integrity check failed.');
    }
    $data = json_decode($json, true, 32, JSON_THROW_ON_ERROR);
    unset($json);
    if (!is_array($data)) throw new RuntimeException('Registry snapshot format is invalid.');
    return $data;
}

function validate_registry_file_descriptor($file, string $pattern, int $limit): void {
    if (!is_array($file) || !is_string($file['file'] ?? null) || !preg_match($pattern, $file['file'])
        || !is_int($file['bytes'] ?? null) || $file['bytes'] < 1 || $file['bytes'] > $limit
        || !is_string($file['sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $file['sha256'])) {
        throw new RuntimeException('Registry file descriptor is invalid.');
    }
}

function validate_filter_facets($facets, int $records): ?array {
    if ($facets === null) return null;
    if (!is_array($facets) || ($facets['version'] ?? null) !== 1 || !snapshot_list($facets['districts'] ?? null)
        || count($facets['districts']) > 2000 || !snapshot_list($facets['values'] ?? null)
        || count($facets['values']) > REGISTRY_MAX_DOCUMENTS || !snapshot_date_valid($facets['date_min'] ?? null)
        || !snapshot_date_valid($facets['date_max'] ?? null)) throw new RuntimeException('Registry filter index is invalid.');
    $districtKeys = [];
    foreach ($facets['districts'] as $district) {
        if (!is_array($district) || !snapshot_string($district['key'] ?? null, 200) || $district['key'] === ''
            || !snapshot_string($district['label'] ?? null, 200) || isset($districtKeys[$district['key']])
            || (isset($district['document_count']) && (!is_int($district['document_count']) || $district['document_count'] < 0 || $district['document_count'] > $records))) {
            throw new RuntimeException('Registry district filter is invalid.');
        }
        $districtKeys[$district['key']] = true;
    }
    foreach ($facets['values'] as $value) {
        if (!snapshot_list($value) || count($value) !== 4
            || ($value[0] !== null && (!is_int($value[0]) || !isset($facets['districts'][$value[0]])))
            || !snapshot_date_valid($value[1]) || !in_array($value[2], [0, 1], true)
            || !is_int($value[3]) || $value[3] < 0 || $value[3] > 31) throw new RuntimeException('Registry document facet is invalid.');
    }
    $tagBits = ['housing' => 1, 'business' => 2, 'infrastructure' => 4, 'public' => 8, 'parking' => 16];
    if (!snapshot_list($facets['description_tags'] ?? null) || count($facets['description_tags']) !== count($tagBits)) {
        throw new RuntimeException('Registry description filters are invalid.');
    }
    $seenTags = [];
    foreach ($facets['description_tags'] as $tag) {
        if (!is_array($tag) || !is_string($tag['key'] ?? null) || !isset($tagBits[$tag['key']]) || isset($seenTags[$tag['key']])
            || ($tag['bit'] ?? null) !== $tagBits[$tag['key']] || !snapshot_string($tag['label_bg'] ?? null, 200)
            || !snapshot_string($tag['label_en'] ?? null, 200) || !is_int($tag['document_count'] ?? null)
            || $tag['document_count'] < 0 || $tag['document_count'] > $records) throw new RuntimeException('Registry description filter is invalid.');
        $seenTags[$tag['key']] = true;
    }
    if (isset($facets['coverage'])) {
        if (!is_array($facets['coverage'])) throw new RuntimeException('Registry filter coverage is invalid.');
        foreach ($facets['coverage'] as $count) {
            if (!is_int($count) || $count < 0 || $count > $records) throw new RuntimeException('Registry filter coverage is invalid.');
        }
    }
    return $facets;
}

function empty_document_date_ranges(): array {
    return array_fill_keys(['building_permits', 'projecting_visas', 'exploitation_certificates'],
        ['date_min' => null, 'date_max' => null, 'dated_document_count' => 0]);
}

function filter_options(?array $facets, ?array $documentDateRanges = null): array {
    $dateOptions = ['scoped_dates_available' => $facets !== null,
        'document_date_ranges' => $documentDateRanges ?? empty_document_date_ranges(), 'date_range_coverage' => 'linked_documents'];
    if ($facets === null) return array_merge(['available' => false, 'districts' => [], 'description_tags' => [], 'date_min' => null, 'date_max' => null, 'coverage' => []], $dateOptions);
    return ['available' => true, 'districts' => $facets['districts'], 'description_tags' => $facets['description_tags'],
        'date_min' => $facets['date_min'] ?? null, 'date_max' => $facets['date_max'] ?? null, 'coverage' => $facets['coverage'] ?? []] + $dateOptions;
}

function filter_facet_matches(array $value, array $facets, array $filter): bool {
    if ($filter['district'] !== null && ($value[0] === null || $facets['districts'][$value[0]]['key'] !== $filter['district'])) return false;
    if ($filter['date_from'] !== null && ($value[1] === null || $value[1] < $filter['date_from'])) return false;
    if ($filter['date_to'] !== null && ($value[1] === null || $value[1] > $filter['date_to'])) return false;
    if ($filter['has_address'] && $value[2] !== 1) return false;
    if ($filter['description_tag'] !== null) {
        $bits = ['housing' => 1, 'business' => 2, 'infrastructure' => 4, 'public' => 8, 'parking' => 16];
        if (($value[3] & $bits[$filter['description_tag']]) === 0) return false;
    }
    return true;
}

function qualifying_types_match(array $types, array $filter): bool {
    if ($filter['record_types'] === []) return $types !== [];
    foreach ($filter['record_types'] as $type) {
        if ($filter['match'] === 'all' && !isset($types[$type])) return false;
        if ($filter['match'] === 'any' && isset($types[$type])) return true;
    }
    return $filter['match'] === 'all';
}

function scoped_document_date_matches(?string $issuedAt, array $range): bool {
    if ($issuedAt === null) return false;
    return ($range['from'] === null || $issuedAt >= $range['from']) && ($range['to'] === null || $issuedAt <= $range['to']);
}

function qualifying_document_dates_match(array $types, array $filter): bool {
    foreach ($filter['document_dates'] as $type => $_) {
        if (!isset($types[$type])) return false;
    }
    return true;
}

function load_registry_v2(string $activePath, ?array $filter = null): array {
    $manifest = bounded_registry_json($activePath, 256 * 1024);
    if (($manifest['version'] ?? null) !== 2 || !is_string($manifest['snapshot_id'] ?? null)
        || !preg_match('/^[a-f0-9]{32}$/', $manifest['snapshot_id']) || !snapshot_timestamp_valid($manifest['generated_at'] ?? null)
        || !snapshot_list($manifest['documents'] ?? null) || count($manifest['documents']) > 1000) {
        throw new RuntimeException('Registry manifest format is invalid.');
    }
    validate_registry_completion($manifest['completion'] ?? null);
    validate_registry_file_descriptor($manifest['index'] ?? null, '/^index\.json$/', REGISTRY_MAX_INDEX_BYTES);
    $root = __DIR__ . '/private/registry-snapshots';
    $directory = $root . '/' . $manifest['snapshot_id'];
    if (is_link($root) || is_link($directory) || !is_dir($directory)) throw new RuntimeException('Registry snapshot directory is unavailable.');
    $shards = [];
    $records = 0;
    $totalBytes = $manifest['index']['bytes'];
    foreach ($manifest['documents'] as $shard) {
        validate_registry_file_descriptor($shard, '/^documents-[0-9]{3}\.jsonl$/', 1024 * 1024);
        if (isset($shards[$shard['file']]) || !is_int($shard['records'] ?? null) || $shard['records'] < 1) {
            throw new RuntimeException('Registry document shard is invalid.');
        }
        $records += $shard['records'];
        if ($records > REGISTRY_MAX_DOCUMENTS) throw new RuntimeException('Registry snapshot contains too many documents.');
        $totalBytes += $shard['bytes'];
        if ($totalBytes > REGISTRY_MAX_DATASET_BYTES) throw new RuntimeException('Registry snapshot exceeds its processing size limit.');
        $path = $directory . '/' . $shard['file'];
        if (!is_file($path) || is_link($path) || filesize($path) !== $shard['bytes']) throw new RuntimeException('Registry shard is unavailable.');
        $shards[$shard['file']] = $shard;
    }
    $index = bounded_registry_json($directory . '/index.json', REGISTRY_MAX_INDEX_BYTES, $manifest['index']['bytes'], $manifest['index']['sha256']);
    if (($index['version'] ?? null) !== 2 || ($index['snapshot_id'] ?? null) !== $manifest['snapshot_id']
        || ($index['generated_at'] ?? null) !== $manifest['generated_at'] || !is_array($index['parcels'] ?? null)
        || count($index['parcels']) > 50000 || !is_array($index['document_counts'] ?? null)) {
        throw new RuntimeException('Registry index format is invalid.');
    }
    validate_registry_completion($index['completion'] ?? null);
    if ($index['completion'] != $manifest['completion']) throw new RuntimeException('Registry snapshot completion is inconsistent.');
    $sources = validate_registry_sources($index['sources'] ?? null);
    $imports = public_registry_imports($index['imports'] ?? null, $sources);
    $referenceFormat = $index['reference_format'] ?? null;
    if ($referenceFormat !== null && !in_array($referenceFormat, ['tuple-v1', 'tuple-v2-facets'], true)) throw new RuntimeException('Registry reference format is invalid.');
    $facets = validate_filter_facets($index['filter_facets'] ?? null, $records);
    if (($referenceFormat === 'tuple-v2-facets') !== ($facets !== null)) throw new RuntimeException('Registry filter references are inconsistent.');
    $advanced = $filter !== null && $filter['advanced'];
    if ($advanced && $facets === null) throw new FilterUnavailableException('Advanced map filters are unavailable until the registry filter index has been published.');
    if ($advanced && $filter['district'] !== null) {
        $districtKeys = array_column($facets['districts'], 'key');
        if (!in_array($filter['district'], $districtKeys, true)) throw new InvalidArgumentException('Unknown district filter.');
        unset($districtKeys);
    }
    $qualifiedIds = [];
    $sourceCodes = array_keys($sources);
    $shardNames = array_keys($shards);
    $documentCounts = array_fill_keys(array_keys($sources), 0);
    foreach ($index['document_counts'] as $code => $count) {
        if (!isset($sources[$code]) || !is_int($count) || $count < 0 || ($code === 'coordinates' && $count !== 0)) throw new RuntimeException('Registry document count is invalid.');
        $documentCounts[$code] = $count;
    }
    if (array_sum($documentCounts) !== $records) throw new RuntimeException('Registry document totals are inconsistent.');

    $byId = [];
    $flags = [];
    $sourceIds = array_fill_keys(array_keys($sources), []);
    $certificateIds = [];
    // Internal references are packed [shard name, newline-delimited exact IDs,
    // facet position]. Repeated links must retain the same observation facet.
    $docRefs = [];
    $indexedCounts = array_fill_keys(array_keys($sources), 0);
    $certificateDocuments = [];
    $documentDateRanges = empty_document_date_ranges();
    // Release decoded references as each parcel is indexed. Retain a compact
    // shard lookup rather than a second copy of every reference array.
    $parcelIds = array_keys($index['parcels']);
    foreach ($parcelIds as $id) {
        $parcel = $index['parcels'][$id];
        unset($index['parcels'][$id]);
        if (!is_string($id) || !preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $id)
            || !is_array($parcel) || !snapshot_list($parcel['documents'] ?? null) || count($parcel['documents']) < 1
            || count($parcel['documents']) > REGISTRY_MAX_DOCUMENTS) throw new RuntimeException('Registry parcel index is invalid.');
        $flags[$id] = empty_document_flags();
        $qualifyingTypes = [];
        $qualifyingDateTypes = [];
        foreach ($parcel['documents'] as $ref) {
            $facetPosition = null;
            if ($referenceFormat === 'tuple-v1' || $referenceFormat === 'tuple-v2-facets') {
                if (!snapshot_list($ref) || count($ref) !== ($referenceFormat === 'tuple-v2-facets' ? 4 : 3) || !is_int($ref[0]) || !isset($sourceCodes[$ref[0]])
                    || !is_int($ref[2]) || !isset($shardNames[$ref[2]])) throw new RuntimeException('Registry compact reference is invalid.');
                $code = $sourceCodes[$ref[0]];
                $documentHash = $ref[1];
                $shardName = $shardNames[$ref[2]];
                if ($referenceFormat === 'tuple-v2-facets') {
                    $facetPosition = $ref[3];
                    if (!is_int($facetPosition) || !isset($facets['values'][$facetPosition])) throw new RuntimeException('Registry facet reference is invalid.');
                }
            } else {
                if (!is_array($ref)) throw new RuntimeException('Registry document reference is invalid.');
                $code = $ref['source_code'] ?? null;
                $documentHash = $ref['document_hash'] ?? null;
                $shardName = $ref['shard'] ?? null;
            }
            if (!is_string($code) || !isset($sources[$code]) || $code === 'coordinates'
                || !is_string($documentHash) || !preg_match('/^[a-f0-9]{64}$/', $documentHash)
                || !is_string($shardName) || !isset($shards[$shardName])) throw new RuntimeException('Registry document reference is invalid.');
            $documentType = source_is_certificate($code) ? 'exploitation_certificates' : $code;
            $key = $code . ':' . $documentHash;
            if (isset($byId[$id][$key]) || (isset($docRefs[$key]) && ($docRefs[$key][0] !== $shardName || ($docRefs[$key][2] ?? null) !== $facetPosition))) {
                throw new RuntimeException('Registry document reference is duplicated or inconsistent.');
            }
            $byId[$id][$key] = $shardName;
            // Validated cadastral IDs contain no newlines. A scalar list avoids
            // allocating one nested associative array for every document.
            if (!isset($docRefs[$key])) {
                $indexedCounts[$code]++;
                $docRefs[$key] = [$shardName, $id . "\n", $facetPosition];
                // Count one observation once, even when it names several plots.
                // These ranges describe dated records linked by an exact ID.
                if ($facetPosition !== null && $facets['values'][$facetPosition][1] !== null) {
                    $issuedAt = $facets['values'][$facetPosition][1];
                    $dateRange = &$documentDateRanges[$documentType];
                    $dateRange['dated_document_count']++;
                    if ($dateRange['date_min'] === null || $issuedAt < $dateRange['date_min']) $dateRange['date_min'] = $issuedAt;
                    if ($dateRange['date_max'] === null || $issuedAt > $dateRange['date_max']) $dateRange['date_max'] = $issuedAt;
                    unset($dateRange);
                }
            } else {
                $docRefs[$key][1] .= $id . "\n";
            }
            $flags[$id]['document_count']++;
            $sourceIds[$code][$id] = true;
            if (source_is_certificate($code)) {
                $flags[$id]['has_exploitation_certificate'] = true;
                $certificateIds[$id] = true;
                $certificateDocuments[$key] = true;
            } elseif ($code === 'building_permits') {
                $flags[$id]['has_building_permit'] = true;
            } elseif ($code === 'projecting_visas') {
                $flags[$id]['has_projecting_visa'] = true;
            }
            if ($advanced && filter_facet_matches($facets['values'][$facetPosition], $facets, $filter)) {
                $qualifyingTypes[$documentType] = true;
                if (isset($filter['document_dates'][$documentType])
                    && scoped_document_date_matches($facets['values'][$facetPosition][1], $filter['document_dates'][$documentType])) {
                    $qualifyingDateTypes[$documentType] = true;
                }
            }
        }
        if ($advanced && qualifying_types_match($qualifyingTypes, $filter)
            && qualifying_document_dates_match($qualifyingDateTypes, $filter)) $qualifiedIds[$id] = true;
    }
    if (count($docRefs) > $records) throw new RuntimeException('Registry indexed document total is invalid.');
    foreach ($indexedCounts as $code => $count) {
        if ($count > $documentCounts[$code]) throw new RuntimeException('Registry indexed source total is invalid.');
    }
    $generatedAt = $manifest['generated_at'];
    $filterOptions = filter_options($facets, $documentDateRanges);
    unset($facets);
    unset($index, $manifest, $parcelIds, $parcel, $ref);
    return [
        'format' => 2, 'directory' => $directory, 'shards' => $shards, 'doc_refs' => $docRefs,
        'generated_at' => $generatedAt, 'sources' => $sources, 'documents' => [], 'imports' => $imports,
        'by_id' => $byId, 'flags' => $flags, 'source_ids' => $sourceIds, 'document_counts' => $documentCounts,
        'certificate_ids' => $certificateIds, 'linked_certificates' => count($certificateDocuments),
        'filter_options' => $filterOptions, 'qualified_ids' => $advanced ? $qualifiedIds : null,
    ];
}

function load_registry_snapshot(?array $filter = null): ?array {
    $activePath = __DIR__ . '/private/registry-active.json';
    if (file_exists($activePath) || is_link($activePath)) return load_registry_v2($activePath, $filter);
    if ($filter !== null && $filter['advanced']) throw new FilterUnavailableException('Advanced map filters are unavailable until the registry filter index has been published.');
    $path = __DIR__ . '/private/registry-data.json';
    if (!file_exists($path) && !is_link($path)) return null;
    $snapshot = bounded_registry_json($path, 10 * 1024 * 1024);
    if (!is_array($snapshot) || ($snapshot['version'] ?? null) !== 1 || !snapshot_timestamp_valid($snapshot['generated_at'] ?? null)
        || !snapshot_list($snapshot['sources'] ?? null) || !snapshot_list($snapshot['documents'] ?? null)
        || !snapshot_list($snapshot['imports'] ?? null) || count($snapshot['sources']) > 5 || count($snapshot['documents']) > REGISTRY_MAX_DOCUMENTS) {
        throw new RuntimeException('Registry snapshot format is invalid.');
    }
    $sources = validate_registry_sources($snapshot['sources']);
    validate_registry_completion($snapshot['completion'] ?? null);

    $byId = [];
    $flags = [];
    $seenDocuments = [];
    $sourceIds = array_fill_keys(array_keys($sources), []);
    $documentCounts = array_fill_keys(array_keys($sources), 0);
    $certificateIds = [];
    $linkedCertificates = 0;
    foreach ($snapshot['documents'] as $index => $document) {
        validate_registry_document($document, $sources);
        $key = $document['source_code'] . ':' . $document['document_hash'];
        if (isset($seenDocuments[$key])) throw new RuntimeException('Registry snapshot contains duplicate documents.');
        $seenDocuments[$key] = true;
        $documentCounts[$document['source_code']]++;
        $ids = [];
        foreach ($document['cadastral_ids'] as $id) {
            if (isset($ids[$id])) continue;
            $ids[$id] = true;
            $byId[$id][] = $index;
            $sourceIds[$document['source_code']][$id] = true;
            if (!isset($flags[$id])) $flags[$id] = empty_document_flags();
            $flags[$id]['document_count']++;
            if (source_is_certificate($document['source_code'])) {
                $flags[$id]['has_exploitation_certificate'] = true;
                $certificateIds[$id] = true;
            } elseif ($document['source_code'] === 'building_permits') {
                $flags[$id]['has_building_permit'] = true;
            } elseif ($document['source_code'] === 'projecting_visas') {
                $flags[$id]['has_projecting_visa'] = true;
            }
        }
        if ($ids !== [] && source_is_certificate($document['source_code'])) $linkedCertificates++;
    }
    $imports = public_registry_imports($snapshot['imports'], $sources);
    return [
        'format' => 1, 'generated_at' => $snapshot['generated_at'], 'sources' => $sources, 'documents' => $snapshot['documents'], 'imports' => $imports,
        'by_id' => $byId, 'flags' => $flags, 'source_ids' => $sourceIds, 'document_counts' => $documentCounts,
        'certificate_ids' => $certificateIds, 'linked_certificates' => $linkedCertificates,
        'filter_options' => filter_options(null), 'qualified_ids' => null,
    ];
}

function cadastre_area_valid($value): bool {
    return (is_int($value) || is_float($value)) && is_finite((float)$value) && $value > 0 && $value <= 1000000000;
}

function cadastre_area_equal(float $a, float $b): bool {
    // Both JSON and TSV are emitted from the same published decimal AREA.
    return $a === $b;
}

function cadastre_source_url_valid($value): bool {
    if (!snapshot_string($value, 4096) || !filter_var($value, FILTER_VALIDATE_URL)) return false;
    $url = parse_url($value);
    if (($url['scheme'] ?? null) !== 'https' || ($url['host'] ?? null) !== 'kais.cadastre.bg'
        || ($url['path'] ?? null) !== '/bg/OpenData/Download' || isset($url['user']) || isset($url['pass'])
        || isset($url['port']) || isset($url['fragment'])) return false;
    if (!preg_match('/^path=[^&]+$/', $url['query'] ?? '')) return false;
    parse_str($url['query'], $query);
    return count($query) === 1 && snapshot_string($query['path'] ?? null, 4096) && $query['path'] !== '';
}

function cadastre_fold_text(string $text): string {
    if (function_exists('mb_strtolower')) return mb_strtolower($text, 'UTF-8');
    return strtolower(strtr($text, ['А' => 'а', 'Б' => 'б', 'В' => 'в', 'Г' => 'г', 'Д' => 'д', 'Е' => 'е', 'Ж' => 'ж', 'З' => 'з', 'И' => 'и', 'Й' => 'й',
        'К' => 'к', 'Л' => 'л', 'М' => 'м', 'Н' => 'н', 'О' => 'о', 'П' => 'п', 'Р' => 'р', 'С' => 'с', 'Т' => 'т', 'У' => 'у',
        'Ф' => 'ф', 'Х' => 'х', 'Ц' => 'ц', 'Ч' => 'ч', 'Ш' => 'ш', 'Щ' => 'щ', 'Ъ' => 'ъ', 'Ь' => 'ь', 'Ю' => 'ю', 'Я' => 'я', 'Ѝ' => 'ѝ']));
}

function cadastre_label_known(?string $label): bool {
    if ($label === null) return false;
    // Match Python's Unicode str.strip() when recognizing official unknowns.
    $whitespace = '[\x{0009}-\x{000D}\x{001C}-\x{0020}\x{0085}\x{00A0}\x{1680}\x{2000}-\x{200A}\x{2028}\x{2029}\x{202F}\x{205F}\x{3000}]';
    $trimmed = preg_replace('/^' . $whitespace . '+|' . $whitespace . '+$/u', '', $label);
    if ($trimmed === null) throw new RuntimeException('Cadastre attribute text is invalid.');
    return $trimmed !== '' && cadastre_fold_text($trimmed) !== 'няма данни';
}

function cadastre_facet_key(string $prefix, ?string $code, string $label): string {
    $identity = json_encode([$code, $label], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_LINE_TERMINATORS | JSON_THROW_ON_ERROR);
    return $prefix . '-' . substr(hash('sha256', $identity), 0, 16);
}

function validate_cadastre_facets(array $manifest): array {
    if ($manifest['version'] === 1) return [];
    $facets = $manifest['facets'] ?? null;
    if (!is_array($facets) || count($facets) !== 4) throw new RuntimeException('Cadastre facet dictionaries are invalid.');
    $lookups = [];
    foreach (['districts' => null, 'purposes' => 'purpose', 'uses' => 'use', 'property_types' => 'property'] as $dimension => $prefix) {
        $rows = $facets[$dimension] ?? null;
        if (!snapshot_list($rows) || count($rows) > ($dimension === 'districts' ? 24 : CADASTRE_MAX_FACET_VALUES)
            || ($dimension === 'districts' && count($rows) !== 24)) throw new RuntimeException('Cadastre facet dictionary size is invalid.');
        $lookups[$dimension] = [];
        $previousKey = null;
        $total = 0;
        foreach ($rows as $position => $row) {
            if (!is_array($row) || count($row) !== 4 || !snapshot_string($row['key'] ?? null, 40) || isset($lookups[$dimension][$row['key']])
                || !snapshot_string($row['label_bg'] ?? null, 2000) || !cadastre_label_known($row['label_bg'])
                || !array_key_exists('code', $row) || !snapshot_string($row['code'], 50, true)
                || !is_int($row['count'] ?? null) || $row['count'] < ($dimension === 'districts' ? 0 : 1) || $row['count'] > $manifest['parcel_count']) {
                throw new RuntimeException('Cadastre facet value is invalid.');
            }
            if ($dimension === 'districts') {
                $source = $manifest['sources'][$position];
                $captionPrefix = 'гр. София (68134) - ';
                if ($row['key'] !== $source['code'] || $row['code'] !== null || $row['count'] !== $source['usable_parcel_count']
                    || strpos($source['label_bg'], $captionPrefix) !== 0
                    || cadastre_fold_text($row['label_bg']) !== cadastre_fold_text(substr($source['label_bg'], strlen($captionPrefix)))) {
                    throw new RuntimeException('Cadastre district dictionary differs from its source.');
                }
            } else {
                if ($row['key'] !== cadastre_facet_key($prefix, $row['code'], $row['label_bg'])
                    || ($previousKey !== null && strcmp($previousKey, $row['key']) >= 0)) throw new RuntimeException('Cadastre stable facet identity is invalid.');
                $previousKey = $row['key'];
            }
            $lookups[$dimension][$row['key']] = $position;
            $total += $row['count'];
        }
        if ($total > $manifest['parcel_count'] || ($dimension === 'districts' && $total !== $manifest['parcel_count'])) {
            throw new RuntimeException('Cadastre facet totals are inconsistent.');
        }
    }
    return $lookups;
}

function validate_cadastre_filter_selection(?array $cadastre, array $filter): void {
    if (!$filter['cadastre_active']) return;
    if ($cadastre === null) throw new FilterUnavailableException('Cadastral filters are unavailable until the open-data snapshot has been published.');
    if (!$filter['cadastre_attributes_active']) return;
    if ($cadastre['version'] !== 2) throw new FilterUnavailableException('Cadastral attribute filters are unavailable until the facet index has been published.');
    foreach ($filter['cadastre_facets'] as $dimension => $values) {
        foreach ($values as $value) {
            if (!isset($cadastre['facet_lookup'][$dimension][$value])) throw new InvalidArgumentException('Unknown cadastral attribute filter.');
        }
    }
}

function load_cadastre_snapshot(): ?array {
    $activePath = __DIR__ . '/private/cadastre-active.json';
    if (!file_exists($activePath) && !is_link($activePath)) return null;
    $manifest = bounded_registry_json($activePath, 256 * 1024);
    $version = $manifest['version'] ?? null;
    if (!in_array($version, [1, 2], true) || !is_string($manifest['snapshot_id'] ?? null)
        || !preg_match('/^[a-f0-9]{32}$/', $manifest['snapshot_id']) || !snapshot_timestamp_valid($manifest['generated_at'] ?? null)
        || ($manifest['reference_format'] ?? null) !== ($version === 2 ? 'area-source-shard-facets-tsv-v2' : 'area-source-shard-tsv-v1') || ($manifest['area_unit'] ?? null) !== 'm2'
        || ($manifest['area_method'] ?? null) !== CADASTRE_AREA_METHOD
        || !is_int($manifest['parcel_count'] ?? null) || $manifest['parcel_count'] < 1 || $manifest['parcel_count'] > CADASTRE_MAX_PARCELS
        || !cadastre_area_valid($manifest['area_min_m2'] ?? null) || !cadastre_area_valid($manifest['area_max_m2'] ?? null)
        || $manifest['area_min_m2'] > $manifest['area_max_m2']) throw new RuntimeException('Cadastre manifest format is invalid.');
    $completion = $manifest['completion'] ?? null;
    if (!is_array($completion) || ($completion['status'] ?? null) !== 'complete' || ($completion['district_count'] ?? null) !== 24
        || !is_string($completion['catalogue_sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $completion['catalogue_sha256'])) {
        throw new RuntimeException('Cadastre snapshot is incomplete.');
    }
    if (!is_int($manifest['source_record_total'] ?? null) || $manifest['source_record_total'] < $manifest['parcel_count']
        || $manifest['source_record_total'] > CADASTRE_MAX_PARCELS
        || !is_int($manifest['ambiguous_parcel_count'] ?? null) || $manifest['ambiguous_parcel_count'] < 0 || $manifest['ambiguous_parcel_count'] > 5000
        || !snapshot_list($manifest['ambiguous_ids'] ?? null) || count($manifest['ambiguous_ids']) !== $manifest['ambiguous_parcel_count']) {
        throw new RuntimeException('Cadastre ambiguity metadata is invalid.');
    }
    $ambiguousLookup = [];
    $previousAmbiguousId = null;
    foreach ($manifest['ambiguous_ids'] as $id) {
        if (!is_string($id) || !preg_match('/^68134\.[0-9]{1,6}\.[0-9]{1,6}$/', $id)
            || ($previousAmbiguousId !== null && strcmp($previousAmbiguousId, $id) >= 0)) throw new RuntimeException('Cadastre ambiguous identifier is invalid.');
        $ambiguousLookup[$id] = true;
        $previousAmbiguousId = $id;
    }
    $conflicts = $manifest['conflicts'] ?? null;
    if ($manifest['ambiguous_parcel_count'] > 0) {
        validate_registry_file_descriptor($conflicts, '/^conflicts\.json$/', 1024 * 1024);
        if (($conflicts['records'] ?? null) !== $manifest['ambiguous_parcel_count']) throw new RuntimeException('Cadastre conflict total is inconsistent.');
    } elseif ($conflicts !== null) {
        throw new RuntimeException('Cadastre conflicts are inconsistent.');
    }
    if (!snapshot_list($manifest['sources'] ?? null) || count($manifest['sources']) !== 24) throw new RuntimeException('Cadastre sources are invalid.');
    $sourceRecords = 0;
    $usableParcels = 0;
    $sourceUrls = [];
    foreach ($manifest['sources'] as $position => $source) {
        if (!is_array($source) || ($source['code'] ?? null) !== sprintf('sofia-district-%02d', $position)
            || !snapshot_string($source['label_bg'] ?? null, 200) || $source['label_bg'] === ''
            || !cadastre_source_url_valid($source['source_url'] ?? null) || isset($sourceUrls[$source['source_url']])
            || ($source['catalogue_url'] ?? null) !== CADASTRE_CATALOGUE_URL
            || !array_key_exists('published_at', $source) || ($source['published_at'] !== null && !snapshot_timestamp_valid($source['published_at']))
            || (isset($source['catalogue_published_at']) && !snapshot_string($source['catalogue_published_at'], 80))
            || !snapshot_timestamp_valid($source['captured_at'] ?? null)
            || !is_string($source['zip_sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $source['zip_sha256'])
            || !is_int($source['zip_bytes'] ?? null) || $source['zip_bytes'] < 1 || $source['zip_bytes'] > CADASTRE_MAX_ZIP_BYTES
            || !is_int($source['record_count'] ?? null) || $source['record_count'] < 0 || $source['record_count'] > CADASTRE_MAX_PARCELS
            || !is_int($source['usable_parcel_count'] ?? null) || $source['usable_parcel_count'] < 0 || $source['usable_parcel_count'] > $source['record_count']) {
            throw new RuntimeException('Cadastre source metadata is invalid.');
        }
        $sourceUrls[$source['source_url']] = true;
        $sourceRecords += $source['record_count'];
        $usableParcels += $source['usable_parcel_count'];
    }
    if ($sourceRecords !== $manifest['source_record_total'] || $usableParcels !== $manifest['parcel_count']) throw new RuntimeException('Cadastre source totals are inconsistent.');
    $facetLookup = validate_cadastre_facets($manifest);
    validate_registry_file_descriptor($manifest['index'] ?? null, '/^index\.tsv$/', CADASTRE_MAX_INDEX_BYTES);
    if (!snapshot_list($manifest['records'] ?? null) || count($manifest['records']) < 1 || count($manifest['records']) > 1000) {
        throw new RuntimeException('Cadastre detail descriptors are invalid.');
    }
    $root = __DIR__ . '/private/cadastre-snapshots';
    $directory = $root . '/' . $manifest['snapshot_id'];
    if (is_link($root) || is_link($directory) || !is_dir($directory)) throw new RuntimeException('Cadastre snapshot directory is unavailable.');
    $indexPath = $directory . '/index.tsv';
    if (!is_file($indexPath) || is_link($indexPath) || filesize($indexPath) !== $manifest['index']['bytes']) {
        throw new RuntimeException('Cadastre index is unavailable.');
    }
    $files = [];
    $recordTotal = 0;
    $totalBytes = $manifest['index']['bytes'] + ($conflicts['bytes'] ?? 0);
    if ($conflicts !== null) {
        $path = $directory . '/conflicts.json';
        if (!is_file($path) || is_link($path) || filesize($path) !== $conflicts['bytes']) throw new RuntimeException('Cadastre conflict file is unavailable.');
    }
    foreach ($manifest['records'] as $position => $descriptor) {
        validate_registry_file_descriptor($descriptor, '/^parcels-[0-9]{3}\.json$/', 1024 * 1024);
        if ($descriptor['file'] !== sprintf('parcels-%03d.json', $position) || isset($files[$descriptor['file']]) || !is_int($descriptor['records'] ?? null) || $descriptor['records'] < 1
            || $descriptor['records'] > CADASTRE_MAX_PARCELS) throw new RuntimeException('Cadastre detail descriptor is invalid.');
        $files[$descriptor['file']] = true;
        $recordTotal += $descriptor['records'];
        $totalBytes += $descriptor['bytes'];
        $path = $directory . '/' . $descriptor['file'];
        if (!is_file($path) || is_link($path) || filesize($path) !== $descriptor['bytes']) throw new RuntimeException('Cadastre detail shard is unavailable.');
    }
    if ($recordTotal !== $manifest['parcel_count'] || $totalBytes > CADASTRE_MAX_DATASET_BYTES) {
        throw new RuntimeException('Cadastre snapshot totals are invalid.');
    }
    $manifest['directory'] = $directory;
    $manifest['index_path'] = $indexPath;
    $manifest['ambiguous_lookup'] = $ambiguousLookup;
    $manifest['facet_lookup'] = $facetLookup;
    return $manifest;
}

function cadastre_filter_options(?array $cadastre): array {
    return ['available' => $cadastre !== null, 'min_m2' => $cadastre['area_min_m2'] ?? null,
        'max_m2' => $cadastre['area_max_m2'] ?? null, 'parcel_count' => $cadastre['parcel_count'] ?? 0,
        'source_url' => CADASTRE_CATALOGUE_URL, 'area_method' => $cadastre['area_method'] ?? null,
        'ambiguous_parcel_count' => $cadastre['ambiguous_parcel_count'] ?? 0];
}

function cadastre_attribute_options(?array $cadastre): array {
    $available = $cadastre !== null && $cadastre['version'] === 2;
    $options = ['available' => $available, 'source_url' => CADASTRE_CATALOGUE_URL,
        'parcel_count' => $cadastre['parcel_count'] ?? 0, 'ambiguous_parcel_count' => $cadastre['ambiguous_parcel_count'] ?? 0];
    foreach (['districts', 'purposes', 'uses', 'property_types'] as $dimension) $options[$dimension] = $available ? $cadastre['facets'][$dimension] : [];
    return $options;
}

function cadastre_metadata(?array $cadastre): ?array {
    if ($cadastre === null) return null;
    return ['label_bg' => 'Кадастрални данни на АГКК', 'label_en' => 'AGCC cadastral open data',
        'source_url' => CADASTRE_CATALOGUE_URL, 'captured_at' => $cadastre['generated_at'],
        'parcel_count' => $cadastre['parcel_count'], 'source_record_total' => $cadastre['source_record_total'],
        'ambiguous_parcel_count' => $cadastre['ambiguous_parcel_count'], 'area_method' => CADASTRE_AREA_METHOD];
}

function cadastre_index_iterator(array $cadastre): Generator {
    $descriptor = $cadastre['index'];
    $path = $cadastre['index_path'];
    if (!is_file($path) || is_link($path) || filesize($path) !== $descriptor['bytes']) throw new RuntimeException('Cadastre index is unavailable.');
    $handle = fopen($path, 'rb');
    if ($handle === false) throw new RuntimeException('Cadastre index cannot be read.');
    $hash = hash_init('sha256');
    $bytes = 0;
    $records = 0;
    $previousId = null;
    $minArea = null;
    $maxArea = null;
    $sourceCounts = array_fill(0, count($cadastre['sources']), 0);
    $shardCounts = array_fill(0, count($cadastre['records']), 0);
    $hasFacets = $cadastre['version'] === 2;
    $facetColumns = ['purposes' => 4, 'uses' => 5, 'property_types' => 6];
    $facetCounts = [];
    if ($hasFacets) {
        foreach ($facetColumns as $dimension => $_) $facetCounts[$dimension] = array_fill(0, count($cadastre['facets'][$dimension]), 0);
    }
    try {
        while (($line = fgets($handle, 256)) !== false) {
            $bytes += strlen($line);
            if ($bytes > $descriptor['bytes'] || strlen($line) > ($hasFacets ? 160 : 120) || substr($line, -1) !== "\n") throw new RuntimeException('Cadastre index row is invalid.');
            hash_update($hash, $line);
            $parts = explode("\t", substr($line, 0, -1));
            if (count($parts) !== ($hasFacets ? 7 : 4) || !preg_match('/^68134\.[0-9]{1,6}\.[0-9]{1,6}$/', $parts[0])
                || ($previousId !== null && strcmp($previousId, $parts[0]) >= 0)
                || !preg_match('/^[0-9]+(?:\.[0-9]+)?$/', $parts[1])
                || !preg_match('/^(?:0|[1-9][0-9]{0,2})$/', $parts[2]) || !preg_match('/^(?:0|[1-9][0-9]{0,2})$/', $parts[3])) {
                throw new RuntimeException('Cadastre index row is invalid.');
            }
            $area = (float)$parts[1];
            $sourceIndex = (int)$parts[2];
            $shardIndex = (int)$parts[3];
            if (!cadastre_area_valid($area) || !isset($cadastre['sources'][$sourceIndex]) || !isset($cadastre['records'][$shardIndex])
                || isset($cadastre['ambiguous_lookup'][$parts[0]])) {
                throw new RuntimeException('Cadastre index reference is invalid.');
            }
            $facetIndices = [];
            if ($hasFacets) {
                foreach ($facetColumns as $dimension => $column) {
                    if (!preg_match('/^(?:-1|0|[1-9][0-9]{0,2})$/', $parts[$column])) throw new RuntimeException('Cadastre facet reference is invalid.');
                    $facetIndex = (int)$parts[$column];
                    if ($facetIndex !== -1 && !isset($cadastre['facets'][$dimension][$facetIndex])) throw new RuntimeException('Cadastre facet reference is invalid.');
                    $facetIndices[$dimension] = $facetIndex;
                    if ($facetIndex !== -1) $facetCounts[$dimension][$facetIndex]++;
                }
            }
            $records++;
            if ($records > $cadastre['parcel_count']) throw new RuntimeException('Cadastre index contains too many parcels.');
            $sourceCounts[$sourceIndex]++;
            $shardCounts[$shardIndex]++;
            $minArea = $minArea === null ? $area : min($minArea, $area);
            $maxArea = $maxArea === null ? $area : max($maxArea, $area);
            $previousId = $parts[0];
            yield ['cadastral_id' => $parts[0], 'area_m2' => $area, 'source_index' => $sourceIndex, 'shard_index' => $shardIndex, 'facet_indices' => $facetIndices];
        }
        if (!feof($handle) || $bytes !== $descriptor['bytes'] || $records !== $cadastre['parcel_count']
            || !hash_equals($descriptor['sha256'], hash_final($hash))
            || !cadastre_area_equal((float)$minArea, (float)$cadastre['area_min_m2'])
            || !cadastre_area_equal((float)$maxArea, (float)$cadastre['area_max_m2'])) {
            throw new RuntimeException('Cadastre index integrity check failed.');
        }
        foreach ($sourceCounts as $position => $count) {
            if ($count !== $cadastre['sources'][$position]['usable_parcel_count']) throw new RuntimeException('Cadastre indexed source total is inconsistent.');
            if ($hasFacets && $count !== $cadastre['facets']['districts'][$position]['count']) throw new RuntimeException('Cadastre indexed district total is inconsistent.');
        }
        foreach ($shardCounts as $position => $count) {
            if ($count !== $cadastre['records'][$position]['records']) throw new RuntimeException('Cadastre indexed shard total is inconsistent.');
        }
        foreach ($facetCounts as $dimension => $counts) {
            foreach ($counts as $position => $count) {
                if ($count !== $cadastre['facets'][$dimension][$position]['count']) throw new RuntimeException('Cadastre indexed facet total is inconsistent.');
            }
        }
    } finally {
        fclose($handle);
    }
}

function cadastre_candidate_ids(PDO $pdo, string $where, array $params, ?array $registry = null, ?array $filter = null): array {
    $stmt = $pdo->prepare('SELECT p.cadastral_id FROM parcels p WHERE ' . $where);
    $stmt->execute($params);
    $ids = [];
    while (($row = $stmt->fetch(PDO::FETCH_NUM)) !== false) $ids[$row[0]] = true;
    $stmt = null;
    // Search can return exact-ID-linked register plots without a coordinate row.
    if ($registry !== null && $filter !== null) {
        foreach ($registry['by_id'] as $id => $_) {
            if (registry_id_matches_filter($id, $registry, $filter)) $ids[$id] = true;
        }
    }
    return $ids;
}

function cadastre_matching_ids(array $cadastre, array $candidateIds, array $filter): array {
    $ids = [];
    $selected = [];
    foreach ($filter['cadastre_facets'] as $dimension => $keys) {
        if ($keys === []) continue;
        $selected[$dimension] = [];
        foreach ($keys as $key) $selected[$dimension][$cadastre['facet_lookup'][$dimension][$key]] = true;
    }
    // Complete the stream even when no candidate survives: its hash and counts
    // must be checked before a filtered response can use the accumulated IDs.
    foreach (cadastre_index_iterator($cadastre) as $entry) {
        if (!isset($candidateIds[$entry['cadastral_id']])) continue;
        if ($filter['area_min_m2'] !== null && $entry['area_m2'] < $filter['area_min_m2']) continue;
        if ($filter['area_max_m2'] !== null && $entry['area_m2'] > $filter['area_max_m2']) continue;
        $matches = true;
        foreach ($selected as $dimension => $positions) {
            $position = $dimension === 'districts' ? $entry['source_index'] : $entry['facet_indices'][$dimension];
            if (!isset($positions[$position])) {
                $matches = false;
                break;
            }
        }
        if (!$matches) continue;
        $ids[$entry['cadastral_id']] = true;
    }
    return $ids;
}

function cadastre_area_filter(PDO $pdo, ?array $ids): string {
    if ($ids === null) return '';
    return $ids === [] ? ' AND 0 = 1' : ' AND p.cadastral_id IN (' . quoted_ids($pdo, array_keys($ids)) . ')';
}

function cadastre_detail_fields(): array {
    return ['address', 'district_name', 'purpose_code', 'purpose', 'use_code', 'use', 'property_type_code', 'property_type', 'approval_act'];
}

function validate_cadastre_record($row, string $id, array $cadastre): void {
    $fields = cadastre_detail_fields();
    if (!preg_match('/^68134\.[0-9]{1,6}\.[0-9]{1,6}$/', $id) || !is_array($row) || count($row) !== count($fields) + 3
        || ($row['cadastral_id'] ?? null) !== $id || !cadastre_area_valid($row['area_m2'] ?? null)
        || !is_int($row['source_index'] ?? null) || !isset($cadastre['sources'][$row['source_index']])) {
        throw new RuntimeException('Cadastre detail record is invalid.');
    }
    foreach ($fields as $field) {
        if (!array_key_exists($field, $row) || !snapshot_string($row[$field], 2000, true)) throw new RuntimeException('Cadastre detail attribute is invalid.');
    }
}

function validate_cadastre_record_facets(array $row, array $entry, array $cadastre): void {
    if ($cadastre['version'] !== 2) return;
    if ($row['district_name'] !== $cadastre['facets']['districts'][$entry['source_index']]['label_bg']) {
        throw new RuntimeException('Cadastre detail district differs from its index.');
    }
    foreach (['purposes' => ['purpose_code', 'purpose'], 'uses' => ['use_code', 'use'], 'property_types' => ['property_type_code', 'property_type']] as $dimension => $fields) {
        $position = $entry['facet_indices'][$dimension];
        if ($position === -1) {
            if (cadastre_label_known($row[$fields[1]])) throw new RuntimeException('Cadastre unknown attribute differs from its index.');
        } else {
            $facet = $cadastre['facets'][$dimension][$position];
            if ($row[$fields[0]] !== $facet['code'] || $row[$fields[1]] !== $facet['label_bg']) throw new RuntimeException('Cadastre detail attribute differs from its index.');
        }
    }
}

function public_cadastre_record(array $row, array $cadastre): array {
    $result = ['cadastral_id' => $row['cadastral_id'], 'area_m2' => (float)$row['area_m2']];
    foreach (cadastre_detail_fields() as $field) $result[$field] = $row[$field];
    $source = $cadastre['sources'][$row['source_index']];
    $publicSource = [];
    foreach (['code', 'label_bg', 'source_url', 'catalogue_url', 'published_at', 'captured_at', 'zip_sha256', 'zip_bytes', 'record_count', 'usable_parcel_count'] as $field) {
        $publicSource[$field] = $source[$field];
    }
    $publicSource['catalogue_published_at'] = $source['catalogue_published_at'] ?? null;
    return $result + ['area_unit' => 'm2', 'area_method' => CADASTRE_AREA_METHOD, 'matching_method' => 'exact_cadastral_id',
        'generated_at' => $cadastre['generated_at'], 'source' => $publicSource];
}

function cadastre_ambiguous_plot(string $id, array $cadastre): array {
    $descriptor = $cadastre['conflicts'];
    $rows = bounded_registry_json($cadastre['directory'] . '/conflicts.json', 1024 * 1024, $descriptor['bytes'], $descriptor['sha256']);
    if (count($rows) !== $cadastre['ambiguous_parcel_count']) throw new RuntimeException('Cadastre conflict total is inconsistent.');
    foreach ($rows as $rowId => $variants) {
        if (!is_string($rowId) || !isset($cadastre['ambiguous_lookup'][$rowId]) || !snapshot_list($variants)
            || count($variants) < 2 || count($variants) > 10000) throw new RuntimeException('Cadastre conflict record is invalid.');
        foreach ($variants as $row) validate_cadastre_record($row, $rowId, $cadastre);
    }
    if (!isset($rows[$id])) throw new RuntimeException('Cadastre ambiguous identifier is inconsistent.');
    $variants = array_map(static function (array $row) use ($cadastre): array { return public_cadastre_record($row, $cadastre); }, $rows[$id]);
    return ['status' => 'ambiguous', 'cadastral_id' => $id, 'variants' => $variants,
        'area_unit' => 'm2', 'area_method' => CADASTRE_AREA_METHOD, 'matching_method' => 'exact_cadastral_id', 'generated_at' => $cadastre['generated_at']];
}

function cadastre_plot(string $id, ?array $cadastre): ?array {
    if ($cadastre === null) return null;
    if (isset($cadastre['ambiguous_lookup'][$id])) return cadastre_ambiguous_plot($id, $cadastre);
    $match = null;
    // Consume the complete stream to verify its hash and totals before use.
    foreach (cadastre_index_iterator($cadastre) as $entry) {
        if ($entry['cadastral_id'] === $id) $match = $entry;
    }
    if ($match === null) return null;
    $descriptor = $cadastre['records'][$match['shard_index']];
    $rows = bounded_registry_json($cadastre['directory'] . '/' . $descriptor['file'], 1024 * 1024, $descriptor['bytes'], $descriptor['sha256']);
    if (count($rows) !== $descriptor['records']) throw new RuntimeException('Cadastre detail total is inconsistent.');
    foreach ($rows as $rowId => $row) {
        if (!is_string($rowId) || isset($cadastre['ambiguous_lookup'][$rowId])) throw new RuntimeException('Cadastre detail identifier is invalid.');
        validate_cadastre_record($row, $rowId, $cadastre);
    }
    $row = $rows[$id] ?? null;
    if ($row === null || $row['source_index'] !== $match['source_index'] || !cadastre_area_equal((float)$row['area_m2'], $match['area_m2'])) {
        throw new RuntimeException('Cadastre exact-ID index is inconsistent.');
    }
    validate_cadastre_record_facets($row, $match, $cadastre);
    return public_cadastre_record($row, $cadastre) + ['status' => 'matched'];
}

function cadastre_plot_status(?array $record, ?array $cadastre): string {
    return $record['status'] ?? ($cadastre === null ? 'unavailable' : 'not_matched');
}

function quoted_ids(PDO $pdo, array $ids): string {
    // IDs have been checked against the cadastral-ID pattern. PDO still quotes every value.
    return implode(',', array_map(static function (string $id) use ($pdo): string { return $pdo->quote($id); }, $ids));
}

function coordinate_backed_id_count(PDO $pdo, array $ids): int {
    // The registry indexes contain unique, validated exact IDs. Count only IDs
    // with coordinates so filter totals describe points available on the map.
    $total = 0;
    foreach (array_chunk($ids, 1000) as $chunk) {
        $total += (int)$pdo->query('SELECT COUNT(*) FROM parcels WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND cadastral_id IN (' . quoted_ids($pdo, $chunk) . ')')->fetchColumn();
    }
    return $total;
}

function registry_filter(PDO $pdo, array $registry, array $filter): string {
    $types = $filter['record_types'];
    if ($filter['advanced']) {
        $ids = array_keys($registry['qualified_ids'] ?? []);
    } elseif ($types === []) {
        return '';
    } elseif ($types === ['no_records']) {
        $ids = array_keys($registry['by_id']);
    } else {
        $matching = null;
        foreach ($types as $type) {
            $sourceIds = $type === 'exploitation_certificates' ? $registry['certificate_ids'] : ($registry['source_ids'][$type] ?? []);
            $matching = $matching === null ? $sourceIds : ($filter['match'] === 'all' ? array_intersect_key($matching, $sourceIds) : $matching + $sourceIds);
        }
        $ids = array_keys($matching ?? []);
    }
    if ($ids === []) return $types === ['no_records'] ? '' : ' AND 0 = 1';
    return ' AND p.cadastral_id ' . ($types === ['no_records'] ? 'NOT IN' : 'IN') . ' (' . quoted_ids($pdo, $ids) . ')';
}

function registry_plot(array $row, array $registry): array {
    return serialize_plot(array_merge($row, $registry['flags'][$row['cadastral_id']] ?? empty_document_flags()));
}

function registry_id_matches_filter(string $id, array $registry, array $filter): bool {
    if ($filter['advanced']) return isset($registry['qualified_ids'][$id]);
    $types = $filter['record_types'];
    if ($types === []) return true;
    if ($types === ['no_records']) return !isset($registry['by_id'][$id]);
    $present = [];
    foreach ($types as $type) {
        if ($type === 'exploitation_certificates' ? isset($registry['certificate_ids'][$id]) : isset($registry['source_ids'][$type][$id])) $present[$type] = true;
    }
    return qualifying_types_match($present, $filter);
}

function registry_document_iterator(array $registry, ?string $parcelId = null, ?array $candidateIds = null): Generator {
    if (($registry['format'] ?? 1) === 1) {
        if ($parcelId === null) {
            foreach ($registry['documents'] as $document) {
                if ($candidateIds !== null && !keyword_document_has_candidate($document, $candidateIds)) continue;
                yield $document;
            }
        } else {
            foreach ($registry['by_id'][$parcelId] ?? [] as $index) yield $registry['documents'][$index];
        }
        return;
    }
    $shardNames = [];
    if ($parcelId === null && $candidateIds === null) {
        $shardNames = array_fill_keys(array_keys($registry['shards']), true);
    } elseif ($candidateIds !== null) {
        foreach ($registry['by_id'] as $id => $refs) {
            if (!isset($candidateIds[$id])) continue;
            foreach ($refs as $shardName) $shardNames[$shardName] = true;
        }
    } else {
        foreach ($registry['by_id'][$parcelId] ?? [] as $shardName) $shardNames[$shardName] = true;
    }
    $seen = [];
    $sourceCounts = array_fill_keys(array_keys($registry['sources']), 0);
    foreach ($shardNames as $name => $_) {
        $shard = $registry['shards'][$name];
        $path = $registry['directory'] . '/' . $name;
        if (!is_file($path) || is_link($path) || filesize($path) !== $shard['bytes']) {
            throw new RuntimeException('Registry document shard is unavailable.');
        }
        $handle = fopen($path, 'rb');
        if ($handle === false) throw new RuntimeException('Registry document shard cannot be read.');
        $hash = hash_init('sha256');
        $bytes = 0;
        $records = 0;
        try {
            while (($line = fgets($handle, 1024 * 1024 + 1)) !== false) {
                $bytes += strlen($line);
                if ($bytes > $shard['bytes'] || trim($line) === '') throw new RuntimeException('Registry JSONL row is invalid.');
                hash_update($hash, $line);
                $document = json_decode($line, true, 32, JSON_THROW_ON_ERROR);
                unset($line);
                validate_registry_document($document, $registry['sources']);
                $key = $document['source_code'] . ':' . $document['document_hash'];
                if (isset($seen[$key])) throw new RuntimeException('Registry document is duplicated.');
                $seen[$key] = true;
                $ids = array_fill_keys($document['cadastral_ids'], true);
                if (count($ids) !== count($document['cadastral_ids'])) throw new RuntimeException('Registry document links are duplicated.');
                $ref = $registry['doc_refs'][$key] ?? null;
                if ($ref !== null) {
                    $actualIds = array_keys($ids);
                    $indexedIds = explode("\n", rtrim($ref[1], "\n"));
                    sort($actualIds, SORT_STRING);
                    sort($indexedIds, SORT_STRING);
                    if ($ref[0] !== $name || $actualIds !== $indexedIds) throw new RuntimeException('Registry exact-ID index is inconsistent.');
                    unset($actualIds, $indexedIds);
                } elseif ($ids !== []) {
                    throw new RuntimeException('Registry exact-ID index is inconsistent.');
                }
                $records++;
                if ($records > $shard['records']) throw new RuntimeException('Registry shard document count is inconsistent.');
                $sourceCounts[$document['source_code']]++;
                if (($parcelId === null || isset($registry['by_id'][$parcelId][$key]))
                    && ($candidateIds === null || keyword_document_has_candidate($document, $candidateIds))) yield $document;
                unset($document, $ids);
            }
            if (!feof($handle) || $records !== $shard['records'] || $bytes !== $shard['bytes']
                || !hash_equals($shard['sha256'], hash_final($hash))) {
                throw new RuntimeException('Registry document shard integrity check failed.');
            }
        } finally {
            fclose($handle);
        }
    }
    // Check the existing compact lookup directly instead of allocating another
    // associative set of every document key during a full-text search.
    foreach ($registry['doc_refs'] as $key => $ref) {
        if (isset($shardNames[$ref[0]]) && !isset($seen[$key])) throw new RuntimeException('Registry referenced document is missing.');
    }
    if (count($shardNames) === count($registry['shards']) && $sourceCounts !== $registry['document_counts']) throw new RuntimeException('Registry source document totals are inconsistent.');
}

function keyword_document_has_candidate(array $document, array $candidateIds): bool {
    foreach ($document['cadastral_ids'] as $id) if (isset($candidateIds[$id])) return true;
    return false;
}

function keyword_value_mask($value, array $terms): int {
    if ($value === null || !is_scalar($value)) return 0;
    $text = cadastre_fold_text(is_bool($value) ? ($value ? 'true' : 'false') : (string)$value);
    $mask = 0;
    foreach ($terms as $position => $term) if (strpos($text, $term) !== false) $mask |= 1 << $position;
    return $mask;
}

function keyword_exact_ids(array $terms): array {
    $ids = [];
    foreach ($terms as $term) if (preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $term)) $ids[$term] = true;
    return $ids;
}

function keyword_id_mask(string $id, array $terms): int {
    $mask = 0;
    foreach ($terms as $position => $term) {
        $matches = preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $term) ? $id === $term : strpos($id, $term) !== false;
        if ($matches) $mask |= 1 << $position;
    }
    return $mask;
}

function keyword_document_mask(array $rawFields, array $terms): int {
    $mask = 0;
    $complete = 0;
    foreach ($terms as $position => $_) $complete |= 1 << $position;
    // Search values individually: field names, source metadata and workbook
    // filenames cannot create matches or join phrases across field boundaries.
    foreach ($rawFields as $value) {
        $mask |= keyword_value_mask($value, $terms);
        if ($mask === $complete) break;
    }
    return $mask;
}

function keyword_database_masks(PDO $pdo, array $candidateIds, array $terms, array &$masks): void {
    // The original MySQL-only installation has no sharded private snapshot.
    // Keyset pages keep decoded fields bounded and search the same scalar values.
    $lastCode = '';
    $lastHash = '';
    $documents = 0;
    $bytes = 0;
    $sources = array_fill_keys(registry_source_codes(), true);
    do {
        $stmt = $pdo->prepare('SELECT source_code, document_hash, record_key, OCTET_LENGTH(raw_fields) AS raw_bytes,
            CASE WHEN OCTET_LENGTH(raw_fields) <= 1048576 THEN raw_fields ELSE NULL END AS raw_fields FROM source_documents
            WHERE source_code > :last_code OR (source_code = :same_code AND document_hash > :last_hash)
            ORDER BY source_code, document_hash LIMIT 20');
        $stmt->execute(['last_code' => $lastCode, 'same_code' => $lastCode, 'last_hash' => $lastHash]);
        $page = $stmt->fetchAll();
        $stmt = null;
        foreach ($page as $document) {
            $lastCode = $document['source_code'];
            $lastHash = $document['document_hash'];
            $documents++;
            $bytes += (int)$document['raw_bytes'];
            if ($documents > REGISTRY_MAX_DOCUMENTS || $bytes > REGISTRY_MAX_DATASET_BYTES || !is_string($document['raw_fields'])) {
                throw new RuntimeException('Database search exceeds its processing limit.');
            }
            $document['raw_fields'] = json_decode($document['raw_fields'], true, 32, JSON_THROW_ON_ERROR);
            $document['cadastral_ids'] = [];
            $document['snapshot_file'] = null;
            validate_registry_document($document, $sources);
            $mask = keyword_document_mask($document['raw_fields'], $terms);
            if ($mask === 0) continue;
            $links = $pdo->prepare('SELECT parcel_cadastral_id FROM parcel_documents WHERE source_code = :code AND document_hash = :hash LIMIT 10001');
            $links->execute(['code' => $lastCode, 'hash' => $lastHash]);
            $count = 0;
            while (($id = $links->fetchColumn()) !== false) {
                if (++$count > 10000 || !preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $id)) throw new RuntimeException('Database document links are invalid.');
                if (isset($candidateIds[$id])) $masks[$id] = ($masks[$id] ?? 0) | $mask;
            }
        }
    } while (count($page) === 20);
}

function keyword_matching_ids(PDO $pdo, ?array $registry, ?array $cadastre, array $candidateIds, array $filter): array {
    if (!$filter['search_active'] || $candidateIds === []) return $candidateIds;
    $terms = $filter['search_folded_terms'];
    $textTerms = $terms;
    foreach ($textTerms as $position => $term) {
        // A complete identifier navigates to its own parcel. An observation
        // naming several IDs must not make those other parcels match that ID.
        if (preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $term)) unset($textTerms[$position]);
    }
    $complete = (1 << count($terms)) - 1;
    $masks = [];
    foreach ($candidateIds as $id => $_) {
        $mask = keyword_id_mask($id, $terms);
        if ($mask !== 0) $masks[$id] = $mask;
    }
    if ($textTerms !== [] && $cadastre !== null && $cadastre['version'] === 2) {
        // These official label/code dictionaries are bounded by the manifest.
        // Addresses and approval orders stay in details; do not scan 84 MB of
        // cadastral details for every map move or claim to search their content.
        $facetMasks = [];
        foreach ($cadastre['facets'] as $dimension => $rows) {
            foreach ($rows as $position => $row) {
                $mask = keyword_value_mask($row['label_bg'], $textTerms) | keyword_value_mask($row['code'], $textTerms);
                if ($mask !== 0) $facetMasks[$dimension][$position] = $mask;
            }
        }
        if ($facetMasks !== []) {
            // Complete the stream to verify its hash, row totals and ordinals.
            foreach (cadastre_index_iterator($cadastre) as $entry) {
                $id = $entry['cadastral_id'];
                if (!isset($candidateIds[$id])) continue;
                $mask = 0;
                foreach ($facetMasks as $dimension => $positions) {
                    $position = $dimension === 'districts' ? $entry['source_index'] : $entry['facet_indices'][$dimension];
                    $mask |= $positions[$position] ?? 0;
                }
                if ($mask !== 0) $masks[$id] = ($masks[$id] ?? 0) | $mask;
            }
        }
    }
    if ($textTerms !== [] && $filter['record_types'] !== ['no_records']) {
        if ($registry !== null) {
            foreach (registry_document_iterator($registry, null, $candidateIds) as $document) {
                $mask = keyword_document_mask($document['raw_fields'], $textTerms);
                if ($mask === 0) continue;
                foreach ($document['cadastral_ids'] as $id) {
                    if (isset($candidateIds[$id])) $masks[$id] = ($masks[$id] ?? 0) | $mask;
                }
            }
        } else {
            keyword_database_masks($pdo, $candidateIds, $textTerms, $masks);
        }
    }
    // A term can be satisfied by any observation of the parcel. Existing
    // document and cadastral filters have already qualified the parcel itself.
    foreach ($masks as $id => $mask) {
        if ($filter['search_match'] === 'all' && $mask !== $complete) unset($masks[$id]);
        else $masks[$id] = true;
    }
    return $masks;
}

function matching_plot_ids(PDO $pdo, ?array $registry, ?array $cadastre, array $filter, string $where, array $params, bool $includeUnmapped = false): array {
    $exactIds = keyword_exact_ids($filter['search_terms']);
    $exactOnly = $exactIds !== [] && ($filter['search_match'] === 'all' || count($exactIds) === count($filter['search_terms']));
    if ($exactOnly) {
        if ($filter['search_match'] === 'all' && count($exactIds) > 1) return [];
        $where .= cadastre_area_filter($pdo, $exactIds);
    }
    $ids = cadastre_candidate_ids($pdo, $where, $params, $includeUnmapped && !$exactOnly ? $registry : null, $includeUnmapped && !$exactOnly ? $filter : null);
    if ($includeUnmapped && $exactOnly && $registry !== null) {
        foreach ($exactIds as $id => $_) {
            if (isset($registry['by_id'][$id]) && registry_id_matches_filter($id, $registry, $filter)) $ids[$id] = true;
        }
    }
    if ($filter['cadastre_active']) $ids = cadastre_matching_ids($cadastre, $ids, $filter);
    return keyword_matching_ids($pdo, $registry, $cadastre, $ids, $filter);
}

function keyword_search_response(PDO $pdo, ?array $registry, array $ids, array $filter): array {
    $empty = ['items' => [], 'total' => 0, 'mapped_total' => 0, 'unmapped_total' => 0, 'truncated' => false, 'bounds' => null];
    if ($ids === []) return $empty;
    $where = '1 = 1' . cadastre_area_filter($pdo, $ids);
    $mappedWhere = $where . ' AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL';
    $summary = $pdo->query('SELECT COUNT(*) AS total, MIN(p.latitude) AS south, MAX(p.latitude) AS north,
        MIN(p.longitude) AS west, MAX(p.longitude) AS east FROM parcels p WHERE ' . $mappedWhere)->fetch();
    $mappedTotal = (int)$summary['total'];
    $exactIds = [];
    foreach ($filter['search_terms'] as $term) {
        if (preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $term) && isset($ids[$term])) $exactIds[$term] = true;
    }
    $order = $exactIds === [] ? '' : '(p.cadastral_id IN (' . quoted_ids($pdo, array_keys($exactIds)) . ')) DESC, ';
    $rows = [];
    $stmt = $pdo->query('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng'
        . ($registry === null ? ', ' . document_flags_select() : '') . ' FROM parcels p '
        . ($registry === null ? document_flags_join() : '') . ' WHERE ' . $mappedWhere . ' ORDER BY ' . $order . 'p.cadastral_id LIMIT 40');
    foreach ($stmt->fetchAll() as $row) $rows[$row['cadastral_id']] = $registry !== null ? registry_plot($row, $registry) : serialize_plot($row);
    // Preserve discoverability of exact linked IDs without a coordinate point.
    foreach ($exactIds as $id => $_) {
        if (!isset($rows[$id])) $rows = [$id => $registry !== null ? registry_plot(['cadastral_id' => $id, 'lat' => null, 'lng' => null], $registry)
            : serialize_plot(['cadastral_id' => $id, 'lat' => null, 'lng' => null] + empty_document_flags())] + $rows;
    }
    if ($mappedTotal < 40 && count($rows) < 40) {
        $remaining = array_keys(array_diff_key($ids, $rows));
        sort($remaining, SORT_STRING);
        foreach (array_slice($remaining, 0, 40 - count($rows)) as $id) {
            $rows[$id] = $registry !== null ? registry_plot(['cadastral_id' => $id, 'lat' => null, 'lng' => null], $registry)
                : serialize_plot(['cadastral_id' => $id, 'lat' => null, 'lng' => null] + empty_document_flags());
        }
    }
    if ($registry === null) {
        foreach ($rows as $row) {
            if ($row['lat'] !== null && $row['lng'] !== null) continue;
            $stmt = $pdo->query('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng, ' . document_flags_select()
                . ' FROM parcels p ' . document_flags_join() . ' WHERE p.cadastral_id IN (' . quoted_ids($pdo, array_keys($rows)) . ')');
            foreach ($stmt->fetchAll() as $databaseRow) $rows[$databaseRow['cadastral_id']] = serialize_plot($databaseRow);
            break;
        }
    }
    $items = array_map(static function (array $row): array {
        return $row + ['primary' => $row['cadastral_id'], 'secondary' => $row['document_count'] . ' linked register records'];
    }, array_slice(array_values($rows), 0, 40));
    return ['items' => $items, 'total' => count($ids), 'mapped_total' => $mappedTotal,
        'unmapped_total' => count($ids) - $mappedTotal, 'truncated' => count($ids) > count($items),
        'bounds' => $mappedTotal === 0 ? null : ['south' => (float)$summary['south'], 'north' => (float)$summary['north'],
            'west' => (float)$summary['west'], 'east' => (float)$summary['east']]];
}

function registry_plot_sources(string $id, array $registry): array {
    $grouped = [];
    foreach (registry_document_iterator($registry, $id) as $document) {
        $code = $document['source_code'];
        $source = $registry['sources'][$code];
        if (!isset($grouped[$code])) $grouped[$code] = array_merge(public_source($source), ['documents' => []]);
        $fallback = ($document['snapshot_file'] ?? null) === ($source['snapshot_file'] ?? null) ? $source['snapshot_date'] : null;
        $grouped[$code]['documents'][] = [
            'id' => $document['document_hash'], 'record_key' => $document['record_key'] ?? null,
            'snapshot_date' => array_key_exists('snapshot_date', $document) ? $document['snapshot_date'] : document_snapshot_date($document['snapshot_file'] ?? null, $fallback),
            'issued_at' => $document['issued_at'] ?? null,
            'raw_fields' => $document['raw_fields'],
        ];
    }
    return array_values($grouped);
}

try {
    $action = $_GET['action'] ?? '';
    $filter = in_array($action, ['viewport', 'search', 'boundaries'], true) ? map_filter_params() : null;
    $configFile = __DIR__ . '/private/config.php';
    if (!is_file($configFile)) {
        respond(['error' => 'Database is not configured. Copy private/config.example.php to private/config.php and enter the hosting database credentials.'], 503);
    }
    $config = require $configFile;
    $dsn = sprintf('mysql:host=%s;dbname=%s;port=%d;charset=utf8mb4', $config['host'], $config['database'], (int)$config['port']);
    $pdo = new PDO($dsn, $config['username'], $config['password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
    $registry = load_registry_snapshot($filter);
    if ($action === 'development') {
        require_once __DIR__ . '/development-data.php';
        if ($registry !== null) {
            // The dashboard streams every validated document without a parcel
            // or candidate selection. Retain the exact-ID integrity references,
            // but release map-only parcel arrays before its grouped analysis.
            $registry['source_plot_counts'] = array_map('count', $registry['source_ids']);
            unset($registry['by_id'], $registry['flags'], $registry['source_ids'],
                $registry['certificate_ids'], $registry['qualified_ids'], $registry['filter_options']);
        }
        respond(development_response($pdo, $registry, development_params()));
    }
    $cadastre = load_cadastre_snapshot();
    if ($filter !== null) validate_cadastre_filter_selection($cadastre, $filter);
    if ($action === 'boundaries') {
        require_once __DIR__ . '/boundary-data.php';
        try {
            respond(boundary_response($pdo, $registry, $cadastre, $filter));
        } catch (InvalidArgumentException $error) {
            throw $error;
        } catch (Throwable $error) {
            error_log('Sofia boundary layer error: ' . $error->getMessage());
            respond(boundary_reply(null, 'unavailable', 'boundary_service_unavailable'), 503);
        }
    }
    if ($action === 'meta') {
        require_once __DIR__ . '/boundary-data.php';
        $boundaryMeta = boundary_metadata();
        $counts = [
            'plots' => (int)$pdo->query('SELECT COUNT(*) FROM parcels WHERE latitude IS NOT NULL AND longitude IS NOT NULL')->fetchColumn(),
            'documents' => (int)$pdo->query('SELECT COUNT(*) FROM source_documents')->fetchColumn(),
        ];
        if ($registry !== null) {
            $counts['documents'] = array_sum($registry['document_counts']);
            $counts['documents_by_source'] = $registry['document_counts'];
            $counts['plots_by_source'] = [];
            foreach ($registry['source_ids'] as $code => $ids) {
                $counts['plots_by_source'][$code] = coordinate_backed_id_count($pdo, array_keys($ids));
            }
            $counts['plots_with_exploitation_certificate'] = coordinate_backed_id_count($pdo, array_keys($registry['certificate_ids']));
            $counts['linked_exploitation_certificates'] = $registry['linked_certificates'];
            respond(['counts' => $counts, 'imports' => $registry['imports'], 'registry_generated_at' => $registry['generated_at'],
                'filter_options' => $registry['filter_options'] + ['parcel_area' => cadastre_filter_options($cadastre), 'cadastre' => cadastre_attribute_options($cadastre)], 'cadastre' => cadastre_metadata($cadastre), 'boundaries' => $boundaryMeta]);
        }
        $counts['documents_by_source'] = [];
        $counts['plots_by_source'] = [];
        foreach ($pdo->query('SELECT ds.code, COUNT(sd.document_hash) AS document_count FROM data_sources ds LEFT JOIN source_documents sd ON sd.source_code = ds.code GROUP BY ds.code')->fetchAll() as $row) {
            $counts['documents_by_source'][$row['code']] = (int)$row['document_count'];
            $counts['plots_by_source'][$row['code']] = 0;
        }
        foreach ($pdo->query('SELECT pd.source_code, COUNT(DISTINCT pd.parcel_cadastral_id) AS plot_count FROM parcel_documents pd JOIN parcels p ON p.cadastral_id = pd.parcel_cadastral_id WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL GROUP BY pd.source_code')->fetchAll() as $row) {
            $counts['plots_by_source'][$row['source_code']] = (int)$row['plot_count'];
        }
        $counts['plots_with_exploitation_certificate'] = (int)$pdo->query("SELECT COUNT(DISTINCT pd.parcel_cadastral_id) FROM parcel_documents pd JOIN parcels p ON p.cadastral_id = pd.parcel_cadastral_id WHERE pd.source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy') AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL")->fetchColumn();
        $counts['linked_exploitation_certificates'] = (int)$pdo->query("SELECT COUNT(*) FROM (SELECT source_code, document_hash FROM parcel_documents WHERE source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy') GROUP BY source_code, document_hash) linked_certificates")->fetchColumn();
        $imports = $pdo->query('SELECT di.source_code, ds.label_bg, ds.label_en, ds.source_url, ds.snapshot_date, ds.snapshot_file AS source_snapshot, di.source_file, di.imported_at, di.records_loaded FROM data_imports di LEFT JOIN data_sources ds ON ds.code = di.source_code ORDER BY di.imported_at DESC')->fetchAll();
        $imports = array_map(static function (array $row): array {
            $fallback = $row['source_file'] === $row['source_snapshot'] ? $row['snapshot_date'] : null;
            $row['snapshot_date'] = document_snapshot_date($row['source_file'], $fallback);
            $row['records_loaded'] = (int)$row['records_loaded'];
            unset($row['source_file'], $row['source_snapshot']);
            return $row;
        }, $imports);
        respond(['counts' => $counts, 'imports' => $imports, 'filter_options' => filter_options(null) + ['parcel_area' => cadastre_filter_options($cadastre), 'cadastre' => cadastre_attribute_options($cadastre)], 'cadastre' => cadastre_metadata($cadastre), 'boundaries' => $boundaryMeta]);
    }

    if ($action === 'viewport') {
        $north = number_param('north', -90, 90);
        $south = number_param('south', -90, 90);
        $east = number_param('east', -180, 180);
        $west = number_param('west', -180, 180);
        $zoom = (int)max(0, min(22, (float)($_GET['zoom'] ?? 13)));
        if ($north <= $south || $east <= $west) {
            respond(['items' => [], 'total' => 0, 'truncated' => false]);
        }

        $where = 'p.latitude BETWEEN :south AND :north AND p.longitude BETWEEN :west AND :east'
            . ($registry !== null ? registry_filter($pdo, $registry, $filter) : record_filter($filter));
        $bounds = ['south' => $south, 'north' => $north, 'west' => $west, 'east' => $east];
        if ($filter['cadastre_active'] || $filter['search_active']) {
            $matchingIds = matching_plot_ids($pdo, $registry, $cadastre, $filter, $where, $bounds);
            $where .= cadastre_area_filter($pdo, $matchingIds);
            unset($matchingIds);
        }
        $countStmt = $pdo->prepare('SELECT COUNT(*) FROM parcels p WHERE ' . $where);
        $countStmt->execute($bounds);
        $total = (int)$countStmt->fetchColumn();
        $pointLimit = 1800;
        $clusterLimit = 1800;
        if ($total === 0) respond(['items' => [], 'total' => 0, 'truncated' => false]);

        if ($zoom >= 17 && $total <= $pointLimit) {
            $stmt = $pdo->prepare('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng' . ($registry !== null ? '' : ', ' . document_flags_select()) . ' FROM parcels p ' . ($registry !== null ? '' : document_flags_join()) . ' WHERE ' . $where . ' ORDER BY p.cadastral_id LIMIT ' . ($pointLimit + 1));
            $stmt->execute($bounds);
            $items = array_map(static function (array $row) use ($registry): array {
                return array_merge(['kind' => 'plot'], $registry !== null ? registry_plot($row, $registry) : serialize_plot($row));
            }, $stmt->fetchAll());
            if (count($items) <= $pointLimit) respond(['items' => $items, 'total' => count($items), 'truncated' => false]);
            // Coordinate edits between the count and select must not produce a
            // truncated subset of points. Fall through to complete aggregation.
            unset($items);
        }

        $certificateExpression = 'COALESCE(flags.has_exploitation_certificate, 0)';
        if ($registry !== null) {
            $certificateExpression = $registry['certificate_ids'] === [] ? '0' : 'p.cadastral_id IN (' . quoted_ids($pdo, array_keys($registry['certificate_ids'])) . ')';
        }
        // A Leaflet/Web Mercator world is 256 * 2^zoom pixels wide. Using
        // 128-pixel cells gives 2^(zoom+1) cells per axis. World anchoring makes
        // every cell split into exactly 2 x 2 children at the next zoom level.
        // Clamp Mercator latitude to avoid poles, zero cosine and invalid LN.
        $mercatorLatitude = 'LEAST(85.05112878, GREATEST(-85.05112878, p.latitude))';
        $mercatorY = '(1 - LN(TAN(RADIANS(' . $mercatorLatitude . ')) + 1 / COS(RADIANS(' . $mercatorLatitude . '))) / PI()) / 2';
        $clusterZoom = $zoom;
        do {
            $worldCells = 1 << ($clusterZoom + 1);
            $stmt = $pdo->prepare(
                'SELECT LEAST(:world_max_x, GREATEST(0, FLOOR((p.longitude + 180) / 360 * :world_cells_x))) AS gx,
                        LEAST(:world_max_y, GREATEST(0, FLOOR(' . $mercatorY . ' * :world_cells_y))) AS gy,
                        AVG(p.latitude) AS lat, AVG(p.longitude) AS lng, COUNT(*) AS point_count,
                        MIN(p.latitude) AS south, MAX(p.latitude) AS north,
                        MIN(p.longitude) AS west, MAX(p.longitude) AS east,
                        SUM(' . $certificateExpression . ') AS certificate_count
                 FROM parcels p ' . ($registry !== null ? '' : document_flags_join()) . ' WHERE ' . $where . '
                 GROUP BY gy, gx ORDER BY point_count DESC, gy, gx LIMIT ' . ($clusterLimit + 1)
            );
            $stmt->execute(array_merge(['world_max_x' => $worldCells - 1, 'world_max_y' => $worldCells - 1,
                'world_cells_x' => $worldCells, 'world_cells_y' => $worldCells], $bounds));
            $rows = $stmt->fetchAll();
            if (count($rows) <= $clusterLimit) break;
            // Very large bounds at a detailed zoom can span too many cells.
            // Regroup all matching points at a coarser level instead of dropping
            // clusters. At level 0 only four world cells are possible.
            $clusterZoom--;
        } while ($clusterZoom >= 0);
        $items = array_map(static function (array $row) use ($zoom, $clusterZoom): array {
            return [
                'kind' => 'cluster',
                'cell_key' => $clusterZoom . ':' . $row['gx'] . ':' . $row['gy'],
                'lat' => (float)$row['lat'],
                'lng' => (float)$row['lng'],
                'count' => (int)$row['point_count'],
                'certificate_count' => (int)$row['certificate_count'],
                'bounds' => ['south' => (float)$row['south'], 'north' => (float)$row['north'],
                    'west' => (float)$row['west'], 'east' => (float)$row['east']],
                'zoom' => $zoom,
                'cluster_zoom' => $clusterZoom,
            ];
        }, $rows);
        $total = array_sum(array_column($items, 'count'));
        respond(['items' => $items, 'total' => $total, 'truncated' => false, 'requested_zoom' => $zoom, 'cluster_zoom' => $clusterZoom]);
    }

    if ($action === 'search') {
        if (!$filter['search_active']) respond(keyword_search_response($pdo, $registry, [], $filter));
        $where = '1 = 1' . ($registry !== null ? registry_filter($pdo, $registry, $filter) : record_filter($filter));
        $matchingIds = matching_plot_ids($pdo, $registry, $cadastre, $filter, $where, [], true);
        respond(keyword_search_response($pdo, $registry, $matchingIds, $filter));
    }

    if ($action === 'plot') {
        $id = trim((string)($_GET['id'] ?? ''));
        if ($id === '' || text_length($id) > 80) {
            respond(['error' => 'A valid cadastral identifier is required.'], 400);
        }
        if ($registry !== null) {
            $stmt = $pdo->prepare('SELECT cadastral_id, latitude AS lat, longitude AS lng FROM parcels WHERE cadastral_id = :id LIMIT 1');
            $stmt->execute(['id' => $id]);
            $plot = $stmt->fetch();
            $cadastreRecord = cadastre_plot($id, $cadastre);
            if (!$plot && !isset($registry['by_id'][$id]) && $cadastreRecord === null) respond(['error' => 'No record was found for this cadastral identifier.'], 404);
            if (!$plot) $plot = ['cadastral_id' => $id, 'lat' => null, 'lng' => null];
            respond(['plot' => registry_plot($plot, $registry), 'sources' => registry_plot_sources($id, $registry),
                'cadastre' => $cadastreRecord, 'cadastre_status' => cadastre_plot_status($cadastreRecord, $cadastre)]);
        }
        $stmt = $pdo->prepare('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng, ' . document_flags_select() . ' FROM parcels p ' . document_flags_join() . ' WHERE p.cadastral_id = :id LIMIT 1');
        $stmt->execute(['id' => $id]);
        $plot = $stmt->fetch();
        if (!$plot) {
            $cadastreRecord = cadastre_plot($id, $cadastre);
            if ($cadastreRecord === null) respond(['error' => 'No record was found for this cadastral identifier.'], 404);
            respond(['plot' => serialize_plot(array_merge(['cadastral_id' => $id, 'lat' => null, 'lng' => null], empty_document_flags())),
                'sources' => [], 'cadastre' => $cadastreRecord, 'cadastre_status' => cadastre_plot_status($cadastreRecord, $cadastre)]);
        }
        $plot = serialize_plot($plot);

        $stmt = $pdo->prepare(
            'SELECT ds.code, ds.label_bg, ds.label_en, ds.source_url, ds.snapshot_date, ds.snapshot_file AS source_snapshot,
                    sd.document_hash, sd.record_key, sd.raw_fields, sd.snapshot_file AS document_snapshot
             FROM parcel_documents pd
             JOIN source_documents sd ON sd.source_code = pd.source_code AND sd.document_hash = pd.document_hash
             JOIN data_sources ds ON ds.code = pd.source_code
             WHERE pd.parcel_cadastral_id = :id
             ORDER BY ds.code, sd.record_key'
        );
        $stmt->execute(['id' => $id]);
        $grouped = [];
        foreach ($stmt->fetchAll() as $row) {
            $code = $row['code'];
            if (!isset($grouped[$code])) {
                $grouped[$code] = [
                    'code' => $code,
                    'label_bg' => $row['label_bg'],
                    'label_en' => $row['label_en'],
                    'source_url' => $row['source_url'],
                    'snapshot_date' => $row['snapshot_date'],
                    'documents' => [],
                ];
            }
            $rawFields = json_decode($row['raw_fields'], true);
            $grouped[$code]['documents'][] = [
                'id' => $row['document_hash'],
                'record_key' => $row['record_key'],
                'snapshot_date' => document_snapshot_date($row['document_snapshot'], $row['document_snapshot'] === $row['source_snapshot'] ? $row['snapshot_date'] : null),
                'raw_fields' => is_array($rawFields) ? $rawFields : [],
            ];
        }
        $cadastreRecord = cadastre_plot($id, $cadastre);
        respond(['plot' => $plot, 'sources' => array_values($grouped), 'cadastre' => $cadastreRecord, 'cadastre_status' => cadastre_plot_status($cadastreRecord, $cadastre)]);
    }

    respond(['error' => 'Unknown API action.'], 404);
} catch (InvalidArgumentException $error) {
    respond(['error' => $error->getMessage()], 400);
} catch (FilterUnavailableException $error) {
    respond(['error' => $error->getMessage()], 503);
} catch (Throwable $error) {
    error_log('Sofia property API error: ' . $error->getMessage());
    respond(['error' => 'The data service is temporarily unavailable.'], 500);
}
