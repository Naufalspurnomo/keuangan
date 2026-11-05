<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('POST');
$config = presensi_config();
presensi_require_internal_secret($config);
$paths = presensi_store_paths();
$lock = presensi_lock($paths);
$claim = null;
$dirty = false;
try {
    $events = presensi_read_events($paths);
    $now = time();
    foreach ($events as &$event) {
        if (!is_array($event)) continue;
        $delivery = presensi_delivery($event);
        $nextRetry = $delivery['next_retry_at'] === null ? 0 : strtotime($delivery['next_retry_at']);
        $leaseExpires = $delivery['lease_expires_at'] === null ? 0 : strtotime($delivery['lease_expires_at']);
        if ($delivery['status'] === 'pending'
            && $delivery['attempts'] >= PRESENSI_OUTBOX_MAX_ATTEMPTS
            && $leaseExpires !== false && $leaseExpires > 0 && $leaseExpires <= $now) {
            $delivery['status'] = 'unknown';
            $delivery['last_error'] = 'lease_expired_after_max_attempts';
            $delivery['next_retry_at'] = null;
            $delivery['lease_token_hash'] = null;
            $delivery['lease_expires_at'] = null;
            $event['whatsapp_delivery'] = $delivery;
            $dirty = true;
            continue;
        }
        $eligibleState = in_array($delivery['status'], ['pending', 'failed'], true);
        if (!$eligibleState || $delivery['attempts'] >= PRESENSI_OUTBOX_MAX_ATTEMPTS
            || ($nextRetry !== false && $nextRetry > $now)
            || ($leaseExpires !== false && $leaseExpires > $now)) {
            continue;
        }
        $photoName = (string) ($event['photo_name'] ?? '');
        if (!preg_match('/^evt-[a-f0-9]{24}\.jpg$/D', $photoName)) continue;
        $photoPath = $paths['photos'] . '/' . $photoName;
        $realPhoto = realpath($photoPath);
        if ($realPhoto === false || dirname($realPhoto) !== $paths['photos'] || !is_file($realPhoto)) continue;
        $photo = file_get_contents($realPhoto);
        if ($photo === false) continue;
        $leaseToken = bin2hex(random_bytes(32));
        $delivery['status'] = 'pending';
        $delivery['attempts']++;
        $delivery['lease_token_hash'] = hash('sha256', $leaseToken);
        $delivery['lease_expires_at'] = gmdate('c', $now + PRESENSI_OUTBOX_LEASE_SECONDS);
        $event['whatsapp_delivery'] = $delivery;
        $dirty = true;
        $claim = [
            'event_id' => (string) $event['id'],
            'lease_token' => $leaseToken,
            'lease_expires_at' => $delivery['lease_expires_at'],
            'attempt' => $delivery['attempts'],
            'employee_name' => (string) ($event['employee_name'] ?? ''),
            'action' => (string) ($event['action'] ?? ''),
            'project_name' => (string) ($event['project_name'] ?? ''),
            'occurred_at' => (string) ($event['occurred_at'] ?? ''),
            'accuracy_m' => (float) ($event['accuracy_m'] ?? 0),
            'photo_mime' => 'image/jpeg',
            'photo_base64' => base64_encode($photo),
        ];
        break;
    }
    unset($event);
    if ($dirty) presensi_write_events($paths, $events);
} finally {
    presensi_unlock($lock);
}
presensi_json_response(200, [
    'version' => 'presensi.outbox.claim.v1',
    'event' => $claim,
]);
