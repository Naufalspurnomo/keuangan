<?php
declare(strict_types=1);

const ADMIN_PATH = '/admin/';
const SESSION_LIFETIME = 2592000;
const SESSION_RENEW_AFTER = 86400;
const MAX_REQUEST_BYTES = 65536;
const MAX_RESPONSE_BYTES = 1048576;

function json_error(int $status, string $code, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode(['error' => ['code' => $code, 'message' => $message]], JSON_UNESCAPED_SLASHES);
    exit;
}

function request_header(string $name): string
{
    $serverName = 'HTTP_' . strtoupper(str_replace('-', '_', $name));
    return trim((string) ($_SERVER[$serverName] ?? ''));
}

function base64url(string $value): string
{
    return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
}

function actor_assertion(array $config, string $path, string $body, string $actor): string
{
    $secret = (string) ($config['dashboard_actor_assertion_secret'] ?? '');
    $audience = (string) ($config['dashboard_actor_assertion_audience'] ?? '');
    $email = strtolower(trim((string) ($config['owner_email'] ?? '')));
    if (strlen($secret) < 32 || $audience === '' || $email === '') {
        json_error(503, 'actor_assertion_unavailable', 'Canonical transaction service unavailable.');
    }
    $now = time();
    $claims = [
        'actor_id' => $actor,
        'email' => $email,
        'role' => 'boss',
        'aud' => $audience,
        'method' => 'POST',
        'path' => $path,
        'body_sha256' => hash('sha256', $body),
        'nonce' => bin2hex(random_bytes(16)),
        'iat' => $now,
        'exp' => $now + 60,
    ];
    $json = json_encode($claims, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    $encoded = base64url($json);
    return $encoded . '.' . base64url(hash_hmac('sha256', $encoded, $secret, true));
}

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store, private');

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    json_error(405, 'method_not_allowed', 'POST required.');
}

$accountRoot = dirname(__DIR__, 3);
$realAccountRoot = realpath($accountRoot);
$sessionPath = $accountRoot . '/.hollawall-admin-sessions';
if ($realAccountRoot === false || is_link($sessionPath)) {
    json_error(503, 'session_storage_unavailable', 'Transaction service unavailable.');
}
if (!file_exists($sessionPath) && !mkdir($sessionPath, 0700, false)) {
    json_error(503, 'session_storage_unavailable', 'Transaction service unavailable.');
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
    json_error(503, 'session_storage_insecure', 'Transaction service unavailable.');
}
$sessionPath = $realSessionPath;
if (session_name('hollawall_admin') === false
    || ini_set('session.use_strict_mode', '1') === false
    || ini_set('session.use_only_cookies', '1') === false
    || ini_set('session.gc_maxlifetime', (string) SESSION_LIFETIME) === false
    || session_save_path($sessionPath) === false
    || session_save_path() !== $sessionPath
    || !session_set_cookie_params(['lifetime' => SESSION_LIFETIME, 'path' => ADMIN_PATH, 'secure' => true, 'httponly' => true, 'samesite' => 'Strict'])) {
    json_error(503, 'session_configuration_unavailable', 'Transaction service unavailable.');
}
if (!session_start()) {
    json_error(503, 'session_start_failed', 'Transaction service unavailable.');
}
if (empty($_SESSION['hollawall_admin_user'])) {
    json_error(401, 'authentication_required', 'Sign in required.');
}
$now = time();
if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > SESSION_LIFETIME) {
    $_SESSION = [];
    session_regenerate_id(true);
    json_error(401, 'session_expired', 'Sign in required.');
}
$_SESSION['last_seen'] = $now;
if ($now - (int) ($_SESSION['cookie_renewed_at'] ?? 0) >= SESSION_RENEW_AFTER) {
    $_SESSION['cookie_renewed_at'] = $now;
    setcookie(session_name(), session_id(), ['expires' => $now + SESSION_LIFETIME, 'path' => ADMIN_PATH, 'secure' => true, 'httponly' => true, 'samesite' => 'Strict']);
}

$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: $accountRoot . '/.hollawall-admin.php';
if (!is_file($configPath)) {
    json_error(503, 'configuration_unavailable', 'Transaction service unavailable.');
}
$config = require $configPath;
if (!is_array($config)) {
    json_error(503, 'configuration_invalid', 'Transaction service unavailable.');
}
$action = trim((string) ($_GET['action'] ?? ''));
$canonical = in_array($action, ['correction', 'reversal'], true);
if ($action !== '' && !$canonical) {
    json_error(422, 'invalid_transaction_action', 'Transaction action is invalid.');
}
if ($canonical && ($config['canonical_finance_writes_enabled'] ?? false) !== true) {
    json_error(503, 'canonical_finance_writes_disabled', 'Canonical transaction writes are disabled.');
}
if (!$canonical && ($config['transaction_writes_enabled'] ?? false) !== true) {
    json_error(503, 'transaction_writes_disabled', 'Transaction writes are disabled.');
}
$transactionId = trim((string) ($_GET['transaction_id'] ?? ''));
if ($canonical && !preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iD', $transactionId)) {
    json_error(422, 'invalid_transaction_id', 'Canonical transaction ID is invalid.');
}

$owner = (string) ($config['username'] ?? '');
if ($owner === '' || !hash_equals($owner, (string) $_SESSION['hollawall_admin_user'])) {
    json_error(403, 'owner_required', 'Owner access required.');
}

$sessionCsrf = (string) ($_SESSION['csrf'] ?? '');
$requestCsrf = request_header('X-CSRF-Token');
if ($sessionCsrf === '' || $requestCsrf === '' || !hash_equals($sessionCsrf, $requestCsrf)) {
    json_error(403, 'csrf_validation_failed', 'Request verification failed.');
}

$contentType = trim((string) ($_SERVER['CONTENT_TYPE'] ?? ''));
if (!preg_match('/^application\/json(?:\s*;\s*charset=utf-8)?$/iD', $contentType)) {
    json_error(422, 'json_required', 'Content-Type must be application/json.');
}

$idempotencyKey = request_header('Idempotency-Key');
if ($idempotencyKey === '') {
    json_error(422, 'idempotency_key_required', 'Idempotency-Key header is required.');
}
if (!preg_match('/^[^\s\x00-\x1F\x7F]{16,128}$/uD', $idempotencyKey)) {
    json_error(422, 'invalid_idempotency_key', 'Idempotency-Key header is invalid.');
}

$contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($contentLength > MAX_REQUEST_BYTES) {
    json_error(413, 'request_too_large', 'Request body is too large.');
}
$rawBody = file_get_contents('php://input', false, null, 0, MAX_REQUEST_BYTES + 1);
if ($rawBody === false || $rawBody === '' || strlen($rawBody) > MAX_REQUEST_BYTES) {
    json_error($rawBody !== false && strlen($rawBody) > MAX_REQUEST_BYTES ? 413 : 400, 'invalid_request_body', 'A JSON object is required.');
}
try {
    $payload = json_decode($rawBody, false, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    if (!$payload instanceof stdClass) {
        json_error(422, 'json_object_required', 'Request body must be a JSON object.');
    }
    if (!property_exists($payload, 'idempotency_key')
        || !is_string($payload->idempotency_key)
        || !hash_equals($idempotencyKey, $payload->idempotency_key)) {
        json_error(422, 'idempotency_key_mismatch', 'Idempotency-Key header must match the request body.');
    }
    $forwardBody = $rawBody;
} catch (JsonException $exception) {
    json_error(422, 'invalid_json', 'Request body contains invalid JSON.');
}

$upstreamBase = (string) ($config[$canonical ? 'upstream_canonical_transactions_url' : 'upstream_transactions_url'] ?? '');
$upstreamParts = parse_url($upstreamBase);
$expectedPath = $canonical ? '/api/dashboard/v1/canonical-transactions' : '/api/dashboard/v1/transactions';
if (!is_array($upstreamParts)
    || strtolower((string) ($upstreamParts['scheme'] ?? '')) !== 'https'
    || (string) ($upstreamParts['host'] ?? '') === ''
    || rtrim((string) ($upstreamParts['path'] ?? ''), '/') !== $expectedPath
    || isset($upstreamParts['user'])
    || isset($upstreamParts['pass'])
    || isset($upstreamParts['query'])
    || isset($upstreamParts['fragment'])) {
    json_error(503, 'configuration_invalid', 'Transaction service unavailable.');
}
$upstreamPath = $expectedPath;
$upstream = rtrim($upstreamBase, '/');
$actorHeader = null;
if ($canonical) {
    $suffix = $action === 'correction' ? 'corrections' : 'reversals';
    $upstreamPath .= '/' . $transactionId . '/' . $suffix;
    $upstream .= '/' . $transactionId . '/' . $suffix;
    $actorHeader = actor_assertion($config, $upstreamPath, $forwardBody, $owner);
}
$token = (string) ($config['proxy_token'] ?? '');
if (!preg_match('/^[^\x00-\x1F\x7F]{16,512}$/D', $token)) {
    json_error(503, 'configuration_invalid', 'Transaction service unavailable.');
}

$requestHeaders = [
    'Accept: application/json',
    'Content-Type: application/json',
    'Idempotency-Key: ' . $idempotencyKey,
    'X-Hollawall-Proxy-Token: ' . $token,
];
if ($actorHeader !== null) {
    $requestHeaders[] = 'X-Hollawall-Actor-Assertion: ' . $actorHeader;
}

$responseBody = '';
$responseTooLarge = false;
$curl = curl_init($upstream);
if ($curl === false) {
    json_error(502, 'upstream_unavailable', 'Transaction service unavailable.');
}
curl_setopt_array($curl, [
    CURLOPT_RETURNTRANSFER => false,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_CONNECTTIMEOUT => 12,
    // A cold Koyeb worker plus authoritative Google Sheets write/readback can
    // legitimately exceed 30 seconds. Keep this above the backend's own bounded
    // transaction path so the proxy returns the idempotent completion response
    // instead of an ambiguous 502 after the write already committed.
    CURLOPT_TIMEOUT => 75,
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $forwardBody,
    CURLOPT_HTTPHEADER => $requestHeaders,
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
    CURLOPT_WRITEFUNCTION => static function ($handle, string $chunk) use (&$responseBody, &$responseTooLarge): int {
        if (strlen($responseBody) + strlen($chunk) > MAX_RESPONSE_BYTES) {
            $responseTooLarge = true;
            return 0;
        }
        $responseBody .= $chunk;
        return strlen($chunk);
    },
]);
$executed = curl_exec($curl);
$status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
$upstreamContentType = (string) curl_getinfo($curl, CURLINFO_CONTENT_TYPE);
curl_close($curl);

$allowedStatuses = [200, 201, 400, 401, 403, 404, 409, 422, 503];
if ($executed === false
    || $responseTooLarge
    || !in_array($status, $allowedStatuses, true)
    || stripos($upstreamContentType, 'application/json') === false) {
    json_error(502, 'upstream_unavailable', 'Transaction service unavailable.');
}

try {
    $decoded = json_decode($responseBody, true, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
} catch (JsonException $exception) {
    json_error(502, 'invalid_upstream_response', 'Transaction service unavailable.');
}

if ($canonical
    && in_array($status, [200, 201], true)
    && is_array($decoded)
    && ($decoded['api_version'] ?? null) === 'finance.v1'
    && is_array($decoded['data'] ?? null)
    && is_array($decoded['data']['transaction'] ?? null)
    && is_string($decoded['data']['transaction']['id'] ?? null)
    && is_int($decoded['data']['transaction']['version'] ?? null)
    && in_array($decoded['data']['transaction']['status'] ?? null, ['correction', 'reversal'], true)
    && is_bool($decoded['data']['duplicate'] ?? null)) {
    $sanitized = [
        'api_version' => 'finance.v1',
        'data' => [
            'transaction' => [
                'id' => $decoded['data']['transaction']['id'],
                'version' => $decoded['data']['transaction']['version'],
                'status' => $decoded['data']['transaction']['status'],
            ],
            'duplicate' => $decoded['data']['duplicate'],
        ],
    ];
} elseif (!$canonical
    && in_array($status, [200, 201], true)
    && is_array($decoded)
    && array_keys($decoded) === ['api_version', 'data']
    && ($decoded['api_version'] ?? null) === 'dashboard.v1'
    && is_array($decoded['data'] ?? null)
    && (static function (array $data): bool {
        $keys = array_keys($data);
        sort($keys);
        return $keys === ['authority', 'duplicate', 'recorded', 'transaction_id', 'transaction_version'];
    })($decoded['data'])
    && ($decoded['data']['recorded'] ?? null) === true
    && ($decoded['data']['authority'] ?? null) === 'postgresql'
    && is_string($decoded['data']['transaction_id'] ?? null)
    && preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iD', $decoded['data']['transaction_id'])
    && is_int($decoded['data']['transaction_version'] ?? null)
    && ($decoded['data']['transaction_version'] ?? 0) > 0
    && is_bool($decoded['data']['duplicate'] ?? null)) {
    $sanitized = [
        'api_version' => 'dashboard.v1',
        'data' => [
            'recorded' => true,
            'authority' => 'postgresql',
            'transaction_id' => $decoded['data']['transaction_id'],
            'transaction_version' => $decoded['data']['transaction_version'],
            'duplicate' => $decoded['data']['duplicate'],
        ],
    ];
} elseif (!$canonical
    && in_array($status, [200, 201], true)
    && is_array($decoded)
    && ($decoded['api_version'] ?? null) === 'dashboard.v1'
    && is_array($decoded['data'] ?? null)
    && !array_key_exists('authority', $decoded['data'])
    && !array_key_exists('transaction_version', $decoded['data'])
    && ($decoded['data']['recorded'] ?? null) === true
    && is_string($decoded['data']['transaction_id'] ?? null)
    && is_string($decoded['data']['sheet_name'] ?? null)
    && is_int($decoded['data']['sheet_row'] ?? null)
    && ($decoded['data']['sheet_row'] ?? 0) > 0
    && is_string($decoded['data']['source_block'] ?? null)
    && is_string($decoded['data']['sheet_message_id'] ?? null)
    && in_array($decoded['data']['projection_status'] ?? null, ['converged', 'pending'], true)) {
    $sanitized = [
        'api_version' => 'dashboard.v1',
        'data' => [
            'recorded' => true,
            'transaction_id' => $decoded['data']['transaction_id'],
            'sheet_name' => $decoded['data']['sheet_name'],
            'sheet_row' => $decoded['data']['sheet_row'],
            'source_block' => $decoded['data']['source_block'],
            'sheet_message_id' => $decoded['data']['sheet_message_id'],
            'projection_status' => $decoded['data']['projection_status'],
            'duplicate' => $status === 200,
        ],
    ];
} elseif (!in_array($status, [200, 201], true)
    && is_array($decoded)
    && is_array($decoded['error'] ?? null)
    && is_string($decoded['error']['code'] ?? null)
    && is_string($decoded['error']['message'] ?? null)
    && preg_match('/^[a-z][a-z0-9_]{0,63}$/D', $decoded['error']['code'])
    && strlen($decoded['error']['message']) <= 256) {
    $sanitized = [
        'error' => [
            'code' => $decoded['error']['code'],
            'message' => $decoded['error']['message'],
        ],
    ];
} else {
    json_error(502, 'invalid_upstream_response', 'Transaction service unavailable.');
}

http_response_code($status);
header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store, private');
echo json_encode($sanitized, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
