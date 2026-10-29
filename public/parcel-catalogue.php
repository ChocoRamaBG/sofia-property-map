<?php
declare(strict_types=1);

// Immutable official parcel identities and display points. No database writes.
function parcel_catalogue_available(?array $snapshot): bool {
    return $snapshot !== null && ($snapshot['version'] ?? null) === 2;
}

function load_parcel_catalogue_snapshot(): ?array {
    $path = __DIR__ . '/private/boundaries-active.json';
    if (!file_exists($path) && !is_link($path)) return null;
    $manifest = bounded_registry_json($path, 256 * 1024);
    if (($manifest['version'] ?? null) === 1) return null;
    if (($manifest['version'] ?? null) !== 2) throw new RuntimeException('Official parcel catalogue version is invalid.');
    return load_boundary_snapshot();
}

function parcel_catalogue_metadata(?array $snapshot): array {
    if (!parcel_catalogue_available($snapshot)) return ['available' => false, 'source_url' => CADASTRE_CATALOGUE_URL];
    return ['available' => true, 'scope' => 'sofia_68134_land_parcels', 'snapshot_id' => $snapshot['snapshot_id'], 'captured_at' => $snapshot['captured_at'],
        'source_url' => CADASTRE_CATALOGUE_URL, 'catalogue_count' => $snapshot['catalogue_count'],
        'mapped_point_count' => $snapshot['mapped_point_count'], 'unmapped_point_count' => $snapshot['unmapped_point_count'],
        'point_method' => $snapshot['point_method']];
}

function parcel_catalogue_source(array $snapshot, ?array $entry = null): array {
    $source = $entry === null ? null : ($snapshot['sources'][$entry['source_index']] ?? null);
    return ['source_url' => CADASTRE_CATALOGUE_URL, 'scope' => 'sofia_68134_land_parcels', 'snapshot_id' => $snapshot['snapshot_id'],
        'captured_at' => $snapshot['captured_at'], 'point_method' => $snapshot['point_method'],
        'district_source_url' => $source['source_url'] ?? null, 'district' => $source['label_bg'] ?? null,
        'certified_survey' => false];
}

function parcel_catalogue_iterator(array $snapshot): Generator {
    if (!parcel_catalogue_available($snapshot)) throw new RuntimeException('Official parcel catalogue is unavailable.');
    $descriptor = $snapshot['catalogue'];
    $handle = fopen(boundary_file($snapshot, $descriptor), 'rb');
    if ($handle === false) throw new RuntimeException('Parcel catalogue cannot be read.');
    $hash = hash_init('sha256'); $bytes = 0; $rows = 0; $mapped = 0; $previous = null;
    $sourceCounts = array_fill(0, 24, 0);
    try {
        while (($line = fgets($handle, 256)) !== false) {
            $bytes += strlen($line); hash_update($hash, $line);
            if ($bytes > $descriptor['bytes'] || substr($line, -1) !== "\n") throw new RuntimeException('Parcel catalogue row exceeds its bounds.');
            $parts = explode("\t", substr($line, 0, -1));
            if (count($parts) !== 5 || !boundary_id_valid($parts[0]) || ($previous !== null && strcmp($previous, $parts[0]) >= 0)
                || !preg_match('/^(?:[0-9]|1[0-9]|2[0-3])$/', $parts[3]) || !isset($snapshot['sources'][(int)$parts[3]])
                || !in_array($parts[4], ['mapped', 'unavailable'], true)) throw new RuntimeException('Parcel catalogue row is invalid.');
            $lat = null; $lng = null;
            if ($parts[4] === 'mapped') {
                if (!preg_match('/^[0-9]{2}\.[0-9]{7}$/', $parts[1]) || !preg_match('/^[0-9]{2}\.[0-9]{7}$/', $parts[2])) throw new RuntimeException('Parcel catalogue coordinates are invalid.');
                $lat = (float)$parts[1]; $lng = (float)$parts[2];
                if (!boundary_number($lat, 40, 45) || !boundary_number($lng, 21, 30)) throw new RuntimeException('Parcel catalogue coordinates are outside their bounds.');
                $mapped++;
            } elseif ($parts[1] !== '' || $parts[2] !== '') throw new RuntimeException('Unmapped parcel has fabricated coordinates.');
            $rows++; $previous = $parts[0]; $sourceCounts[(int)$parts[3]]++;
            if ($rows > $descriptor['rows']) throw new RuntimeException('Parcel catalogue contains too many rows.');
            yield ['cadastral_id' => $parts[0], 'lat' => $lat, 'lng' => $lng, 'source_index' => (int)$parts[3], 'status' => $parts[4]];
        }
        if (!feof($handle) || $bytes !== $descriptor['bytes'] || $rows !== $snapshot['catalogue_count']
            || $rows !== $descriptor['rows'] || $mapped !== $snapshot['mapped_point_count']
            || $rows - $mapped !== $snapshot['unmapped_point_count'] || !hash_equals($descriptor['sha256'], hash_final($hash))) throw new RuntimeException('Parcel catalogue integrity verification failed.');
        foreach ($sourceCounts as $position => $count) if ($count > $snapshot['sources'][$position]['record_count']) throw new RuntimeException('Parcel catalogue source references exceed the capture records.');
    } finally { fclose($handle); }
}

function parcel_catalogue_entry(array $snapshot, string $id): ?array {
    $found = null;
    foreach (parcel_catalogue_iterator($snapshot) as $entry) if ($entry['cadastral_id'] === $id) $found = $entry;
    return $found;
}

function parcel_catalogue_database_flags(PDO $pdo): array {
    static $cache = [];
    $key = spl_object_id($pdo);
    if (isset($cache[$key])) return $cache[$key];
    $query = $pdo->query("SELECT parcel_cadastral_id AS cadastral_id, COUNT(*) AS document_count,
        MAX(source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy')) AS has_exploitation_certificate,
        MAX(source_code = 'building_permits') AS has_building_permit,
        MAX(source_code = 'projecting_visas') AS has_projecting_visa FROM parcel_documents GROUP BY parcel_cadastral_id");
    $flags = [];
    while ($row = $query->fetch(PDO::FETCH_ASSOC)) {
        if (count($flags) >= CADASTRE_MAX_PARCELS) throw new RuntimeException('Database document flags exceed their bound.');
        $id = $row['cadastral_id']; unset($row['cadastral_id']); $flags[$id] = $row;
    }
    return $cache[$key] = $flags;
}

function parcel_catalogue_flags(PDO $pdo, ?array $registry): array {
    return $registry['flags'] ?? parcel_catalogue_database_flags($pdo);
}

function parcel_catalogue_document_match(string $id, ?array $registry, array $flags, array $filter): bool {
    if ($registry !== null) return registry_id_matches_filter($id, $registry, $filter);
    if ($filter['advanced']) throw new FilterUnavailableException('Advanced document filters require the registry snapshot.');
    if ($filter['record_types'] === []) return true;
    $row = $flags[$id] ?? empty_document_flags();
    if ($filter['record_types'] === ['no_records']) return (int)$row['document_count'] === 0;
    $present = [];
    foreach (['building_permits' => 'has_building_permit', 'projecting_visas' => 'has_projecting_visa', 'exploitation_certificates' => 'has_exploitation_certificate'] as $type => $key) if (!empty($row[$key])) $present[$type] = true;
    return qualifying_types_match($present, $filter);
}

function parcel_catalogue_plot(array $row, array $snapshot, array $flags, bool $current = true): array {
    $status = $current ? 'current' : (boundary_id_valid($row['cadastral_id']) ? 'not_in_latest_snapshot' : 'unavailable');
    return serialize_plot($row + ($flags[$row['cadastral_id']] ?? empty_document_flags()))
        + ['catalogue_status' => $status, 'catalogue_source' => parcel_catalogue_source($snapshot, $current ? $row : null),
            'coordinate_method' => $current && $row['lat'] !== null ? 'official_geometry_interior' : ($current ? 'unavailable' : 'historical_coordinate_workbook')];
}

function parcel_catalogue_candidates(array $snapshot, ?array $bounds = null, bool $mappedOnly = false): array {
    $ids = [];
    foreach (parcel_catalogue_iterator($snapshot) as $entry) {
        if (($mappedOnly || $bounds !== null) && $entry['lat'] === null) continue;
        if ($bounds !== null && ($entry['lat'] < $bounds['south'] || $entry['lat'] > $bounds['north'] || $entry['lng'] < $bounds['west'] || $entry['lng'] > $bounds['east'])) continue;
        $ids[$entry['cadastral_id']] = true;
    }
    return $ids;
}

function parcel_catalogue_filter_ids(PDO $pdo, ?array $registry, ?array $cadastre, array $filter, array $ids, ?array $flags = null): array {
    $exact = keyword_exact_ids($filter['search_terms']);
    $exactOnly = $exact !== [] && ($filter['search_match'] === 'all' || count($exact) === count($filter['search_terms']));
    if ($exactOnly) {
        if ($filter['search_match'] === 'all' && count($exact) > 1) return [];
        $ids = array_intersect_key($ids, $exact);
    }
    $flags = $flags ?? parcel_catalogue_flags($pdo, $registry);
    foreach ($ids as $id => $_) if (!parcel_catalogue_document_match($id, $registry, $flags, $filter)) unset($ids[$id]);
    if ($filter['cadastre_active']) $ids = cadastre_matching_ids($cadastre, $ids, $filter);
    return keyword_matching_ids($pdo, $registry, $cadastre, $ids, $filter);
}

function parcel_catalogue_viewport(PDO $pdo, array $snapshot, ?array $registry, ?array $cadastre, array $filter): array {
    $view = ['north' => number_param('north', -90, 90), 'south' => number_param('south', -90, 90), 'east' => number_param('east', -180, 180), 'west' => number_param('west', -180, 180)];
    $zoom = (int)max(0, min(22, (float)($_GET['zoom'] ?? 13)));
    if ($view['north'] <= $view['south'] || $view['east'] <= $view['west']) return ['items' => [], 'total' => 0, 'truncated' => false];
    $flags = parcel_catalogue_flags($pdo, $registry);
    $ids = parcel_catalogue_filter_ids($pdo, $registry, $cadastre, $filter, parcel_catalogue_candidates($snapshot, $view, true), $flags);
    $total = count($ids); $points = []; $cells = []; $clusterZoom = $zoom;
    $showPoints = $zoom >= 17 && $total <= 1800;
    foreach (parcel_catalogue_iterator($snapshot) as $entry) {
        if (!isset($ids[$entry['cadastral_id']])) continue;
        if ($showPoints) { $points[] = ['kind' => 'plot'] + parcel_catalogue_plot($entry, $snapshot, $flags); continue; }
        $world = 1 << ($clusterZoom + 1);
        $gx = (int)max(0, min($world - 1, floor(($entry['lng'] + 180) / 360 * $world)));
        $latitude = deg2rad(max(-85.05112878, min(85.05112878, $entry['lat'])));
        $gy = (int)max(0, min($world - 1, floor((1 - log(tan($latitude) + 1 / cos($latitude)) / M_PI) / 2 * $world)));
        $key = $gy . ':' . $gx;
        $cell = ['gx' => $gx, 'gy' => $gy, 'lat_sum' => $entry['lat'], 'lng_sum' => $entry['lng'], 'count' => 1,
            'certificate_count' => !empty($flags[$entry['cadastral_id']]['has_exploitation_certificate']) ? 1 : 0,
            'south' => $entry['lat'], 'north' => $entry['lat'], 'west' => $entry['lng'], 'east' => $entry['lng']];
        parcel_catalogue_merge_cell($cells, $key, $cell);
        while (count($cells) > 1800 && $clusterZoom > 0) {
            $parents = []; $clusterZoom--;
            foreach ($cells as $cell) { $cell['gx'] = intdiv($cell['gx'], 2); $cell['gy'] = intdiv($cell['gy'], 2); parcel_catalogue_merge_cell($parents, $cell['gy'] . ':' . $cell['gx'], $cell); }
            $cells = $parents;
        }
    }
    if ($showPoints) return ['items' => $points, 'total' => $total, 'truncated' => false];
    usort($cells, static function ($a, $b) { return ($b['count'] <=> $a['count']) ?: ($a['gy'] <=> $b['gy']) ?: ($a['gx'] <=> $b['gx']); });
    $items = [];
    foreach ($cells as $cell) $items[] = ['kind' => 'cluster', 'cell_key' => $clusterZoom . ':' . $cell['gx'] . ':' . $cell['gy'],
        'lat' => $cell['lat_sum'] / $cell['count'], 'lng' => $cell['lng_sum'] / $cell['count'], 'count' => $cell['count'], 'certificate_count' => $cell['certificate_count'],
        'bounds' => ['south' => $cell['south'], 'north' => $cell['north'], 'west' => $cell['west'], 'east' => $cell['east']], 'zoom' => $zoom, 'cluster_zoom' => $clusterZoom];
    return ['items' => $items, 'total' => $total, 'truncated' => false, 'requested_zoom' => $zoom, 'cluster_zoom' => $clusterZoom];
}

function parcel_catalogue_merge_cell(array &$cells, string $key, array $cell): void {
    if (!isset($cells[$key])) { $cells[$key] = $cell; return; }
    foreach (['lat_sum', 'lng_sum', 'count', 'certificate_count'] as $field) $cells[$key][$field] += $cell[$field];
    foreach (['south', 'west'] as $field) $cells[$key][$field] = min($cells[$key][$field], $cell[$field]);
    foreach (['north', 'east'] as $field) $cells[$key][$field] = max($cells[$key][$field], $cell[$field]);
}

function parcel_catalogue_search(PDO $pdo, array $snapshot, ?array $registry, ?array $cadastre, array $filter): array {
    $empty = ['items' => [], 'total' => 0, 'mapped_total' => 0, 'unmapped_total' => 0, 'truncated' => false, 'bounds' => null];
    if (!$filter['search_active']) return $empty;
    $flags = parcel_catalogue_flags($pdo, $registry);
    $current = parcel_catalogue_candidates($snapshot);
    $history = []; $exact = keyword_exact_ids($filter['search_terms']);
    foreach ($exact as $id => $_) {
        if (isset($current[$id])) continue;
        $query = $pdo->prepare('SELECT cadastral_id, latitude AS lat, longitude AS lng FROM parcels WHERE cadastral_id = :id LIMIT 1');
        $query->execute(['id' => $id]); $old = $query->fetch();
        if ($old || isset($registry['by_id'][$id])) $history[$id] = ['cadastral_id' => $id, 'lat' => null, 'lng' => null];
    }
    $ids = parcel_catalogue_filter_ids($pdo, $registry, $cadastre, $filter, $current + array_fill_keys(array_keys($history), true), $flags);
    unset($current);
    $rows = []; $exactRows = []; $mapped = 0; $bounds = null;
    foreach (parcel_catalogue_iterator($snapshot) as $entry) {
        $id = $entry['cadastral_id']; if (!isset($ids[$id])) continue;
        if ($entry['lat'] !== null) {
            $mapped++;
            if ($bounds === null) $bounds = ['south' => $entry['lat'], 'north' => $entry['lat'], 'west' => $entry['lng'], 'east' => $entry['lng']];
            else { $bounds['south'] = min($bounds['south'], $entry['lat']); $bounds['north'] = max($bounds['north'], $entry['lat']); $bounds['west'] = min($bounds['west'], $entry['lng']); $bounds['east'] = max($bounds['east'], $entry['lng']); }
        }
        if (isset($exact[$id])) $exactRows[$id] = parcel_catalogue_plot($entry, $snapshot, $flags);
        elseif (count($rows) < 40) $rows[$id] = parcel_catalogue_plot($entry, $snapshot, $flags);
    }
    foreach ($history as $id => $row) if (isset($ids[$id])) $exactRows[$id] = parcel_catalogue_plot($row, $snapshot, $flags, false);
    $items = array_slice(array_values($exactRows + $rows), 0, 40);
    foreach ($items as &$row) { $row['primary'] = $row['cadastral_id']; $row['secondary'] = $row['document_count'] . ' linked register records'; } unset($row);
    return ['items' => $items, 'total' => count($ids), 'mapped_total' => $mapped, 'unmapped_total' => count($ids) - $mapped, 'truncated' => count($ids) > count($items), 'bounds' => $bounds];
}

function parcel_catalogue_meta_counts(PDO $pdo, array $snapshot, ?array $registry): array {
    $flags = parcel_catalogue_flags($pdo, $registry); $bySource = ['building_permits' => 0, 'projecting_visas' => 0, 'exploitation_certificates' => 0, 'exploitation_certificates_legacy' => 0]; $certificates = 0;
    $sourceIds = $registry['source_ids'] ?? [];
    if ($registry === null) {
        $query = $pdo->query('SELECT parcel_cadastral_id, source_code FROM parcel_documents GROUP BY parcel_cadastral_id, source_code');
        $rows = 0;
        while ($row = $query->fetch(PDO::FETCH_ASSOC)) {
            if (++$rows > CADASTRE_MAX_PARCELS * 4) throw new RuntimeException('Database source identifiers exceed their bound.');
            if (isset($bySource[$row['source_code']])) $sourceIds[$row['source_code']][$row['parcel_cadastral_id']] = true;
        }
    }
    foreach (parcel_catalogue_iterator($snapshot) as $entry) {
        if ($entry['lat'] === null) continue;
        $id = $entry['cadastral_id'];
        if (!empty($flags[$id]['has_exploitation_certificate'])) $certificates++;
        foreach ($bySource as $code => $_) if (isset($sourceIds[$code][$id])) $bySource[$code]++;
    }
    return ['plots' => $snapshot['mapped_point_count'], 'plots_by_source' => $bySource, 'plots_with_exploitation_certificate' => $certificates];
}
