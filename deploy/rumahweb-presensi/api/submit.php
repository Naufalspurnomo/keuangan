<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('POST');
presensi_require_same_origin();
$contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($contentLength <= 0 || $contentLength > 5_242_880) {
    presensi_error(413, 'request_too_large', 'Ukuran bukti presensi tidak valid.');
}
presensi_public_session();
$sessionEmployee = presensi_public_employee();
$csrf = (string) ($_POST['csrf'] ?? '');
if ($csrf === '' || !hash_equals((string) ($_SESSION['presensi_csrf'] ?? ''), $csrf)) {
    presensi_error(403, 'csrf_invalid', 'Sesi formulir tidak valid. Muat ulang halaman.');
}
presensi_validate_capture_token((string) ($_POST['capture_token'] ?? ''));

$submissionId = trim((string) ($_POST['submission_id'] ?? ''));
$employeeId = $sessionEmployee['id'];
$projectId = trim((string) ($_POST['project_id'] ?? ''));
$action = trim((string) ($_POST['action'] ?? ''));
if (!preg_match('/^sub-[a-f0-9]{32}$/', $submissionId)) {
    presensi_error(422, 'submission_invalid', 'Identitas pengiriman tidak valid. Muat ulang halaman.');
}
$latitude = filter_var($_POST['latitude'] ?? null, FILTER_VALIDATE_FLOAT);
$longitude = filter_var($_POST['longitude'] ?? null, FILTER_VALIDATE_FLOAT);
$accuracy = filter_var($_POST['accuracy_m'] ?? null, FILTER_VALIDATE_FLOAT);
presensi_require_fresh_observation($_POST['location_observed_at_ms'] ?? null, 'location_stale', 'Lokasi sudah tidak segar. Ambil selfie dan lokasi lagi.');
presensi_require_fresh_observation($_POST['selfie_observed_at_ms'] ?? null, 'selfie_stale', 'Selfie sudah tidak segar. Ambil selfie dan lokasi lagi.');
$config = presensi_config();
$employee = presensi_find_named($config['employees'], $employeeId);
$project = presensi_find_named($config['projects'], $projectId);
if ($employee === null) {
    presensi_error(422, 'employee_invalid', 'Pegawai tidak valid.');
}
if (!in_array($action, ['check_in', 'check_out'], true)) {
    presensi_error(422, 'action_invalid', 'Jenis presensi tidak valid.');
}
if ($action === 'check_in' && $project === null) {
    presensi_error(422, 'project_invalid', 'Proyek aktif tidak valid.');
}
if ($latitude === false || $longitude === false || $accuracy === false
    || !is_finite((float) $latitude) || !is_finite((float) $longitude) || !is_finite((float) $accuracy)
    || $latitude < -90 || $latitude > 90 || $longitude < -180 || $longitude > 180 || $accuracy <= 0) {
    presensi_error(422, 'location_required', 'Lokasi presisi wajib diaktifkan.');
}
$selfie = presensi_validate_selfie($_FILES['selfie'] ?? []);
$paths = presensi_store_paths();
$lock = presensi_lock($paths);
$photoPath = null;
$storageFailure = null;
$now = time();
try {
    $events = presensi_read_events($paths);
    foreach ($events as $existing) {
        if (hash_equals((string) ($existing['submission_id'] ?? ''), $submissionId)) {
            presensi_error(409, 'submission_replayed', 'Pengiriman ini sudah diterima server.');
        }
    }
    presensi_rate_limit($events, $employeeId, $now);
    $open = presensi_open_event($events, $employeeId);
    if ($action === 'check_in' && $open !== null) {
        presensi_error(409, 'already_checked_in', 'Pegawai masih aktif di proyek ' . (string) $open['project_name'] . '.');
    }
    if ($action === 'check_out' && $open === null) {
        presensi_error(409, 'check_in_required', 'Check-in wajib dilakukan lebih dulu.');
    }
    if ($action === 'check_out' && !hash_equals((string) $open['project_id'], $projectId)) {
        presensi_error(409, 'project_mismatch', 'Check-out wajib pada proyek yang sama.');
    }
    if ($action === 'check_out') {
        $project = ['id' => (string) $open['project_id'], 'name' => (string) $open['project_name']];
    }

    $eventId = 'evt-' . bin2hex(random_bytes(12));
    $pairId = $action === 'check_in' ? 'prs-' . bin2hex(random_bytes(12)) : (string) $open['pair_id'];
    $photoName = $eventId . '.' . $selfie['extension'];
    $photoPath = $paths['photos'] . '/' . $photoName;
    if (file_put_contents($photoPath, $selfie['bytes'], LOCK_EX) === false) {
        throw new PresensiStorageException(503, 'storage_unavailable', 'Selfie belum dapat disimpan.');
    }
    chmod($photoPath, 0600);
    $event = [
        'id' => $eventId,
        'submission_id' => $submissionId,
        'recovery_hash' => hash_hmac('sha256', $submissionId, (string) $_SESSION['presensi_recovery_key']),
        'pair_id' => $pairId,
        'action' => $action,
        'employee_id' => $employee['id'],
        'employee_name' => $employee['name'],
        'project_id' => $project['id'],
        'project_name' => $project['name'],
        'occurred_at' => gmdate('c'),
        'latitude' => round((float) $latitude, 6),
        'longitude' => round((float) $longitude, 6),
        'accuracy_m' => round((float) $accuracy, 1),
        'photo_name' => $photoName,
        'photo_mime' => $selfie['mime'],
        'photo_width' => $selfie['width'],
        'photo_height' => $selfie['height'],
        'whatsapp_delivery' => [
            'status' => 'pending',
            'attempts' => 0,
            'next_retry_at' => gmdate('c'),
            'provider_message_id' => null,
            'last_error' => null,
            'lease_token_hash' => null,
            'lease_expires_at' => null,
        ],
    ];
    $events[] = $event;
    presensi_write_events($paths, $events);
} catch (PresensiStorageException $error) {
    if ($photoPath !== null && is_file($photoPath)) {
        @unlink($photoPath);
    }
    $storageFailure = $error;
} catch (Throwable $error) {
    if ($photoPath !== null && is_file($photoPath)) {
        @unlink($photoPath);
    }
    throw $error;
} finally {
    presensi_unlock($lock);
}
if ($storageFailure instanceof PresensiStorageException) {
    presensi_error($storageFailure->httpStatus, $storageFailure->publicCode, $storageFailure->publicMessage);
}
$_SESSION['presensi_csrf'] = bin2hex(random_bytes(24));
$nextCaptureToken = presensi_consume_capture_token();
presensi_trigger_delivery($config);
presensi_json_response(201, [
    'version' => 'presensi.submission.v1',
    'success' => true,
    'record' => [
        'id' => $event['id'],
        'pair_id' => $event['pair_id'],
        'action' => $event['action'],
        'employee_name' => $event['employee_name'],
        'project_name' => $event['project_name'],
        'occurred_at' => $event['occurred_at'],
        'accuracy_m' => $event['accuracy_m'],
    ],
    'csrf' => (string) $_SESSION['presensi_csrf'],
    'capture_token' => $nextCaptureToken,
]);
