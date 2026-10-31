<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
require dirname(__DIR__) . '/api/presensi-common.php';

function purge_reconcile_quarantines(array $paths, array $events): array
{
    $referenced = [];
    foreach ($events as $event) {
        if (!is_array($event)) {
            continue;
        }
        $photoName = (string) ($event['photo_name'] ?? '');
        if ($photoName !== '' && basename($photoName) === $photoName) {
            $referenced[$photoName] = true;
        }
    }
    $matches = glob($paths['photos'] . '/*.purge-*');
    if ($matches === false) {
        throw new PresensiStorageException(503, 'storage_unavailable', 'Rekonsiliasi foto gagal.');
    }
    $restored = 0;
    $deleted = 0;
    foreach ($matches as $quarantine) {
        $name = basename($quarantine);
        if (is_link($quarantine)
            || !is_file($quarantine)
            || !preg_match('/^(evt-[a-f0-9]{24}\.jpg)\.purge-[a-f0-9]{12}$/', $name, $parts)) {
            throw new PresensiStorageException(503, 'storage_insecure', 'Artefak karantina tidak aman.');
        }
        $photoName = $parts[1];
        $original = $paths['photos'] . '/' . $photoName;
        if (isset($referenced[$photoName])) {
            if (file_exists($original) || !rename($quarantine, $original) || !chmod($original, 0600)) {
                throw new PresensiStorageException(503, 'storage_unavailable', 'Pemulihan foto karantina gagal.');
            }
            $restored++;
            continue;
        }
        if (!unlink($quarantine) || file_exists($quarantine)) {
            throw new PresensiStorageException(503, 'storage_unavailable', 'Penghapusan foto karantina gagal.');
        }
        $deleted++;
    }
    return ['restored_photos' => $restored, 'deleted_quarantines' => $deleted];
}

$config = presensi_config();
$paths = presensi_store_paths();
$lock = presensi_lock($paths);
$quarantined = [];
$removed = 0;
$eventsCommitted = false;
$reconciled = ['restored_photos' => 0, 'deleted_quarantines' => 0];
try {
    $events = presensi_read_events($paths);
    $reconciled = purge_reconcile_quarantines($paths, $events);
    $events = presensi_read_events($paths);
    $cutoff = time() - ((int) $config['retention_days'] * 86_400);
    $completedPairs = [];
    foreach ($events as $event) {
        if (!is_array($event) || ($event['action'] ?? null) !== 'check_out') {
            continue;
        }
        $occurredAt = strtotime((string) ($event['occurred_at'] ?? ''));
        if ($occurredAt !== false && $occurredAt < $cutoff) {
            $completedPairs[(string) ($event['pair_id'] ?? '')] = true;
        }
    }
    $keep = [];
    $expired = [];
    foreach ($events as $event) {
        $pairId = is_array($event) ? (string) ($event['pair_id'] ?? '') : '';
        if ($pairId !== '' && isset($completedPairs[$pairId])) {
            $expired[] = $event;
        } else {
            $keep[] = $event;
        }
    }
    foreach ($expired as $event) {
        $photoName = basename((string) ($event['photo_name'] ?? ''));
        if (!preg_match('/^evt-[a-f0-9]{24}\.jpg$/', $photoName)) {
            throw new PresensiStorageException(503, 'storage_insecure', 'Referensi foto presensi tidak aman.');
        }
        $source = $paths['photos'] . '/' . $photoName;
        if (!is_file($source) || is_link($source)) {
            throw new PresensiStorageException(503, 'storage_unavailable', 'Foto presensi tidak lengkap.');
        }
        $quarantine = $source . '.purge-' . bin2hex(random_bytes(6));
        if (!rename($source, $quarantine)) {
            throw new PresensiStorageException(503, 'storage_unavailable', 'Pembersihan foto gagal.');
        }
        $quarantined[$source] = $quarantine;
    }
    if ($expired) {
        presensi_write_events($paths, $keep);
        $eventsCommitted = true;
    }
    foreach ($quarantined as $quarantine) {
        if (!unlink($quarantine) || file_exists($quarantine)) {
            throw new PresensiStorageException(503, 'storage_unavailable', 'Penghapusan foto karantina gagal.');
        }
    }
    $removed = count($expired);
} catch (Throwable $error) {
    if (!$eventsCommitted) {
        foreach ($quarantined as $source => $quarantine) {
            if (is_file($quarantine) && (!rename($quarantine, $source) || !chmod($source, 0600))) {
                fwrite(STDERR, "Presensi purge rollback failed for " . basename($source) . PHP_EOL);
            }
        }
    }
    fwrite(STDERR, "Presensi purge failed: " . $error->getMessage() . PHP_EOL);
    presensi_unlock($lock);
    exit(1);
}
presensi_unlock($lock);
echo json_encode([
    'removed_events' => $removed,
    'restored_photos' => $reconciled['restored_photos'],
    'deleted_quarantines' => $reconciled['deleted_quarantines'],
], JSON_UNESCAPED_SLASHES) . PHP_EOL;
