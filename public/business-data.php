<?php
declare(strict_types=1);

// Standalone read-only snapshot API. A registered office is an address
// association; it does not establish ownership or occupation of a parcel.
const BUSINESS_MAX_FILE_BYTES = 10000000;
const BUSINESS_MAX_INDEX_BYTES = 9500000;
const BUSINESS_MAX_SHARD_BYTES = 1048576;
const BUSINESS_MAX_MANIFEST_BYTES = 262144;
const BUSINESS_MAX_DATASET_BYTES = 134217728;
const BUSINESS_MAX_ROWS = 2000000;
const BUSINESS_SCOPE = 'registered_office_address_association';
const BUSINESS_SCOPE_LABEL = 'Съвпадение на вписан фирмен адрес с кадастрален адрес. Не доказва собственост, наем или дейност на място.';

function business_keys($value, array $keys): bool {
    if (!is_array($value) || count($value) !== count($keys)) return false;
    foreach ($keys as $key) if (!array_key_exists($key, $value)) return false;
    return true;
}

function business_list($value): bool {
    return is_array($value) && ($value === [] || array_keys($value) === range(0, count($value) - 1));
}

function business_text($value, int $maximum, bool $empty = false): bool {
    if (!is_string($value) || strlen($value) > $maximum * 4 || preg_match('//u', $value) !== 1
        || preg_match('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', $value)) return false;
    $length = function_exists('mb_strlen') ? mb_strlen($value, 'UTF-8') : preg_match_all('/./us', $value);
    return $length <= $maximum && ($empty || trim($value) !== '');
}

function business_timestamp($value): bool {
    return is_string($value) && preg_match('/^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)$/', $value)
        && strtotime($value) !== false;
}

function business_date($value): bool {
    return is_string($value) && preg_match('/^(?:19|20)[0-9]{2}-[0-9]{2}-[0-9]{2}$/', $value)
        && checkdate((int)substr($value, 5, 2), (int)substr($value, 8, 2), (int)substr($value, 0, 4));
}

function business_id($value): bool {
    return is_string($value) && preg_match('/^68134\.[0-9]{1,6}\.[0-9]{1,6}$/D', $value) === 1;
}

function business_uic($value): bool {
    if (!is_string($value) || preg_match('/^[0-9]{9}$/D', $value) !== 1) return false;
    $first = 0; $second = 0;
    for ($i = 0; $i < 8; $i++) { $first += ($i + 1) * (int)$value[$i]; $second += ($i + 3) * (int)$value[$i]; }
    $check = $first % 11;
    if ($check === 10) { $check = $second % 11; if ($check === 10) $check = 0; }
    return $check === (int)$value[8];
}

function business_fold(string $value): string {
    if (function_exists('mb_strtolower')) return mb_strtolower($value, 'UTF-8');
    return strtolower(strtr($value, ['А'=>'а','Б'=>'б','В'=>'в','Г'=>'г','Д'=>'д','Е'=>'е','Ж'=>'ж','З'=>'з','И'=>'и','Й'=>'й','К'=>'к','Л'=>'л','М'=>'м','Н'=>'н','О'=>'о','П'=>'п','Р'=>'р','С'=>'с','Т'=>'т','У'=>'у','Ф'=>'ф','Х'=>'х','Ц'=>'ц','Ч'=>'ч','Ш'=>'ш','Щ'=>'щ','Ъ'=>'ъ','Ь'=>'ь','Ю'=>'ю','Я'=>'я','Ѝ'=>'ѝ']));
}

function business_private_text(string $value): bool {
    return preg_match('/@|(?<![0-9])[0-9]{10}(?![0-9])|(?:ЕГН|ЛНЧ)(?:\s|:)|(?:телефон|факс)\s*:/iu', $value) === 1;
}

function business_bytes(string $path, int $maximum, ?array $descriptor = null): string {
    if (is_link($path) || !is_file($path)) throw new RuntimeException('Snapshot file unavailable.');
    $size = filesize($path);
    if ($size === false || $size < 2 || $size > $maximum || ($descriptor !== null && $size !== $descriptor['bytes'])) throw new RuntimeException('Snapshot file size invalid.');
    $handle = fopen($path, 'rb');
    if ($handle === false) throw new RuntimeException('Snapshot file unreadable.');
    try { $raw = stream_get_contents($handle, $maximum + 1); } finally { fclose($handle); }
    if (!is_string($raw) || strlen($raw) !== $size || ($descriptor !== null && !hash_equals($descriptor['sha256'], hash('sha256', $raw)))) throw new RuntimeException('Snapshot file integrity failed.');
    return $raw;
}

function business_json(string $raw): array {
    $data = json_decode($raw, true, 24, JSON_THROW_ON_ERROR);
    if (!is_array($data)) throw new RuntimeException('Snapshot JSON invalid.');
    return $data;
}

function business_descriptor($value, string $filename, int $maximum): array {
    if (!business_keys($value, ['file', 'bytes', 'sha256']) || ($value['file'] ?? null) !== $filename
        || !is_int($value['bytes']) || $value['bytes'] < 2 || $value['bytes'] > $maximum
        || !is_string($value['sha256']) || preg_match('/^[a-f0-9]{64}$/D', $value['sha256']) !== 1) throw new RuntimeException('Snapshot descriptor invalid.');
    return $value;
}

function business_cadastre_url($value): bool {
    if (!business_text($value, 4096) || !filter_var($value, FILTER_VALIDATE_URL)) return false;
    $url = parse_url($value);
    return ($url['scheme'] ?? null) === 'https' && ($url['host'] ?? null) === 'kais.cadastre.bg'
        && ($url['path'] ?? null) === '/bg/OpenData/Download' && preg_match('/^path=[^&]+$/D', $url['query'] ?? '')
        && !isset($url['user']) && !isset($url['pass']) && !isset($url['port']) && !isset($url['fragment']);
}

function business_source($source): void {
    if (!business_keys($source, ['repo', 'commit', 'path', 'files'])
        || $source['repo'] !== 'ChocoRamaBG/register-of-outpatient-care-facilities-and-hospices'
        || !is_string($source['commit']) || preg_match('/^[a-f0-9]{40}$/D', $source['commit']) !== 1
        || $source['path'] !== 'registry_agency_scraper/registry_agency_outputs'
        || !business_list($source['files']) || count($source['files']) < 1 || count($source['files']) > 64) throw new RuntimeException('Company source invalid.');
    $seen = []; $bytes = 0;
    foreach ($source['files'] as $file) {
        if (!business_keys($file, ['name', 'bytes', 'git_blob_sha1', 'sha256'])
            || !is_string($file['name']) || preg_match('/^registry_agency_data_mega(?:_part(?:[2-9]|[1-9][0-9]+))?\.csv$/D', $file['name']) !== 1 || isset($seen[$file['name']])
            || !is_int($file['bytes']) || $file['bytes'] < 1 || $file['bytes'] > 134217728
            || !is_string($file['git_blob_sha1']) || preg_match('/^[a-f0-9]{40}$/D', $file['git_blob_sha1']) !== 1
            || !is_string($file['sha256']) || preg_match('/^[a-f0-9]{64}$/D', $file['sha256']) !== 1) throw new RuntimeException('Company source part invalid.');
        $seen[$file['name']] = true;
        $bytes += $file['bytes'];
    }
    if ($bytes > 1073741824) throw new RuntimeException('Company source byte limit exceeded.');
}

function business_snapshot(): array {
    $private = __DIR__ . '/private'; $root = $private . '/business-snapshots';
    if (is_link($private) || is_link($root)) throw new RuntimeException('Snapshot root invalid.');
    $pointer = business_json(business_bytes($private . '/business-active.json', 1024));
    if (!business_keys($pointer, ['version', 'snapshot_id', 'manifest_sha256']) || $pointer['version'] !== 1
        || !is_string($pointer['snapshot_id']) || preg_match('/^[a-f0-9]{32}$/D', $pointer['snapshot_id']) !== 1
        || !is_string($pointer['manifest_sha256']) || preg_match('/^[a-f0-9]{64}$/D', $pointer['manifest_sha256']) !== 1) throw new RuntimeException('Snapshot pointer invalid.');
    $directory = $root . '/' . $pointer['snapshot_id'];
    if (is_link($directory) || !is_dir($directory)) throw new RuntimeException('Snapshot directory unavailable.');
    $raw = business_bytes($directory . '/manifest.json', BUSINESS_MAX_MANIFEST_BYTES);
    if (!hash_equals($pointer['manifest_sha256'], hash('sha256', $raw))) throw new RuntimeException('Snapshot manifest integrity failed.');
    $data = business_json($raw);
    if (!business_keys($data, ['version', 'snapshot_id', 'generated_at', 'source', 'cadastre', 'counts', 'shards', 'parcel_index', 'search_index'])
        || $data['version'] !== 1 || $data['snapshot_id'] !== $pointer['snapshot_id'] || !business_timestamp($data['generated_at'])) throw new RuntimeException('Snapshot manifest invalid.');
    business_source($data['source']);
    $cadastre = $data['cadastre'];
    if (!business_keys($cadastre, ['manifest_sha256', 'snapshot_id', 'captured_from', 'captured_to', 'sources'])
        || !is_string($cadastre['manifest_sha256']) || preg_match('/^[a-f0-9]{64}$/D', $cadastre['manifest_sha256']) !== 1
        || !is_string($cadastre['snapshot_id']) || preg_match('/^[a-f0-9]{32}$/D', $cadastre['snapshot_id']) !== 1
        || !business_timestamp($cadastre['captured_from']) || !business_timestamp($cadastre['captured_to'])
        || !business_list($cadastre['sources']) || count($cadastre['sources']) !== 24) throw new RuntimeException('Cadastral source invalid.');
    $codes = [];
    foreach ($cadastre['sources'] as $source) {
        if (!business_keys($source, ['code', 'source_url', 'zip_sha256', 'captured_at'])
            || !is_string($source['code']) || preg_match('/^sofia-district-(?:0[0-9]|1[0-9]|2[0-3])$/D', $source['code']) !== 1 || isset($codes[$source['code']])
            || !business_cadastre_url($source['source_url']) || !business_timestamp($source['captured_at'])
            || !is_string($source['zip_sha256']) || preg_match('/^[a-f0-9]{64}$/D', $source['zip_sha256']) !== 1) throw new RuntimeException('Cadastral source descriptor invalid.');
        $codes[$source['code']] = true;
    }
    if (!is_array($data['counts']) || count($data['counts']) > 100) throw new RuntimeException('Coverage counts invalid.');
    foreach ($data['counts'] as $key => $count) if (!is_string($key) || !preg_match('/^[a-z][a-z0-9_]{0,63}$/D', $key) || !is_int($count) || $count < 0 || $count > 10000000) throw new RuntimeException('Coverage count invalid.');
    foreach (['matched_companies', 'matched_parcels', 'sofia_candidates'] as $key) if (!isset($data['counts'][$key]) || $data['counts'][$key] < 1 || $data['counts'][$key] > BUSINESS_MAX_ROWS) throw new RuntimeException('Coverage required count invalid.');
    if ($data['counts']['matched_parcels'] > $data['counts']['matched_companies'] || $data['counts']['matched_companies'] > $data['counts']['sofia_candidates']) throw new RuntimeException('Coverage counts inconsistent.');
    business_descriptor($data['parcel_index'], 'parcel-index.json', BUSINESS_MAX_INDEX_BYTES);
    business_descriptor($data['search_index'], 'search-index.json', BUSINESS_MAX_INDEX_BYTES);
    if (!is_array($data['shards']) || count($data['shards']) < 1 || count($data['shards']) > 512) throw new RuntimeException('Company shards invalid.');
    $bytes = $data['parcel_index']['bytes'] + $data['search_index']['bytes'];
    $descriptors = [$data['parcel_index'], $data['search_index']];
    foreach ($data['shards'] as $name => $descriptor) {
        if (!is_string($name) || preg_match('/^companies-[0-9]{3}\.json$/D', $name) !== 1 || !business_keys($descriptor, ['bytes', 'sha256'])) throw new RuntimeException('Company shard name invalid.');
        $descriptor = business_descriptor(['file' => $name] + $descriptor, $name, BUSINESS_MAX_SHARD_BYTES);
        $bytes += $descriptor['bytes']; $descriptors[] = $descriptor;
    }
    if ($bytes > BUSINESS_MAX_DATASET_BYTES) throw new RuntimeException('Company snapshot too large.');
    foreach ($descriptors as $descriptor) {
        $path = $directory . '/' . $descriptor['file'];
        if (is_link($path) || !is_file($path) || filesize($path) !== $descriptor['bytes']) throw new RuntimeException('Company snapshot incomplete.');
    }
    $data['directory'] = $directory;
    return $data;
}

function business_coverage(array $snapshot): array {
    return ['status' => 'available', 'counts' => $snapshot['counts'], 'scope' => BUSINESS_SCOPE, 'scope_label' => BUSINESS_SCOPE_LABEL,
        'generated_at' => $snapshot['generated_at'], 'source' => $snapshot['source'], 'cadastre' => $snapshot['cadastre']];
}

function business_parcel_index(array $snapshot): array {
    $descriptor = $snapshot['parcel_index'];
    $index = business_json(business_bytes($snapshot['directory'] . '/parcel-index.json', BUSINESS_MAX_INDEX_BYTES, $descriptor));
    if (count($index) !== $snapshot['counts']['matched_parcels']) throw new RuntimeException('Parcel index count invalid.');
    foreach ($index as $id => $shard) if (!business_id($id) || !is_string($shard) || !isset($snapshot['shards'][$shard])) throw new RuntimeException('Parcel index invalid.');
    return $index;
}

function business_company($value): array {
    if (!business_keys($value, ['uic', 'name', 'legal_form', 'activity', 'registered_address', 'status', 'as_of', 'source_url'])
        || !business_uic($value['uic']) || !business_text($value['name'], 300) || !business_text($value['legal_form'], 160)
        || preg_match('/едноличен\s+търговец|физическо\s+лице/iu', $value['legal_form'])
        || !business_text($value['activity'], 500, true) || !business_text($value['registered_address'], 240)
        || business_private_text($value['name']) || business_private_text($value['activity']) || business_private_text($value['registered_address'])
        || !preg_match('/^гр\. София, (?:ул\.|бул\.|пл\.) .+ № [0-9]+[а-яa-z]?$/iuD', $value['registered_address'])
        || $value['status'] !== 'not_verified' || ($value['as_of'] !== '' && !business_date($value['as_of']))
        || $value['source_url'] !== 'https://portal.registryagency.bg/CR/Reports/ActiveConditionTabResult?uic=' . $value['uic']) throw new RuntimeException('Company record invalid.');
    return $value;
}

function business_integer(string $key, int $default, int $maximum): int {
    if (!isset($_GET[$key])) return $default;
    $value = $_GET[$key];
    if (!is_string($value) || !preg_match('/^(?:0|[1-9][0-9]{0,6})$/D', $value) || (int)$value > $maximum) throw new InvalidArgumentException('Invalid pagination.');
    return (int)$value;
}

function business_plot(array $snapshot): array {
    $id = $_GET['id'] ?? null;
    if (!business_id($id)) throw new InvalidArgumentException('Invalid cadastral identifier.');
    $offset = business_integer('offset', 0, BUSINESS_MAX_ROWS); $limit = business_integer('limit', 20, 50);
    if ($limit < 1) throw new InvalidArgumentException('Invalid result limit.');
    $index = business_parcel_index($snapshot); $companies = [];
    if (isset($index[$id])) {
        $name = $index[$id]; $descriptor = ['file' => $name] + $snapshot['shards'][$name];
        $shard = business_json(business_bytes($snapshot['directory'] . '/' . $name, BUSINESS_MAX_SHARD_BYTES, $descriptor));
        if (!isset($shard[$id]) || !business_list($shard[$id])) throw new RuntimeException('Company shard parcel absent.');
        foreach ($shard as $parcel => $records) {
            if (!business_id($parcel) || ($index[$parcel] ?? null) !== $name || !business_list($records) || count($records) < 1 || count($records) > BUSINESS_MAX_ROWS) throw new RuntimeException('Company shard invalid.');
            foreach ($records as $record) business_company($record);
        }
        $companies = $shard[$id];
    }
    $total = count($companies);
    return ['cadastral_id' => $id, 'companies' => array_slice($companies, $offset, $limit), 'total' => $total,
        'offset' => $offset, 'limit' => $limit, 'has_more' => $offset + $limit < $total];
}

// Decode one bounded object at a time, rather than retaining a 9.5 MB JSON
// array and its expanded PHP representation on the shared hosting account.
function business_search_rows(array $snapshot): Generator {
    $descriptor = $snapshot['search_index']; $path = $snapshot['directory'] . '/search-index.json';
    $handle = fopen($path, 'rb');
    if ($handle === false || is_link($path)) throw new RuntimeException('Search index unavailable.');
    $hash = hash_init('sha256'); $bytes = 0; $state = 'start'; $buffer = ''; $depth = 0; $quoted = false; $escaped = false; $rows = 0;
    try {
        while (!feof($handle)) {
            $chunk = fread($handle, 65536);
            if ($chunk === false || ($chunk === '' && !feof($handle))) throw new RuntimeException('Search index unreadable.');
            $bytes += strlen($chunk); hash_update($hash, $chunk);
            if ($bytes > $descriptor['bytes']) throw new RuntimeException('Search index byte limit exceeded.');
            for ($i = 0, $length = strlen($chunk); $i < $length; $i++) {
                $char = $chunk[$i];
                if ($state === 'object') {
                    $buffer .= $char;
                    if (strlen($buffer) > 4096) throw new RuntimeException('Search record too large.');
                    if ($quoted) { if ($escaped) $escaped = false; elseif ($char === '\\') $escaped = true; elseif ($char === '"') $quoted = false; }
                    elseif ($char === '"') $quoted = true;
                    elseif ($char === '{' || $char === '[') $depth++;
                    elseif ($char === '}' || $char === ']') $depth--;
                    if ($depth === 0) {
                        $row = business_json($buffer); $rows++;
                        if ($rows > BUSINESS_MAX_ROWS) throw new RuntimeException('Search index row limit exceeded.');
                        yield $row; $buffer = ''; $state = 'after';
                    }
                    continue;
                }
                if ($char === ' ' || $char === "\r" || $char === "\n" || $char === "\t") continue;
                if ($state === 'start' && $char === '[') { $state = 'first'; continue; }
                if (($state === 'first' || $state === 'next') && $char === '{') { $state = 'object'; $buffer = '{'; $depth = 1; $quoted = false; $escaped = false; continue; }
                if (($state === 'first' || $state === 'after') && $char === ']') { $state = 'end'; continue; }
                if ($state === 'after' && $char === ',') { $state = 'next'; continue; }
                throw new RuntimeException('Search index structure invalid.');
            }
        }
        if ($state !== 'end' || $bytes !== $descriptor['bytes'] || $rows !== $snapshot['counts']['matched_companies'] || !hash_equals($descriptor['sha256'], hash_final($hash))) throw new RuntimeException('Search index integrity failed.');
    } finally { fclose($handle); }
}

function business_search(array $snapshot): array {
    $raw = $_GET['q'] ?? null;
    if (!business_text($raw, 120)) throw new InvalidArgumentException('Enter a company name or EIK (2–120 characters).');
    $query = trim(preg_replace('/\s+/u', ' ', $raw));
    $length = function_exists('mb_strlen') ? mb_strlen($query, 'UTF-8') : preg_match_all('/./us', $query);
    if ($length < 2) throw new InvalidArgumentException('Enter at least two characters.');
    $query = business_fold($query); $limit = business_integer('limit', 40, 40);
    if ($limit < 1) throw new InvalidArgumentException('Invalid result limit.');
    $index = business_parcel_index($snapshot); $results = []; $total = 0;
    foreach (business_search_rows($snapshot) as $row) {
        if (!business_keys($row, ['uic', 'name', 'registered_address', 'cadastral_id']) || !business_uic($row['uic'])
            || !business_text($row['name'], 300) || !business_text($row['registered_address'], 240)
            || business_private_text($row['name']) || business_private_text($row['registered_address'])
            || !business_id($row['cadastral_id']) || !isset($index[$row['cadastral_id']])) throw new RuntimeException('Search record invalid.');
        if (strpos(business_fold($row['name']), $query) === false && strpos($row['uic'], $query) === false) continue;
        $total++; if (count($results) < $limit) $results[] = $row;
    }
    return ['results' => $results, 'total' => $total, 'truncated' => $total > count($results), 'limit' => $limit];
}

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');
header('X-Content-Type-Options: nosniff');
try {
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    if (!in_array($method, ['GET', 'HEAD'], true)) { header('Allow: GET, HEAD'); http_response_code(405); throw new InvalidArgumentException('Read-only endpoint.'); }
    $action = $_GET['action'] ?? 'meta';
    if (!is_string($action) || !in_array($action, ['meta', 'plot', 'search'], true)) throw new InvalidArgumentException('Unknown business action.');
    $snapshot = business_snapshot();
    $reply = ['available' => true, 'status' => 'available', 'snapshot_id' => $snapshot['snapshot_id'], 'generated_at' => $snapshot['generated_at'],
        'scope' => BUSINESS_SCOPE, 'scope_label' => BUSINESS_SCOPE_LABEL, 'coverage' => business_coverage($snapshot)];
    if ($action === 'meta') $reply += ['source' => $snapshot['source'], 'cadastre' => $snapshot['cadastre'], 'counts' => $snapshot['counts']];
    elseif ($action === 'plot') $reply += business_plot($snapshot);
    else $reply += business_search($snapshot);
} catch (InvalidArgumentException $error) {
    if (http_response_code() !== 405) http_response_code(400);
    $reply = ['available' => false, 'status' => 'invalid_request', 'error' => $error->getMessage()];
} catch (Throwable $error) {
    error_log('Sofia business snapshot unavailable: ' . $error->getMessage());
    http_response_code(503); header('Retry-After: 300');
    $reply = ['available' => false, 'status' => 'unavailable', 'error' => 'Business address data is temporarily unavailable.', 'total' => null, 'companies' => [], 'results' => [],
        'scope' => BUSINESS_SCOPE, 'scope_label' => BUSINESS_SCOPE_LABEL];
}
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'HEAD') echo json_encode($reply, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
