<?php
declare(strict_types=1);

function json_error(int $status, string $code, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store');
    echo json_encode(['error' => ['code' => $code, 'message' => $message]], JSON_UNESCAPED_SLASHES);
    exit;
}

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store, private');

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    json_error(405, 'method_not_allowed', 'Read-only endpoint.');
}

session_name('hollawall_admin');
session_set_cookie_params(['lifetime' => 0, 'path' => '/admin/', 'secure' => true, 'httponly' => true, 'samesite' => 'Strict']);
session_start();
if (empty($_SESSION['hollawall_admin_user'])) {
    json_error(401, 'authentication_required', 'Sign in required.');
}
if (isset($_SESSION['last_seen']) && time() - (int) $_SESSION['last_seen'] > 28800) {
    $_SESSION = [];
    session_regenerate_id(true);
    json_error(401, 'session_expired', 'Sign in required.');
}
$_SESSION['last_seen'] = time();

$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: dirname(__DIR__, 3) . '/.hollawall-admin.php';
if (!is_file($configPath)) {
    json_error(503, 'configuration_unavailable', 'Snapshot unavailable.');
}
$config = require $configPath;
$upstream = (string) ($config['upstream_snapshot_url'] ?? '');
$token = (string) ($config['proxy_token'] ?? '');
if (strpos($upstream, 'https://') !== 0 || $token === '') {
    json_error(503, 'configuration_invalid', 'Snapshot unavailable.');
}

$curl = curl_init($upstream);
curl_setopt_array($curl, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_CONNECTTIMEOUT => 8,
    CURLOPT_TIMEOUT => 30,
    CURLOPT_HTTPHEADER => ['Accept: application/json', 'X-Hollawall-Proxy-Token: ' . $token],
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
]);
$body = curl_exec($curl);
$status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
$contentType = (string) curl_getinfo($curl, CURLINFO_CONTENT_TYPE);
$failed = $body === false;
curl_close($curl);

if ($failed || $status < 200 || $status >= 300 || strpos(strtolower($contentType), 'application/json') === false) {
    json_error(502, 'upstream_unavailable', 'Snapshot unavailable.');
}

$decoded = json_decode((string) $body, true);
if (!is_array($decoded) || ($decoded['version'] ?? null) !== 'dashboard.snapshot.v1') {
    json_error(502, 'invalid_upstream_response', 'Snapshot unavailable.');
}

http_response_code(200);
header('Content-Type: application/json; charset=UTF-8');
echo json_encode($decoded, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);