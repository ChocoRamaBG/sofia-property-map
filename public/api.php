<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

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

function record_type_param(): string {
    $value = $_GET['record_type'] ?? 'all';
    if (!is_string($value) || !in_array($value, ['all', 'exploitation_certificates', 'building_permits', 'projecting_visas', 'no_records'], true)) {
        throw new InvalidArgumentException('Invalid register filter.');
    }
    return $value;
}

function record_filter(string $recordType): string {
    if ($recordType === 'all') return '';
    if ($recordType === 'no_records') {
        return ' AND NOT EXISTS (SELECT 1 FROM parcel_documents filter_pd WHERE filter_pd.parcel_cadastral_id = p.cadastral_id)';
    }
    if ($recordType === 'exploitation_certificates') {
        return " AND EXISTS (SELECT 1 FROM parcel_documents filter_pd WHERE filter_pd.parcel_cadastral_id = p.cadastral_id AND filter_pd.source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy'))";
    }
    return ' AND EXISTS (SELECT 1 FROM parcel_documents filter_pd WHERE filter_pd.parcel_cadastral_id = p.cadastral_id AND filter_pd.source_code = :filter_source)';
}

function record_filter_params(string $recordType): array {
    return in_array($recordType, ['all', 'no_records', 'exploitation_certificates'], true) ? [] : ['filter_source' => $recordType];
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

function load_registry_snapshot(): ?array {
    $path = __DIR__ . '/private/registry-data.json';
    if (!file_exists($path)) return null;
    $bytes = filesize($path);
    if ($bytes === false || $bytes <= 0 || $bytes > 10 * 1024 * 1024) {
        throw new RuntimeException('Registry snapshot has an invalid size.');
    }
    $json = file_get_contents($path, false, null, 0, 10 * 1024 * 1024 + 1);
    if ($json === false || strlen($json) > 10 * 1024 * 1024) throw new RuntimeException('Registry snapshot cannot be read.');
    $snapshot = json_decode($json, true, 32, JSON_THROW_ON_ERROR);
    if (!is_array($snapshot) || ($snapshot['version'] ?? null) !== 1 || !snapshot_timestamp_valid($snapshot['generated_at'] ?? null)
        || !snapshot_list($snapshot['sources'] ?? null) || !snapshot_list($snapshot['documents'] ?? null)
        || !snapshot_list($snapshot['imports'] ?? null) || count($snapshot['sources']) > 5 || count($snapshot['documents']) > 60000) {
        throw new RuntimeException('Registry snapshot format is invalid.');
    }
    $allowedCodes = ['coordinates', 'building_permits', 'exploitation_certificates', 'exploitation_certificates_legacy', 'projecting_visas'];
    $coreCodes = ['building_permits', 'exploitation_certificates', 'projecting_visas'];
    $sources = [];
    foreach ($snapshot['sources'] as $source) {
        if (!is_array($source) || !in_array($source['code'] ?? null, $allowedCodes, true) || isset($sources[$source['code']])
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
    foreach ($coreCodes as $code) {
        if (!isset($sources[$code])) throw new RuntimeException('Registry snapshot is missing a register.');
    }
    $completion = $snapshot['completion'] ?? null;
    if (!is_array($completion) || ($completion['status'] ?? null) !== 'complete' || !snapshot_list($completion['sources'] ?? null)) {
        throw new RuntimeException('Registry snapshot is incomplete.');
    }
    foreach ($completion['sources'] as $code) {
        if (!in_array($code, $allowedCodes, true)) throw new RuntimeException('Registry completion source is invalid.');
    }
    if (array_diff($coreCodes, $completion['sources']) !== []
        || (isset($completion['start_date']) && !snapshot_date_valid($completion['start_date']))
        || (isset($completion['finished_at']) && !snapshot_timestamp_valid($completion['finished_at']))) {
        throw new RuntimeException('Registry snapshot is incomplete.');
    }

    $byId = [];
    $flags = [];
    $seenDocuments = [];
    $sourceIds = array_fill_keys(array_keys($sources), []);
    $documentCounts = array_fill_keys(array_keys($sources), 0);
    $certificateIds = [];
    $linkedCertificates = 0;
    foreach ($snapshot['documents'] as $index => $document) {
        if (!is_array($document) || !isset($sources[$document['source_code'] ?? '']) || ($document['source_code'] ?? '') === 'coordinates'
            || !is_string($document['document_hash'] ?? null) || !preg_match('/^[a-f0-9]{64}$/', $document['document_hash'])
            || !snapshot_string($document['record_key'] ?? null, 190, true) || !is_array($document['raw_fields'] ?? null)
            || count($document['raw_fields']) > 100 || !snapshot_list($document['cadastral_ids'] ?? null)
            || count($document['cadastral_ids']) > 10000 || !snapshot_string($document['snapshot_file'] ?? null, 255, true)
            || (isset($document['snapshot_date']) && !snapshot_date_valid($document['snapshot_date']))
            || (isset($document['issued_at']) && !snapshot_date_valid($document['issued_at']))) {
            throw new RuntimeException('Registry document is invalid.');
        }
        $key = $document['source_code'] . ':' . $document['document_hash'];
        if (isset($seenDocuments[$key])) throw new RuntimeException('Registry snapshot contains duplicate documents.');
        $seenDocuments[$key] = true;
        foreach ($document['raw_fields'] as $field => $value) {
            if (!snapshot_string((string)$field, 200) || (!is_scalar($value) && $value !== null)
                || (is_string($value) && strlen($value) > 500000)) throw new RuntimeException('Registry fields are invalid.');
        }
        $documentCounts[$document['source_code']]++;
        $ids = [];
        foreach ($document['cadastral_ids'] as $id) {
            if (!is_string($id) || !preg_match('/^[0-9]{5}\.[0-9]{1,6}\.[0-9]{1,6}$/', $id)) {
                throw new RuntimeException('Registry cadastral link is invalid.');
            }
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
    $imports = [];
    foreach ($snapshot['imports'] as $import) {
        if (!is_array($import) || !isset($sources[$import['source_code'] ?? ''])
            || !snapshot_string($import['source_file'] ?? null, 255, true)
            || !snapshot_string($import['imported_at'] ?? null, 50)
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
    return [
        'generated_at' => $snapshot['generated_at'], 'sources' => $sources, 'documents' => $snapshot['documents'], 'imports' => $imports,
        'by_id' => $byId, 'flags' => $flags, 'source_ids' => $sourceIds, 'document_counts' => $documentCounts,
        'certificate_ids' => $certificateIds, 'linked_certificates' => $linkedCertificates,
    ];
}

function quoted_ids(PDO $pdo, array $ids): string {
    // IDs have been checked against the cadastral-ID pattern. PDO still quotes every value.
    return implode(',', array_map(static function (string $id) use ($pdo): string { return $pdo->quote($id); }, $ids));
}

function registry_filter(PDO $pdo, array $registry, string $recordType): string {
    if ($recordType === 'all') return '';
    $ids = $recordType === 'no_records' ? array_keys($registry['by_id'])
        : ($recordType === 'exploitation_certificates' ? array_keys($registry['certificate_ids']) : array_keys($registry['source_ids'][$recordType] ?? []));
    if ($ids === []) return $recordType === 'no_records' ? '' : ' AND 0 = 1';
    return ' AND p.cadastral_id ' . ($recordType === 'no_records' ? 'NOT IN' : 'IN') . ' (' . quoted_ids($pdo, $ids) . ')';
}

function registry_plot(array $row, array $registry): array {
    return serialize_plot(array_merge($row, $registry['flags'][$row['cadastral_id']] ?? empty_document_flags()));
}

function registry_id_matches_filter(string $id, array $registry, string $recordType): bool {
    if ($recordType === 'all') return true;
    if ($recordType === 'no_records') return !isset($registry['by_id'][$id]);
    if ($recordType === 'exploitation_certificates') return isset($registry['certificate_ids'][$id]);
    return isset($registry['source_ids'][$recordType][$id]);
}

function contains_text(string $haystack, string $needle): bool {
    return function_exists('mb_stripos') ? mb_stripos($haystack, $needle, 0, 'UTF-8') !== false : stripos($haystack, $needle) !== false;
}

function registry_search(PDO $pdo, array $registry, string $term, string $recordType): array {
    $candidateIds = [];
    foreach ($registry['by_id'] as $id => $_) {
        if (registry_id_matches_filter($id, $registry, $recordType) && contains_text($id, $term)) $candidateIds[$id] = true;
    }
    foreach ($registry['documents'] as $document) {
        $text = json_encode($document['raw_fields'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($text === false || !contains_text($text, $term)) continue;
        foreach ($document['cadastral_ids'] as $id) {
            if (registry_id_matches_filter($id, $registry, $recordType)) $candidateIds[$id] = true;
        }
    }
    $like = '%' . str_replace(['%', '_'], ['\\%', '\\_'], $term) . '%';
    $stmt = $pdo->prepare('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng FROM parcels p WHERE p.cadastral_id LIKE :term' . registry_filter($pdo, $registry, $recordType) . ' ORDER BY (p.cadastral_id = :exact_term) DESC, p.cadastral_id LIMIT 40');
    $stmt->execute(['term' => $like, 'exact_term' => $term]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) $rows[$row['cadastral_id']] = registry_plot($row, $registry);
    if ($candidateIds !== []) {
        foreach (array_keys($candidateIds) as $id) $rows[$id] = registry_plot(['cadastral_id' => $id, 'lat' => null, 'lng' => null], $registry);
        $stmt = $pdo->query('SELECT cadastral_id, latitude AS lat, longitude AS lng FROM parcels WHERE cadastral_id IN (' . quoted_ids($pdo, array_keys($candidateIds)) . ')');
        foreach ($stmt->fetchAll() as $row) $rows[$row['cadastral_id']] = registry_plot($row, $registry);
    }
    $rows = array_values($rows);
    usort($rows, static function (array $a, array $b) use ($term): int {
        if (($a['cadastral_id'] === $term) !== ($b['cadastral_id'] === $term)) return $a['cadastral_id'] === $term ? -1 : 1;
        return strcmp($a['cadastral_id'], $b['cadastral_id']);
    });
    return array_map(static function (array $row): array {
        return array_merge($row, ['primary' => $row['cadastral_id'], 'secondary' => $row['document_count'] . ' linked register records']);
    }, array_slice($rows, 0, 40));
}

function registry_plot_sources(string $id, array $registry): array {
    $grouped = [];
    foreach ($registry['by_id'][$id] ?? [] as $index) {
        $document = $registry['documents'][$index];
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
    $registry = load_registry_snapshot();

    $action = $_GET['action'] ?? '';
    if ($action === 'meta') {
        $counts = [
            'plots' => (int)$pdo->query('SELECT COUNT(*) FROM parcels WHERE latitude IS NOT NULL AND longitude IS NOT NULL')->fetchColumn(),
            'documents' => (int)$pdo->query('SELECT COUNT(*) FROM source_documents')->fetchColumn(),
        ];
        if ($registry !== null) {
            $counts['documents'] = count($registry['documents']);
            $counts['documents_by_source'] = $registry['document_counts'];
            $counts['plots_by_source'] = array_map('count', $registry['source_ids']);
            $counts['plots_with_exploitation_certificate'] = count($registry['certificate_ids']);
            $counts['linked_exploitation_certificates'] = $registry['linked_certificates'];
            respond(['counts' => $counts, 'imports' => $registry['imports'], 'registry_generated_at' => $registry['generated_at']]);
        }
        $counts['documents_by_source'] = [];
        $counts['plots_by_source'] = [];
        foreach ($pdo->query('SELECT ds.code, COUNT(sd.document_hash) AS document_count FROM data_sources ds LEFT JOIN source_documents sd ON sd.source_code = ds.code GROUP BY ds.code')->fetchAll() as $row) {
            $counts['documents_by_source'][$row['code']] = (int)$row['document_count'];
            $counts['plots_by_source'][$row['code']] = 0;
        }
        foreach ($pdo->query('SELECT source_code, COUNT(DISTINCT parcel_cadastral_id) AS plot_count FROM parcel_documents GROUP BY source_code')->fetchAll() as $row) {
            $counts['plots_by_source'][$row['source_code']] = (int)$row['plot_count'];
        }
        $counts['plots_with_exploitation_certificate'] = (int)$pdo->query("SELECT COUNT(DISTINCT parcel_cadastral_id) FROM parcel_documents WHERE source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy')")->fetchColumn();
        $counts['linked_exploitation_certificates'] = (int)$pdo->query("SELECT COUNT(*) FROM (SELECT source_code, document_hash FROM parcel_documents WHERE source_code IN ('exploitation_certificates', 'exploitation_certificates_legacy') GROUP BY source_code, document_hash) linked_certificates")->fetchColumn();
        $imports = $pdo->query('SELECT di.source_code, ds.label_bg, ds.label_en, ds.source_url, ds.snapshot_date, ds.snapshot_file AS source_snapshot, di.source_file, di.imported_at, di.records_loaded FROM data_imports di LEFT JOIN data_sources ds ON ds.code = di.source_code ORDER BY di.imported_at DESC')->fetchAll();
        $imports = array_map(static function (array $row): array {
            $fallback = $row['source_file'] === $row['source_snapshot'] ? $row['snapshot_date'] : null;
            $row['snapshot_date'] = document_snapshot_date($row['source_file'], $fallback);
            $row['records_loaded'] = (int)$row['records_loaded'];
            unset($row['source_file'], $row['source_snapshot']);
            return $row;
        }, $imports);
        respond(['counts' => $counts, 'imports' => $imports]);
    }

    if ($action === 'viewport') {
        $recordType = record_type_param();
        $north = number_param('north', -90, 90);
        $south = number_param('south', -90, 90);
        $east = number_param('east', -180, 180);
        $west = number_param('west', -180, 180);
        $zoom = (int)max(0, min(22, (float)($_GET['zoom'] ?? 13)));
        if ($north <= $south || $east <= $west) {
            respond(['items' => [], 'total' => 0, 'truncated' => false]);
        }

        $where = 'p.latitude BETWEEN :south AND :north AND p.longitude BETWEEN :west AND :east'
            . ($registry !== null ? registry_filter($pdo, $registry, $recordType) : record_filter($recordType));
        $bounds = array_merge(['south' => $south, 'north' => $north, 'west' => $west, 'east' => $east], $registry !== null ? [] : record_filter_params($recordType));
        $countStmt = $pdo->prepare('SELECT COUNT(*) FROM parcels p WHERE ' . $where);
        $countStmt->execute($bounds);
        $total = (int)$countStmt->fetchColumn();
        $limit = 900;

        if ($zoom >= 16) {
            $stmt = $pdo->prepare('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng' . ($registry !== null ? '' : ', ' . document_flags_select()) . ' FROM parcels p ' . ($registry !== null ? '' : document_flags_join()) . ' WHERE ' . $where . ' ORDER BY p.cadastral_id LIMIT ' . ($limit + 1));
            $stmt->execute($bounds);
            $items = array_map(static function (array $row) use ($registry): array {
                return array_merge(['kind' => 'plot'], $registry !== null ? registry_plot($row, $registry) : serialize_plot($row));
            }, $stmt->fetchAll());
            $truncated = count($items) > $limit;
            if ($truncated) array_pop($items);
            respond(['items' => $items, 'total' => $total, 'truncated' => $truncated]);
        }

        $cell = $zoom >= 14 ? 0.002 : 0.008;
        $certificateExpression = 'COALESCE(flags.has_exploitation_certificate, 0)';
        if ($registry !== null) {
            $certificateExpression = $registry['certificate_ids'] === [] ? '0' : 'p.cadastral_id IN (' . quoted_ids($pdo, array_keys($registry['certificate_ids'])) . ')';
        }
        $stmt = $pdo->prepare(
            'SELECT FLOOR(p.latitude / :cell_lat) AS gy, FLOOR(p.longitude / :cell_lng) AS gx,
                    AVG(p.latitude) AS lat, AVG(p.longitude) AS lng, COUNT(*) AS point_count,
                    SUM(' . $certificateExpression . ') AS certificate_count
             FROM parcels p ' . ($registry !== null ? '' : document_flags_join()) . ' WHERE ' . $where . '
             GROUP BY gy, gx ORDER BY point_count DESC LIMIT ' . ($limit + 1)
        );
        $stmt->execute(array_merge(['cell_lat' => $cell, 'cell_lng' => $cell], $bounds));
        $rows = $stmt->fetchAll();
        $truncated = count($rows) > $limit;
        if ($truncated) array_pop($rows);
        $items = array_map(static function (array $row) use ($zoom): array {
            return [
                'kind' => 'cluster',
                'cell_key' => $row['gy'] . ':' . $row['gx'],
                'lat' => (float)$row['lat'],
                'lng' => (float)$row['lng'],
                'count' => (int)$row['point_count'],
                'certificate_count' => (int)$row['certificate_count'],
                'zoom' => $zoom,
            ];
        }, $rows);
        respond(['items' => $items, 'total' => $total, 'truncated' => $truncated]);
    }

    if ($action === 'search') {
        $recordType = record_type_param();
        $term = trim((string)($_GET['q'] ?? ''));
        if ($term === '' || text_length($term) > 120) {
            respond(['items' => []]);
        }
        if ($registry !== null) respond(['items' => registry_search($pdo, $registry, $term, $recordType)]);
        $like = '%' . str_replace(['%', '_'], ['\%', '\_'], $term) . '%';
        $stmt = $pdo->prepare(
            'SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng, ' . document_flags_select() . '
             FROM parcels p ' . document_flags_join() . '
             WHERE (p.cadastral_id LIKE :id_term
                OR EXISTS (
                    SELECT 1 FROM parcel_documents pd
                    JOIN source_documents sd ON sd.source_code = pd.source_code AND sd.document_hash = pd.document_hash
                    WHERE pd.parcel_cadastral_id = p.cadastral_id AND sd.raw_fields LIKE :raw_term
                ))' . record_filter($recordType) . '
             ORDER BY (p.cadastral_id = :exact_term) DESC, p.cadastral_id LIMIT 40'
        );
        $stmt->execute(array_merge(['id_term' => $like, 'raw_term' => $like, 'exact_term' => $term], record_filter_params($recordType)));
        $items = array_map(static function (array $row): array {
            return array_merge(serialize_plot($row), [
                'primary' => $row['cadastral_id'],
                'secondary' => ((int)$row['document_count']) . ' linked register records',
            ]);
        }, $stmt->fetchAll());
        respond(['items' => $items]);
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
            if (!$plot && !isset($registry['by_id'][$id])) respond(['error' => 'No record was found for this cadastral identifier.'], 404);
            if (!$plot) $plot = ['cadastral_id' => $id, 'lat' => null, 'lng' => null];
            respond(['plot' => registry_plot($plot, $registry), 'sources' => registry_plot_sources($id, $registry)]);
        }
        $stmt = $pdo->prepare('SELECT p.cadastral_id, p.latitude AS lat, p.longitude AS lng, ' . document_flags_select() . ' FROM parcels p ' . document_flags_join() . ' WHERE p.cadastral_id = :id LIMIT 1');
        $stmt->execute(['id' => $id]);
        $plot = $stmt->fetch();
        if (!$plot) respond(['error' => 'No record was found for this cadastral identifier.'], 404);
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
        respond(['plot' => $plot, 'sources' => array_values($grouped)]);
    }

    respond(['error' => 'Unknown API action.'], 404);
} catch (InvalidArgumentException $error) {
    respond(['error' => $error->getMessage()], 400);
} catch (Throwable $error) {
    error_log('Sofia property API error: ' . $error->getMessage());
    respond(['error' => 'The data service is temporarily unavailable.'], 500);
}
