<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('POST');
presensi_require_same_origin();
presensi_public_session();
$csrf = (string) ($_POST['csrf'] ?? '');
if ($csrf === '' || !hash_equals((string) ($_SESSION['presensi_csrf'] ?? ''), $csrf)) {
    presensi_error(403, 'csrf_invalid', 'Sesi formulir tidak valid.');
}
$_SESSION = [];
if (ini_get('session.use_cookies')) {
    setcookie(session_name(), '', [
        'expires' => time() - 3600,
        'path' => PRESENSI_PUBLIC_PATH,
        'secure' => true,
        'httponly' => true,
        'samesite' => 'Strict',
    ]);
}
session_destroy();
presensi_json_response(200, ['version' => 'presensi.logout.v1', 'success' => true]);
