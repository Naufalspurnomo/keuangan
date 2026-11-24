<?php
declare(strict_types=1);

const SNAPSHOT_HEALTH_MAX_BYTES = 1_048_576;

function health_json(int $status, array $payload): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    header('X-Robots-Tag: noindex, nofollow, noarchive');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function health_base64url(string $value): string
{
    return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
}

function health_actor_assertion(array $config, string $path): string
{
    $secret = (string) ($config['dashboard_actor_assertion_secret'] ?? '');
    $audience = (string) ($config['dashboard_actor_assertion_audience'] ?? '');
    $email = strtolower(trim((string) ($config['owner_email'] ?? '')));
    if (strlen($secret) < 32 || $audience === '' || $email === '') {
        health_json(503, ['ok' => false, 'code' => 'configuration_invalid']);
    }
    $now = time();
    $claims = [
        'actor_id' => $email,
        'email' => $email,
        'role' => 'boss',
        'aud' => $audience,
        'method' => 'GET',
        'path' => $path,
        'body_sha256' => hash('sha256', ''),
        'nonce' => bin2hex(random_bytes(16)),
        'iat' => $now,
        'exp' => $now + 60,
    ];
    $encoded = health_base64url((string) json_encode($claims, JSON_UNESCAPED_SLASHES));
    return $encoded . '.' . health_base64url(hash_hmac('sha256', $encoded, $secret, true));
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    health_json(405, ['ok' => false, 'code' => 'method_not_allowed']);
}

$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: dirname(__DIR__, 3) . '/.hollawall-admin.php';
if (!is_file($configPath)) {
    health_json(503, ['ok' => false, 'code' => 'configuration_unavailable']);
}
$config = require $configPath;
if (!is_array($config)) {
    health_json(503, ['ok' => false, 'code' => 'configuration_invalid']);
}
$expectedToken = (string) ($config['proxy_token'] ?? '');
$suppliedToken = (string) ($_SERVER['HTTP_X_HOLLAWALL_PROXY_TOKEN'] ?? '');
if ($expectedToken === '' || $suppliedToken === '' || !hash_equals($expectedToken, $suppliedToken)) {
    health_json(401, ['ok' => false, 'code' => 'authentication_required']);
}
$upstream = (string) ($config['upstream_snapshot_url'] ?? '');
if (strpos($upstream, 'https://') !== 0) {
    health_json(503, ['ok' => false, 'code' => 'configuration_invalid']);
}
$path = (string) (parse_url($upstream, PHP_URL_PATH) ?: '');
$curl = curl_init($upstream);
if ($curl === false) {
    health_json(502, ['ok' => false, 'code' => 'upstream_unavailable']);
}
curl_setopt_array($curl, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_CONNECTTIMEOUT => 12,
    CURLOPT_TIMEOUT => 75,
    CURLOPT_HTTPHEADER => [
        'Accept: application/json',
        'X-Hollawall-Proxy-Token: ' . $expectedToken,
        'X-Hollawall-Actor-Assertion: ' . health_actor_assertion($config, $path),
    ],
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
]);
$body = curl_exec($curl);
$status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
$contentType = strtolower((string) curl_getinfo($curl, CURLINFO_CONTENT_TYPE));
curl_close($curl);
if ($body === false || $status < 200 || $status >= 300 || strpos($contentType, 'application/json') === false) {
    health_json(502, ['ok' => false, 'code' => 'upstream_unavailable', 'upstream_status' => $status]);
}
if (strlen((string) $body) > SNAPSHOT_HEALTH_MAX_BYTES) {
    health_json(502, ['ok' => false, 'code' => 'upstream_response_too_large']);
}
$payload = json_decode((string) $body, true);
if (!is_array($payload) || ($payload['version'] ?? null) !== 'dashboard.snapshot.v1') {
    health_json(502, ['ok' => false, 'code' => 'invalid_upstream_response']);
}
health_json(200, [
    'ok' => true,
    'snapshot_version' => 'dashboard.snapshot.v1',
    'upstream_status' => $status,
]);
