<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('GET');
presensi_public_session();
$employee = presensi_public_employee();
$employeeId = $employee['id'];
$submissionId = trim((string) ($_GET['submission_id'] ?? ''));
$submissionAction = trim((string) ($_GET['submission_action'] ?? ''));
$submissionProject = trim((string) ($_GET['submission_project'] ?? ''));
if ($submissionId !== '' && (!preg_match('/^sub-[a-f0-9]{32}$/', $submissionId)
    || !in_array($submissionAction, ['check_in', 'check_out'], true)
    || $submissionProject === '')) {
    presensi_error(422, 'submission_invalid', 'Identitas pengiriman tidak valid.');
}
$events = presensi_read_events(presensi_store_paths());
$open = presensi_open_event($events, $employeeId);
$submissionReceived = false;
if ($submissionId !== '') {
    $expectedRecoveryHash = hash_hmac('sha256', $submissionId, (string) $_SESSION['presensi_recovery_key']);
    foreach ($events as $event) {
        if (hash_equals((string) ($event['submission_id'] ?? ''), $submissionId)
            && hash_equals((string) ($event['employee_id'] ?? ''), $employeeId)
            && hash_equals((string) ($event['action'] ?? ''), $submissionAction)
            && hash_equals((string) ($event['project_id'] ?? ''), $submissionProject)
            && hash_equals((string) ($event['recovery_hash'] ?? ''), $expectedRecoveryHash)) {
            $submissionReceived = true;
            break;
        }
    }
}
$recoveryCaptureToken = $submissionReceived ? presensi_issue_capture_token() : null;
presensi_json_response(200, [
    'version' => 'presensi.status.v1',
    'employee' => $employee,
    'submission_received' => $submissionReceived,
    'recovery' => $submissionReceived ? [
        'csrf' => (string) $_SESSION['presensi_csrf'],
        'capture_token' => $recoveryCaptureToken,
    ] : null,
    'next_action' => $open === null ? 'check_in' : 'check_out',
    'active_project' => $open === null ? null : [
        'id' => $open['project_id'],
        'name' => $open['project_name'],
    ],
]);
