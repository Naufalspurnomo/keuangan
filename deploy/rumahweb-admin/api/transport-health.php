<?php
declare(strict_types=1);

const ADMIN_PATH = '/admin/';
const SESSION_LIFETIME = 2592000;

function json_result(int $status, array $payload): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES);
    exit;
}

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    json_result(405, ['ok' => false, 'code' => 'method_not_allowed']);
}
$accountRoot = dirname(__DIR__, 3);
$realAccountRoot = realpath($accountRoot);
$sessionPath = $accountRoot . '/.hollawall-admin-sessions';
$realSessionPath = realpath($sessionPath);
if ($realAccountRoot === false || $realSessionPath === false || dirname($realSessionPath) !== $realAccountRoot) {
    json_result(503, ['ok' => false, 'code' => 'session_unavailable']);
}
if (session_name('hollawall_admin') === false
    || ini_set('session.use_strict_mode', '1') === false
    || ini_set('session.use_only_cookies', '1') === false
    || ini_set('session.gc_maxlifetime', (string) SESSION_LIFETIME) === false
    || session_save_path($realSessionPath) === false
    || !session_set_cookie_params(['lifetime' => SESSION_LIFETIME, 'path' => ADMIN_PATH, 'secure' => true, 'httponly' => true, 'samesite' => 'Strict'])
    || !session_start()) {
    json_result(503, ['ok' => false, 'code' => 'session_unavailable']);
}
$user = (string) ($_SESSION['hollawall_admin_user'] ?? '');
session_write_close();
if ($user === '') {
    json_result(401, ['ok' => false, 'code' => 'authentication_required']);
}
$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: $accountRoot . '/.hollawall-admin.php';
$config = is_file($configPath) ? require $configPath : null;
if (!is_array($config) || !hash_equals((string) ($config['username'] ?? ''), $user)) {
    json_result(403, ['ok' => false, 'code' => 'owner_required']);
}
$upstream = (string) ($config['upstream_transactions_url'] ?? '');
$token = (string) ($config['proxy_token'] ?? '');
$curl = curl_init($upstream);
if ($curl === false) {
    json_result(200, ['ok' => false, 'curl_errno' => -1]);
}
curl_setopt_array($curl, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_CONNECTTIMEOUT => 12,
    CURLOPT_TIMEOUT => 20,
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
    CURLOPT_HTTPHEADER => [
        'Accept: application/json',
        'Authorization: Bearer ' . $token,
        'Cache-Control: no-store',
    ],
]);
$body = curl_exec($curl);
$result = [
    'ok' => $body !== false,
    'curl_errno' => curl_errno($curl),
    'http_status' => (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE),
    'content_type' => (string) curl_getinfo($curl, CURLINFO_CONTENT_TYPE),
    'primary_ip_present' => ((string) curl_getinfo($curl, CURLINFO_PRIMARY_IP)) !== '',
    'total_time_ms' => (int) round(((float) curl_getinfo($curl, CURLINFO_TOTAL_TIME)) * 1000),
];
curl_close($curl);
json_result(200, $result);
