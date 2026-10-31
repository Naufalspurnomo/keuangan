<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('GET');
presensi_public_session();
$config = presensi_config();
presensi_json_response(200, [
    'version' => 'presensi.bootstrap.v1',
    'employees' => $config['employees'],
    'projects' => array_map(static fn(array $project): array => [
        'id' => $project['id'],
        'name' => $project['name'],
        'company' => $project['company'],
    ], $config['projects']),
    'csrf' => (string) $_SESSION['presensi_csrf'],
    'capture_token' => presensi_issue_capture_token(),
    'capture_expires_in' => 300,
]);
