<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('POST');
presensi_require_same_origin();
presensi_public_session();
$csrf = (string) ($_POST['csrf'] ?? '');
if ($csrf === '' || !hash_equals((string) ($_SESSION['presensi_csrf'] ?? ''), $csrf)) {
    presensi_error(403, 'authentication_failed', 'Kode pegawai atau PIN tidak valid.');
}
$code = strtoupper(trim((string) ($_POST['code'] ?? '')));
$pin = (string) ($_POST['pin'] ?? '');
if (strlen($code) > 32 || strlen($pin) > 128) {
    presensi_error(401, 'authentication_failed', 'Kode pegawai atau PIN tidak valid.');
}
$config = presensi_config();
$paths = presensi_store_paths();
$keys = presensi_login_keys($code);
$retryAfter = presensi_login_locked($paths, $keys);
if ($retryAfter > 0) {
    header('Retry-After: ' . $retryAfter);
    presensi_error(429, 'authentication_failed', 'Kode pegawai atau PIN tidak valid. Coba lagi nanti.');
}

$authenticated = null;
foreach ($config['employees'] as $employee) {
    $codeMatches = hash_equals((string) $employee['code'], $code);
    if ($codeMatches) { $authenticated = $employee; break; }
}
$dummyHash = '$2y$10$7OuurItIj7ylUssqZ9D7MuqfBJGMN6U9.2sRCO1obS0ys04e..J.G';
$pinMatches = password_verify($pin, (string) ($authenticated['pin_hash'] ?? $dummyHash));
if ($authenticated === null || !$pinMatches || !preg_match('/^[A-Z0-9][A-Z0-9-]{2,31}$/D', $code)) {
    $retryAfter = presensi_login_attempts($paths, $keys, false);
    if ($retryAfter > 0) header('Retry-After: ' . $retryAfter);
    presensi_error($retryAfter > 0 ? 429 : 401, 'authentication_failed', 'Kode pegawai atau PIN tidak valid.' . ($retryAfter > 0 ? ' Coba lagi nanti.' : ''));
}
presensi_login_attempts($paths, $keys, true);
if (!session_regenerate_id(true)) {
    presensi_error(503, 'authentication_unavailable', 'Masuk belum dapat diproses.');
}
$now = time();
$_SESSION['presensi_employee_id'] = (string) $authenticated['id'];
$_SESSION['presensi_employee_name'] = (string) $authenticated['name'];
$_SESSION['presensi_authenticated_at'] = $now;
$_SESSION['presensi_last_seen'] = $now;
$_SESSION['presensi_csrf'] = bin2hex(random_bytes(24));
$_SESSION['presensi_recovery_key'] = bin2hex(random_bytes(32));
unset($_SESSION['capture_token_hash'], $_SESSION['capture_token_expires']);
presensi_json_response(200, [
    'version' => 'presensi.login.v1',
    'success' => true,
    'employee' => ['id' => $authenticated['id'], 'name' => $authenticated['name']],
]);
