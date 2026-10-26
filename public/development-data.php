<?php
declare(strict_types=1);

// Loaded by the read-only API after its registry and database validation.
// Keep this module free of filesystem writes, contacts and ownership inference.
const DEVELOPMENT_TYPES = ['building_permits', 'projecting_visas', 'exploitation_certificates', 'exploitation_certificates_legacy'];
const DEVELOPMENT_LABELS = [
    'building_permits' => 'Разрешения за строеж',
    'projecting_visas' => 'Визи за проектиране',
    'exploitation_certificates' => 'Удостоверения за въвеждане в експлоатация',
    'exploitation_certificates_legacy' => 'Архивни удостоверения за въвеждане в експлоатация',
];

function development_integer_param(string $key, int $default, int $minimum, int $maximum): int {
    $raw = $_GET[$key] ?? null;
    if ($raw === null || $raw === '') return $default;
    if (!is_string($raw) || !preg_match('/^[0-9]{1,5}$/', $raw)) throw new InvalidArgumentException('Invalid development pagination or year.');
    $value = (int)$raw;
    if ($value < $minimum || $value > $maximum) throw new InvalidArgumentException('Development pagination or year is out of range.');
    return $value;
}

function development_saved_ids(): array {
    // A 200-document shortlist exceeds common GET request-line limits. POST
    // carries only this bounded read selection; the endpoint still never writes.
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    if (!in_array($method, ['GET', 'HEAD', 'POST'], true)) throw new InvalidArgumentException('Unsupported development request method.');
    if ($method === 'POST') {
        if (isset($_GET['saved_ids']) || count($_POST) !== 1 || !array_key_exists('saved_ids', $_POST)) throw new InvalidArgumentException('Only a saved document selection may be posted.');
        $raw = $_POST['saved_ids'];
        if (!is_string($raw) || $raw === '' || strlen($raw) > 13000) throw new InvalidArgumentException('Invalid saved development selection.');
    } else {
        $raw = optional_filter_string('saved_ids', 13000);
    }
    $ids = $raw === null ? [] : array_values(array_unique(explode(',', $raw)));
    if (count($ids) > 200) throw new InvalidArgumentException('Choose at most 200 saved development documents.');
    foreach ($ids as $id) if (!preg_match('/^[a-f0-9]{64}$/', $id)) throw new InvalidArgumentException('Invalid saved development document.');
    return $ids;
}

function development_params(): array {
    $rawTypes = optional_filter_string('type', 180) ?? 'all';
    $types = $rawTypes === 'all' ? DEVELOPMENT_TYPES : array_values(array_unique(explode(',', $rawTypes)));
    foreach ($types as $type) if (!in_array($type, DEVELOPMENT_TYPES, true)) throw new InvalidArgumentException('Invalid development document type.');
    $year = development_integer_param('year', 0, 1, 9999);
    $dates = document_date_range_params('date_from', 'date_to');
    $period = optional_filter_string('period', 10) ?? 'month';
    if (!in_array($period, ['month', 'year'], true)) throw new InvalidArgumentException('Invalid development grouping period.');
    $investor = optional_filter_string('investor', 10) ?? 'any';
    if (!in_array($investor, ['any', 'known'], true)) throw new InvalidArgumentException('Invalid published contracting-authority filter.');
    $savedIds = development_saved_ids();
    $district = optional_filter_string('district', 200);
    $query = optional_filter_string('q', 120);
    foreach ([$district, $query] as $value) if ($value !== null && !preg_match('//u', $value)) throw new InvalidArgumentException('Development text filters must use UTF-8.');
    return ['types' => $types, 'year' => $year ?: null, 'date_from' => $dates['from'], 'date_to' => $dates['to'],
        'district' => $district === null ? null : development_normalize($district), 'investor' => $investor,
        'q' => $query, 'period' => $period,
        'saved_ids' => $savedIds,
        'offset' => development_integer_param('offset', 0, 0, 2000), 'limit' => development_integer_param('limit', 20, 1, 50)];
}

function development_normalize(string $value): string {
    return cadastre_fold_text(trim(preg_replace('/\s+/u', ' ', $value)));
}

function development_text($value, int $limit = 2000): ?string {
    if (!is_string($value) && !is_int($value) && !is_float($value)) return null;
    $text = trim(preg_replace('/\s+/u', ' ', (string)$value));
    if (in_array(development_normalize($text), ['', '-', '—', '–', 'n/a', 'null', 'няма'], true)) return null;
    // A summary never needs an email address, telephone or personal identifier.
    $text = preg_replace('/[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}/iu', '[скрит контакт]', $text);
    $text = preg_replace('/(?<![0-9])(?:\+359|00359|0)[\s().\-]*(?:[0-9][\s().\-]*){8,9}(?![0-9])/u', '[скрит контакт]', $text);
    $text = preg_replace('/(?<![0-9])[0-9]{10}(?![0-9])/u', '[скрит идентификатор]', $text);
    if (function_exists('mb_substr')) return mb_substr($text, 0, $limit, 'UTF-8');
    preg_match('/^.{0,' . $limit . '}/us', $text, $match);
    return $match[0];
}

function development_fields(array $document): array {
    $result = [];
    foreach ($document['raw_fields'] as $field => $value) $result[development_normalize((string)$field)] = $value;
    return $result;
}

function development_field(array $fields, array $names, int $limit = 2000): ?string {
    foreach ($names as $name) {
        $text = development_text($fields[$name] ?? null, $limit);
        if ($text !== null) return $text;
    }
    return null;
}

function development_number(array $document, array $fields): ?string {
    $number = development_field($fields, ['№', 'номер', 'удостоверение', 'разрешение за строеж', 'виза', 'number'], 190);
    if ($number !== null) return $number;
    $fallback = development_text($document['record_key'] ?? null, 190);
    // An old visa workbook used its first (date) cell as record_key. A date
    // alone cannot identify a document, nor can a truncated hash substitute.
    if ($fallback !== null && !preg_match('/^(?:[0-9]{2}\.[0-9]{2}\.[0-9]{4}|[a-f0-9]{16,64})$/i', $fallback)) return $fallback;
    return null;
}

function development_identity(array $document, array $fields): array {
    $number = development_number($document, $fields);
    $issuer = development_field($fields, ['издател', 'issuer'], 500);
    $district = development_field($fields, ['район', 'district'], 200);
    // Permit numbers can repeat across district issuing authorities. Preserve
    // that scope. Missing numbers retain separate observations conservatively.
    $reliable = $number !== null && (($document['issued_at'] ?? null) !== null || preg_match('/(?<![0-9])(?:19|20)[0-9]{2}(?![0-9])/', $number));
    $scope = $issuer ?? $district;
    if ($scope === null) $reliable = false;
    $identity = !$reliable ? ['hash', $document['document_hash']]
        : ['number', development_normalize($number), $document['issued_at'] ?? null, development_normalize($scope)];
    return [hash('sha256', $document['source_code'] . "\n" . json_encode($identity, JSON_UNESCAPED_UNICODE)), $number, $district, $reliable];
}

function development_investors(array $fields): array {
    $entities = [];
    foreach (['възложител' => 'Възложител', 'инвеститор' => 'Инвеститор', 'contracting authority' => 'Възложител', 'investor' => 'Инвеститор'] as $field => $label) {
        $text = development_field($fields, [$field], 3000);
        if ($text === null) continue;
        foreach (preg_split('/[,;\n]+/u', $text) as $segment) {
            $segment = trim($segment);
            // Retain allowlisted incorporated companies/public organizations.
            // Sole traders and unincorporated partnerships are not treated as
            // legal entities; personal applicants/contacts stay excluded.
            if (preg_match('/(?:["„“«]([^"„“»«]{2,160})["“»]\s*((?:ЕООД|ООД|ЕАД|АД|КД|СД))(?=$|[\s,;.]))/iu', $segment, $match)) {
                $name = '„' . trim($match[1]) . '“ ' . $match[2];
            } elseif (preg_match('/^[\p{L}\p{N} .„“"\-–&()]{2,160}\s(?:ЕООД|ООД|ЕАД|АД|КД|СД)$/iu', $segment)) {
                $name = $segment;
            } elseif (preg_match('/^(?:Столична община|Община\s|СО\s*[-–]|Министерство\s|Агенция\s)[\p{L}\p{N} .„“"\-–()]{0,160}$/iu', $segment)) {
                $name = $segment;
            } else continue;
            if (strpos($name, '[скрит') !== false) continue;
            $key = development_normalize($name) . ':' . $field;
            $entities[$key] = ['role' => $field, 'label' => $label, 'value' => $name];
            if (count($entities) >= 5) return array_values($entities);
        }
    }
    return array_values($entities);
}

function development_snapshot_date(array $document, array $source): ?string {
    $fallback = ($document['snapshot_file'] ?? null) === ($source['snapshot_file'] ?? null) ? $source['snapshot_date'] : null;
    return array_key_exists('snapshot_date', $document) ? $document['snapshot_date'] : document_snapshot_date($document['snapshot_file'] ?? null, $fallback);
}

function development_matches(array $document, array $fields, ?string $district, array $investors, array $params): bool {
    if (!in_array($document['source_code'], $params['types'], true)) return false;
    $issued = $document['issued_at'] ?? null;
    if ($params['year'] !== null && ($issued === null || (int)substr($issued, 0, 4) !== $params['year'])) return false;
    if (($params['date_from'] !== null || $params['date_to'] !== null) && !scoped_document_date_matches($issued, ['from' => $params['date_from'], 'to' => $params['date_to']])) return false;
    if ($params['district'] !== null && ($district === null || development_normalize($district) !== $params['district'])) return false;
    if ($params['investor'] === 'known' && $investors === []) return false;
    if ($params['q'] !== null) {
        $values = [development_number($document, $fields) ?? '', $district ?? '',
            development_field($fields, ['обект', 'строеж/обект', 'строеж / обект', 'object', 'construction / object']) ?? '',
            development_field($fields, ['местоположение', 'обхват', 'обхват и идентификатори', 'адрес', 'address', 'scope and identifiers', 'scope', 'location']) ?? '',
            implode(' ', $document['cadastral_ids'])];
        foreach ($investors as $investor) $values[] = $investor['value'];
        if (strpos(development_normalize(implode("\n", $values)), development_normalize($params['q'])) === false) return false;
    }
    return true;
}

function development_empty_counts(): array {
    return array_fill_keys(DEVELOPMENT_TYPES, 0) + ['total' => 0];
}

function development_response(PDO $pdo, ?array $registry, array $params): array {
    if ($registry === null) throw new FilterUnavailableException('The development dashboard requires a published, validated register snapshot.');
    $groups = [];
    $observations = 0;
    $unlinked = 0;
    $linkedObservations = 0;
    $observationCounts = array_fill_keys(DEVELOPMENT_TYPES, 0);
    $unlinkedCounts = array_fill_keys(DEVELOPMENT_TYPES, 0);
    // One compact JSON scalar per identity avoids retaining raw fields or a
    // second copy of the large registry index in InfinityFree PHP memory.
    foreach (registry_document_iterator($registry) as $document) {
        $observations++;
        $sourceCode = $document['source_code'];
        $observationCounts[$sourceCode]++;
        if ($document['cadastral_ids'] === []) { $unlinked++; $unlinkedCounts[$sourceCode]++; continue; }
        $linkedObservations++;
        $fields = development_fields($document);
        [$identity, $number, $district, $reliableIdentity] = development_identity($document, $fields);
        $snapshotDate = development_snapshot_date($document, $registry['sources'][$sourceCode]);
        $rank = ($snapshotDate ?? '0000-00-00') . ':' . $document['document_hash'];
        $previous = isset($groups[$identity]) ? json_decode($groups[$identity], true, 4, JSON_THROW_ON_ERROR) : null;
        if ($previous !== null && $previous[4] > $rank) { $previous[6]++; $groups[$identity] = json_encode($previous, JSON_UNESCAPED_UNICODE); continue; }
        $investors = development_investors($fields);
        $groups[$identity] = json_encode([$sourceCode, $document['issued_at'] ?? null,
            $district === null ? null : development_normalize($district), $district, $rank, $document['document_hash'],
            ($previous[6] ?? 0) + 1, development_matches($document, $fields, $district, $investors, $params), $investors !== [], $reliableIdentity], JSON_UNESCAPED_UNICODE);
    }

    $years = [];
    $districts = [];
    $typeCounts = development_empty_counts();
    $selectedTypeCounts = development_empty_counts();
    $datedSourceCounts = array_fill_keys(DEVELOPMENT_TYPES, 0);
    $sourceDateRanges = array_fill_keys(DEVELOPMENT_TYPES, ['date_min' => null, 'date_max' => null]);
    $periods = [];
    $dateMin = null;
    $dateMax = null;
    $dated = 0;
    $matchedObservations = 0;
    $knownInvestor = 0;
    $fallbackIdentities = 0;
    $selectedFallbackIdentities = 0;
    $heap = new SplMinHeap();
    $take = $params['offset'] + $params['limit'];
    $savedIds = array_fill_keys($params['saved_ids'], true);
    foreach ($groups as $identity => $packed) {
        $row = json_decode($packed, true, 4, JSON_THROW_ON_ERROR);
        [$code, $issued, $districtKey, $districtLabel] = $row;
        $typeCounts[$code]++; $typeCounts['total']++;
        if (!$row[9]) $fallbackIdentities++;
        if ($issued !== null) {
            $year = (int)substr($issued, 0, 4);
            $years[$year] = ($years[$year] ?? 0) + 1;
            $datedSourceCounts[$code]++;
            $sourceDateRanges[$code]['date_min'] = $sourceDateRanges[$code]['date_min'] === null ? $issued : min($sourceDateRanges[$code]['date_min'], $issued);
            $sourceDateRanges[$code]['date_max'] = $sourceDateRanges[$code]['date_max'] === null ? $issued : max($sourceDateRanges[$code]['date_max'], $issued);
            $dateMin = $dateMin === null ? $issued : min($dateMin, $issued);
            $dateMax = $dateMax === null ? $issued : max($dateMax, $issued);
        }
        if ($districtKey !== null) {
            if (!isset($districts[$districtKey])) $districts[$districtKey] = ['key' => $districtKey, 'label' => $districtLabel, 'count' => 0];
            $districts[$districtKey]['count']++;
        }
        if (!$row[7] || ($savedIds !== [] && !isset($savedIds[$identity]))) continue;
        $selectedTypeCounts[$code]++; $selectedTypeCounts['total']++;
        if (!$row[9]) $selectedFallbackIdentities++;
        $matchedObservations += $row[6];
        $knownInvestor += (int)$row[8];
        if ($issued !== null) {
            $dated++;
            $period = substr($issued, 0, $params['period'] === 'month' ? 7 : 4);
            if (!isset($periods[$period])) $periods[$period] = ['period' => $period, 'observed' => true] + development_empty_counts();
            $periods[$period][$code]++; $periods[$period]['total']++;
            if (count($periods) > 1200) throw new FilterUnavailableException('Choose a shorter date range or yearly grouping for the development chart.');
        }
        $heap->insert([($issued ?? '0000-00-00') . ':' . $identity, $identity]);
        if ($heap->count() > $take) $heap->extract();
    }
    if ($params['district'] !== null && !isset($districts[$params['district']])) throw new InvalidArgumentException('Unknown development document district.');
    $ordered = [];
    while (!$heap->isEmpty()) $ordered[] = $heap->extract()[1];
    $pageIdentities = array_slice(array_reverse($ordered), $params['offset'], $params['limit']);
    $page = array_fill_keys($pageIdentities, true);
    $items = [];
    $matchingIds = [];
    // Complete this second verified stream even after finding the last page
    // item: footer/hash failures must never produce a partial success response.
    foreach (registry_document_iterator($registry) as $document) {
        if ($document['cadastral_ids'] === []) continue;
        $fields = development_fields($document);
        [$identity, $number, $district] = development_identity($document, $fields);
        $group = json_decode($groups[$identity], true, 4, JSON_THROW_ON_ERROR);
        if (!$group[7] || ($savedIds !== [] && !isset($savedIds[$identity]))) continue;
        foreach ($document['cadastral_ids'] as $id) $matchingIds[$id] = true;
        if (!isset($page[$identity]) || $document['document_hash'] !== $group[5]) continue;
        $source = $registry['sources'][$document['source_code']];
        $ids = array_slice($document['cadastral_ids'], 0, 100);
        $items[$identity] = ['id' => $identity, 'source_code' => $document['source_code'], 'source_name' => $source['label_bg'],
            'source_url' => $source['source_url'], 'record_key' => $number, 'issued_at' => $document['issued_at'] ?? null,
            'snapshot_date' => development_snapshot_date($document, $source), 'first_observed_at' => null,
            'observation_count' => $group[6], 'district' => $district,
            'address' => development_field($fields, ['адрес', 'address', 'местоположение', 'обхват', 'обхват и идентификатори', 'scope and identifiers', 'scope', 'location'], 1000),
            'description' => development_field($fields, ['обект', 'строеж/обект', 'строеж / обект', 'object', 'construction / object']),
            'investors' => development_investors($fields), 'cadastral_ids' => $ids,
            'cadastral_id_count' => count($document['cadastral_ids']), 'cadastral_ids_truncated' => count($ids) !== count($document['cadastral_ids']), 'plots' => []];
    }
    unset($groups);

    $mappedTotal = 0;
    $bounds = null;
    foreach (array_chunk(array_keys($matchingIds), 1000) as $chunk) {
        $summary = $pdo->query('SELECT COUNT(*) AS total, MIN(latitude) AS south, MAX(latitude) AS north, MIN(longitude) AS west, MAX(longitude) AS east FROM parcels WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND cadastral_id IN (' . quoted_ids($pdo, $chunk) . ')')->fetch();
        $mappedTotal += (int)$summary['total'];
        if ((int)$summary['total'] === 0) continue;
        foreach (['south', 'west'] as $edge) $bounds[$edge] = isset($bounds[$edge]) ? min($bounds[$edge], (float)$summary[$edge]) : (float)$summary[$edge];
        foreach (['north', 'east'] as $edge) $bounds[$edge] = isset($bounds[$edge]) ? max($bounds[$edge], (float)$summary[$edge]) : (float)$summary[$edge];
    }
    $pageIds = [];
    foreach ($items as $item) foreach ($item['cadastral_ids'] as $id) $pageIds[$id] = true;
    $coordinates = [];
    foreach (array_chunk(array_keys($pageIds), 1000) as $chunk) {
        foreach ($pdo->query('SELECT cadastral_id, latitude AS lat, longitude AS lng FROM parcels WHERE cadastral_id IN (' . quoted_ids($pdo, $chunk) . ')')->fetchAll() as $plot) {
            $coordinates[$plot['cadastral_id']] = ['cadastral_id' => $plot['cadastral_id'], 'lat' => $plot['lat'] === null ? null : (float)$plot['lat'], 'lng' => $plot['lng'] === null ? null : (float)$plot['lng']];
        }
    }
    $feed = [];
    foreach ($pageIdentities as $identity) {
        if (!isset($items[$identity])) throw new RuntimeException('A selected development observation is missing.');
        $item = $items[$identity];
        foreach ($item['cadastral_ids'] as $id) $item['plots'][] = $coordinates[$id] ?? ['cadastral_id' => $id, 'lat' => null, 'lng' => null];
        $feed[] = $item;
    }

    $sources = [];
    $latestSnapshot = null;
    $cutoff = null;
    $cutoffKnown = true;
    foreach (DEVELOPMENT_TYPES as $code) {
        $source = $registry['sources'][$code] ?? null;
        $snapshot = $source['snapshot_date'] ?? null;
        if ($snapshot !== null) $latestSnapshot = $latestSnapshot === null ? $snapshot : max($latestSnapshot, $snapshot);
        $sources[] = ['source_code' => $code, 'source_name' => $source['label_bg'] ?? DEVELOPMENT_LABELS[$code], 'source_url' => $source['source_url'] ?? null,
            'snapshot_date' => $snapshot, 'observations' => $observationCounts[$code], 'unlinked_observations' => $unlinkedCounts[$code],
            'date_min' => $sourceDateRanges[$code]['date_min'], 'date_max' => $sourceDateRanges[$code]['date_max'],
            'documents' => $typeCounts[$code], 'dated_documents' => $datedSourceCounts[$code], 'linked_plots' => $registry['source_plot_counts'][$code] ?? count($registry['source_ids'][$code] ?? [])];
        if (!in_array($code, $params['types'], true) || $typeCounts[$code] === 0) continue;
        if ($snapshot === null) $cutoffKnown = false;
        else $cutoff = $cutoff === null ? $snapshot : min($cutoff, $snapshot);
    }
    // A calendar period can be open at the capture cutoff. Closed periods are
    // still observed records, never proof of complete official city totals.
    $today = (new DateTimeImmutable('now', new DateTimeZone('Europe/Sofia')))->format('Y-m-d');
    $currentPeriod = substr($today, 0, $params['period'] === 'month' ? 7 : 4);
    foreach ($periods as &$row) {
        $periodKey = $row['period'];
        $row['partial'] = $periodKey >= $currentPeriod || ($cutoff !== null && $periodKey >= substr($cutoff, 0, strlen($periodKey)));
        $row['completeness_known'] = false;
    }
    unset($row);
    ksort($periods, SORT_STRING);
    krsort($years, SORT_NUMERIC);
    ksort($districts, SORT_STRING);
    $yearOptions = [];
    foreach ($years as $year => $count) $yearOptions[] = ['year' => $year, 'count' => $count];
    $typeOptions = [];
    foreach (DEVELOPMENT_TYPES as $code) $typeOptions[] = ['key' => $code, 'label' => DEVELOPMENT_LABELS[$code], 'count' => $typeCounts[$code]];
    return ['generated_at' => $registry['generated_at'], 'filters' => $params,
        'coverage' => ['scope' => 'available_exact_id_linked_register_documents', 'date_min' => $dateMin, 'date_max' => $dateMax,
            'latest_snapshot_date' => $latestSnapshot, 'cutoff_at' => $cutoffKnown ? $cutoff : null, 'cutoff_known' => $cutoffKnown,
            'observations' => $observations, 'linked_observations' => $linkedObservations, 'unlinked_observations' => $unlinked,
            'documents' => $typeCounts['total'], 'revision_observations' => $linkedObservations - $typeCounts['total'],
            'identity_fallback_documents' => $fallbackIdentities, 'unknown_date_documents' => $typeCounts['total'] - array_sum($datedSourceCounts),
            'first_observed_available' => false, 'complete_official_totals' => false, 'per_source' => $sources,
            'aggregation_note' => 'Налични документи с точен кадастрален идентификатор; един документ се брои веднъж за издател, номер и дата, а версиите се отчитат отделно. Записи без надеждна самоличност остават отделни наблюдения. Липсващи периоди не означават нула. Данните не доказват покупка, промяна на статут или започнал строеж.',
            'investor_note' => 'Показват се само изрично посочени юридически лица и публични организации с ролята им в източника. Възложителят не е доказан собственик или контакт за финансиране.'],
        'facets' => ['types' => $typeOptions, 'years' => $yearOptions, 'districts' => array_values($districts)],
        'totals' => ['documents' => $selectedTypeCounts['total'], 'observations' => $matchedObservations, 'dated_documents' => $dated,
            'identity_fallback_documents' => $selectedFallbackIdentities,
            'unknown_date_documents' => $selectedTypeCounts['total'] - $dated, 'linked_plots' => count($matchingIds),
            'mapped_plots' => $mappedTotal, 'published_investor_documents' => $knownInvestor, 'by_source' => $selectedTypeCounts],
        'periods' => array_values($periods), 'items' => $feed, 'bounds' => $bounds,
        'pagination' => ['offset' => $params['offset'], 'limit' => $params['limit'], 'total' => $selectedTypeCounts['total'],
            'has_more' => $params['offset'] + count($feed) < $selectedTypeCounts['total'], 'max_offset' => 2000]];
}
