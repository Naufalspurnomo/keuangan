<?php
declare(strict_types=1);

const IR_ADMIN_PATH = '/admin/';
const IR_SESSION_LIFETIME = 2592000;
const IR_SESSION_RENEW_AFTER = 86400;
const IR_MAX_REQUEST_BYTES = 8192;
const IR_MAX_RESPONSE_BYTES = 1048576;

function ir_error(int $status, string $code, string $message): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode(['error' => ['code' => $code, 'message' => $message]], JSON_UNESCAPED_SLASHES);
    exit;
}

function ir_header(string $name): string
{
    $serverName = 'HTTP_' . strtoupper(str_replace('-', '_', $name));
    return trim((string) ($_SERVER[$serverName] ?? ''));
}

function ir_exact_fields(array $values, array $allowed): void
{
    foreach (array_keys($values) as $field) {
        if (!is_string($field) || !in_array($field, $allowed, true)) {
            ir_error(422, 'unsupported_fields', 'Request contains unsupported fields.');
        }
    }
}

function ir_event_key(mixed $value): string
{
    $key = is_string($value) ? $value : '';
    if (!preg_match('/^[0-9a-f]{64}$/D', $key)) {
        ir_error(422, 'invalid_event_key', 'Review event identifier is invalid.');
    }
    return $key;
}

function ir_session(string $accountRoot): void
{
    $realAccountRoot = realpath($accountRoot);
    $sessionPath = $accountRoot . '/.hollawall-admin-sessions';
    if ($realAccountRoot === false || is_link($sessionPath)) {
        ir_error(503, 'session_storage_unavailable', 'Review service unavailable.');
    }
    if (!file_exists($sessionPath) && !mkdir($sessionPath, 0700, false)) {
        ir_error(503, 'session_storage_unavailable', 'Review service unavailable.');
    }
    clearstatcache(true, $sessionPath);
    $realSessionPath = realpath($sessionPath);
    if (!is_dir($sessionPath)
        || is_link($sessionPath)
        || $realSessionPath === false
        || dirname($realSessionPath) !== $realAccountRoot
        || fileowner($realSessionPath) !== fileowner($realAccountRoot)
        || ((int) fileperms($realSessionPath) & 0777) !== 0700
        || !is_writable($realSessionPath)) {
        ir_error(503, 'session_storage_insecure', 'Review service unavailable.');
    }
    if (session_name('hollawall_admin') === false
        || ini_set('session.use_strict_mode', '1') === false
        || ini_set('session.use_only_cookies', '1') === false
        || ini_set('session.gc_maxlifetime', (string) IR_SESSION_LIFETIME) === false
        || session_save_path($realSessionPath) === false
        || session_save_path() !== $realSessionPath
        || !session_set_cookie_params([
            'lifetime' => IR_SESSION_LIFETIME,
            'path' => IR_ADMIN_PATH,
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Strict',
        ])) {
        ir_error(503, 'session_configuration_unavailable', 'Review service unavailable.');
    }
    if (!session_start()) {
        ir_error(503, 'session_start_failed', 'Review service unavailable.');
    }
    if (empty($_SESSION['hollawall_admin_user'])) {
        ir_error(401, 'authentication_required', 'Sign in required.');
    }
    $now = time();
    if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > IR_SESSION_LIFETIME) {
        $_SESSION = [];
        session_regenerate_id(true);
        ir_error(401, 'session_expired', 'Sign in required.');
    }
    $_SESSION['last_seen'] = $now;
    if ($now - (int) ($_SESSION['cookie_renewed_at'] ?? 0) >= IR_SESSION_RENEW_AFTER) {
        $_SESSION['cookie_renewed_at'] = $now;
        setcookie(session_name(), session_id(), [
            'expires' => $now + IR_SESSION_LIFETIME,
            'path' => IR_ADMIN_PATH,
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Strict',
        ]);
    }
}

function ir_upstream_url(mixed $value): string
{
    $url = is_string($value) ? $value : '';
    $parts = parse_url($url);
    if (!is_array($parts)
        || strtolower((string) ($parts['scheme'] ?? '')) !== 'https'
        || (string) ($parts['host'] ?? '') === ''
        || isset($parts['user'])
        || isset($parts['pass'])
        || isset($parts['query'])
        || isset($parts['fragment'])
        || rtrim((string) ($parts['path'] ?? ''), '/') !== '/api/dashboard/v1/inbox/reviews') {
        ir_error(503, 'configuration_invalid', 'Review service unavailable.');
    }
    return rtrim($url, '/');
}

function ir_json_body(): array
{
    $contentType = trim((string) ($_SERVER['CONTENT_TYPE'] ?? ''));
    if (!preg_match('/^application\/json(?:\s*;\s*charset=utf-8)?$/iD', $contentType)) {
        ir_error(415, 'json_required', 'Content-Type must be application/json.');
    }
    $contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($contentLength > IR_MAX_REQUEST_BYTES) {
        ir_error(413, 'request_too_large', 'Request body is too large.');
    }
    $raw = file_get_contents('php://input', false, null, 0, IR_MAX_REQUEST_BYTES + 1);
    if ($raw === false || $raw === '') {
        ir_error(422, 'json_object_required', 'Request body must be a JSON object.');
    }
    if (strlen($raw) > IR_MAX_REQUEST_BYTES) {
        ir_error(413, 'request_too_large', 'Request body is too large.');
    }
    try {
        $body = json_decode($raw, true, 16, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    } catch (JsonException $exception) {
        ir_error(422, 'invalid_json', 'Request body contains invalid JSON.');
    }
    if (!is_array($body) || array_is_list($body)) {
        ir_error(422, 'json_object_required', 'Request body must be a JSON object.');
    }
    return $body;
}

function ir_post_validation(array $config): array
{
    $origin = rtrim(ir_header('Origin'), '/');
    $expectedOrigin = rtrim((string) ($config['public_origin'] ?? ''), '/');
    if ($origin === ''
        || $expectedOrigin === ''
        || !hash_equals($expectedOrigin, $origin)
        || ir_header('Sec-Fetch-Site') !== 'same-origin') {
        ir_error(403, 'same_origin_required', 'Same-origin request required.');
    }
    $sessionCsrf = (string) ($_SESSION['csrf'] ?? '');
    $requestCsrf = ir_header('X-CSRF-Token');
    if ($sessionCsrf === '' || $requestCsrf === '' || !hash_equals($sessionCsrf, $requestCsrf)) {
        ir_error(403, 'csrf_validation_failed', 'Request verification failed.');
    }
    $key = ir_header('Idempotency-Key');
    if (!preg_match('/^[^\s\x00-\x1F\x7F]{16,128}$/uD', $key)) {
        ir_error(422, 'idempotency_key_required', 'A valid Idempotency-Key is required.');
    }
    $body = ir_json_body();
    ir_exact_fields($body, ['action', 'reason', 'expected_status']);
    if (!in_array($body['action'] ?? null, ['ignore', 'confirm_processed'], true)) {
        ir_error(422, 'invalid_review_action', 'Unsupported review action.');
    }
    $reason = $body['reason'] ?? null;
    if (!is_string($reason) || trim($reason) === '' || strlen(trim($reason)) > 1000) {
        ir_error(422, 'invalid_review_reason', 'Review reason must be 1 to 1000 characters.');
    }
    $expected = $body['expected_status'] ?? null;
    if (!is_string($expected) || !preg_match('/^needs_review(?:_[a-z0-9_]+)?$/D', $expected)) {
        ir_error(422, 'invalid_expected_status', 'Expected review status is invalid.');
    }
    return [[
        'action' => $body['action'],
        'reason' => trim($reason),
        'expected_status' => $expected,
    ], $key, $requestCsrf];
}

function ir_text(array $source, string $field, bool $nullable = false): string|null
{
    $value = $source[$field] ?? null;
    if ($nullable && $value === null) {
        return null;
    }
    if (!is_string($value) || strlen($value) > 65536) {
        ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
    }
    return $value;
}

function ir_item(mixed $value, bool $detail = false): array
{
    if (!is_array($value) || array_is_list($value)) {
        ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
    }
    $key = ir_text($value, 'event_key');
    if (!preg_match('/^[0-9a-f]{64}$/D', $key)
        || !is_bool($value['is_group'] ?? null)
        || !is_bool($value['finance_signal'] ?? null)
        || !is_int($value['payload_score'] ?? null)
        || !is_int($value['attempts'] ?? null)) {
        ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
    }
    $safe = [
        'event_key' => $key,
        'provider' => ir_text($value, 'provider'),
        'message_id' => ir_text($value, 'message_id'),
        'event_type' => ir_text($value, 'event_type'),
        'is_group' => $value['is_group'],
        'finance_signal' => $value['finance_signal'],
        'payload_score' => $value['payload_score'],
        'status' => ir_text($value, 'status'),
        'result_status' => ir_text($value, 'result_status'),
        'attempts' => $value['attempts'],
        'received_at' => ir_text($value, 'received_at'),
        'updated_at' => ir_text($value, 'updated_at'),
    ];
    if ($detail) {
        if (!is_bool($value['media_available'] ?? null)) {
            ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
        }
        $safe['body_text'] = ir_text($value, 'body_text');
        $safe['quoted_message_id'] = ir_text($value, 'quoted_message_id', true);
        $safe['media_available'] = $value['media_available'];
    }
    return $safe;
}

function ir_sanitize(int $status, array $decoded, string $route, bool $localWrites): array
{
    if ($status === 200 && ($decoded['api_version'] ?? null) === 'dashboard.v1' && is_array($decoded['data'] ?? null)) {
        $data = $decoded['data'];
        if ($route === 'list') {
            if (!is_array($data['items'] ?? null)
                || !is_bool($data['writes_enabled'] ?? null)
                || !is_array($data['allowed_actions'] ?? null)
                || !is_int($data['total'] ?? null)
                || !is_int($data['offset'] ?? null)
                || !is_int($data['limit'] ?? null)
                || !is_bool($data['has_more'] ?? null)) {
                ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
            }
            $allowed = [];
            if ($localWrites && $data['writes_enabled'] === true) {
                foreach ($data['allowed_actions'] as $action) {
                    if (in_array($action, ['ignore', 'confirm_processed'], true)) {
                        $allowed[] = $action;
                    }
                }
            }
            return ['api_version' => 'dashboard.v1', 'data' => [
                'items' => array_map(static fn ($item) => ir_item($item), $data['items']),
                'writes_enabled' => $localWrites && $data['writes_enabled'] === true,
                'allowed_actions' => array_values(array_unique($allowed)),
                'total' => $data['total'],
                'offset' => $data['offset'],
                'limit' => $data['limit'],
                'has_more' => $data['has_more'],
            ]];
        }
        if ($route === 'detail') {
            return ['api_version' => 'dashboard.v1', 'data' => ir_item($data, true)];
        }
        if (!is_string($data['event_key'] ?? null)
            || !preg_match('/^[0-9a-f]{64}$/D', $data['event_key'])
            || !is_string($data['message_id'] ?? null)
            || !in_array($data['action'] ?? null, ['ignore', 'confirm_processed'], true)
            || !is_string($data['status'] ?? null)) {
            ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
        }
        return ['api_version' => 'dashboard.v1', 'data' => [
            'event_key' => $data['event_key'],
            'message_id' => $data['message_id'],
            'action' => $data['action'],
            'status' => $data['status'],
        ]];
    }
    $error = $decoded['error'] ?? null;
    if ($status !== 200
        && is_array($error)
        && is_string($error['code'] ?? null)
        && is_string($error['message'] ?? null)
        && preg_match('/^[a-z][a-z0-9_]{0,63}$/D', $error['code'])
        && strlen($error['message']) <= 256) {
        return ['error' => ['code' => $error['code'], 'message' => $error['message']]];
    }
    ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
}

function ir_proxy(string $method, string $url, array|false $payload, string $route, string $token, bool $localWrites, string $commandKey = '', string $csrf = ''): never
{
    $responseBody = '';
    $tooLarge = false;
    $headers = ['Accept: application/json', 'X-Hollawall-Proxy-Token: ' . $token];
    $body = null;
    if ($payload !== false) {
        try {
            $body = json_encode($payload, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        } catch (JsonException $exception) {
            ir_error(422, 'invalid_json', 'Request body contains invalid JSON.');
        }
        $headers[] = 'Content-Type: application/json';
        $headers[] = 'X-CSRF-Token: ' . $csrf;
        $headers[] = 'Idempotency-Key: ' . $commandKey;
    }
    $curl = curl_init($url);
    if ($curl === false) {
        ir_error(502, 'upstream_unavailable', 'Review service unavailable.');
    }
    curl_setopt_array($curl, [
        CURLOPT_RETURNTRANSFER => false,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 12,
        CURLOPT_TIMEOUT => 45,
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_WRITEFUNCTION => static function ($handle, string $chunk) use (&$responseBody, &$tooLarge): int {
            if (strlen($responseBody) + strlen($chunk) > IR_MAX_RESPONSE_BYTES) {
                $tooLarge = true;
                return 0;
            }
            $responseBody .= $chunk;
            return strlen($chunk);
        },
    ]);
    $executed = curl_exec($curl);
    $status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
    $contentType = strtolower((string) curl_getinfo($curl, CURLINFO_CONTENT_TYPE));
    curl_close($curl);
    $allowedStatuses = [200, 400, 401, 403, 404, 409, 413, 415, 422, 503];
    if ($executed === false
        || $tooLarge
        || !in_array($status, $allowedStatuses, true)
        || !str_contains($contentType, 'application/json')) {
        ir_error(502, 'upstream_unavailable', 'Review service unavailable.');
    }
    try {
        $decoded = json_decode($responseBody, true, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    } catch (JsonException $exception) {
        ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
    }
    if (!is_array($decoded) || array_is_list($decoded)) {
        ir_error(502, 'invalid_upstream_response', 'Review service unavailable.');
    }
    $safe = ir_sanitize($status, $decoded, $route, $localWrites);
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode($safe, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store, private');

$method = (string) ($_SERVER['REQUEST_METHOD'] ?? '');
if (!in_array($method, ['GET', 'POST'], true)) {
    header('Allow: GET, POST');
    ir_error(405, 'method_not_allowed', 'GET or POST required.');
}
$accountRoot = dirname(__DIR__, 3);
ir_session($accountRoot);
$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: $accountRoot . '/.hollawall-admin.php';
if (!is_file($configPath)) {
    ir_error(503, 'configuration_unavailable', 'Review service unavailable.');
}
$config = require $configPath;
if (!is_array($config)) {
    ir_error(503, 'configuration_invalid', 'Review service unavailable.');
}
$owner = (string) ($config['username'] ?? '');
if ($owner === '' || !hash_equals($owner, (string) $_SESSION['hollawall_admin_user'])) {
    ir_error(403, 'owner_required', 'Owner access required.');
}
$token = (string) ($config['proxy_token'] ?? '');
if (!preg_match('/^[^\x00-\x1F\x7F]{16,512}$/D', $token)) {
    ir_error(503, 'configuration_invalid', 'Review service unavailable.');
}
$upstream = ir_upstream_url($config['upstream_inbox_reviews_url'] ?? null);
$localWrites = ($config['inbox_review_writes_enabled'] ?? false) === true;

if ($method === 'GET') {
    $action = is_string($_GET['action'] ?? null) ? $_GET['action'] : '';
    if ($action === 'list') {
        ir_exact_fields($_GET, ['action', 'offset', 'limit']);
        $offset = filter_var($_GET['offset'] ?? 0, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0]]);
        $limit = filter_var($_GET['limit'] ?? 25, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 50]]);
        if ($offset === false || $limit === false) {
            ir_error(422, 'invalid_pagination', 'Review pagination is invalid.');
        }
        session_write_close();
        ir_proxy('GET', $upstream . '?offset=' . $offset . '&limit=' . $limit, false, 'list', $token, $localWrites);
    }
    if ($action === 'detail') {
        ir_exact_fields($_GET, ['action', 'event_key']);
        $key = ir_event_key($_GET['event_key'] ?? null);
        session_write_close();
        ir_proxy('GET', $upstream . '/' . $key, false, 'detail', $token, $localWrites);
    }
    ir_error(400, 'invalid_action', 'Unsupported review action.');
}

ir_exact_fields($_GET, ['event_key']);
$key = ir_event_key($_GET['event_key'] ?? null);
if (!$localWrites) {
    ir_error(503, 'review_writes_disabled', 'Review actions are disabled.');
}
[$payload, $commandKey, $csrf] = ir_post_validation($config);
session_write_close();
ir_proxy('POST', $upstream . '/' . $key . '/actions', $payload, 'action', $token, true, $commandKey, $csrf);
