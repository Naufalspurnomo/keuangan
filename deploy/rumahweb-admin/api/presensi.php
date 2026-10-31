<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('GET');
presensi_admin_session();
$projectId = trim((string) ($_GET['project_id'] ?? ''));
if (!preg_match('/^[a-z0-9][a-z0-9-]{1,63}$/', $projectId)) {
    presensi_error(422, 'project_invalid', 'Proyek tidak valid.');
}
$events = presensi_read_events(presensi_store_paths());
presensi_json_response(200, [
    'version' => 'presensi.admin.v1',
    'project_id' => $projectId,
    'records' => presensi_build_records($events, $projectId),
]);
