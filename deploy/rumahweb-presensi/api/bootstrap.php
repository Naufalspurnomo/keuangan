<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('GET');
presensi_public_session();
$config = presensi_config();
$employee = presensi_public_employee(false);
$payload = [
    'version' => 'presensi.bootstrap.v2',
    'authenticated' => $employee !== null,
    'employee' => $employee,
    'csrf' => (string) $_SESSION['presensi_csrf'],
];
if ($employee !== null) {
    $payload['projects'] = array_map(static fn(array $project): array => [
        'id' => $project['id'],
        'name' => $project['name'],
        'company' => $project['company'],
    ], $config['projects']);
    $payload['capture_token'] = presensi_issue_capture_token();
    $payload['capture_expires_in'] = 300;
}
presensi_json_response(200, $payload);
