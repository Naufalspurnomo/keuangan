<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('GET');
presensi_public_session();
$employeeId = trim((string) ($_GET['employee_id'] ?? ''));
$config = presensi_config();
$employee = presensi_find_named($config['employees'], $employeeId);
if ($employee === null) {
    presensi_error(422, 'employee_invalid', 'Pegawai tidak valid.');
}
$events = presensi_read_events(presensi_store_paths());
$open = presensi_open_event($events, $employeeId);
presensi_json_response(200, [
    'version' => 'presensi.status.v1',
    'employee' => $employee,
    'next_action' => $open === null ? 'check_in' : 'check_out',
    'active_project' => $open === null ? null : [
        'id' => $open['project_id'],
        'name' => $open['project_name'],
    ],
]);
