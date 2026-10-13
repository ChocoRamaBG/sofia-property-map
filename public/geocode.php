<?php
declare(strict_types=1);

// End-user initiated address lookup only; never use this endpoint in the parsers.
// https://operations.osmfoundation.org/policies/nominatim/
// The private cache/lock is incidental provider-policy state, not registry data.
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
// Turn runtime warnings into the same opaque JSON error, even on hosts that
// display PHP warnings. Suppressed optional chmod failures remain harmless.
set_error_handler(static function (int $severity, string $message, string $file, int $line): bool {
    if (!(error_reporting() & $severity)) return false;
    throw new ErrorException($message, 0, $severity, $file, $line);
});

const ADDRESS_CACHE_MAX_BYTES = 2 * 1024 * 1024;
const ADDRESS_CACHE_MAX_ENTRIES = 150;
const ADDRESS_CACHE_TTL = 7 * 86400;
const ADDRESS_MIN_INTERVAL = 1.1;
const ADDRESS_SOURCE_MAX_BYTES = 256 * 1024;
const ADDRESS_QUERY_VERSION = 'sofia-street-prefix-v2';
const ADDRESS_SOUTH = 42.45;
const ADDRESS_NORTH = 42.90;
const ADDRESS_WEST = 23.05;
const ADDRESS_EAST = 23.65;

function address_respond(array $body, int $status = 200, ?int $retryAfter = null): void {
    http_response_code($status);
    if ($retryAfter !== null) header('Retry-After: ' . $retryAfter);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function address_https_url(string $url): bool {
    $parts = parse_url($url);
    return is_array($parts) && ($parts['scheme'] ?? '') === 'https' && isset($parts['host'])
        && !isset($parts['user']) && !isset($parts['pass']) && !isset($parts['port'])
        && !preg_match('/[\x00-\x20]/', $url);
}

function address_provider(): array {
    $config = [
        'endpoint' => 'https://nominatim.openstreetmap.org/search',
        'label' => 'OpenStreetMap Nominatim',
        'policy_url' => 'https://operations.osmfoundation.org/policies/nominatim/',
        'privacy_url' => 'https://osmfoundation.org/wiki/Privacy_Policy',
        'site_origin' => 'https://sofiapermits.site.je',
        'enabled' => true,
        'approved_provider_origins' => [],
    ];
    // A compatible provider can be changed by trusted host configuration without
    // a frontend release. Never accept a provider URL from a public request.
    $configPath = __DIR__ . '/private/geocode-config.php';
    if (is_file($configPath)) {
        $override = require $configPath;
        if (!is_array($override)) throw new RuntimeException('Invalid provider configuration.');
        $config = array_replace($config, $override);
    }
    if (!is_string($config['endpoint']) || !address_https_url($config['endpoint'])) throw new RuntimeException('Invalid provider.');
    $parts = parse_url($config['endpoint']);
    $origin = 'https://' . strtolower($parts['host']);
    $approved = $config['approved_provider_origins'];
    if (!is_array($approved) || count($approved) > 5) throw new RuntimeException('Invalid provider.');
    $approved[] = 'https://nominatim.openstreetmap.org';
    if (!in_array($origin, $approved, true) || isset($parts['query']) || isset($parts['fragment'])
        || !preg_match('~^/[a-zA-Z0-9/_.-]+$~', $parts['path'] ?? '')) throw new RuntimeException('Invalid provider.');
    foreach (['policy_url', 'privacy_url', 'site_origin'] as $key) {
        if (!is_string($config[$key]) || !address_https_url($config[$key])) throw new RuntimeException('Invalid provider.');
    }
    if (!is_string($config['label']) || strlen($config['label']) > 120 || !preg_match('//u', $config['label'])) throw new RuntimeException('Invalid provider.');
    return $config;
}

function address_provider_public(array $provider): array {
    return [
        'label' => $provider['label'],
        'policy_url' => $provider['policy_url'],
        'privacy_url' => $provider['privacy_url'],
        'attribution' => '© OpenStreetMap contributors · ODbL',
        'attribution_url' => 'https://www.openstreetmap.org/copyright',
        'enabled' => $provider['enabled'] === true,
    ];
}

function address_cache_write($handle, array $state): void {
    // Drop the oldest response first; never evict rate-limit state.
    uasort($state['entries'], static function ($left, $right): int { return $left['stored_at'] <=> $right['stored_at']; });
    while (count($state['entries']) > ADDRESS_CACHE_MAX_ENTRIES) array_shift($state['entries']);
    $encoded = json_encode($state, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    while (strlen($encoded) > ADDRESS_CACHE_MAX_BYTES && $state['entries'] !== []) {
        array_shift($state['entries']);
        $encoded = json_encode($state, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    }
    if (strlen($encoded) > ADDRESS_CACHE_MAX_BYTES || !rewind($handle) || !ftruncate($handle, 0)) throw new RuntimeException('Cache unavailable.');
    $written = 0;
    $length = strlen($encoded);
    while ($written < $length) {
        $step = fwrite($handle, substr($encoded, $written));
        if ($step === false || $step === 0) throw new RuntimeException('Cache unavailable.');
        $written += $step;
    }
    if (!fflush($handle)) throw new RuntimeException('Cache unavailable.');
}

function address_clean_string($value, int $maxBytes): ?string {
    if (!is_string($value) || $value === '' || strlen($value) > $maxBytes || !preg_match('//u', $value)) return null;
    return preg_replace('/[\x00-\x1F\x7F]/u', ' ', $value);
}

function address_provider_query(string $query): string {
    // Bulgarian street-type prefixes can prevent Nominatim from matching the
    // stored road name. Remove only a leading street-type token, preserving the
    // actual name, house number and city. Never broaden a missing house number
    // silently: street-only lookup is a separate explicit user action.
    $query = preg_replace('/^(?:(?:ул|ul|бул|bul|пл|pl)\.\s*|(?:ул|улица|ul|ulitsa|бул|булевард|bul|boulevard|пл|площад|pl|square)(?:\s+|(?=["„“”«»])))/iu', '', $query);
    $query = preg_replace('/["„“”«»]/u', '', $query);
    $query = trim(preg_replace('/\s+/u', ' ', $query));
    return preg_match('/(?:\bsofia\b|софия)/iu', $query) ? $query : $query . ', София, България';
}

function address_results(array $rows): array {
    if (count($rows) > 5) throw new RuntimeException('Invalid provider response.');
    $results = [];
    foreach ($rows as $row) {
        if (!is_array($row) || !is_numeric($row['lat'] ?? null) || !is_numeric($row['lon'] ?? null)) throw new RuntimeException('Invalid provider response.');
        $lat = (float)$row['lat'];
        $lng = (float)$row['lon'];
        $label = address_clean_string($row['display_name'] ?? null, 1800);
        if ($label === null || !is_finite($lat) || !is_finite($lng)) throw new RuntimeException('Invalid provider response.');
        if ($lat < ADDRESS_SOUTH || $lat > ADDRESS_NORTH || $lng < ADDRESS_WEST || $lng > ADDRESS_EAST) continue;
        $type = $row['osm_type'] ?? null;
        $osmId = $row['osm_id'] ?? null;
        if (!in_array($type, ['node', 'way', 'relation'], true) || (!is_int($osmId) && !is_string($osmId)) || !preg_match('/^[1-9][0-9]{0,19}$/', (string)$osmId)) throw new RuntimeException('Invalid provider response.');
        $id = $type . '-' . $osmId;
        $bounds = null;
        $box = $row['boundingbox'] ?? null;
        if (is_array($box) && count($box) === 4 && count(array_filter($box, 'is_numeric')) === 4) {
            [$south, $north, $west, $east] = array_map('floatval', array_values($box));
            if ($south <= $lat && $lat <= $north && $west <= $lng && $lng <= $east
                && $south >= ADDRESS_SOUTH && $north <= ADDRESS_NORTH && $west >= ADDRESS_WEST && $east <= ADDRESS_EAST) {
                $bounds = ['south' => $south, 'north' => $north, 'west' => $west, 'east' => $east];
            }
        }
        $address = is_array($row['address'] ?? null) ? $row['address'] : [];
        $rank = is_numeric($row['place_rank'] ?? null) ? (int)$row['place_rank'] : 0;
        $precision = address_clean_string($address['house_number'] ?? null, 120) !== null && $rank >= 28 ? 'address' : ($rank >= 26 ? 'street' : 'area');
        $results[$id] = ['id' => $id, 'label' => $label, 'lat' => $lat, 'lng' => $lng, 'bounds' => $bounds,
            'precision' => $precision, 'source_url' => 'https://www.openstreetmap.org/' . $type . '/' . $osmId];
    }
    return array_values($results);
}

$cacheHandle = null;
try {
    $provider = address_provider();
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    if ($method === 'GET' && ($_GET['action'] ?? '') === 'meta') address_respond(['provider' => address_provider_public($provider)]);
    if ($method !== 'POST') {
        header('Allow: POST');
        address_respond(['error' => 'method_not_allowed'], 405);
    }
    if ($provider['enabled'] !== true) address_respond(['error' => 'unavailable'], 503);
    // Same-origin browser use only. No public CORS, JSONP or request-selected URLs.
    $requestOrigin = $_SERVER['HTTP_ORIGIN'] ?? null;
    if ($requestOrigin !== null && $requestOrigin !== $provider['site_origin']) address_respond(['error' => 'forbidden'], 403);
    if (strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '')[0])) !== 'application/json') address_respond(['error' => 'invalid_query'], 400);
    if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 2048) address_respond(['error' => 'invalid_query'], 400);
    $body = file_get_contents('php://input', false, null, 0, 2049);
    if (!is_string($body) || strlen($body) > 2048) address_respond(['error' => 'invalid_query'], 400);
    try { $input = json_decode($body, true, 4, JSON_THROW_ON_ERROR); }
    catch (JsonException $error) { address_respond(['error' => 'invalid_query'], 400); }
    $query = is_array($input) ? ($input['q'] ?? null) : null;
    $language = is_array($input) ? ($input['lang'] ?? 'bg') : 'bg';
    if (!is_string($query) || !preg_match('//u', $query) || !in_array($language, ['bg', 'en'], true)
        || preg_match('/[\x00-\x1F\x7F]/u', $query)) address_respond(['error' => 'invalid_query'], 400);
    $query = preg_replace('/^\s+|\s+$/u', '', $query);
    $queryLength = preg_match_all('/./us', $query);
    if ($queryLength < 3 || $queryLength > 160) address_respond(['error' => 'invalid_query'], 400);
    $query = preg_replace('/\s+/u', ' ', $query);
    $providerQuery = address_provider_query($query);
    $folded = function_exists('mb_strtolower') ? mb_strtolower($providerQuery, 'UTF-8') : strtolower($providerQuery);
    $cacheKey = hash('sha256', ADDRESS_QUERY_VERSION . '\n' . $provider['endpoint'] . '\n' . $language . '\n' . $folded);

    $privatePath = realpath(__DIR__ . '/private');
    if ($privatePath === false || !is_file($privatePath . '/.htaccess')) throw new RuntimeException('Cache unavailable.');
    $cachePath = $privatePath . '/geocode-cache.json';
    if (is_link($cachePath) || (is_file($cachePath) && filesize($cachePath) > ADDRESS_CACHE_MAX_BYTES)) throw new RuntimeException('Cache unavailable.');
    $cacheHandle = fopen($cachePath, 'c+');
    if ($cacheHandle === false) throw new RuntimeException('Cache unavailable.');
    @chmod($cachePath, 0600);
    $lockDeadline = microtime(true) + 0.25;
    $locked = false;
    do {
        $locked = flock($cacheHandle, LOCK_EX | LOCK_NB);
        if (!$locked) usleep(25000);
    } while (!$locked && microtime(true) < $lockDeadline);
    if (!$locked) address_respond(['error' => 'busy', 'retry_after' => 2], 429, 2);
    rewind($cacheHandle);
    $raw = stream_get_contents($cacheHandle, ADDRESS_CACHE_MAX_BYTES + 1);
    if (!is_string($raw) || strlen($raw) > ADDRESS_CACHE_MAX_BYTES) throw new RuntimeException('Cache unavailable.');
    $state = $raw === '' ? ['version' => 1, 'last_request_at' => 0, 'cooldown_until' => 0, 'requests' => [], 'entries' => []]
        : json_decode($raw, true, 20, JSON_THROW_ON_ERROR);
    if (!is_array($state) || ($state['version'] ?? null) !== 1 || !is_numeric($state['last_request_at'] ?? null)
        || !is_numeric($state['cooldown_until'] ?? null) || !is_array($state['requests'] ?? null)
        || count($state['requests']) > 120 || !is_array($state['entries'] ?? null)
        || count($state['entries']) > ADDRESS_CACHE_MAX_ENTRIES) throw new RuntimeException('Cache unavailable.');
    $now = microtime(true);
    foreach ($state['entries'] as $key => $entry) {
        if (!is_string($key) || !preg_match('/^[a-f0-9]{64}$/', $key) || !is_array($entry) || !is_numeric($entry['stored_at'] ?? null)
            || !is_array($entry['results'] ?? null) || count($entry['results']) > 5) throw new RuntimeException('Cache unavailable.');
        if ($entry['stored_at'] < $now - ADDRESS_CACHE_TTL) unset($state['entries'][$key]);
    }
    if (isset($state['entries'][$cacheKey])) {
        address_respond(['results' => $state['entries'][$cacheKey]['results'], 'provider' => address_provider_public($provider), 'cached' => true]);
    }
    $state['requests'] = array_values(array_filter($state['requests'], static function ($timestamp) use ($now): bool {
        if (!is_numeric($timestamp)) throw new RuntimeException('Cache unavailable.');
        return $timestamp > $now - 3600;
    }));
    $recent = array_filter($state['requests'], static function ($timestamp) use ($now): bool { return $timestamp > $now - 600; });
    $wait = max(0, ADDRESS_MIN_INTERVAL - ($now - $state['last_request_at']), $state['cooldown_until'] - $now);
    if ($wait > 0 || count($recent) >= 30 || count($state['requests']) >= 120) {
        $retry = $wait > 0 ? min(3600, max(1, (int)ceil($wait))) : (count($recent) >= 30 ? 60 : 300);
        address_respond(['error' => 'rate_limited', 'retry_after' => $retry], 429, $retry);
    }
    if (!function_exists('curl_init')) throw new RuntimeException('Provider unavailable.');
    // Persist the global limiter before sending. A failed provider call consumes
    // the same budget, and failures never cause unbounded automated retries.
    $state['last_request_at'] = $now;
    $state['requests'][] = $now;
    address_cache_write($cacheHandle, $state);
    $url = $provider['endpoint'] . '?' . http_build_query([
        'q' => $providerQuery, 'format' => 'jsonv2', 'addressdetails' => 1, 'limit' => 5,
        'countrycodes' => 'bg', 'layer' => 'address', 'bounded' => 1,
        'viewbox' => ADDRESS_WEST . ',' . ADDRESS_NORTH . ',' . ADDRESS_EAST . ',' . ADDRESS_SOUTH,
        'accept-language' => $language === 'en' ? 'en,bg' : 'bg,en',
    ], '', '&', PHP_QUERY_RFC3986);
    $responseBody = '';
    $retryAfter = null;
    $curl = curl_init($url);
    if ($curl === false) throw new RuntimeException('Provider unavailable.');
    curl_setopt_array($curl, [
        CURLOPT_CONNECTTIMEOUT_MS => 1200, CURLOPT_TIMEOUT_MS => 3000,
        CURLOPT_FOLLOWLOCATION => false, CURLOPT_SSL_VERIFYPEER => true, CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
        CURLOPT_USERAGENT => 'SofiaPermits/1.0 (address lookup; ' . $provider['site_origin'] . '/about.html)',
        CURLOPT_HTTPHEADER => ['Accept: application/json'],
        CURLOPT_WRITEFUNCTION => static function ($handle, string $chunk) use (&$responseBody): int {
            if (strlen($responseBody) + strlen($chunk) > ADDRESS_SOURCE_MAX_BYTES) return 0;
            $responseBody .= $chunk;
            return strlen($chunk);
        },
        CURLOPT_HEADERFUNCTION => static function ($handle, string $line) use (&$retryAfter): int {
            if (preg_match('/^Retry-After:\s*([0-9]+)\s*$/i', trim($line), $matches)) $retryAfter = min(3600, max(1, (int)$matches[1]));
            return strlen($line);
        },
    ]);
    $ok = curl_exec($curl);
    $status = (int)curl_getinfo($curl, CURLINFO_HTTP_CODE);
    curl_close($curl);
    if ($status === 429 || $status === 503) {
        $retryAfter = $retryAfter ?? 60;
        $state['cooldown_until'] = microtime(true) + $retryAfter;
        address_cache_write($cacheHandle, $state);
        address_respond(['error' => 'rate_limited', 'retry_after' => $retryAfter], 429, $retryAfter);
    }
    if ($ok === false || $status !== 200) throw new RuntimeException('Provider unavailable.');
    $rows = json_decode($responseBody, true, 20, JSON_THROW_ON_ERROR);
    if (!is_array($rows) || array_keys($rows) !== ($rows === [] ? [] : range(0, count($rows) - 1))) throw new RuntimeException('Invalid provider response.');
    $results = address_results($rows);
    $state['entries'][$cacheKey] = ['stored_at' => microtime(true), 'results' => $results];
    address_cache_write($cacheHandle, $state);
    address_respond(['results' => $results, 'provider' => address_provider_public($provider), 'cached' => false]);
} catch (Throwable $error) {
    // No query, provider body, secret configuration or filesystem error is logged
    // or returned to the browser. The client receives a stable translated state.
    address_respond(['error' => 'unavailable'], 503);
}
