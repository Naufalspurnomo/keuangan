<?php
declare(strict_types=1);

const EV_ADMIN_PATH = '/admin/';
const EV_SESSION_LIFETIME = 2592000;
const EV_MAX_IMAGE_BYTES = 5242880;
const EV_MAX_JSON_BYTES = 2097152;

function ev_error(int $status, string $code, string $message): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode(['error' => ['code' => $code, 'message' => $message]], JSON_UNESCAPED_SLASHES);
    exit;
}

function ev_header(string $name): string
{
    return trim((string) ($_SERVER['HTTP_' . strtoupper(str_replace('-', '_', $name))] ?? ''));
}

function ev_uuid(mixed $value): string
{
    $text = is_string($value) ? $value : '';
    if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iD', $text)) {
        ev_error(422, 'invalid_identifier', 'A valid resource identifier is required.');
    }
    return strtolower($text);
}

function ev_session(string $accountRoot): void
{
    $realRoot = realpath($accountRoot);
    $path = $accountRoot . '/.hollawall-admin-sessions';
    if ($realRoot === false || is_link($path)) {
        ev_error(503, 'session_storage_unavailable', 'Evidence service unavailable.');
    }
    if (!file_exists($path) && !mkdir($path, 0700, false)) {
        ev_error(503, 'session_storage_unavailable', 'Evidence service unavailable.');
    }
    clearstatcache(true, $path);
    $realPath = realpath($path);
    if (!is_dir($path) || is_link($path) || $realPath === false || dirname($realPath) !== $realRoot
        || fileowner($realPath) !== fileowner($realRoot) || ((int) fileperms($realPath) & 0777) !== 0700
        || !is_writable($realPath)) {
        ev_error(503, 'session_storage_insecure', 'Evidence service unavailable.');
    }
    if (session_name('hollawall_admin') === false
        || ini_set('session.use_strict_mode', '1') === false
        || ini_set('session.use_only_cookies', '1') === false
        || ini_set('session.gc_maxlifetime', (string) EV_SESSION_LIFETIME) === false
        || session_save_path($realPath) === false
        || !session_set_cookie_params([
            'lifetime' => EV_SESSION_LIFETIME, 'path' => EV_ADMIN_PATH, 'secure' => true,
            'httponly' => true, 'samesite' => 'Strict',
        ]) || !session_start()) {
        ev_error(503, 'session_configuration_unavailable', 'Evidence service unavailable.');
    }
    if (empty($_SESSION['hollawall_admin_user'])) {
        ev_error(401, 'authentication_required', 'Sign in required.');
    }
    $now = time();
    if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > EV_SESSION_LIFETIME) {
        $_SESSION = [];
        session_regenerate_id(true);
        ev_error(401, 'session_expired', 'Sign in required.');
    }
    $_SESSION['last_seen'] = $now;
}

function ev_same_origin(array $config): void
{
    $origin = rtrim(ev_header('Origin'), '/');
    $expected = rtrim((string) ($config['public_origin'] ?? ''), '/');
    if ($origin === '' || $expected === '' || !hash_equals($expected, $origin)
        || ev_header('Sec-Fetch-Site') !== 'same-origin') {
        ev_error(403, 'same_origin_required', 'Same-origin request required.');
    }
    $sessionCsrf = (string) ($_SESSION['csrf'] ?? '');
    $csrf = ev_header('X-CSRF-Token');
    if ($sessionCsrf === '' || $csrf === '' || !hash_equals($sessionCsrf, $csrf)) {
        ev_error(403, 'csrf_validation_failed', 'Request verification failed.');
    }
}

function ev_key(): string
{
    $key = ev_header('Idempotency-Key');
    if (!preg_match('/^[^\s\x00-\x1F\x7F]{16,128}$/uD', $key)) {
        ev_error(422, 'invalid_idempotency_key', 'Idempotency-Key header is invalid.');
    }
    return $key;
}

function ev_base(array $config): string
{
    $value = (string) ($config['upstream_projects_url'] ?? '');
    $parts = parse_url($value);
    $path = rtrim((string) ($parts['path'] ?? ''), '/');
    if (!is_array($parts) || strtolower((string) ($parts['scheme'] ?? '')) !== 'https'
        || (string) ($parts['host'] ?? '') === '' || isset($parts['user']) || isset($parts['pass'])
        || isset($parts['query']) || isset($parts['fragment']) || !str_ends_with($path, '/projects')) {
        ev_error(503, 'configuration_invalid', 'Evidence service unavailable.');
    }
    return substr(rtrim($value, '/'), 0, -strlen('/projects'));
}

function ev_proxy(string $method, string $url, string $token, array $headers, array|string|false $body, bool $image): never
{
    $response = '';
    $tooLarge = false;
    $limit = $image ? EV_MAX_IMAGE_BYTES : EV_MAX_JSON_BYTES;
    $curl = curl_init($url);
    if ($curl === false) {
        ev_error(502, 'upstream_unavailable', 'Evidence service unavailable.');
    }
    curl_setopt_array($curl, [
        CURLOPT_RETURNTRANSFER => false, CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 12, CURLOPT_TIMEOUT => 75, CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_POSTFIELDS => $body === false ? null : $body,
        CURLOPT_HTTPHEADER => array_merge(['X-Hollawall-Proxy-Token: ' . $token], $headers),
        CURLOPT_SSL_VERIFYPEER => true, CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_WRITEFUNCTION => static function ($handle, string $chunk) use (&$response, &$tooLarge, $limit): int {
            if (strlen($response) + strlen($chunk) > $limit) {
                $tooLarge = true;
                return 0;
            }
            $response .= $chunk;
            return strlen($chunk);
        },
    ]);
    $executed = curl_exec($curl);
    $status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
    $contentType = strtolower((string) curl_getinfo($curl, CURLINFO_CONTENT_TYPE));
    curl_close($curl);
    if ($executed === false || $tooLarge) {
        ev_error(502, 'upstream_unavailable', 'Evidence service unavailable.');
    }
    if ($image) {
        $valid = $status === 200 && (
            ($contentType === 'image/jpeg' && str_starts_with($response, "\xFF\xD8\xFF"))
            || ($contentType === 'image/png' && str_starts_with($response, "\x89PNG\r\n\x1A\n"))
            || ($contentType === 'image/webp' && strlen($response) >= 12 && str_starts_with($response, 'RIFF') && substr($response, 8, 4) === 'WEBP')
        );
        if (!$valid) {
            ev_error(502, 'invalid_upstream_response', 'Evidence service unavailable.');
        }
        http_response_code(200);
        header('Content-Type: ' . $contentType);
        header('Content-Length: ' . strlen($response));
        header('Content-Disposition: attachment; filename="payment-evidence"');
        header('Cache-Control: no-store, private');
        echo $response;
        exit;
    }
    $allowed = [200, 201, 400, 401, 403, 404, 409, 412, 413, 415, 422, 428, 503];
    if (!in_array($status, $allowed, true) || !str_contains($contentType, 'application/json')) {
        ev_error(502, 'invalid_upstream_response', 'Evidence service unavailable.');
    }
    try {
        $decoded = json_decode($response, true, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    } catch (JsonException $exception) {
        ev_error(502, 'invalid_upstream_response', 'Evidence service unavailable.');
    }
    if (in_array($status, [200, 201], true)) {
        if (($decoded['api_version'] ?? null) !== 'dashboard.v1' || !is_array($decoded['data'] ?? null)) {
            ev_error(502, 'invalid_upstream_response', 'Evidence service unavailable.');
        }
        $output = $decoded;
    } elseif (is_string($decoded['error']['code'] ?? null) && is_string($decoded['error']['message'] ?? null)) {
        $output = ['error' => ['code' => $decoded['error']['code'], 'message' => $decoded['error']['message']]];
    } else {
        ev_error(502, 'invalid_upstream_response', 'Evidence service unavailable.');
    }
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode($output, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store, private');

$accountRoot = dirname(__DIR__, 3);
ev_session($accountRoot);
$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: $accountRoot . '/.hollawall-admin.php';
if (!is_file($configPath)) {
    ev_error(503, 'configuration_unavailable', 'Evidence service unavailable.');
}
$config = require $configPath;
if (!is_array($config) || !hash_equals((string) ($config['username'] ?? ''), (string) $_SESSION['hollawall_admin_user'])) {
    ev_error(403, 'owner_required', 'Owner access required.');
}
$token = (string) ($config['proxy_token'] ?? '');
if (!preg_match('/^[^\x00-\x1F\x7F]{16,512}$/D', $token)) {
    ev_error(503, 'configuration_invalid', 'Evidence service unavailable.');
}
$base = ev_base($config);
$method = (string) ($_SERVER['REQUEST_METHOD'] ?? '');
$action = is_string($_GET['action'] ?? null) ? $_GET['action'] : '';

if ($method === 'GET' && $action === 'list' && count($_GET) === 2) {
    $project = ev_uuid($_GET['project_id'] ?? null);
    session_write_close();
    ev_proxy('GET', $base . '/projects/' . $project . '/evidence', $token, ['Accept: application/json'], false, false);
}
if ($method === 'GET' && $action === 'download' && count($_GET) === 2) {
    $evidence = ev_uuid($_GET['evidence_id'] ?? null);
    session_write_close();
    ev_proxy('GET', $base . '/evidence/' . $evidence . '/download', $token, ['Accept: image/jpeg, image/png, image/webp'], false, true);
}
if ($method !== 'POST') {
    header('Allow: GET, POST');
    ev_error(405, 'method_not_allowed', 'GET or POST required.');
}
if (($config['project_document_writes_enabled'] ?? false) !== true) {
    ev_error(503, 'project_document_writes_disabled', 'Evidence writes are disabled.');
}
ev_same_origin($config);
$key = ev_key();

if ($action === 'upload') {
    if (count($_GET) !== 2) {
        ev_error(422, 'unsupported_fields', 'Evidence query fields are invalid.');
    }
    $project = ev_uuid($_GET['project_id'] ?? null);
    if (array_keys($_POST) !== ['ledger_source_key'] || array_keys($_FILES) !== ['evidence']) {
        ev_error(422, 'invalid_evidence_upload', 'Evidence upload fields are invalid.');
    }
    $file = $_FILES['evidence'];
    if (!is_array($file) || ($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK
        || !is_uploaded_file((string) ($file['tmp_name'] ?? ''))
        || (int) ($file['size'] ?? 0) < 1 || (int) $file['size'] > EV_MAX_IMAGE_BYTES) {
        ev_error(413, 'request_too_large', 'Evidence image must be 1 byte to 5 MiB.');
    }
    $mime = (new finfo(FILEINFO_MIME_TYPE))->file((string) $file['tmp_name']);
    if (!in_array($mime, ['image/jpeg', 'image/png', 'image/webp'], true)) {
        ev_error(415, 'invalid_evidence_image', 'Evidence must be JPEG, PNG, or WebP.');
    }
    $curlFile = new CURLFile((string) $file['tmp_name'], $mime, basename((string) $file['name']));
    $payload = ['ledger_source_key' => (string) $_POST['ledger_source_key'], 'evidence' => $curlFile];
    session_write_close();
    ev_proxy('POST', $base . '/projects/' . $project . '/evidence', $token, [
        'Accept: application/json', 'Idempotency-Key: ' . $key,
    ], $payload, false);
}

if ($action === 'review') {
    if (count($_GET) !== 2) {
        ev_error(422, 'unsupported_fields', 'Evidence query fields are invalid.');
    }
    $evidence = ev_uuid($_GET['evidence_id'] ?? null);
    $raw = file_get_contents('php://input', false, null, 0, 262145);
    try {
        $body = json_decode((string) $raw, true, 16, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    } catch (JsonException $exception) {
        ev_error(422, 'invalid_json', 'Request body contains invalid JSON.');
    }
    if (!is_array($body) || array_is_list($body)
        || array_diff(array_keys($body), ['expected_version', 'status', 'note'])
        || !is_int($body['expected_version'] ?? null)
        || !in_array($body['status'] ?? null, ['approved', 'rejected'], true)
        || !is_string($body['note'] ?? null)) {
        ev_error(422, 'invalid_evidence_review', 'Evidence review fields are invalid.');
    }
    $payload = json_encode([
        'idempotency_key' => $key, 'expected_version' => $body['expected_version'],
        'status' => $body['status'], 'note' => $body['note'],
    ], JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    session_write_close();
    ev_proxy('POST', $base . '/evidence/' . $evidence . '/review', $token, [
        'Accept: application/json', 'Content-Type: application/json',
        'Idempotency-Key: ' . $key, 'If-Match: "' . $body['expected_version'] . '"',
    ], $payload, false);
}

ev_error(400, 'invalid_action', 'Unsupported evidence action.');
