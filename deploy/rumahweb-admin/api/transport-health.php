<?php
declare(strict_types=1);
require_once __DIR__ . '/_common.php';
require_method('GET');
$config = require_private_config();
require_owner($config);
$upstream = (string) ($config['upstream_transactions_url'] ?? '');
$token = (string) ($config['proxy_token'] ?? '');
$curl = curl_init($upstream);
if ($curl === false) {
    json_response(200, ['ok' => false, 'curl_errno' => -1]);
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
json_response(200, $result);
