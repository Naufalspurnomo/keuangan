<?php
declare(strict_types=1);

const ADMIN_PATH = '/admin/';
const SESSION_LIFETIME = 2592000;
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
    return trim((string) ($_SERVER['HTTP_' . strtoupper(str_replace('-', '_', $name))] ?? ''));
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
        json_error(503, 'actor_assertion_unavailable', 'Debt service unavailable.');
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
    $encoded = base64url(json_encode($claims, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));
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
    json_error(503, 'session_storage_unavailable', 'Debt service unavailable.');
}
if (!file_exists($sessionPath) && !mkdir($sessionPath, 0700, false)) {
    json_error(503, 'session_storage_unavailable', 'Debt service unavailable.');
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
    json_error(503, 'session_storage_insecure', 'Debt service unavailable.');
}
if (session_name('hollawall_admin') === false
    || ini_set('session.use_strict_mode', '1') === false
    || ini_set('session.use_only_cookies', '1') === false
    || ini_set('session.gc_maxlifetime', (string) SESSION_LIFETIME) === false
    || session_save_path($realSessionPath) === false
    || !session_set_cookie_params(['lifetime' => SESSION_LIFETIME, 'path' => ADMIN_PATH, 'secure' => true, 'httponly' => true, 'samesite' => 'Strict'])) {
    json_error(503, 'session_configuration_unavailable', 'Debt service unavailable.');
}
if (!session_start() || empty($_SESSION['hollawall_admin_user'])) {
    json_error(401, 'authentication_required', 'Sign in required.');
}
$now = time();
if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > SESSION_LIFETIME) {
    $_SESSION = [];
    session_regenerate_id(true);
    json_error(401, 'session_expired', 'Sign in required.');
}
$_SESSION['last_seen'] = $now;

$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: $accountRoot . '/.hollawall-admin.php';
if (!is_file($configPath)) json_error(503, 'configuration_unavailable', 'Debt service unavailable.');
$config = require $configPath;
if (!is_array($config)) json_error(503, 'configuration_invalid', 'Debt service unavailable.');
if (($config['canonical_debt_writes_enabled'] ?? false) !== true) {
    json_error(503, 'canonical_debt_writes_disabled', 'Canonical debt writes are disabled.');
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
session_write_close();

$action = trim((string) ($_GET['action'] ?? ''));
if (!in_array($action, ['create', 'repay', 'correct', 'reverse'], true)) json_error(422, 'invalid_debt_action', 'Debt action is invalid.');
$debtId = trim((string) ($_GET['debt_id'] ?? ''));
if ($action !== 'create' && !preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iD', $debtId)) {
    json_error(422, 'invalid_debt_id', 'Debt ID is invalid.');
}
$eventId = trim((string) ($_GET['event_id'] ?? ''));
if (in_array($action, ['correct', 'reverse'], true)
    && !preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iD', $eventId)) {
    json_error(422, 'invalid_debt_event_id', 'Debt event ID is invalid.');
}
$contentType = trim((string) ($_SERVER['CONTENT_TYPE'] ?? ''));
if (!preg_match('/^application\/json(?:\s*;\s*charset=utf-8)?$/iD', $contentType)) {
    json_error(422, 'json_required', 'Content-Type must be application/json.');
}
$idempotencyKey = request_header('Idempotency-Key');
if (!preg_match('/^[^\s\x00-\x1F\x7F]{16,128}$/uD', $idempotencyKey)) {
    json_error(422, 'invalid_idempotency_key', 'Idempotency-Key header is invalid.');
}
$contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($contentLength > MAX_REQUEST_BYTES) json_error(413, 'request_too_large', 'Request body is too large.');
$rawBody = file_get_contents('php://input', false, null, 0, MAX_REQUEST_BYTES + 1);
if ($rawBody === false || $rawBody === '' || strlen($rawBody) > MAX_REQUEST_BYTES) {
    json_error(400, 'invalid_request_body', 'A JSON object is required.');
}
try {
    $payload = json_decode($rawBody, false, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    if (!$payload instanceof stdClass) json_error(422, 'json_object_required', 'Request body must be a JSON object.');
    if (!property_exists($payload, 'idempotency_key') || !is_string($payload->idempotency_key) || !hash_equals($idempotencyKey, $payload->idempotency_key)) {
        json_error(422, 'idempotency_key_mismatch', 'Idempotency-Key header must match the request body.');
    }
} catch (JsonException $exception) {
    json_error(422, 'invalid_json', 'Request body contains invalid JSON.');
}

$upstreamBase = (string) ($config['upstream_debts_url'] ?? '');
$parts = parse_url($upstreamBase);
$expectedPath = '/api/dashboard/v1/debts';
if (!is_array($parts)
    || strtolower((string) ($parts['scheme'] ?? '')) !== 'https'
    || (string) ($parts['host'] ?? '') === ''
    || rtrim((string) ($parts['path'] ?? ''), '/') !== $expectedPath
    || isset($parts['user']) || isset($parts['pass']) || isset($parts['query']) || isset($parts['fragment'])) {
    json_error(503, 'configuration_invalid', 'Debt service unavailable.');
}
$upstreamPath = $expectedPath;
$upstream = rtrim($upstreamBase, '/');
if ($action === 'repay') {
    $upstreamPath .= '/' . $debtId . '/repayments';
    $upstream .= '/' . $debtId . '/repayments';
} elseif ($action === 'correct') {
    $upstreamPath .= '/' . $debtId . '/events/' . $eventId . '/corrections';
    $upstream .= '/' . $debtId . '/events/' . $eventId . '/corrections';
} elseif ($action === 'reverse') {
    $upstreamPath .= '/' . $debtId . '/events/' . $eventId . '/reversals';
    $upstream .= '/' . $debtId . '/events/' . $eventId . '/reversals';
}
$token = (string) ($config['proxy_token'] ?? '');
if (!preg_match('/^[^\x00-\x1F\x7F]{16,512}$/D', $token)) json_error(503, 'configuration_invalid', 'Debt service unavailable.');
$headers = [
    'Accept: application/json',
    'Content-Type: application/json',
    'Idempotency-Key: ' . $idempotencyKey,
    'X-Hollawall-Proxy-Token: ' . $token,
    'X-Hollawall-Actor-Assertion: ' . actor_assertion($config, $upstreamPath, $rawBody, $owner),
];
$responseBody = '';
$responseTooLarge = false;
$curl = curl_init($upstream);
if ($curl === false) json_error(502, 'upstream_unavailable', 'Debt service unavailable.');
curl_setopt_array($curl, [
    CURLOPT_RETURNTRANSFER => false,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_CONNECTTIMEOUT => 12,
    CURLOPT_TIMEOUT => 75,
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $rawBody,
    CURLOPT_HTTPHEADER => $headers,
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
    CURLOPT_WRITEFUNCTION => static function ($handle, string $chunk) use (&$responseBody, &$responseTooLarge): int {
        if (strlen($responseBody) + strlen($chunk) > MAX_RESPONSE_BYTES) { $responseTooLarge = true; return 0; }
        $responseBody .= $chunk;
        return strlen($chunk);
    },
]);
$executed = curl_exec($curl);
$status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
$upstreamContentType = (string) curl_getinfo($curl, CURLINFO_CONTENT_TYPE);
curl_close($curl);
if ($executed === false || $responseTooLarge || !in_array($status, [200, 201, 400, 401, 403, 404, 409, 422, 503], true) || stripos($upstreamContentType, 'application/json') === false) {
    json_error(502, 'upstream_unavailable', 'Debt service unavailable.');
}
try {
    $decoded = json_decode($responseBody, true, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
} catch (JsonException $exception) {
    json_error(502, 'invalid_upstream_response', 'Debt service unavailable.');
}
if (in_array($status, [200, 201], true)
    && is_array($decoded)
    && ($decoded['api_version'] ?? null) === 'finance.v1'
    && is_array($decoded['data'] ?? null)
    && is_array($decoded['data']['debt'] ?? null)
    && is_string($decoded['data']['debt']['id'] ?? null)
    && is_int($decoded['data']['debt']['version'] ?? null)
    && in_array($decoded['data']['debt']['status'] ?? null, ['open', 'paid', 'reversed'], true)
    && is_bool($decoded['data']['duplicate'] ?? null)) {
    $sanitized = ['api_version' => 'finance.v1', 'data' => [
        'debt' => [
            'id' => $decoded['data']['debt']['id'],
            'version' => $decoded['data']['debt']['version'],
            'status' => $decoded['data']['debt']['status'],
        ],
        'duplicate' => $decoded['data']['duplicate'],
    ]];
} elseif (!in_array($status, [200, 201], true)
    && is_array($decoded['error'] ?? null)
    && is_string($decoded['error']['code'] ?? null)
    && is_string($decoded['error']['message'] ?? null)
    && preg_match('/^[a-z][a-z0-9_]{0,63}$/D', $decoded['error']['code'])
    && strlen($decoded['error']['message']) <= 256) {
    $sanitized = ['error' => ['code' => $decoded['error']['code'], 'message' => $decoded['error']['message']]];
} else {
    json_error(502, 'invalid_upstream_response', 'Debt service unavailable.');
}
http_response_code($status);
header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store, private');
echo json_encode($sanitized, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
