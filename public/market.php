<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
set_error_handler(static function (int $severity, string $message, string $file, int $line): bool {
    if (!(error_reporting() & $severity)) return false;
    throw new ErrorException($message, 0, $severity, $file, $line);
});

const MARKET_MAX_LISTINGS = 50000;
const MARKET_MAX_SHARDS = 512;
const MARKET_PUBLIC_FIELDS = ['id', 'url', 'neighborhood_key', 'neighborhood_bg', 'type_key', 'type_bg', 'area_sqm', 'price_eur', 'eur_per_sqm', 'price_currency', 'vat_basis', 'construction_year', 'construction_cohort', 'last_modified_at', 'observed_at', 'first_seen_at', 'comparison', 'change', 'historical', 'quality_flags', 'floor_bg', 'construction_label_bg', 'address_bg', 'price_total_derived', 'quoted_eur_per_sqm', 'seller_type', 'seller_evidence', 'seller_checked_at', 'location', 'analysis', 'asking_estimate', 'agency', 'property_features'];

function market_optional_text($value, int $limit): bool {
    return $value === null || (is_string($value) && strlen($value) <= $limit && preg_match('//u', $value) === 1);
}

function market_evidence_date($value, bool $nullable = true): bool {
    return ($nullable && $value === null) || (is_string($value) && preg_match('/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?$/', $value) === 1 && strtotime($value) !== false);
}

function market_finite_number($value, float $minimum, float $maximum): bool {
    return (is_int($value) || is_float($value)) && is_finite((float)$value) && $value >= $minimum && $value <= $maximum;
}

function market_location($value): void {
    if ($value === null) return;
    $fields = ['key', 'lat', 'lng', 'precision', 'label_bg', 'radius_m', 'method', 'source_url', 'reference_date', 'evidence'];
    if (!is_array($value) || array_diff(array_keys($value), $fields) !== []
        || !is_string($value['key'] ?? null) || !preg_match('/^[a-zA-Z0-9_.:-]{1,160}$/', $value['key'])
        || !market_finite_number($value['lat'] ?? null, 42.4, 43) || !market_finite_number($value['lng'] ?? null, 22.8, 24)
        || !in_array($value['precision'] ?? null, ['street', 'neighborhood'], true)
        || !is_string($value['label_bg'] ?? null) || !market_optional_text($value['label_bg'], 600)
        || !market_finite_number($value['radius_m'] ?? null, 200, 12000)
        || !in_array($value['method'] ?? null, ['cadastre_street_reference', 'cadastre_neighborhood_reference'], true)
        || !in_array($value['evidence'] ?? null, ['listed_address', 'description_street', 'listed_neighborhood'], true)
        || !is_string($value['reference_date'] ?? null) || !preg_match('/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/', $value['reference_date'])
        || ($value['method'] ?? null) !== 'cadastre_' . $value['precision'] . '_reference'
        || ($value['source_url'] ?? null) !== 'https://kais.cadastre.bg/bg/OpenData') throw new RuntimeException('Market reference location is invalid.');
    $source = parse_url($value['source_url']);
    if (!is_array($source) || ($source['scheme'] ?? '') !== 'https' || ($source['host'] ?? '') !== 'kais.cadastre.bg'
        || isset($source['user']) || isset($source['pass']) || isset($source['port']) || strlen($value['source_url']) > 1200) throw new RuntimeException('Market location source is invalid.');
}

function market_analysis($value): void {
    if ($value === null) return;
    $fields = ['completion_stage', 'condition', 'area_basis', 'risk_flags', 'checked_at', 'description_analyzed'];
    if (!is_array($value) || array_diff(array_keys($value), $fields) !== []
        || !in_array($value['completion_stage'] ?? null, ['planned', 'completed', 'unknown'], true)
        || !in_array($value['condition'] ?? null, ['renovated', 'needs_renovation', 'unknown'], true)
        || !in_array($value['area_basis'] ?? null, ['net', 'gross', 'terrace_included', 'unknown'], true)
        || !is_bool($value['description_analyzed'] ?? null) || !market_optional_text($value['checked_at'] ?? null, 80)
        || !is_array($value['risk_flags'] ?? null) || !array_is_list($value['risk_flags']) || count($value['risk_flags']) > 5
        || array_diff($value['risk_flags'], ['share_sale', 'auction', 'tenanted', 'nonresidential', 'mandatory_extra_cost']) !== []) throw new RuntimeException('Market text analysis is invalid.');
}

function market_estimate($value): void {
    if ($value === null) return;
    $fields = ['status', 'method_version', 'peer_count', 'median_eur_per_sqm', 'p25_eur_per_sqm', 'p75_eur_per_sqm', 'indicated_price_eur', 'range_low_eur', 'range_high_eur', 'location_basis'];
    if (($value['method_version'] ?? null) === 3) $fields[] = 'evidence';
    if (!is_array($value) || count($value) !== count($fields) || array_diff(array_keys($value), $fields) !== []
        || !in_array($value['status'] ?? null, ['available', 'insufficient_comparables', 'needs_review', 'invalid_inputs'], true)
        || !in_array($value['method_version'] ?? null, [2, 3], true) || !is_int($value['peer_count'] ?? null) || $value['peer_count'] < 0 || $value['peer_count'] > MARKET_MAX_LISTINGS
        || !in_array($value['location_basis'] ?? null, ['street', 'neighborhood', null], true)) throw new RuntimeException('Market asking-price estimate is invalid.');
    foreach (['median_eur_per_sqm', 'p25_eur_per_sqm', 'p75_eur_per_sqm', 'indicated_price_eur', 'range_low_eur', 'range_high_eur'] as $field) {
        if (($value[$field] ?? null) !== null && !market_finite_number($value[$field], 0.000001, 1e12)) throw new RuntimeException('Market asking-price range is invalid.');
    }
    if ($value['status'] === 'available' && ($value['peer_count'] < 8
        || !market_finite_number($value['indicated_price_eur'] ?? null, 0.000001, 1e12)
        || !market_finite_number($value['range_low_eur'] ?? null, 0.000001, 1e12)
        || !market_finite_number($value['range_high_eur'] ?? null, 0.000001, 1e12)
        || $value['range_low_eur'] > $value['indicated_price_eur'] || $value['indicated_price_eur'] > $value['range_high_eur'])) throw new RuntimeException('Market available estimate is inconsistent.');
    if ($value['method_version'] === 3) {
        $evidence = $value['evidence'] ?? null;
        $keys = ['quality', 'matched_fields', 'missing_fields', 'spread_pct', 'price_position', 'duplicate_peer_count', 'unknown_physical_duplicates'];
        $factors = ['neighborhood', 'type', 'vat_basis', 'construction_age', 'construction_type', 'completion_stage', 'area_basis', 'floor', 'furnishing', 'condition', 'elevator', 'area_tolerance', 'street'];
        if (!is_array($evidence) || count($evidence) !== count($keys) || array_diff(array_keys($evidence), $keys) !== []
            || !in_array($evidence['quality'] ?? null, ['detailed', 'limited', 'insufficient'], true)
            || !in_array($evidence['price_position'] ?? null, ['below_range', 'within_range', 'above_range', 'unavailable'], true)
            || ($evidence['unknown_physical_duplicates'] ?? null) !== true
            || !is_int($evidence['duplicate_peer_count'] ?? null) || $evidence['duplicate_peer_count'] < 0 || $evidence['duplicate_peer_count'] > MARKET_MAX_LISTINGS
            || (($evidence['spread_pct'] ?? null) !== null && !market_finite_number($evidence['spread_pct'], 0, 1e9))) throw new RuntimeException('Market comparison evidence is invalid.');
        foreach (['matched_fields', 'missing_fields'] as $field) {
            $items = $evidence[$field] ?? null;
            if (!is_array($items) || !array_is_list($items) || count($items) > count($factors) || count(array_unique($items, SORT_REGULAR)) !== count($items) || array_diff($items, $factors) !== []) throw new RuntimeException('Market comparison factors are invalid.');
        }
        if (array_intersect($evidence['matched_fields'], $evidence['missing_fields']) !== [] || count($evidence['matched_fields']) + count($evidence['missing_fields']) !== count($factors)
            || ($value['status'] !== 'available' && $evidence['price_position'] !== 'unavailable')) throw new RuntimeException('Market comparison factors conflict.');
    }
}

function market_professional_url($value, bool $profile = false): bool {
    if (!is_string($value) || strlen($value) > 500 || preg_match('/[\x00-\x20\x7f]/', $value)) return false;
    $parts = parse_url($value);
    if (!is_array($parts) || ($parts['scheme'] ?? '') !== 'https' || !is_string($parts['host'] ?? null) || isset($parts['user']) || isset($parts['pass']) || isset($parts['port'])) return false;
    $host = strtolower($parts['host']);
    return $profile ? preg_match('/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.imot\.bg$/', $host) === 1 && $host !== 'www.imot.bg' : preg_match('/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/', $host) === 1;
}

function market_property_features($value): void {
    if ($value === null) return;
    $fields = ['construction_type', 'furnishing', 'building_year', 'year_basis', 'floor_number', 'total_floors', 'elevator', 'checked_at', 'source'];
    if (!is_array($value) || count($value) !== count($fields) || array_diff(array_keys($value), $fields) !== []
        || !in_array($value['construction_type'] ?? null, ['brick', 'panel', 'epk', 'monolithic', 'other', 'unknown'], true)
        || !in_array($value['furnishing'] ?? null, ['furnished', 'partial', 'unfurnished', 'unknown'], true)
        || !in_array($value['year_basis'] ?? null, ['built', 'commissioned', 'planned', 'unknown'], true)
        || !in_array($value['elevator'] ?? null, ['yes', 'no', 'unknown'], true)
        || !in_array($value['source'] ?? null, ['card', 'description'], true)
        || !market_evidence_date($value['checked_at'] ?? null)) throw new RuntimeException('Market property features are invalid.');
    foreach (['building_year' => [1800, 2100], 'floor_number' => [-5, 100], 'total_floors' => [1, 100]] as $field => [$minimum, $maximum]) {
        if ($value[$field] !== null && (!is_int($value[$field]) || $value[$field] < $minimum || $value[$field] > $maximum)) throw new RuntimeException('Market property feature bounds are invalid.');
    }
    if (($value['building_year'] === null && $value['year_basis'] !== 'unknown') || ($value['floor_number'] !== null && $value['total_floors'] !== null && $value['floor_number'] > $value['total_floors'])) throw new RuntimeException('Market property features conflict.');
}

function market_agency($value, string $seller): void {
    if ($value === null) return;
    $fields = ['name', 'profile_url', 'phone', 'website', 'checked_at', 'evidence'];
    if ($seller !== 'agency' || !is_array($value) || count($value) !== count($fields) || array_diff(array_keys($value), $fields) !== []
        || !is_string($value['name'] ?? null) || trim($value['name']) === '' || !market_optional_text($value['name'], 480) || preg_match_all('/./us', $value['name']) > 120
        || !market_professional_url($value['profile_url'] ?? null, true)
        || ($value['phone'] !== null && (!is_string($value['phone']) || !preg_match('/^\+?[0-9]{7,15}$/', $value['phone'])))
        || ($value['website'] !== null && !market_professional_url($value['website']))
        || ($value['evidence'] ?? null) !== 'professional_profile'
        || !market_evidence_date($value['checked_at'] ?? null, false)) throw new RuntimeException('Market professional agency is invalid.');
}

function market_respond(array $body, int $status = 200): void {
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    exit;
}

function market_json(string $path, int $limit, ?array $descriptor = null): array {
    if (!is_file($path) || is_link($path)) throw new RuntimeException('Market file is unavailable.');
    $size = filesize($path);
    if ($size === false || $size < 1 || $size > $limit || ($descriptor !== null && $size !== $descriptor['bytes'])) throw new RuntimeException('Market file size is invalid.');
    $payload = file_get_contents($path);
    if ($payload === false || strlen($payload) !== $size || ($descriptor !== null && !hash_equals($descriptor['sha256'], hash('sha256', $payload)))) throw new RuntimeException('Market file integrity failed.');
    $value = json_decode($payload, true, 32, JSON_THROW_ON_ERROR);
    if (!is_array($value)) throw new RuntimeException('Market JSON is invalid.');
    return $value;
}

function market_descriptor($value, string $pattern, int $limit): void {
    if (!is_array($value) || !is_string($value['path'] ?? null) || !preg_match($pattern, $value['path'])
        || !is_int($value['bytes'] ?? null) || $value['bytes'] < 1 || $value['bytes'] > $limit
        || !is_string($value['sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $value['sha256'])) throw new RuntimeException('Market descriptor is invalid.');
}

function market_snapshot(): array {
    $private = __DIR__ . '/private';
    $root = $private . '/market-snapshots';
    if (is_link($private) || is_link($root)) throw new RuntimeException('Market directory is invalid.');
    $pointer = market_json($private . '/market-active.json', 4096);
    $id = $pointer['snapshot_id'] ?? null;
    if (($pointer['version'] ?? null) !== 1 || !is_string($id) || !preg_match('/^[a-f0-9]{32}$/', $id)
        || ($pointer['manifest_path'] ?? null) !== 'market-snapshots/' . $id . '/manifest.json'
        || !is_string($pointer['manifest_sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $pointer['manifest_sha256'])) throw new RuntimeException('Market pointer is invalid.');
    $folder = $root . '/' . $id;
    if (!is_dir($folder) || is_link($folder)) throw new RuntimeException('Market snapshot is unavailable.');
    $manifestPath = $folder . '/manifest.json';
    $manifest = market_json($manifestPath, 256 * 1024);
    if (!hash_equals($pointer['manifest_sha256'], hash_file('sha256', $manifestPath)) || ($manifest['version'] ?? null) !== 1 || ($manifest['snapshot_id'] ?? null) !== $id
        || !in_array($manifest['mode'] ?? null, ['historical_bootstrap', 'daily'], true)
        || ($manifest['mode'] === 'daily' && ($manifest['capture']['complete'] ?? null) !== true)) throw new RuntimeException('Market manifest is invalid.');
    market_descriptor($manifest['summary_file'] ?? null, '/^summary\.json$/', 2 * 1024 * 1024);
    market_descriptor($manifest['state_file'] ?? null, '/^state\.json(?:\.gz)?$/', ($manifest['state_file']['path'] ?? '') === 'state.json.gz' ? 9 * 1024 * 1024 : 64 * 1024 * 1024);
    if (($manifest['state_file']['path'] ?? '') === 'state.json.gz' && (($manifest['state_file']['encoding'] ?? null) !== 'gzip'
        || !is_int($manifest['state_file']['expanded_bytes'] ?? null) || $manifest['state_file']['expanded_bytes'] < 1 || $manifest['state_file']['expanded_bytes'] > 64 * 1024 * 1024
        || !is_string($manifest['state_file']['expanded_sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $manifest['state_file']['expanded_sha256']))) throw new RuntimeException('Market private state descriptor is invalid.');
    $shards = $manifest['listing_shards'] ?? null;
    if (!is_array($shards) || !array_is_list($shards) || count($shards) < 1 || count($shards) > MARKET_MAX_SHARDS) throw new RuntimeException('Market shard count is invalid.');
    $count = 0;
    $names = [];
    foreach ($shards as $descriptor) {
        market_descriptor($descriptor, '/^listings-[0-9]{3}\.json$/', 256 * 1024);
        if (isset($names[$descriptor['path']]) || !is_int($descriptor['count'] ?? null) || $descriptor['count'] < 0 || $descriptor['count'] > 250) throw new RuntimeException('Market shard is invalid.');
        $names[$descriptor['path']] = true;
        $count += $descriptor['count'];
    }
    if ($count < 1 || $count > MARKET_MAX_LISTINGS || $count !== ($manifest['counts']['listing_count'] ?? null)) throw new RuntimeException('Market totals are invalid.');
    $summary = market_json($folder . '/summary.json', 2 * 1024 * 1024, $manifest['summary_file']);
    if (($summary['snapshot_id'] ?? null) !== $id || ($summary['mode'] ?? null) !== $manifest['mode'] || ($summary['counts']['listing_count'] ?? null) !== $count) throw new RuntimeException('Market summary is inconsistent.');
    return [$folder, $manifest, $summary];
}

function market_source_url($url, string $id): bool {
    if (!is_string($url) || strlen($url) > 1600) return false;
    $parts = parse_url($url);
    if (!is_array($parts) || ($parts['scheme'] ?? '') !== 'https' || ($parts['host'] ?? '') !== 'www.imot.bg'
        || isset($parts['user']) || isset($parts['pass']) || isset($parts['port']) || isset($parts['fragment'])) return false;
    $path = $parts['path'] ?? '';
    if (preg_match('/^\/obiava-([a-z0-9]{6,64})(?:[-\/]|$)/i', $path, $match)) return strtolower($match[1]) === $id && !isset($parts['query']);
    if ($path !== '/pcgi/imot.cgi') return false;
    return ($parts['query'] ?? '') === 'act=5&adv=' . $id;
}

function market_offer($row): array {
    if (!is_array($row) || array_diff(array_keys($row), MARKET_PUBLIC_FIELDS) !== []
        || !is_string($row['id'] ?? null) || !preg_match('/^[a-z0-9]{6,64}$/', $row['id'])
        || !market_source_url($row['url'] ?? null, $row['id'])
        || !in_array($row['vat_basis'] ?? null, ['included', 'excluded', 'unknown'], true)
        || !is_bool($row['historical'] ?? null) || !is_array($row['comparison'] ?? null) || !is_array($row['change'] ?? null)) throw new RuntimeException('Public market offer is invalid.');
    if (isset($row['price_total_derived']) && !is_bool($row['price_total_derived'])) throw new RuntimeException('Market price basis is invalid.');
    if (isset($row['seller_type']) && !in_array($row['seller_type'], ['agency', 'private', 'unknown'], true)) throw new RuntimeException('Market seller type is invalid.');
    if (isset($row['seller_evidence']) && !in_array($row['seller_evidence'], ['agency_profile', 'explicit_private_claim', 'not_reported', 'conflicting_signals'], true)) throw new RuntimeException('Market seller evidence is invalid.');
    if (isset($row['seller_type']) && !in_array(($row['seller_type'] ?? '') . ':' . ($row['seller_evidence'] ?? ''), ['agency:agency_profile', 'private:explicit_private_claim', 'unknown:not_reported', 'unknown:conflicting_signals'], true)) throw new RuntimeException('Market seller evidence contradicts its label.');
    if (!market_optional_text($row['seller_checked_at'] ?? null, 80)) throw new RuntimeException('Market seller date is invalid.');
    market_location($row['location'] ?? null);
    market_analysis($row['analysis'] ?? null);
    market_estimate($row['asking_estimate'] ?? null);
    market_property_features($row['property_features'] ?? null);
    market_agency($row['agency'] ?? null, $row['seller_type'] ?? 'unknown');
    foreach (['area_sqm', 'price_eur', 'eur_per_sqm', 'quoted_eur_per_sqm'] as $key) {
        $value = $row[$key] ?? null;
        if ($value !== null && ((!is_float($value) && !is_int($value)) || !is_finite((float)$value) || $value <= 0 || $value > 1e12)) throw new RuntimeException('Market numeric field is invalid.');
    }
    return $row;
}

function market_filter_string(string $key, int $limit = 80): string {
    $value = $_GET[$key] ?? '';
    if (!is_string($value) || strlen($value) > $limit || !preg_match('//u', $value)) throw new InvalidArgumentException('Invalid market filter.');
    return trim($value);
}

function market_number(string $key, float $maximum): ?float {
    $value = market_filter_string($key, 40);
    if ($value === '') return null;
    if (!preg_match('/^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/', $value)) throw new InvalidArgumentException('Invalid numeric filter.');
    $number = (float)$value;
    if (!is_finite($number) || $number < 0 || $number > $maximum) throw new InvalidArgumentException('Market filter is out of range.');
    return $number;
}

function market_integer(string $key, int $default, int $maximum): int {
    $value = market_filter_string($key, 8);
    if ($value === '') return $default;
    if (!preg_match('/^[0-9]+$/', $value) || (int)$value < 1 || (int)$value > $maximum) throw new InvalidArgumentException('Invalid market page.');
    return (int)$value;
}

function market_listing_filters(array $summary): array {
    $filters = [];
    foreach (['neighborhood' => 'neighborhoods', 'type' => 'types', 'vat' => 'vat_bases'] as $parameter => $dimension) {
        $value = market_filter_string($parameter);
        if ($value !== '' && !in_array($value, array_column($summary['filter_options'][$dimension] ?? [], 'key'), true)) throw new InvalidArgumentException('Unknown market filter.');
        $filters[$parameter] = $value;
    }
    $filters['seller'] = market_filter_string('seller', 20);
    if (!in_array($filters['seller'], ['', 'agency', 'private', 'unknown'], true)) throw new InvalidArgumentException('Invalid seller filter.');
    foreach (['construction_type' => ['brick', 'panel', 'epk', 'monolithic', 'other', 'unknown'], 'furnishing' => ['furnished', 'partial', 'unfurnished', 'unknown'], 'elevator' => ['yes', 'no', 'unknown']] as $field => $values) {
        $filters[$field] = market_filter_string($field, 30);
        if ($filters[$field] !== '' && !in_array($filters[$field], $values, true)) throw new InvalidArgumentException('Invalid property feature filter.');
    }
    $filters['precision'] = market_filter_string('precision', 20);
    if (!in_array($filters['precision'], ['', 'address', 'street', 'neighborhood', 'unknown'], true)) throw new InvalidArgumentException('Invalid location filter.');
    $filters['location_key'] = market_filter_string('location_key', 160);
    if ($filters['location_key'] !== '' && !preg_match('/^[a-zA-Z0-9_.:-]{1,160}$/', $filters['location_key'])) throw new InvalidArgumentException('Invalid reference-area filter.');
    foreach (['min_area', 'max_area'] as $key) $filters[$key] = market_number($key, 100000);
    foreach (['min_price', 'max_price'] as $key) $filters[$key] = market_number($key, 1e10);
    $filters['min_discount'] = market_number('min_discount', 100);
    foreach (['area', 'price'] as $key) if ($filters['min_' . $key] !== null && $filters['max_' . $key] !== null && $filters['min_' . $key] > $filters['max_' . $key]) throw new InvalidArgumentException('Filter minimum exceeds maximum.');
    $filters['deals_only'] = market_filter_string('deals_only', 1);
    if (!in_array($filters['deals_only'], ['', '0', '1'], true)) throw new InvalidArgumentException('Invalid opportunity filter.');
    $filters['daily_only'] = market_filter_string('daily_only', 1);
    if (!in_array($filters['daily_only'], ['', '0', '1'], true)) throw new InvalidArgumentException('Invalid daily-change filter.');
    $filters['include_unknown_vat'] = market_filter_string('include_unknown_vat', 1);
    if (!in_array($filters['include_unknown_vat'], ['', '0', '1'], true)) throw new InvalidArgumentException('Invalid unknown-VAT filter.');
    $filters['change'] = market_filter_string('change', 30);
    if (!in_array($filters['change'], ['', 'new', 'price_drop', 'became_eligible', 'baseline', 'unchanged', 'historical'], true)) throw new InvalidArgumentException('Invalid change filter.');
    $filters['sort'] = market_filter_string('sort', 20) ?: 'discount';
    if (!in_array($filters['sort'], ['discount', 'eur_per_sqm', 'price', 'newest'], true)) throw new InvalidArgumentException('Invalid market sort.');
    $filters['page'] = market_integer('page', 1, MARKET_MAX_LISTINGS);
    $filters['page_size'] = market_integer('page_size', 24, 60);
    return $filters;
}

function market_matches(array $row, array $filters): bool {
    foreach (['neighborhood' => 'neighborhood_key', 'type' => 'type_key', 'vat' => 'vat_basis'] as $parameter => $field) if ($filters[$parameter] !== '' && $row[$field] !== $filters[$parameter]) return false;
    if ($filters['seller'] !== '' && ($row['seller_type'] ?? 'unknown') !== $filters['seller']) return false;
    foreach (['construction_type', 'furnishing', 'elevator'] as $field) if ($filters[$field] !== '' && ($row['property_features'][$field] ?? 'unknown') !== $filters[$field]) return false;
    if ($filters['precision'] !== '' && ($row['location']['precision'] ?? 'unknown') !== $filters['precision']) return false;
    if ($filters['location_key'] !== '' && ($row['location']['key'] ?? '') !== $filters['location_key']) return false;
    foreach (['area' => 'area_sqm', 'price' => 'price_eur'] as $range => $field) {
        if ($filters['min_' . $range] !== null && ($row[$field] === null || $row[$field] < $filters['min_' . $range])) return false;
        if ($filters['max_' . $range] !== null && ($row[$field] === null || $row[$field] > $filters['max_' . $range])) return false;
    }
    $comparison = $row['comparison'];
    if ($filters['deals_only'] === '1' && ($comparison['eligible'] ?? false) !== true) return false;
    if ($filters['daily_only'] === '1') {
        if ($row['historical'] || !in_array($row['change']['kind'] ?? '', ['new', 'price_drop', 'became_eligible'], true)) return false;
        $knownVatCandidate = in_array($row['vat_basis'], ['included', 'excluded'], true) && ($comparison['alert_eligible'] ?? false) === true;
        $unknownVatCandidate = $filters['include_unknown_vat'] === '1' && $row['vat_basis'] === 'unknown'
            && ($comparison['eligible'] ?? false) === true
            && ($row['change']['area_changed'] ?? false) === false
            && ($row['change']['price_basis_changed'] ?? false) === false;
        if (!$knownVatCandidate && !$unknownVatCandidate) return false;
    }
    if ($filters['min_discount'] !== null && (!is_numeric($comparison['below_median_pct'] ?? null) || $comparison['below_median_pct'] < $filters['min_discount'])) return false;
    return $filters['change'] === '' || ($row['change']['kind'] ?? '') === $filters['change'];
}

function market_shard(string $folder, array $descriptor, string $id): array {
    $data = market_json($folder . '/' . $descriptor['path'], 256 * 1024, $descriptor);
    if (($data['snapshot_id'] ?? null) !== $id || !is_array($data['listings'] ?? null) || !array_is_list($data['listings']) || count($data['listings']) !== $descriptor['count']) throw new RuntimeException('Market shard identity is invalid.');
    return $data['listings'];
}

function market_coordinate(string $key, float $minimum, float $maximum): float {
    $raw = market_filter_string($key, 40);
    if ($raw === '' || !preg_match('/^-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/', $raw)) throw new InvalidArgumentException('Invalid map bounds.');
    $value = (float)$raw;
    if (!is_finite($value) || $value < $minimum || $value > $maximum) throw new InvalidArgumentException('Map bounds are out of range.');
    return $value;
}

function market_viewport(string $folder, array $manifest, array $summary, array $filters): void {
    $north = market_coordinate('north', -85, 85);
    $south = market_coordinate('south', -85, 85);
    $west = market_coordinate('west', -180, 180);
    $east = market_coordinate('east', -180, 180);
    if ($north < $south || $east < $west) throw new InvalidArgumentException('Map bounds are reversed.');
    $zoom = market_integer('zoom', 12, 19);
    $groups = [];
    $seen = [];
    $total = 0;
    $located = 0;
    $viewportTotal = 0;
    foreach ($manifest['listing_shards'] as $descriptor) {
        $rows = market_shard($folder, $descriptor, $manifest['snapshot_id']);
        foreach ($rows as $raw) {
            $row = market_offer($raw);
            if (isset($seen[$row['id']])) throw new RuntimeException('Duplicate market offer ID.');
            $seen[$row['id']] = true;
            if (!market_matches($row, $filters)) continue;
            $total++;
            $location = $row['location'] ?? null;
            if ($location === null) continue;
            $located++;
            if ($location['lat'] < $south || $location['lat'] > $north || $location['lng'] < $west || $location['lng'] > $east) continue;
            $viewportTotal++;
            $key = $location['key'];
            if (!isset($groups[$key])) {
                if (count($groups) >= 10000) throw new RuntimeException('Market reference-area limit exceeded.');
                $groups[$key] = ['kind' => 'reference', 'location' => $location, 'lat' => $location['lat'], 'lng' => $location['lng'], 'count' => 0, 'eligible_count' => 0, 'seller_counts' => ['agency' => 0, 'private' => 0, 'unknown' => 0]];
            } else {
                foreach (['lat', 'lng', 'precision', 'label_bg', 'radius_m', 'method', 'source_url', 'reference_date'] as $field) {
                    if (($groups[$key]['location'][$field] ?? null) != ($location[$field] ?? null)) throw new RuntimeException('Market reference-area definitions conflict.');
                }
            }
            $groups[$key]['count']++;
            if (($row['comparison']['eligible'] ?? false) === true) $groups[$key]['eligible_count']++;
            $groups[$key]['seller_counts'][$row['seller_type'] ?? 'unknown']++;
        }
        unset($rows, $raw, $row);
    }
    if (count($seen) !== $manifest['counts']['listing_count']) throw new RuntimeException('Market listing totals are inconsistent.');
    unset($seen);
    // Aggregate reference centers, never inferred property positions. Coarsen as needed;
    // no result truncation and no coordinate jitter for overlapping reference areas.
    $level = min(17, $zoom);
    do {
        $cells = [];
        $scale = (256 * (2 ** $level)) / 100;
        foreach ($groups as $key => $group) {
            $x = (int)floor(($group['lng'] + 180) / 360 * $scale);
            $latitude = max(-85.0, min(85.0, (float)$group['lat'])) * M_PI / 180;
            $y = (int)floor((1 - log(tan($latitude) + 1 / cos($latitude)) / M_PI) / 2 * $scale);
            $cellKey = $x . ':' . $y;
            if (!isset($cells[$cellKey])) $cells[$cellKey] = [];
            $cells[$cellKey][] = $key;
        }
        if (count($cells) <= 800 || $level <= 1) break;
        $level--;
    } while (true);
    $items = [];
    foreach ($cells as $cellKey => $keys) {
        if (count($keys) === 1) { $items[] = $groups[$keys[0]]; continue; }
        $item = ['kind' => 'cluster', 'key' => $level . ':' . $cellKey, 'count' => 0, 'eligible_count' => 0, 'reference_count' => count($keys), 'lat' => 0.0, 'lng' => 0.0,
            'bounds' => ['south' => 85.0, 'north' => -85.0, 'west' => 180.0, 'east' => -180.0], 'precision_counts' => ['address' => 0, 'street' => 0, 'neighborhood' => 0], 'references' => []];
        foreach ($keys as $key) {
            $group = $groups[$key];
            $item['count'] += $group['count'];
            $item['eligible_count'] += $group['eligible_count'];
            $item['lat'] += $group['lat'] * $group['count'];
            $item['lng'] += $group['lng'] * $group['count'];
            $item['bounds']['south'] = min($item['bounds']['south'], $group['lat']);
            $item['bounds']['north'] = max($item['bounds']['north'], $group['lat']);
            $item['bounds']['west'] = min($item['bounds']['west'], $group['lng']);
            $item['bounds']['east'] = max($item['bounds']['east'], $group['lng']);
            $item['precision_counts'][$group['location']['precision']] += $group['count'];
            // Overlapping reference centers remain selectable at maximum zoom.
            // At lower zoom, the cluster's bounds provide the next navigation step.
            if ($zoom >= 17) $item['references'][] = ['key' => $key, 'label_bg' => $group['location']['label_bg'], 'precision' => $group['location']['precision'], 'count' => $group['count']];
        }
        $item['lat'] /= $item['count'];
        $item['lng'] /= $item['count'];
        $items[] = $item;
    }
    market_respond(['snapshot_id' => $summary['snapshot_id'], 'captured_at' => $summary['captured_at'], 'mode' => $summary['mode'], 'total' => $total, 'located_total' => $located,
        'unlocated_total' => $total - $located, 'viewport_total' => $viewportTotal, 'zoom' => $level, 'items' => $items]);
}

try {
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') { header('Allow: GET'); market_respond(['error' => 'method_not_allowed'], 405); }
    [$folder, $manifest, $summary] = market_snapshot();
    $action = market_filter_string('action', 20) ?: 'summary';
    if ($action === 'summary') {
        foreach (array_merge($summary['top_offers'] ?? [], $summary['daily_candidates'] ?? []) as $row) market_offer($row);
        $allowed = ['snapshot_id', 'generated_at', 'captured_at', 'mode', 'coverage', 'counts', 'methodology', 'totals', 'neighborhoods', 'filter_options', 'top_offers', 'daily_candidates', 'daily_candidates_total', 'history'];
        market_respond(array_intersect_key($summary, array_fill_keys($allowed, true)));
    }
    if (!in_array($action, ['listings', 'viewport'], true)) market_respond(['error' => 'unknown_action'], 404);
    $filters = market_listing_filters($summary);
    if ($action === 'viewport') market_viewport($folder, $manifest, $summary, $filters);
    $references = [];
    $seen = [];
    foreach ($manifest['listing_shards'] as $shardIndex => $descriptor) {
        $rows = market_shard($folder, $descriptor, $manifest['snapshot_id']);
        foreach ($rows as $rowIndex => $raw) {
            $row = market_offer($raw);
            if (isset($seen[$row['id']])) throw new RuntimeException('Duplicate market offer ID.');
            $seen[$row['id']] = true;
            if (!market_matches($row, $filters)) continue;
            // Retain only a compact sort/reference tuple, never 50k full offers.
            $sort = $filters['sort'];
            $rank = $sort === 'discount' ? ($row['comparison']['below_median_pct'] ?? -PHP_FLOAT_MAX)
                : ($sort === 'newest' ? ($row['first_seen_at'] ?? $row['last_modified_at'] ?? '') : ($row[$sort === 'price' ? 'price_eur' : 'eur_per_sqm'] ?? PHP_FLOAT_MAX));
            $references[] = [$rank, $row['id'], $shardIndex, $rowIndex];
        }
        unset($rows, $raw, $row);
    }
    if (count($seen) !== $manifest['counts']['listing_count']) throw new RuntimeException('Market listing totals are inconsistent.');
    unset($seen);
    $descending = in_array($filters['sort'], ['discount', 'newest'], true);
    usort($references, static function (array $left, array $right) use ($descending): int { return ($descending ? $right[0] <=> $left[0] : $left[0] <=> $right[0]) ?: strcmp($left[1], $right[1]); });
    $total = count($references);
    $pages = max(1, (int)ceil($total / $filters['page_size']));
    $page = min($filters['page'], $pages);
    $selected = array_slice($references, ($page - 1) * $filters['page_size'], $filters['page_size']);
    unset($references);
    $wanted = [];
    foreach ($selected as $position => $reference) $wanted[$reference[2]][$reference[3]] = $position;
    $items = [];
    foreach ($wanted as $shardIndex => $positions) {
        $rows = market_shard($folder, $manifest['listing_shards'][$shardIndex], $manifest['snapshot_id']);
        foreach ($positions as $rowIndex => $position) {
            $row = market_offer($rows[$rowIndex]);
            if ($row['id'] !== $selected[$position][1]) throw new RuntimeException('Market result reference is inconsistent.');
            $items[$position] = $row;
        }
    }
    ksort($items);
    market_respond(['snapshot_id' => $summary['snapshot_id'], 'items' => array_values($items), 'total' => $total, 'page' => $page, 'pages' => $pages, 'page_size' => $filters['page_size'], 'captured_at' => $summary['captured_at'], 'mode' => $summary['mode']]);
} catch (InvalidArgumentException $error) {
    market_respond(['error' => 'invalid_filter', 'message' => $error->getMessage()], 400);
} catch (Throwable $error) {
    error_log('Sofia market API: ' . $error->getMessage());
    market_respond(['error' => 'market_unavailable'], 503);
}
