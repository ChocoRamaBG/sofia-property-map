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
const BUSINESS_MAX_VIEW_ITEMS = 1200;
const BUSINESS_LOCATION_METHOD = 'official_parcel_representative_point';
const BUSINESS_ADDRESS_LOCATION_METHOD = 'official_municipal_address_point';
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

function business_address_id($value): bool {
    return is_string($value) && preg_match('/^address-[a-f0-9]{24}$/D', $value) === 1;
}

function business_point($point): bool {
    return business_keys($point, ['lat', 'lng']) && (is_int($point['lat']) || is_float($point['lat'])) && (is_int($point['lng']) || is_float($point['lng']))
        && is_finite((float)$point['lat']) && is_finite((float)$point['lng']) && $point['lat'] >= 42.4 && $point['lat'] <= 43.1 && $point['lng'] >= 22.8 && $point['lng'] <= 24;
}

function business_municipal_source($value): void {
    if (!business_keys($value, ['version','source_revision','coordinate_crs','crs_basis','publisher_crs_explicit','sources']) || $value['version'] !== 1
        || !is_string($value['source_revision']) || !preg_match('/^[a-f0-9]{64}$/D', $value['source_revision']) || $value['coordinate_crs'] !== 'OGC:CRS84'
        || !in_array($value['crs_basis'], ['GeoJSON_default_CRS84','publisher_explicit_geographic_crs'], true) || !is_bool($value['publisher_crs_explicit'])
        || !business_list($value['sources']) || count($value['sources']) !== 2) throw new RuntimeException('Municipal source invalid.');
    $expected = ['address_sofia-zip'=>['7b32c5f8-5f25-4b24-92f9-43e265275587','GeoJSON','address_sofia'], 'streets_names_new_old-zip'=>['c3ec6293-b1b0-48b7-98ae-9693ae7abd77','CSV','streets_names_new_old']];
    foreach ($value['sources'] as $source) {
        if (!business_keys($source, ['dataset','resource_id','url','format','data_as_of','retrieved_at','bytes','sha256','metadata_sha256','license_id','license_url','policy_url']) || !isset($expected[$source['dataset']])) throw new RuntimeException('Municipal source descriptor invalid.');
        [$resource,$format,$filename] = $expected[$source['dataset']]; unset($expected[$source['dataset']]);
        $url = is_string($source['url']) ? parse_url($source['url']) : [];
        if ($source['resource_id'] !== $resource || $source['format'] !== $format || ($url['scheme'] ?? '') !== 'https' || ($url['host'] ?? '') !== 'urbandata.sofia.bg'
            || !preg_match('~^/dataset/[a-f0-9-]{36}/resource/' . preg_quote($resource,'~') . '/download/' . $filename . '\.zip$~D', $url['path'] ?? '')
            || isset($url['user']) || isset($url['pass']) || isset($url['port']) || isset($url['query']) || isset($url['fragment']) || ($source['data_as_of'] !== '' && !business_date($source['data_as_of']))
            || ($source['retrieved_at'] !== null && !business_timestamp($source['retrieved_at'])) || !is_int($source['bytes']) || $source['bytes'] < 1 || $source['bytes'] > 8388608
            || !is_string($source['sha256']) || !preg_match('/^[a-f0-9]{64}$/D',$source['sha256']) || !is_string($source['metadata_sha256']) || !preg_match('/^[a-f0-9]{64}$/D',$source['metadata_sha256'])
            || $source['license_id'] !== 'CC-BY-4.0' || $source['license_url'] !== 'https://creativecommons.org/licenses/by/4.0/' || $source['policy_url'] !== 'https://www.sofia.bg/bg/web/guest/urbanization-data') throw new RuntimeException('Municipal evidence invalid.');
    }
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
    return preg_match('/@|https?:\/\/|www\.|(?<![0-9])[0-9]{10}(?![0-9])|(?:ЕГН|ЛНЧ)(?:\s|:)|(?<!\w)(?:тел(?:ефон)?|факс|e-?mail|имейл)\s*[:.]|\+?[0-9][0-9 ()\/-]{7,}[0-9]/iu', $value) === 1;
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
    if ($bytes > 8589934592) throw new RuntimeException('Company source byte limit exceeded.');
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
    $manifestKeys = ['version', 'snapshot_id', 'generated_at', 'source', 'cadastre', 'counts', 'shards', 'parcel_index', 'search_index'];
    if (array_key_exists('points_index', $data)) $manifestKeys[] = 'points_index';
    if (($data['version'] ?? null) === 2) { $manifestKeys[] = 'municipal_source'; $manifestKeys[] = 'address_index'; $manifestKeys[] = 'address_shards'; }
    if (!business_keys($data, $manifestKeys)
        || !in_array($data['version'], [1,2], true) || $data['snapshot_id'] !== $pointer['snapshot_id'] || !business_timestamp($data['generated_at'])) throw new RuntimeException('Snapshot manifest invalid.');
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
    foreach (['matched_companies', 'matched_parcels', 'sofia_candidates'] as $key) if (!isset($data['counts'][$key]) || $data['counts'][$key] < ($data['version'] === 1 ? 1 : 0) || $data['counts'][$key] > BUSINESS_MAX_ROWS) throw new RuntimeException('Coverage required count invalid.');
    if ($data['counts']['matched_parcels'] > $data['counts']['matched_companies'] || $data['counts']['matched_companies'] > $data['counts']['sofia_candidates']) throw new RuntimeException('Coverage counts inconsistent.');
    business_descriptor($data['parcel_index'], 'parcel-index.json', BUSINESS_MAX_INDEX_BYTES);
    business_descriptor($data['search_index'], 'search-index.json', BUSINESS_MAX_INDEX_BYTES);
    if (!is_array($data['shards']) || count($data['shards']) < ($data['version'] === 1 ? 1 : 0) || count($data['shards']) > 512) throw new RuntimeException('Company shards invalid.');
    $bytes = strlen($raw) + $data['parcel_index']['bytes'] + $data['search_index']['bytes'];
    $descriptors = [$data['parcel_index'], $data['search_index']];
    if (isset($data['points_index'])) {
        business_descriptor($data['points_index'], 'points-index.json', BUSINESS_MAX_INDEX_BYTES);
        $bytes += $data['points_index']['bytes']; $descriptors[] = $data['points_index'];
        foreach (['mapped_business_parcels', 'unmapped_business_parcels', 'mapped_companies', 'unmapped_companies'] as $key) {
            if (!isset($data['counts'][$key]) || $data['counts'][$key] > BUSINESS_MAX_ROWS) throw new RuntimeException('Business point coverage count invalid.');
        }
        if ($data['counts']['mapped_business_parcels'] + $data['counts']['unmapped_business_parcels'] !== $data['counts']['matched_parcels']
            || $data['counts']['mapped_companies'] + $data['counts']['unmapped_companies'] !== $data['counts']['matched_companies']) throw new RuntimeException('Business point coverage inconsistent.');
    }
    foreach ($data['shards'] as $name => $descriptor) {
        if (!is_string($name) || preg_match('/^companies-[0-9]{3}\.json$/D', $name) !== 1 || !business_keys($descriptor, ['bytes', 'sha256'])) throw new RuntimeException('Company shard name invalid.');
        $descriptor = business_descriptor(['file' => $name] + $descriptor, $name, BUSINESS_MAX_SHARD_BYTES);
        $bytes += $descriptor['bytes']; $descriptors[] = $descriptor;
    }
    if ($data['version'] === 2) {
        business_municipal_source($data['municipal_source']);
        business_descriptor($data['address_index'], 'address-index.json', BUSINESS_MAX_INDEX_BYTES);
        $bytes += $data['address_index']['bytes']; $descriptors[] = $data['address_index'];
        if (!is_array($data['address_shards']) || count($data['address_shards']) > 512) throw new RuntimeException('Address shards invalid.');
        foreach ($data['address_shards'] as $name => $descriptor) {
            if (!is_string($name) || !preg_match('/^addresses-[0-9]{3}\.json$/D',$name) || !business_keys($descriptor,['bytes','sha256'])) throw new RuntimeException('Address shard name invalid.');
            $descriptor = business_descriptor(['file'=>$name]+$descriptor,$name,BUSINESS_MAX_SHARD_BYTES); $bytes += $descriptor['bytes']; $descriptors[] = $descriptor;
        }
        foreach (['address_only_companies','address_only_locations','located_companies','located_locations','exact_cadastral_address_companies','municipal_parcel_companies'] as $key) if (!isset($data['counts'][$key])) throw new RuntimeException('Municipal coverage count missing.');
        if ($data['counts']['exact_cadastral_address_companies']+$data['counts']['municipal_parcel_companies'] !== $data['counts']['matched_companies']
            || $data['counts']['located_companies'] !== ($data['counts']['mapped_companies'] ?? 0)+$data['counts']['address_only_companies']
            || $data['counts']['located_locations'] !== ($data['counts']['mapped_business_parcels'] ?? 0)+$data['counts']['address_only_locations']) throw new RuntimeException('Municipal coverage counts inconsistent.');
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
    $coverage = ['status' => 'available', 'counts' => $snapshot['counts'], 'scope' => BUSINESS_SCOPE, 'scope_label' => BUSINESS_SCOPE_LABEL,
        'generated_at' => $snapshot['generated_at'], 'source' => $snapshot['source'], 'cadastre' => $snapshot['cadastre'],
        'map_available' => isset($snapshot['points_index']), 'location_method' => isset($snapshot['points_index']) ? BUSINESS_LOCATION_METHOD : null];
    if ($snapshot['version'] === 2) { $coverage['municipal_source'] = $snapshot['municipal_source']; $coverage['location_methods'] = [BUSINESS_LOCATION_METHOD,BUSINESS_ADDRESS_LOCATION_METHOD]; $coverage['match_methods'] = ['cadastre_address','municipal_parcel','municipal_address']; $coverage['map_available'] = true; }
    return $coverage;
}

function business_parcel_index(array $snapshot): array {
    $descriptor = $snapshot['parcel_index'];
    $index = business_json(business_bytes($snapshot['directory'] . '/parcel-index.json', BUSINESS_MAX_INDEX_BYTES, $descriptor));
    if (count($index) !== $snapshot['counts']['matched_parcels']) throw new RuntimeException('Parcel index count invalid.');
    foreach ($index as $id => $shard) if (!business_id($id) || !is_string($shard) || !isset($snapshot['shards'][$shard])) throw new RuntimeException('Parcel index invalid.');
    return $index;
}

function business_company($value, int $version = 1, bool $addressOnly = false): array {
    $keys = ['uic', 'name', 'legal_form', 'activity', 'registered_address', 'status', 'as_of', 'source_url'];
    if ($version === 2) { $keys[] = 'match_method'; $keys[] = 'reference_ids'; }
    if (!business_keys($value, $keys)
        || !business_uic($value['uic']) || !business_text($value['name'], 300) || !business_text($value['legal_form'], 160)
        || preg_match('/едноличен\s+търговец|физическо\s+лице/iu', $value['legal_form'])
        || !business_text($value['activity'], 500, true) || !business_text($value['registered_address'], 240)
        || business_private_text($value['name']) || business_private_text($value['activity']) || business_private_text($value['registered_address'])
        || ($version === 1 && !preg_match('/^гр\. София, (?:ул\.|бул\.|пл\.) .+ № [0-9]+[а-яa-z]?$/iuD', $value['registered_address']))
        || $value['status'] !== 'not_verified' || ($value['as_of'] !== '' && !business_date($value['as_of']))
        || $value['source_url'] !== 'https://portal.registryagency.bg/CR/Reports/ActiveConditionTabResult?uic=' . $value['uic']) throw new RuntimeException('Company record invalid.');
    if ($version === 2) {
        if (!in_array($value['match_method'], $addressOnly ? ['municipal_address'] : ['cadastre_address','municipal_parcel'], true) || !business_list($value['reference_ids']) || count($value['reference_ids']) > 32 || count($value['reference_ids']) !== count(array_unique($value['reference_ids'], SORT_REGULAR))) throw new RuntimeException('Company match evidence invalid.');
        foreach ($value['reference_ids'] as $id) if ((!is_string($id) && !is_int($id)) || !preg_match('/^[a-zA-Z0-9._:-]{1,80}$/D',(string)$id)) throw new RuntimeException('Municipal reference ID invalid.');
        if ($value['match_method'] !== 'cadastre_address' && count($value['reference_ids']) < 1) throw new RuntimeException('Municipal reference evidence absent.');
    }
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
            $seen = []; foreach ($records as $record) { business_company($record,$snapshot['version']); if (isset($seen[$record['uic']])) throw new RuntimeException('Duplicate company UIC.'); $seen[$record['uic']] = true; }
        }
        $companies = $shard[$id];
    }
    $total = count($companies);
    return ['cadastral_id' => $id, 'companies' => array_slice($companies, $offset, $limit), 'total' => $total,
        'offset' => $offset, 'limit' => $limit, 'has_more' => $offset + $limit < $total];
}

function business_address_index(array $snapshot): array {
    if ($snapshot['version'] !== 2) return [];
    $index = business_json(business_bytes($snapshot['directory'].'/address-index.json',BUSINESS_MAX_INDEX_BYTES,$snapshot['address_index']));
    if (count($index) !== $snapshot['counts']['address_only_locations']) throw new RuntimeException('Address index count invalid.');
    $total = 0;
    foreach ($index as $id=>$entry) {
        if (!business_address_id($id) || !business_keys($entry,['file','lat','lng','label','company_count']) || !is_string($entry['file']) || !isset($snapshot['address_shards'][$entry['file']])
            || !business_point(['lat'=>$entry['lat'],'lng'=>$entry['lng']]) || !business_text($entry['label'],240) || business_private_text($entry['label'])
            || !is_int($entry['company_count']) || $entry['company_count'] < 1 || $entry['company_count'] > BUSINESS_MAX_ROWS) throw new RuntimeException('Address index invalid.');
        $total += $entry['company_count'];
    }
    if ($total !== $snapshot['counts']['address_only_companies']) throw new RuntimeException('Address company totals invalid.');
    return $index;
}

function business_address(array $snapshot): array {
    $id = $_GET['id'] ?? null;
    if (!business_address_id($id)) throw new InvalidArgumentException('Invalid address identifier.');
    $offset = business_integer('offset',0,BUSINESS_MAX_ROWS); $limit = business_integer('limit',20,50);
    if ($limit < 1) throw new InvalidArgumentException('Invalid result limit.');
    $index = business_address_index($snapshot);
    if (!isset($index[$id])) return ['address'=>null,'companies'=>[],'total'=>0,'offset'=>$offset,'limit'=>$limit,'has_more'=>false];
    $entry = $index[$id]; $name = $entry['file'];
    $shard = business_json(business_bytes($snapshot['directory'].'/'.$name,BUSINESS_MAX_SHARD_BYTES,['file'=>$name]+$snapshot['address_shards'][$name]));
    $seen = [];
    foreach ($shard as $addressId=>$group) {
        if (!business_address_id($addressId) || !isset($index[$addressId]) || $index[$addressId]['file'] !== $name || !business_keys($group,['address_label','lat','lng','companies'])
            || $group['address_label'] !== $index[$addressId]['label'] || $group['lat'] != $index[$addressId]['lat'] || $group['lng'] != $index[$addressId]['lng']
            || !business_point(['lat'=>$group['lat'],'lng'=>$group['lng']]) || !business_list($group['companies']) || count($group['companies']) !== $index[$addressId]['company_count']) throw new RuntimeException('Address group invalid.');
        foreach ($group['companies'] as $company) { business_company($company,2,true); if (isset($seen[$company['uic']])) throw new RuntimeException('Duplicate company in address shard.'); $seen[$company['uic']] = true; }
    }
    if (!isset($shard[$id])) throw new RuntimeException('Address group missing.');
    $companies = $shard[$id]['companies']; $total = count($companies);
    return ['address'=>['address_id'=>$id,'label'=>$entry['label'],'lat'=>$entry['lat'],'lng'=>$entry['lng']], 'companies'=>array_slice($companies,$offset,$limit),'total'=>$total,'offset'=>$offset,'limit'=>$limit,'has_more'=>$offset+$limit<$total];
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
        if ($state !== 'end' || $bytes !== $descriptor['bytes'] || $rows !== $snapshot['counts']['matched_companies']+($snapshot['counts']['address_only_companies'] ?? 0) || !hash_equals($descriptor['sha256'], hash_final($hash))) throw new RuntimeException('Search index integrity failed.');
    } finally { fclose($handle); }
}

function business_query(bool $optional = false): string {
    $raw = $_GET['q'] ?? ($optional ? '' : null);
    if (!business_text($raw, 120, $optional)) throw new InvalidArgumentException('Enter a company name or EIK (2–120 characters).');
    $query = trim(preg_replace('/\s+/u', ' ', $raw));
    if ($optional && $query === '') return '';
    $length = function_exists('mb_strlen') ? mb_strlen($query, 'UTF-8') : preg_match_all('/./us', $query);
    if ($length < 2) throw new InvalidArgumentException('Enter at least two characters.');
    return $query;
}

function business_search_record(array $row, array $index, array $addresses = []): string {
    $address = array_key_exists('address_id',$row); $idKey = $address ? 'address_id' : 'cadastral_id';
    if (!business_keys($row, ['uic', 'name', 'registered_address', $idKey]) || !business_uic($row['uic'])
        || !business_text($row['name'], 300) || !business_text($row['registered_address'], 240)
        || business_private_text($row['name']) || business_private_text($row['registered_address'])
        || ($address ? !business_address_id($row[$idKey]) || !isset($addresses[$row[$idKey]]) : !business_id($row[$idKey]) || !isset($index[$row[$idKey]]))) throw new RuntimeException('Search record invalid.');
    return $row[$idKey];
}

function business_search(array $snapshot): array {
    $query = business_fold(business_query()); $limit = business_integer('limit', 40, 40);
    if ($limit < 1) throw new InvalidArgumentException('Invalid result limit.');
    $index = business_parcel_index($snapshot); $addresses = business_address_index($snapshot); $results = []; $total = 0; $seen = [];
    foreach (business_search_rows($snapshot) as $row) {
        business_search_record($row, $index, $addresses);
        if (isset($seen[$row['uic']])) throw new RuntimeException('Duplicate company across locations.');
        $seen[$row['uic']] = true;
        if (strpos(business_fold($row['name']), $query) === false && strpos($row['uic'], $query) === false) continue;
        $total++; if (count($results) < $limit) $results[] = $row;
    }
    return ['results' => $results, 'total' => $total, 'truncated' => $total > count($results), 'limit' => $limit];
}

function business_view_number(string $name, float $minimum, float $maximum): float {
    $value = $_GET[$name] ?? null;
    if (!is_string($value) || strlen($value) > 32 || !preg_match('/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,20})?$/D', $value)
        || !is_finite((float)$value) || (float)$value < $minimum || (float)$value > $maximum) throw new InvalidArgumentException('Invalid business map bounds or zoom.');
    return (float)$value;
}

function business_extend_bounds(?array $bounds, float $lat, float $lng): array {
    if ($bounds === null) return ['south' => $lat, 'north' => $lat, 'west' => $lng, 'east' => $lng];
    return ['south' => min($bounds['south'], $lat), 'north' => max($bounds['north'], $lat),
        'west' => min($bounds['west'], $lng), 'east' => max($bounds['east'], $lng)];
}

function business_outward_bounds(?array $bounds): ?array {
    if ($bounds === null) return null;
    return ['south' => $bounds['south'] - 0.0000001, 'north' => $bounds['north'] + 0.0000001,
        'west' => $bounds['west'] - 0.0000001, 'east' => $bounds['east'] + 0.0000001];
}

function business_viewport(array $snapshot): array {
    $north = business_view_number('north', -90, 90); $south = business_view_number('south', -90, 90);
    $east = business_view_number('east', -180, 180); $west = business_view_number('west', -180, 180);
    $zoom = (int)floor(business_view_number('zoom', 0, 22)); $query = business_query(true);
    if ($north <= $south || $east <= $west) throw new InvalidArgumentException('Invalid business map bounds.');
    $level = $_GET['level'] ?? 'all';
    if (!is_string($level) || !in_array($level,['all','parcel','address'],true)) throw new InvalidArgumentException('Invalid location level.');
    if (!isset($snapshot['points_index']) && $snapshot['version'] === 1) throw new RuntimeException('Business map points have not been published.');
    $index = business_parcel_index($snapshot); $addresses = business_address_index($snapshot);
    $points = isset($snapshot['points_index']) ? business_json(business_bytes($snapshot['directory'] . '/points-index.json', BUSINESS_MAX_INDEX_BYTES, $snapshot['points_index'])) : [];
    if (count($points) !== ($snapshot['counts']['mapped_business_parcels'] ?? 0)) throw new RuntimeException('Business map point coverage unavailable.');
    foreach ($points as $id => $point) {
        if (!business_id($id) || !isset($index[$id]) || !business_keys($point, ['lat', 'lng'])
            || (!is_float($point['lat']) && !is_int($point['lat'])) || (!is_float($point['lng']) && !is_int($point['lng']))
            || !is_finite((float)$point['lat']) || !is_finite((float)$point['lng'])
            || $point['lat'] < 42.4 || $point['lat'] > 43.1 || $point['lng'] < 22.8 || $point['lng'] > 24) throw new RuntimeException('Business map point invalid.');
    }
    $locations = [];
    foreach ($points as $id=>$point) $locations[$id] = $point+['address_only'=>false];
    foreach ($addresses as $id=>$entry) $locations[$id] = ['lat'=>$entry['lat'],'lng'=>$entry['lng'],'registered_address'=>$entry['label'],'address_only'=>true];
    // Validate every search row and finish its digest before returning a single
    // result. A preview's forty-item limit never constrains the map selection.
    $allCounts = []; $matchingCounts = []; $folded = business_fold($query); $seen = [];
    foreach (business_search_rows($snapshot) as $row) {
        $id = business_search_record($row, $index, $addresses);
        if (isset($seen[$row['uic']])) throw new RuntimeException('Duplicate company across locations.');
        $seen[$row['uic']] = true;
        $allCounts[$id] = ($allCounts[$id] ?? 0) + 1;
        if ($query === '' || strpos(business_fold($row['name']), $folded) !== false || strpos($row['uic'], $folded) !== false) $matchingCounts[$id] = ($matchingCounts[$id] ?? 0) + 1;
    }
    if (count($allCounts) !== count($index)+count($addresses)) throw new RuntimeException('Business map company/location index inconsistent.');
    $parcelCompanies = 0;
    foreach ($index as $id=>$_) $parcelCompanies += $allCounts[$id] ?? 0;
    if ($parcelCompanies !== $snapshot['counts']['matched_companies']) throw new RuntimeException('Parcel company count inconsistent.');
    foreach ($addresses as $id=>$entry) if (($allCounts[$id] ?? 0) !== $entry['company_count']) throw new RuntimeException('Address company count inconsistent.');
    $mappedCompanies = 0;
    foreach ($points as $id => $_) $mappedCompanies += $allCounts[$id];
    if ($mappedCompanies !== ($snapshot['counts']['mapped_companies'] ?? 0)) throw new RuntimeException('Business map company coverage inconsistent.');
    $bounds = null; $selected = []; $companyTotal = 0; $matchingCompanyTotal = 0; $matchingTotal = 0; $parcelTotal = 0; $addressTotal = 0;
    foreach ($matchingCounts as $id => $count) {
        if (!isset($locations[$id])) continue;
        $point = $locations[$id];
        if (($level === 'parcel' && $point['address_only']) || ($level === 'address' && !$point['address_only'])) continue;
        $lat = (float)$point['lat']; $lng = (float)$point['lng'];
        $bounds = business_extend_bounds($bounds, $lat, $lng); $matchingTotal++; $matchingCompanyTotal += $count;
        if ($lat < $south || $lat > $north || $lng < $west || $lng > $east) continue;
        $selected[$id] = $point+['company_count'=>$count]; $companyTotal += $count;
        if ($point['address_only']) $addressTotal++; else $parcelTotal++;
    }
    $total = count($selected); $items = []; $clusterZoom = $zoom;
    if ($zoom >= 16 && $total <= BUSINESS_MAX_VIEW_ITEMS) {
        foreach ($selected as $id => $point) {
            $addressOnly = $point['address_only']; unset($point['address_only']);
            $items[] = ['kind'=>'point', $addressOnly ? 'address_id' : 'cadastral_id'=>$id]+$point+['location_method'=>$addressOnly ? BUSINESS_ADDRESS_LOCATION_METHOD : BUSINESS_LOCATION_METHOD];
        }
    } elseif ($total > 0) {
        do {
            // Globally anchored 128-pixel Web Mercator cells split into four
            // children on zoom-in. Dense views regroup all points at a coarser
            // level; no arbitrary LIMIT or dropped subset is ever returned.
            $cells = 1 << ($clusterZoom + 1); $groups = [];
            foreach ($selected as $point) {
                $radians = deg2rad($point['lat']);
                $gx = (int)floor(($point['lng'] + 180) / 360 * $cells);
                $gy = (int)floor((1 - log(tan($radians) + 1 / cos($radians)) / M_PI) / 2 * $cells);
                $key = $clusterZoom . ':' . $gx . ':' . $gy;
                if (!isset($groups[$key])) $groups[$key] = ['lat' => 0.0, 'lng' => 0.0, 'count' => 0, 'company_count' => 0, 'parcel_count'=>0, 'address_only_count'=>0, 'bounds' => null];
                $groups[$key]['lat'] += $point['lat']; $groups[$key]['lng'] += $point['lng']; $groups[$key]['count']++;
                $groups[$key]['company_count'] += $point['company_count'];
                $groups[$key][$point['address_only'] ? 'address_only_count' : 'parcel_count']++;
                $groups[$key]['bounds'] = business_extend_bounds($groups[$key]['bounds'], $point['lat'], $point['lng']);
            }
            if (count($groups) <= BUSINESS_MAX_VIEW_ITEMS) break;
            $clusterZoom--;
        } while ($clusterZoom >= 0);
        foreach ($groups as $key => $group) $items[] = ['kind' => 'cluster', 'cell_key' => $key,
            'lat' => $group['lat'] / $group['count'], 'lng' => $group['lng'] / $group['count'],
            'count' => $group['count'], 'company_count' => $group['company_count'], 'parcel_count'=>$group['parcel_count'],'address_only_count'=>$group['address_only_count'],'bounds' => business_outward_bounds($group['bounds']),
            'zoom' => $zoom, 'cluster_zoom' => $clusterZoom];
    }
    return ['items' => $items, 'total' => $total, 'company_total' => $companyTotal, 'complete' => true, 'truncated' => false,
        'matching_total' => $matchingTotal, 'matching_company_total' => $matchingCompanyTotal,
        'bounds' => business_outward_bounds($bounds), 'query' => $query, 'requested_zoom' => $zoom, 'cluster_zoom' => $clusterZoom,
        'level'=>$level,'parcel_total'=>$parcelTotal,'address_only_total'=>$addressTotal,'location_method' => $snapshot['version'] === 1 ? BUSINESS_LOCATION_METHOD : 'mixed_official_locations'];
}

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');
header('X-Content-Type-Options: nosniff');
try {
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    if (!in_array($method, ['GET', 'HEAD'], true)) { header('Allow: GET, HEAD'); http_response_code(405); throw new InvalidArgumentException('Read-only endpoint.'); }
    $action = $_GET['action'] ?? 'meta';
    if (!is_string($action) || !in_array($action, ['meta', 'plot', 'address', 'search', 'viewport'], true)) throw new InvalidArgumentException('Unknown business action.');
    $snapshot = business_snapshot();
    $reply = ['available' => true, 'status' => 'available', 'snapshot_id' => $snapshot['snapshot_id'], 'generated_at' => $snapshot['generated_at'],
        'scope' => BUSINESS_SCOPE, 'scope_label' => BUSINESS_SCOPE_LABEL, 'coverage' => business_coverage($snapshot)];
    if ($action === 'meta') $reply += ['source' => $snapshot['source'], 'cadastre' => $snapshot['cadastre'], 'counts' => $snapshot['counts']];
    elseif ($action === 'plot') $reply += business_plot($snapshot);
    elseif ($action === 'address') $reply += business_address($snapshot);
    elseif ($action === 'search') $reply += business_search($snapshot);
    else $reply += business_viewport($snapshot);
} catch (InvalidArgumentException $error) {
    if (http_response_code() !== 405) http_response_code(400);
    $reply = ['available' => false, 'status' => 'invalid_request', 'error' => $error->getMessage()];
} catch (Throwable $error) {
    error_log('Sofia business snapshot unavailable: ' . $error->getMessage());
    http_response_code(503); header('Retry-After: 300');
    $reply = ['available' => false, 'status' => 'unavailable', 'error' => 'Business address data is temporarily unavailable.', 'total' => null, 'companies' => [], 'results' => [], 'items' => [],
        'scope' => BUSINESS_SCOPE, 'scope_label' => BUSINESS_SCOPE_LABEL];
}
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'HEAD') echo json_encode($reply, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
