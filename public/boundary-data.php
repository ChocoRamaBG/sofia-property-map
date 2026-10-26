<?php
declare(strict_types=1);

// Read-only, exact-ID parcel geometry. All coordinates are retained from the
// validated official geometry export; point markers never become polygons.
const BOUNDARY_MAX_FILE_BYTES = 10000000;
const BOUNDARY_MAX_DATASET_BYTES = 256 * 1024 * 1024;
const BOUNDARY_MAX_PARCELS = 500000;
const BOUNDARY_MAX_SHARDS = 1024;
const BOUNDARY_MAX_FEATURE_VERTICES = 200000;
const BOUNDARY_MAX_DATASET_VERTICES = 10000000;
const BOUNDARY_MIN_ZOOM = 16;
const BOUNDARY_MAX_FEATURES = 600;
const BOUNDARY_MAX_VIEW_VERTICES = 100000;
const BOUNDARY_MAX_RESPONSE_BYTES = 3 * 1024 * 1024;
const BOUNDARY_MAX_VIEW_SHARD_BYTES = 16 * 1024 * 1024;
const BOUNDARY_MAX_CANDIDATES = 10000;

function boundary_id_valid($value): bool {
    return is_string($value) && preg_match('/^68134\.[0-9]{1,6}\.[0-9]{1,6}$/', $value) === 1;
}

function boundary_number($value, float $minimum, float $maximum): bool {
    return (is_int($value) || is_float($value)) && is_finite((float)$value) && $value >= $minimum && $value <= $maximum;
}

function boundary_bbox_valid($bbox): bool {
    return snapshot_list($bbox) && count($bbox) === 4
        && boundary_number($bbox[0], 21, 30) && boundary_number($bbox[2], 21, 30)
        && boundary_number($bbox[1], 40, 45) && boundary_number($bbox[3], 40, 45)
        && $bbox[0] < $bbox[2] && $bbox[1] < $bbox[3];
}

function boundary_contains(array $outer, array $inner, float $tolerance = 0.00000011): bool {
    return $inner[0] >= $outer[0] - $tolerance && $inner[1] >= $outer[1] - $tolerance
        && $inner[2] <= $outer[2] + $tolerance && $inner[3] <= $outer[3] + $tolerance;
}

function boundary_intersects(array $bbox, array $view): bool {
    return $bbox[0] <= $view['east'] && $bbox[2] >= $view['west']
        && $bbox[1] <= $view['north'] && $bbox[3] >= $view['south'];
}

function boundary_descriptor($descriptor, string $pattern, int $maximum, string $countKey, bool $empty = false): void {
    if (!is_array($descriptor) || !is_string($descriptor['file'] ?? null) || !preg_match($pattern, $descriptor['file'])
        || !is_int($descriptor['bytes'] ?? null) || $descriptor['bytes'] < ($empty ? 0 : 1) || $descriptor['bytes'] > $maximum
        || !is_string($descriptor['sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $descriptor['sha256'])
        || !is_int($descriptor[$countKey] ?? null) || $descriptor[$countKey] < ($empty ? 0 : 1) || $descriptor[$countKey] > BOUNDARY_MAX_PARCELS) {
        throw new RuntimeException('Boundary file descriptor is invalid.');
    }
    if (($descriptor['bytes'] === 0) !== ($descriptor[$countKey] === 0)) throw new RuntimeException('Boundary empty file metadata is inconsistent.');
}

function boundary_file(array $snapshot, array $descriptor): string {
    $path = $snapshot['directory'] . '/' . $descriptor['file'];
    if (!is_file($path) || is_link($path) || filesize($path) !== $descriptor['bytes']) throw new RuntimeException('Boundary snapshot file is unavailable.');
    return $path;
}

function load_boundary_snapshot(): ?array {
    $active = __DIR__ . '/private/boundaries-active.json';
    if (!file_exists($active) && !is_link($active)) return null;
    $data = bounded_registry_json($active, 256 * 1024);
    if (($data['version'] ?? null) !== 1 || ($data['reference_format'] ?? null) !== 'boundary-bbox-geojson-v1'
        || !is_string($data['snapshot_id'] ?? null) || !preg_match('/^[a-f0-9]{32}$/', $data['snapshot_id'])
        || !snapshot_timestamp_valid($data['generated_at'] ?? null) || !snapshot_timestamp_valid($data['captured_at'] ?? null)
        || ($data['crs'] ?? null) !== 'EPSG:4326' || ($data['native_crs'] ?? null) !== 'EPSG:7801' || ($data['coordinate_precision'] ?? null) !== 7
        || ($data['index_precision'] ?? null) !== 6 || ($data['completion']['status'] ?? null) !== 'complete'
        || ($data['completion']['source_count'] ?? null) !== 24 || ($data['min_zoom'] ?? null) !== BOUNDARY_MIN_ZOOM
        || ($data['source_url'] ?? null) !== CADASTRE_CATALOGUE_URL
        || !is_int($data['parcel_count'] ?? null) || $data['parcel_count'] < 1 || $data['parcel_count'] > BOUNDARY_MAX_PARCELS
        || ($data['feature_count'] ?? null) !== $data['parcel_count']
        || !is_int($data['record_count'] ?? null) || $data['record_count'] < $data['parcel_count'] || $data['record_count'] > BOUNDARY_MAX_PARCELS
        || ($data['completion']['record_count'] ?? null) !== $data['record_count']
        || !is_int($data['ambiguous_parcel_count'] ?? null) || $data['ambiguous_parcel_count'] < 0 || $data['ambiguous_parcel_count'] > $data['record_count']
        || !snapshot_string($data['geometry_method'] ?? null, 200) || !snapshot_string($data['native_crs'] ?? null, 100)
        || !boundary_number($data['transform_accuracy_m'] ?? null, 0, 100)) throw new RuntimeException('Boundary manifest is invalid or incomplete.');
    $root = __DIR__ . '/private/boundary-snapshots';
    $data['directory'] = $root . '/' . $data['snapshot_id'];
    if (is_link($root) || is_link($data['directory']) || !is_dir($data['directory'])) throw new RuntimeException('Boundary snapshot directory is unavailable.');
    $immutable = bounded_registry_json($data['directory'] . '/manifest.json', 256 * 1024);
    $activeCopy = $data; unset($activeCopy['directory']);
    if ($immutable !== $activeCopy) throw new RuntimeException('Boundary active and immutable manifests differ.');
    boundary_descriptor($data['index'] ?? null, '/^boundaries\.tsv$/', BOUNDARY_MAX_FILE_BYTES, 'rows');
    if ($data['index']['rows'] !== $data['parcel_count']) throw new RuntimeException('Boundary index total is inconsistent.');
    boundary_descriptor($data['ambiguous_index'] ?? null, '/^ambiguous\.tsv$/', BOUNDARY_MAX_FILE_BYTES, 'rows', true);
    if ($data['ambiguous_index']['rows'] !== $data['ambiguous_parcel_count']) throw new RuntimeException('Boundary exclusions are inconsistent.');
    if (!snapshot_list($data['sources'] ?? null) || count($data['sources']) !== 24) throw new RuntimeException('Boundary sources are incomplete.');
    $sourceLookup = []; $sourceRecords = 0;
    foreach ($data['sources'] as $source) {
        if (!is_array($source) || !is_string($source['key'] ?? null) || !preg_match('/^sofia-district-(?:0[0-9]|1[0-9]|2[0-3])$/', $source['key'])
            || isset($sourceLookup[$source['key']]) || !snapshot_string($source['label_bg'] ?? null, 190)
            || !cadastre_source_url_valid($source['source_url'] ?? null) || !snapshot_timestamp_valid($source['captured_at'] ?? null)
            || !is_string($source['archive_sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $source['archive_sha256'])
            || !is_string($source['projection_sha256'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $source['projection_sha256'])
            || !is_int($source['record_count'] ?? null) || $source['record_count'] < 0 || $source['record_count'] > BOUNDARY_MAX_PARCELS) throw new RuntimeException('Boundary source metadata is invalid.');
        $sourceLookup[$source['key']] = $source;
        $sourceRecords += $source['record_count'];
    }
    if ($sourceRecords !== $data['record_count']) throw new RuntimeException('Boundary source record totals are inconsistent.');
    if (!snapshot_list($data['shards'] ?? null) || count($data['shards']) < 1 || count($data['shards']) > BOUNDARY_MAX_SHARDS) throw new RuntimeException('Boundary shards are invalid.');
    $records = 0; $vertices = 0; $bytes = $data['index']['bytes'] + $data['ambiguous_index']['bytes'];
    foreach ($data['shards'] as $position => $shard) {
        boundary_descriptor($shard, '/^boundaries-[0-9]{4}\.json$/', 1024 * 1024, 'feature_count');
        if ($shard['file'] !== sprintf('boundaries-%04d.json', $position) || !boundary_bbox_valid($shard['bounds'] ?? null)
            || !is_int($shard['vertex_count'] ?? null) || $shard['vertex_count'] < $shard['feature_count'] * 4 || $shard['vertex_count'] > BOUNDARY_MAX_DATASET_VERTICES) throw new RuntimeException('Boundary shard metadata is invalid.');
        $records += $shard['feature_count']; $vertices += $shard['vertex_count']; $bytes += $shard['bytes'];
        boundary_file($data, $shard);
    }
    if ($records !== $data['parcel_count'] || ($data['vertex_count'] ?? null) !== $vertices
        || $vertices > BOUNDARY_MAX_DATASET_VERTICES || $bytes > BOUNDARY_MAX_DATASET_BYTES) throw new RuntimeException('Boundary dataset totals exceed their bounds.');
    boundary_file($data, $data['index']); boundary_file($data, $data['ambiguous_index']);
    $data['source_lookup'] = $sourceLookup;
    return $data;
}

function boundary_public_source(?array $snapshot, ?string $key = null): array {
    $source = $key === null ? null : ($snapshot['source_lookup'][$key] ?? null);
    return ['label_bg' => $source['label_bg'] ?? 'АГКК — кадастрални граници на поземлени имоти',
        'label_en' => 'AGCC cadastral land-parcel geometry', 'url' => $source['source_url'] ?? CADASTRE_CATALOGUE_URL,
        'captured_at' => $source['captured_at'] ?? ($snapshot['captured_at'] ?? null),
        'coordinate_crs' => 'EPSG:4326', 'native_crs' => $snapshot['native_crs'] ?? null,
        'transform_accuracy_m' => $snapshot['transform_accuracy_m'] ?? null, 'coordinate_precision' => 7,
        'geometry_method' => $snapshot['geometry_method'] ?? null, 'certified_survey' => false];
}

function boundary_metadata(): array {
    try {
        $snapshot = load_boundary_snapshot();
        return ['available' => $snapshot !== null, 'status' => $snapshot === null ? 'unavailable' : 'available',
            'min_zoom' => BOUNDARY_MIN_ZOOM, 'max_features' => BOUNDARY_MAX_FEATURES,
            'captured_at' => $snapshot['captured_at'] ?? null, 'generated_at' => $snapshot['generated_at'] ?? null,
            'parcel_count' => $snapshot['parcel_count'] ?? 0, 'unusable_parcel_count' => $snapshot['ambiguous_parcel_count'] ?? 0,
            'source_url' => CADASTRE_CATALOGUE_URL, 'source' => boundary_public_source($snapshot),
            'scope' => 'exact_id_mapped_parcels', 'dimension_method' => 'published_AREA_and_PERIM_snapshot'];
    } catch (Throwable $error) {
        error_log('Sofia boundary metadata error: ' . $error->getMessage());
        return ['available' => false, 'status' => 'unavailable', 'reason' => 'invalid_snapshot', 'min_zoom' => BOUNDARY_MIN_ZOOM, 'source_url' => CADASTRE_CATALOGUE_URL];
    }
}

function boundary_index_iterator(array $snapshot): Generator {
    $descriptor = $snapshot['index']; $path = boundary_file($snapshot, $descriptor);
    $handle = fopen($path, 'rb'); if ($handle === false) throw new RuntimeException('Boundary index cannot be read.');
    $hash = hash_init('sha256'); $bytes = 0; $rows = 0; $previous = null;
    $shardCounts = array_fill(0, count($snapshot['shards']), 0);
    try {
        while (($line = fgets($handle, 512)) !== false) {
            $bytes += strlen($line); hash_update($hash, $line);
            if ($bytes > $descriptor['bytes'] || strlen($line) > 256 || substr($line, -1) !== "\n") throw new RuntimeException('Boundary index row is invalid.');
            $parts = explode("\t", substr($line, 0, -1));
            if (count($parts) !== 6 || !boundary_id_valid($parts[0]) || ($previous !== null && strcmp($previous, $parts[0]) >= 0)
                || !preg_match('/^(?:0|[1-9][0-9]{0,3})$/', $parts[5])) throw new RuntimeException('Boundary index reference is invalid.');
            foreach (array_slice($parts, 1, 4) as $coordinate) if (!preg_match('/^[0-9]+(?:\.[0-9]{1,6})?$/', $coordinate)) throw new RuntimeException('Boundary index bounds are invalid.');
            $bbox = [(float)$parts[3], (float)$parts[1], (float)$parts[4], (float)$parts[2]];
            $shard = (int)$parts[5];
            if (!isset($snapshot['shards'][$shard]) || !boundary_bbox_valid($bbox) || !boundary_contains($snapshot['shards'][$shard]['bounds'], $bbox, 0.0000011)) throw new RuntimeException('Boundary index bounds or shard is inconsistent.');
            $rows++; $shardCounts[$shard]++; $previous = $parts[0];
            if ($rows > $snapshot['parcel_count']) throw new RuntimeException('Boundary index contains too many rows.');
            yield ['cadastral_id' => $parts[0], 'bbox' => $bbox, 'shard' => $shard];
        }
        if (!feof($handle) || $bytes !== $descriptor['bytes'] || $rows !== $descriptor['rows'] || !hash_equals($descriptor['sha256'], hash_final($hash))) throw new RuntimeException('Boundary index integrity check failed.');
        foreach ($shardCounts as $position => $count) if ($count !== $snapshot['shards'][$position]['feature_count']) throw new RuntimeException('Boundary shard/index count differs.');
    } finally { fclose($handle); }
}

function boundary_check_exclusions(array $snapshot, array $geometryCandidates, array $pointHasGeometry): void {
    $descriptor = $snapshot['ambiguous_index']; $handle = fopen(boundary_file($snapshot, $descriptor), 'rb');
    if ($handle === false) throw new RuntimeException('Boundary exclusions cannot be read.');
    $hash = hash_init('sha256'); $bytes = 0; $rows = 0; $previous = null;
    try {
        while (($line = fgets($handle, 128)) !== false) {
            $bytes += strlen($line); hash_update($hash, $line); $id = substr($line, 0, -1);
            if ($bytes > $descriptor['bytes'] || substr($line, -1) !== "\n" || !boundary_id_valid($id)
                || ($previous !== null && strcmp($previous, $id) >= 0) || isset($geometryCandidates[$id]) || isset($pointHasGeometry[$id])) throw new RuntimeException('Boundary exclusions or index are inconsistent.');
            $rows++; $previous = $id;
            if ($rows > $descriptor['rows']) throw new RuntimeException('Boundary exclusions contain too many rows.');
        }
        if (!feof($handle) || $bytes !== $descriptor['bytes'] || $rows !== $descriptor['rows'] || !hash_equals($descriptor['sha256'], hash_final($hash))) throw new RuntimeException('Boundary exclusion integrity check failed.');
    } finally { fclose($handle); }
}

function boundary_feature_vertices(array $feature, array $snapshot, array $shard): int {
    $properties = $feature['properties'] ?? null; $geometry = $feature['geometry'] ?? null; $bbox = $feature['bbox'] ?? null;
    if (($feature['type'] ?? null) !== 'Feature' || !boundary_id_valid($feature['id'] ?? null) || !is_array($properties)
        || ($properties['cadastral_id'] ?? null) !== $feature['id'] || count($properties) !== 6
        || !array_key_exists('area_m2', $properties) || ($properties['area_m2'] !== null && !cadastre_area_valid($properties['area_m2']))
        || !array_key_exists('perimeter_m', $properties) || ($properties['perimeter_m'] !== null && !boundary_number($properties['perimeter_m'], 0, 1000000000))
        || !is_string($properties['source_key'] ?? null) || !isset($snapshot['source_lookup'][$properties['source_key']])
        || ($properties['native_crs'] ?? null) !== 'BGS2005_LCC' || !is_int($properties['vertex_count'] ?? null)
        || $properties['vertex_count'] < 4 || $properties['vertex_count'] > BOUNDARY_MAX_FEATURE_VERTICES
        || !boundary_bbox_valid($bbox) || !boundary_contains($shard['bounds'], $bbox)
        || !is_array($geometry) || count($geometry) !== 2 || !in_array($geometry['type'] ?? null, ['Polygon', 'MultiPolygon'], true)
        || !snapshot_list($geometry['coordinates'] ?? null)) throw new RuntimeException('Boundary geometry feature is invalid.');
    $polygons = $geometry['type'] === 'Polygon' ? [$geometry['coordinates']] : $geometry['coordinates'];
    if (count($polygons) < 1 || count($polygons) > 10000) throw new RuntimeException('Boundary polygon count is invalid.');
    $vertices = 0; $actual = [180.0, 90.0, -180.0, -90.0];
    foreach ($polygons as $rings) {
        if (!snapshot_list($rings) || count($rings) < 1 || count($rings) > 10000) throw new RuntimeException('Boundary rings are invalid.');
        foreach ($rings as $ring) {
            if (!snapshot_list($ring) || count($ring) < 4 || count($ring) > BOUNDARY_MAX_FEATURE_VERTICES || $ring[0] !== $ring[count($ring) - 1]) throw new RuntimeException('Boundary ring is open or invalid.');
            foreach ($ring as $position) {
                if (!snapshot_list($position) || count($position) !== 2 || !boundary_number($position[0], 21, 30) || !boundary_number($position[1], 40, 45)) throw new RuntimeException('Boundary coordinates are invalid.');
                $vertices++; if ($vertices > BOUNDARY_MAX_FEATURE_VERTICES) throw new RuntimeException('Boundary geometry exceeds its vertex limit.');
                $actual[0] = min($actual[0], $position[0]); $actual[1] = min($actual[1], $position[1]);
                $actual[2] = max($actual[2], $position[0]); $actual[3] = max($actual[3], $position[1]);
            }
        }
    }
    if ($vertices !== $properties['vertex_count']) throw new RuntimeException('Boundary vertex count differs.');
    foreach ($actual as $edge => $value) if (abs($value - $bbox[$edge]) > 0.00000011) throw new RuntimeException('Boundary bounds do not match its full coordinates.');
    return $vertices;
}

function boundary_reply(?array $snapshot, string $status, ?string $reason = null): array {
    return ['type' => 'FeatureCollection', 'status' => $status, 'features' => [], 'fallback_points' => [],
        'complete' => $status === 'available', 'truncated' => false, 'total' => $status === 'available' ? 0 : null,
        'geometry_count' => $status === 'available' ? 0 : null, 'missing_count' => $status === 'available' ? 0 : null,
        'min_zoom' => BOUNDARY_MIN_ZOOM, 'reason' => $reason, 'source' => boundary_public_source($snapshot),
        'generated_at' => $snapshot['generated_at'] ?? null, 'snapshot_id' => $snapshot['snapshot_id'] ?? null,
        'dimension_method' => 'published_AREA_and_PERIM_snapshot', 'scope' => 'exact_id_mapped_parcels'];
}

function boundary_response(PDO $pdo, ?array $registry, ?array $cadastre, array $filter): array {
    $snapshot = load_boundary_snapshot();
    if ($snapshot === null) return boundary_reply(null, 'unavailable', 'snapshot_not_published');
    $view = ['north' => number_param('north', -90, 90), 'south' => number_param('south', -90, 90), 'east' => number_param('east', -180, 180), 'west' => number_param('west', -180, 180)];
    $rawZoom = $_GET['zoom'] ?? '13';
    if (!is_numeric($rawZoom) || !is_finite((float)$rawZoom) || $rawZoom < 0 || $rawZoom > 22) throw new InvalidArgumentException('Invalid boundary map zoom.');
    if ($view['north'] <= $view['south'] || $view['east'] <= $view['west']) throw new InvalidArgumentException('Invalid boundary map bounds.');
    if ((float)$rawZoom < BOUNDARY_MIN_ZOOM) return boundary_reply($snapshot, 'zoom_in', 'minimum_zoom');
    if ($view['north'] - $view['south'] > 0.1 || $view['east'] - $view['west'] > 0.1) return boundary_reply($snapshot, 'zoom_in', 'viewport_too_large');
    $documentWhere = $registry !== null ? registry_filter($pdo, $registry, $filter) : record_filter($filter);
    $pointQuery = $pdo->prepare('SELECT p.cadastral_id FROM parcels p WHERE p.latitude BETWEEN :south AND :north AND p.longitude BETWEEN :west AND :east' . $documentWhere . ' LIMIT ' . (BOUNDARY_MAX_CANDIDATES + 1));
    $pointQuery->execute($view); $pointIds = [];
    while ($row = $pointQuery->fetch(PDO::FETCH_NUM)) $pointIds[$row[0]] = true;
    if (count($pointIds) > BOUNDARY_MAX_CANDIDATES) return boundary_reply($snapshot, 'too_dense', 'candidate_limit');
    $candidates = []; $pointHasGeometry = []; $candidateCount = 0;
    foreach (boundary_index_iterator($snapshot) as $entry) {
        $id = $entry['cadastral_id'];
        if (isset($cadastre['ambiguous_lookup'][$id])) continue;
        if (isset($pointIds[$id])) $pointHasGeometry[$id] = true;
        if (!boundary_intersects($entry['bbox'], $view)) continue;
        $candidateCount++;
        if ($candidateCount <= BOUNDARY_MAX_CANDIDATES) $candidates[$id] = $entry;
    }
    boundary_check_exclusions($snapshot, $candidates, $pointHasGeometry);
    if ($candidateCount > BOUNDARY_MAX_CANDIDATES) return boundary_reply($snapshot, 'too_dense', 'candidate_limit');
    $allIds = array_fill_keys(array_keys($candidates), true) + $pointIds;
    $allowed = $allIds === [] ? [] : matching_plot_ids($pdo, $registry, $cadastre, $filter,
        'p.latitude IS NOT NULL AND p.longitude IS NOT NULL' . $documentWhere . cadastre_area_filter($pdo, $allIds), []);
    $candidates = array_intersect_key($candidates, $allowed);
    $missing = array_diff_key(array_intersect_key($pointIds, $allowed), $pointHasGeometry);
    unset($allIds, $allowed, $pointIds, $pointHasGeometry);
    if (count($candidates) + count($missing) > BOUNDARY_MAX_FEATURES) return boundary_reply($snapshot, 'too_dense', 'feature_limit');
    $needed = []; $processingBytes = 0;
    foreach ($candidates as $entry) if (!isset($needed[$entry['shard']])) { $needed[$entry['shard']] = true; $processingBytes += $snapshot['shards'][$entry['shard']]['bytes']; }
    if ($processingBytes > BOUNDARY_MAX_VIEW_SHARD_BYTES) return boundary_reply($snapshot, 'too_dense', 'processing_limit');
    $plots = []; $visibleIds = array_fill_keys(array_keys($candidates), true) + $missing;
    if ($visibleIds !== []) {
        $query = $pdo->query('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng' . ($registry === null ? ', ' . document_flags_select() : '')
            . ' FROM parcels p ' . ($registry === null ? document_flags_join() : '') . ' WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL AND p.cadastral_id IN (' . quoted_ids($pdo, array_keys($visibleIds)) . ')');
        foreach ($query->fetchAll() as $row) $plots[$row['cadastral_id']] = $registry === null ? serialize_plot($row) : registry_plot($row, $registry);
    }
    if (count($plots) !== count($visibleIds)) throw new RuntimeException('Mapped boundary plots changed during the request.');
    $features = []; $viewVertices = 0; $tooManyVertices = false;
    foreach ($needed as $position => $_) {
        $shard = $snapshot['shards'][$position];
        $data = bounded_registry_json(boundary_file($snapshot, $shard), 1024 * 1024, $shard['bytes'], $shard['sha256']);
        if (($data['type'] ?? null) !== 'FeatureCollection' || !snapshot_list($data['features'] ?? null) || count($data['features']) !== $shard['feature_count']) throw new RuntimeException('Boundary GeoJSON shard is invalid.');
        $shardVertices = 0; $seen = [];
        foreach ($data['features'] as $feature) {
            if (!is_array($feature)) throw new RuntimeException('Boundary GeoJSON feature is invalid.');
            $vertices = boundary_feature_vertices($feature, $snapshot, $shard); $shardVertices += $vertices;
            $id = $feature['id']; if (isset($seen[$id])) throw new RuntimeException('Boundary shard contains a duplicate parcel.'); $seen[$id] = true;
            if (!isset($candidates[$id])) continue;
            $entry = $candidates[$id];
            if ($entry['shard'] !== $position || !boundary_contains($entry['bbox'], $feature['bbox'], 0.00000001)) throw new RuntimeException('Boundary exact-ID spatial index differs from its geometry.');
            foreach ($entry['bbox'] as $edge => $value) if (abs($value - $feature['bbox'][$edge]) > 0.0000011) throw new RuntimeException('Boundary index margin exceeds outward rounding.');
            $viewVertices += $vertices;
            if ($viewVertices > BOUNDARY_MAX_VIEW_VERTICES) { $tooManyVertices = true; $features = []; continue; }
            $properties = $feature['properties'];
            $feature = ['type' => 'Feature', 'id' => $id, 'bbox' => $feature['bbox'], 'geometry' => $feature['geometry'],
                'properties' => $plots[$id] + ['area_m2' => $properties['area_m2'], 'published_perimeter_m' => $properties['perimeter_m'],
                    'vertex_count' => $vertices, 'source' => boundary_public_source($snapshot, $properties['source_key']), 'boundary_status' => 'matched']];
            $features[$id] = $feature;
        }
        if ($shardVertices !== $shard['vertex_count']) throw new RuntimeException('Boundary shard vertex total differs.');
        unset($data, $seen);
    }
    if ($tooManyVertices) return boundary_reply($snapshot, 'too_dense', 'vertex_limit');
    if (count($features) !== count($candidates)) throw new RuntimeException('A requested boundary geometry is missing.');
    $reply = boundary_reply($snapshot, 'available'); ksort($features, SORT_STRING); $reply['features'] = array_values($features);
    foreach ($missing as $id => $_) $reply['fallback_points'][] = $plots[$id] + ['kind' => 'plot', 'boundary_status' => 'unavailable'];
    $reply['geometry_count'] = count($features); $reply['missing_count'] = count($missing); $reply['total'] = count($features) + count($missing);
    $reply['vertex_count'] = $viewVertices;
    $encoded = json_encode($reply, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    if (strlen($encoded) > BOUNDARY_MAX_RESPONSE_BYTES) return boundary_reply($snapshot, 'too_dense', 'response_limit');
    return $reply;
}
