<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('POST');
$config = presensi_config();
presensi_require_internal_secret($config);
$contentType = strtolower(trim(explode(';', (string) ($_SERVER['CONTENT_TYPE'] ?? ''))[0]));
if ($contentType !== 'application/json') presensi_error(415, 'content_type_invalid', 'Content-Type tidak valid.');
$raw = file_get_contents('php://input');
$body = $raw === false ? null : json_decode($raw, true);
if (!is_array($body)) presensi_error(422, 'payload_invalid', 'Payload tidak valid.');
$eventId = trim((string) ($body['event_id'] ?? ''));
$leaseToken = trim((string) ($body['lease_token'] ?? ''));
$outcome = trim((string) ($body['outcome'] ?? ''));
$providerMessageId = trim((string) ($body['provider_message_id'] ?? ''));
$errorCode = preg_replace('/[^a-z0-9_.:-]/i', '', trim((string) ($body['error_code'] ?? ''))) ?? '';
if (!preg_match('/^evt-[a-f0-9]{24}$/D', $eventId) || !preg_match('/^[a-f0-9]{64}$/D', $leaseToken)
    || !in_array($outcome, ['sent', 'failed', 'unknown'], true)
    || strlen($providerMessageId) > 160 || strlen($errorCode) > 80) {
    presensi_error(422, 'payload_invalid', 'Payload tidak valid.');
}
$paths = presensi_store_paths();
$lock = presensi_lock($paths);
$updated = null;
try {
    $events = presensi_read_events($paths);
    foreach ($events as &$event) {
        if (!is_array($event) || !hash_equals((string) ($event['id'] ?? ''), $eventId)) continue;
        $delivery = presensi_delivery($event);
        if ($delivery['status'] === 'sent') {
            $updated = $delivery;
            break;
        }
        $leaseHash = (string) ($delivery['lease_token_hash'] ?? '');
        if ($leaseHash === '' || !hash_equals($leaseHash, hash('sha256', $leaseToken))) {
            presensi_error(409, 'lease_invalid', 'Lease pengiriman tidak valid.');
        }
        $delivery['lease_token_hash'] = null;
        $delivery['lease_expires_at'] = null;
        $delivery['provider_message_id'] = $outcome === 'sent' && $providerMessageId !== '' ? $providerMessageId : null;
        $delivery['last_error'] = $outcome === 'sent' ? null : ($errorCode !== '' ? $errorCode : $outcome);
        if ($outcome === 'sent') {
            $delivery['status'] = 'sent';
            $delivery['next_retry_at'] = null;
        } elseif ($outcome === 'unknown') {
            // Unknown may already have reached WhatsApp. Stop automatic retries to avoid duplicates.
            $delivery['status'] = 'unknown';
            $delivery['next_retry_at'] = null;
        } elseif ($delivery['attempts'] >= PRESENSI_OUTBOX_MAX_ATTEMPTS) {
            $delivery['status'] = 'failed';
            $delivery['next_retry_at'] = null;
        } else {
            $delivery['status'] = 'failed';
            $backoff = min(3600, 30 * (2 ** max(0, $delivery['attempts'] - 1)));
            $delivery['next_retry_at'] = gmdate('c', time() + $backoff);
        }
        $event['whatsapp_delivery'] = $delivery;
        $updated = $delivery;
        presensi_write_events($paths, $events);
        break;
    }
    unset($event);
} finally {
    presensi_unlock($lock);
}
if ($updated === null) presensi_error(404, 'event_not_found', 'Event tidak ditemukan.');
presensi_json_response(200, [
    'version' => 'presensi.outbox.ack.v1',
    'event_id' => $eventId,
    'status' => $updated['status'],
    'attempts' => $updated['attempts'],
]);
