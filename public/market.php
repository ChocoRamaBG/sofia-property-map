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
const MARKET_MAX_SHARDS = 256;
const MARKET_PUBLIC_FIELDS = ['id', 'url', 'neighborhood_key', 'neighborhood_bg', 'type_key', 'type_bg', 'area_sqm', 'price_eur', 'eur_per_sqm', 'price_currency', 'vat_basis', 'construction_year', 'construction_cohort', 'last_modified_at', 'observed_at', 'first_seen_at', 'comparison', 'change', 'historical', 'quality_flags', 'floor_bg', 'construction_label_bg', 'address_bg', 'price_total_derived', 'quoted_eur_per_sqm'];

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
    foreach (['min_area', 'max_area'] as $key) $filters[$key] = market_number($key, 100000);
    foreach (['min_price', 'max_price'] as $key) $filters[$key] = market_number($key, 1e10);
    $filters['min_discount'] = market_number('min_discount', 100);
    foreach (['area', 'price'] as $key) if ($filters['min_' . $key] !== null && $filters['max_' . $key] !== null && $filters['min_' . $key] > $filters['max_' . $key]) throw new InvalidArgumentException('Filter minimum exceeds maximum.');
    $filters['deals_only'] = market_filter_string('deals_only', 1);
    if (!in_array($filters['deals_only'], ['', '0', '1'], true)) throw new InvalidArgumentException('Invalid opportunity filter.');
    $filters['daily_only'] = market_filter_string('daily_only', 1);
    if (!in_array($filters['daily_only'], ['', '0', '1'], true)) throw new InvalidArgumentException('Invalid daily-change filter.');
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
    foreach (['area' => 'area_sqm', 'price' => 'price_eur'] as $range => $field) {
        if ($filters['min_' . $range] !== null && ($row[$field] === null || $row[$field] < $filters['min_' . $range])) return false;
        if ($filters['max_' . $range] !== null && ($row[$field] === null || $row[$field] > $filters['max_' . $range])) return false;
    }
    $comparison = $row['comparison'];
    if ($filters['deals_only'] === '1' && ($comparison['eligible'] ?? false) !== true) return false;
    if ($filters['daily_only'] === '1' && ($row['historical'] || ($comparison['alert_eligible'] ?? false) !== true
        || !in_array($row['vat_basis'], ['included', 'excluded'], true)
        || !in_array($row['change']['kind'] ?? '', ['new', 'price_drop', 'became_eligible'], true))) return false;
    if ($filters['min_discount'] !== null && (!is_numeric($comparison['below_median_pct'] ?? null) || $comparison['below_median_pct'] < $filters['min_discount'])) return false;
    return $filters['change'] === '' || ($row['change']['kind'] ?? '') === $filters['change'];
}

function market_shard(string $folder, array $descriptor, string $id): array {
    $data = market_json($folder . '/' . $descriptor['path'], 256 * 1024, $descriptor);
    if (($data['snapshot_id'] ?? null) !== $id || !is_array($data['listings'] ?? null) || !array_is_list($data['listings']) || count($data['listings']) !== $descriptor['count']) throw new RuntimeException('Market shard identity is invalid.');
    return $data['listings'];
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
    if ($action !== 'listings') market_respond(['error' => 'unknown_action'], 404);
    $filters = market_listing_filters($summary);
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
