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

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store, private');

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    json_error(405, 'method_not_allowed', 'GET required.');
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

$owner = (string) ($config['username'] ?? '');
if ($owner === '' || !hash_equals($owner, (string) $_SESSION['hollawall_admin_user'])) {
    json_error(403, 'owner_required', 'Owner access required.');
}

if (empty($_SESSION['csrf'])) {
    $_SESSION['csrf'] = bin2hex(random_bytes(32));
}
$csrf = (string) $_SESSION['csrf'];
session_write_close();
header('Content-Type: application/json; charset=UTF-8');
echo json_encode([
    'api_version' => 'dashboard.v1',
    'data' => [
        'csrf_token' => $csrf,
        'capabilities' => [
            'writes_enabled' => ($config['transaction_writes_enabled'] ?? false) === true,
            'canonical_finance_writes_enabled' => ($config['canonical_finance_writes_enabled'] ?? false) === true,
            'canonical_debt_writes_enabled' => ($config['canonical_debt_writes_enabled'] ?? false) === true,
        ],
    ],
], JSON_UNESCAPED_SLASHES);
