<?php
declare(strict_types=1);

// Shared Task-4 implementation. Entry points must define PD_PROXY_RESOURCE as
// either `projects` or `documents` before loading this file.
const PD_ADMIN_PATH = '/admin/';
const PD_SESSION_LIFETIME = 2592000;
const PD_SESSION_RENEW_AFTER = 86400;
const PD_MAX_REQUEST_BYTES = 262144;
const PD_MAX_JSON_RESPONSE_BYTES = 2097152;
const PD_MAX_PDF_RESPONSE_BYTES = 10485760;

function pd_error(int $status, string $code, string $message): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode(['error' => ['code' => $code, 'message' => $message]], JSON_UNESCAPED_SLASHES);
    exit;
}

function pd_header(string $name): string
{
    $serverName = 'HTTP_' . strtoupper(str_replace('-', '_', $name));
    return trim((string) ($_SERVER[$serverName] ?? ''));
}

function pd_uuid(mixed $value): string
{
    $text = is_string($value) ? $value : '';
    if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iD', $text)) {
        pd_error(422, 'invalid_identifier', 'A valid resource identifier is required.');
    }
    return strtolower($text);
}

function pd_validate_url(string $value, string $suffix): string
{
    $parts = parse_url($value);
    if (!is_array($parts)
        || strtolower((string) ($parts['scheme'] ?? '')) !== 'https'
        || (string) ($parts['host'] ?? '') === ''
        || isset($parts['user'])
        || isset($parts['pass'])
        || isset($parts['query'])
        || isset($parts['fragment'])
        || !str_ends_with(rtrim((string) ($parts['path'] ?? ''), '/'), $suffix)) {
        pd_error(503, 'configuration_invalid', 'Project document service unavailable.');
    }
    return rtrim($value, '/');
}

function pd_session(string $accountRoot): void
{
    $realAccountRoot = realpath($accountRoot);
    $sessionPath = $accountRoot . '/.hollawall-admin-sessions';
    if ($realAccountRoot === false || is_link($sessionPath)) {
        pd_error(503, 'session_storage_unavailable', 'Project document service unavailable.');
    }
    if (!file_exists($sessionPath) && !mkdir($sessionPath, 0700, false)) {
        pd_error(503, 'session_storage_unavailable', 'Project document service unavailable.');
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
        pd_error(503, 'session_storage_insecure', 'Project document service unavailable.');
    }
    if (session_name('hollawall_admin') === false
        || ini_set('session.use_strict_mode', '1') === false
        || ini_set('session.use_only_cookies', '1') === false
        || ini_set('session.gc_maxlifetime', (string) PD_SESSION_LIFETIME) === false
        || session_save_path($realSessionPath) === false
        || session_save_path() !== $realSessionPath
        || !session_set_cookie_params([
            'lifetime' => PD_SESSION_LIFETIME,
            'path' => PD_ADMIN_PATH,
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Strict',
        ])) {
        pd_error(503, 'session_configuration_unavailable', 'Project document service unavailable.');
    }
    if (!session_start()) {
        pd_error(503, 'session_start_failed', 'Project document service unavailable.');
    }
    if (empty($_SESSION['hollawall_admin_user'])) {
        pd_error(401, 'authentication_required', 'Sign in required.');
    }
    $now = time();
    if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > PD_SESSION_LIFETIME) {
        $_SESSION = [];
        session_regenerate_id(true);
        pd_error(401, 'session_expired', 'Sign in required.');
    }
    $_SESSION['last_seen'] = $now;
    if ($now - (int) ($_SESSION['cookie_renewed_at'] ?? 0) >= PD_SESSION_RENEW_AFTER) {
        $_SESSION['cookie_renewed_at'] = $now;
        setcookie(session_name(), session_id(), [
            'expires' => $now + PD_SESSION_LIFETIME,
            'path' => PD_ADMIN_PATH,
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Strict',
        ]);
    }
}

function pd_json_body(): array
{
    $contentType = trim((string) ($_SERVER['CONTENT_TYPE'] ?? ''));
    if (!preg_match('/^application\/json(?:\s*;\s*charset=utf-8)?$/iD', $contentType)) {
        pd_error(415, 'json_required', 'Content-Type must be application/json.');
    }
    $contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($contentLength > PD_MAX_REQUEST_BYTES) {
        pd_error(413, 'request_too_large', 'Request body is too large.');
    }
    $raw = file_get_contents('php://input', false, null, 0, PD_MAX_REQUEST_BYTES + 1);
    if ($raw === false || $raw === '') {
        pd_error(422, 'json_object_required', 'Request body must be a JSON object.');
    }
    if (strlen($raw) > PD_MAX_REQUEST_BYTES) {
        pd_error(413, 'request_too_large', 'Request body is too large.');
    }
    try {
        $decoded = json_decode($raw, true, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    } catch (JsonException $exception) {
        pd_error(422, 'invalid_json', 'Request body contains invalid JSON.');
    }
    if (!is_array($decoded) || array_is_list($decoded)) {
        pd_error(422, 'json_object_required', 'Request body must be a JSON object.');
    }
    return $decoded;
}

function pd_exact_fields(array $body, array $allowed): void
{
    foreach (array_keys($body) as $field) {
        if (!is_string($field) || !in_array($field, $allowed, true)) {
            pd_error(422, 'unsupported_fields', 'Request body contains unsupported fields.');
        }
    }
}

function pd_write_headers(array $body, string $action, array $config): array
{
    $origin = rtrim(pd_header('Origin'), '/');
    $expectedOrigin = rtrim((string) ($config['public_origin'] ?? ''), '/');
    if ($origin === ''
        || $expectedOrigin === ''
        || !hash_equals($expectedOrigin, $origin)
        || pd_header('Sec-Fetch-Site') !== 'same-origin') {
        pd_error(403, 'same_origin_required', 'Same-origin request required.');
    }
    $sessionCsrf = (string) ($_SESSION['csrf'] ?? '');
    $requestCsrf = pd_header('X-CSRF-Token');
    if ($sessionCsrf === '' || $requestCsrf === '' || !hash_equals($sessionCsrf, $requestCsrf)) {
        pd_error(403, 'csrf_validation_failed', 'Request verification failed.');
    }
    $key = pd_header('Idempotency-Key');
    if ($key === '') {
        pd_error(422, 'idempotency_key_required', 'Idempotency-Key header is required.');
    }
    if (!preg_match('/^[^\s\x00-\x1F\x7F]{16,128}$/uD', $key)) {
        pd_error(422, 'invalid_idempotency_key', 'Idempotency-Key header is invalid.');
    }
    if (!is_string($body['idempotency_key'] ?? null) || !hash_equals($key, $body['idempotency_key'])) {
        pd_error(422, 'idempotency_key_mismatch', 'Idempotency-Key header must match the request body.');
    }
    $ifMatch = pd_header('If-Match');
    if ($ifMatch === '') {
        pd_error(428, 'if_match_required', 'If-Match header is required.');
    }
    $create = in_array($action, ['create', 'create_invoice', 'create_receipt'], true);
    if ($create) {
        if ($ifMatch !== '*') {
            pd_error(412, 'if_match_failed', 'If-Match must be * for creation.');
        }
    } else {
        if (!preg_match('/^"(0|[1-9][0-9]*)"$/D', $ifMatch, $match)) {
            pd_error(422, 'invalid_if_match', 'If-Match must be a quoted lock version.');
        }
        $expected = $body['expected_version'] ?? null;
        if (!is_int($expected) || $expected < 0) {
            pd_error(422, 'expected_version_required', 'expected_version is required.');
        }
        if ((int) $match[1] !== $expected) {
            pd_error(412, 'if_match_failed', 'If-Match must match expected_version.');
        }
    }
    return [$key, $ifMatch];
}

function pd_get_route(string $resource, string $action, array $query, string $projectsBase, string $documentsBase): array
{
    if ($resource === 'projects') {
        $allowed = [
            'list' => ['action'],
            'get' => ['action', 'project_id'],
            'audit' => ['action', 'project_id'],
        ];
        if (!isset($allowed[$action])) {
            pd_error(400, 'invalid_action', 'Unsupported project action.');
        }
        pd_exact_fields($query, $allowed[$action]);
        if ($action === 'list') {
            return ['GET', $projectsBase, false];
        }
        $id = pd_uuid($query['project_id'] ?? null);
        return ['GET', $projectsBase . '/' . $id . ($action === 'audit' ? '/audit' : ''), false];
    }
    $allowed = [
        'list' => ['action', 'project_id'],
        'get' => ['action', 'document_id'],
        'audit' => ['action', 'document_id'],
        'download' => ['action', 'document_id'],
    ];
    if (!isset($allowed[$action])) {
        pd_error(400, 'invalid_action', 'Unsupported document action.');
    }
    pd_exact_fields($query, $allowed[$action]);
    if ($action === 'list') {
        $id = pd_uuid($query['project_id'] ?? null);
        return ['GET', $projectsBase . '/' . $id . '/documents', false];
    }
    $id = pd_uuid($query['document_id'] ?? null);
    $suffix = $action === 'get' ? '' : '/' . $action;
    return ['GET', $documentsBase . '/' . $id . $suffix, $action === 'download'];
}

function pd_post_route(string $resource, string $action, array $body, string $projectsBase, string $documentsBase): array
{
    if ($resource === 'projects') {
        $fields = [
            'create' => ['action', 'idempotency_key', 'values'],
            'update' => ['action', 'project_id', 'idempotency_key', 'expected_version', 'changes'],
            'status' => ['action', 'project_id', 'idempotency_key', 'expected_version', 'status'],
            'archive' => ['action', 'project_id', 'idempotency_key', 'expected_version'],
        ];
        if (!isset($fields[$action])) {
            pd_error(400, 'invalid_action', 'Unsupported project action.');
        }
        pd_exact_fields($body, $fields[$action]);
        if ($action === 'create') {
            return ['POST', $projectsBase, ['idempotency_key' => $body['idempotency_key'] ?? null, 'values' => $body['values'] ?? null]];
        }
        $id = pd_uuid($body['project_id'] ?? null);
        $payload = $body;
        unset($payload['action'], $payload['project_id']);
        $suffix = $action === 'update' ? '' : '/' . $action;
        return [$action === 'update' ? 'PATCH' : 'POST', $projectsBase . '/' . $id . $suffix, $payload];
    }
    $fields = [
        'create_invoice' => ['action', 'project_id', 'idempotency_key', 'kind', 'values'],
        'create_receipt' => ['action', 'project_id', 'idempotency_key', 'allocations', 'values'],
        'update' => ['action', 'document_id', 'idempotency_key', 'expected_version', 'changes'],
        'issue' => ['action', 'document_id', 'idempotency_key', 'expected_version'],
        'void' => ['action', 'document_id', 'idempotency_key', 'expected_version', 'reason'],
        'revise' => ['action', 'document_id', 'idempotency_key', 'expected_version'],
    ];
    if (!isset($fields[$action])) {
        pd_error(400, 'invalid_action', 'Unsupported document action.');
    }
    pd_exact_fields($body, $fields[$action]);
    if (str_starts_with($action, 'create_')) {
        $id = pd_uuid($body['project_id'] ?? null);
        $payload = $body;
        unset($payload['action'], $payload['project_id']);
        $suffix = $action === 'create_invoice' ? '/documents/invoices' : '/documents/receipts';
        return ['POST', $projectsBase . '/' . $id . $suffix, $payload];
    }
    $id = pd_uuid($body['document_id'] ?? null);
    $payload = $body;
    unset($payload['action'], $payload['document_id']);
    $suffix = $action === 'update' ? '' : '/' . $action;
    return [$action === 'update' ? 'PATCH' : 'POST', $documentsBase . '/' . $id . $suffix, $payload];
}

function pd_proxy(string $method, string $url, array|false $payload, bool $pdf, string $token, bool $localWritesEnabled, string $key = '', string $ifMatch = ''): never
{
    $response = '';
    $tooLarge = false;
    $limit = $pdf ? PD_MAX_PDF_RESPONSE_BYTES : PD_MAX_JSON_RESPONSE_BYTES;
    $headers = [
        $pdf ? 'Accept: application/pdf' : 'Accept: application/json',
        'X-Hollawall-Proxy-Token: ' . $token,
    ];
    $body = null;
    if ($payload !== false) {
        try {
            $body = json_encode($payload, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        } catch (JsonException $exception) {
            pd_error(422, 'invalid_json', 'Request body contains invalid JSON.');
        }
        $headers[] = 'Content-Type: application/json';
        $headers[] = 'Idempotency-Key: ' . $key;
        $headers[] = 'If-Match: ' . $ifMatch;
    }
    $curl = curl_init($url);
    if ($curl === false) {
        pd_error(502, 'upstream_unavailable', 'Project document service unavailable.');
    }
    curl_setopt_array($curl, [
        CURLOPT_RETURNTRANSFER => false,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
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
        pd_error(502, 'upstream_unavailable', 'Project document service unavailable.');
    }
    if ($pdf) {
        if ($status !== 200 || !str_starts_with($contentType, 'application/pdf') || !str_starts_with($response, '%PDF-')) {
            pd_error(502, 'invalid_upstream_response', 'Project document service unavailable.');
        }
        http_response_code(200);
        header('Content-Type: application/pdf');
        header('Content-Length: ' . strlen($response));
        header('Content-Disposition: attachment; filename="hollawall-document.pdf"');
        header('Cache-Control: no-store, private');
        echo $response;
        exit;
    }
    $allowedStatuses = [200, 201, 400, 401, 403, 404, 409, 412, 413, 415, 422, 428, 503];
    if (!in_array($status, $allowedStatuses, true) || !str_contains($contentType, 'application/json')) {
        pd_error(502, 'invalid_upstream_response', 'Project document service unavailable.');
    }
    try {
        $decoded = json_decode($response, true, 32, JSON_THROW_ON_ERROR | JSON_BIGINT_AS_STRING);
    } catch (JsonException $exception) {
        pd_error(502, 'invalid_upstream_response', 'Project document service unavailable.');
    }
    if (in_array($status, [200, 201], true)
        && is_array($decoded)
        && ($decoded['api_version'] ?? null) === 'dashboard.v1'
        && array_key_exists('data', $decoded)
        && is_array($decoded['meta']['capabilities'] ?? null)) {
        $capabilities = $decoded['meta']['capabilities'];
        $sanitized = [
            'api_version' => 'dashboard.v1',
            'data' => $decoded['data'],
            'meta' => ['capabilities' => [
                'reads_enabled' => ($capabilities['reads_enabled'] ?? null) === true,
                'project_document_writes_enabled' => $localWritesEnabled
                    && ($capabilities['project_document_writes_enabled'] ?? null) === true,
                'transaction_correction_reversal' => false,
                'hard_delete' => false,
            ]],
        ];
    } elseif (!in_array($status, [200, 201], true)
        && is_array($decoded['error'] ?? null)
        && is_string($decoded['error']['code'] ?? null)
        && is_string($decoded['error']['message'] ?? null)
        && preg_match('/^[a-z][a-z0-9_]{0,63}$/D', $decoded['error']['code'])
        && strlen($decoded['error']['message']) <= 256) {
        $sanitized = ['error' => [
            'code' => $decoded['error']['code'],
            'message' => $decoded['error']['message'],
        ]];
    } else {
        pd_error(502, 'invalid_upstream_response', 'Project document service unavailable.');
    }
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode($sanitized, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store, private');

$resource = defined('PD_PROXY_RESOURCE') ? (string) PD_PROXY_RESOURCE : '';
if (!in_array($resource, ['projects', 'documents'], true)) {
    pd_error(500, 'proxy_configuration_error', 'Project document service unavailable.');
}
$method = (string) ($_SERVER['REQUEST_METHOD'] ?? '');
if (!in_array($method, ['GET', 'POST'], true)) {
    header('Allow: GET, POST');
    pd_error(405, 'method_not_allowed', 'GET or POST required.');
}
$accountRoot = dirname(__DIR__, 3);
pd_session($accountRoot);
$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: $accountRoot . '/.hollawall-admin.php';
if (!is_file($configPath)) {
    pd_error(503, 'configuration_unavailable', 'Project document service unavailable.');
}
$config = require $configPath;
if (!is_array($config)) {
    pd_error(503, 'configuration_invalid', 'Project document service unavailable.');
}
$owner = (string) ($config['username'] ?? '');
if ($owner === '' || !hash_equals($owner, (string) $_SESSION['hollawall_admin_user'])) {
    pd_error(403, 'owner_required', 'Owner access required.');
}
$token = (string) ($config['proxy_token'] ?? '');
if (!preg_match('/^[^\x00-\x1F\x7F]{16,512}$/D', $token)) {
    pd_error(503, 'configuration_invalid', 'Project document service unavailable.');
}
$projectsBase = pd_validate_url((string) ($config['upstream_projects_url'] ?? ''), '/api/dashboard/v1/projects');
$documentsBase = pd_validate_url((string) ($config['upstream_documents_url'] ?? ''), '/api/dashboard/v1/documents');
$localWritesEnabled = ($config['project_document_writes_enabled'] ?? false) === true;

if ($method === 'GET') {
    $action = is_string($_GET['action'] ?? null) ? $_GET['action'] : '';
    [$upstreamMethod, $url, $pdf] = pd_get_route($resource, $action, $_GET, $projectsBase, $documentsBase);
    session_write_close();
    pd_proxy($upstreamMethod, $url, false, $pdf, $token, $localWritesEnabled);
}

$body = pd_json_body();
$action = is_string($body['action'] ?? null) ? $body['action'] : '';
$allowedActions = $resource === 'projects'
    ? ['create', 'update', 'status', 'archive']
    : ['create_invoice', 'create_receipt', 'update', 'issue', 'void', 'revise'];
if (!in_array($action, $allowedActions, true)) {
    pd_error(400, 'invalid_action', 'Unsupported project document action.');
}
if (!$localWritesEnabled) {
    pd_error(503, 'project_document_writes_disabled', 'Project and document writes are disabled.');
}
[$key, $ifMatch] = pd_write_headers($body, $action, $config);
[$upstreamMethod, $url, $payload] = pd_post_route($resource, $action, $body, $projectsBase, $documentsBase);
session_write_close();
pd_proxy($upstreamMethod, $url, $payload, false, $token, true, $key, $ifMatch);
