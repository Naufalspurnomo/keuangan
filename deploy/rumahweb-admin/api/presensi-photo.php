<?php
declare(strict_types=1);
require __DIR__ . '/presensi-common.php';

presensi_require_method('GET');
presensi_admin_session();
$eventId = trim((string) ($_GET['id'] ?? ''));
if (!preg_match('/^evt-[a-f0-9]{24}$/', $eventId)) {
    presensi_error(404, 'photo_not_found', 'Foto tidak ditemukan.');
}
$paths = presensi_store_paths();
$events = presensi_read_events($paths);
$event = null;
foreach ($events as $candidate) {
    if (is_array($candidate) && isset($candidate['id']) && hash_equals((string) $candidate['id'], $eventId)) {
        $event = $candidate;
        break;
    }
}
if ($event === null || !isset($event['photo_name'], $event['photo_mime'])) {
    presensi_error(404, 'photo_not_found', 'Foto tidak ditemukan.');
}
$name = (string) $event['photo_name'];
if (!preg_match('/^evt-[a-f0-9]{24}\.(jpg|png|webp)$/', $name)) {
    presensi_error(404, 'photo_not_found', 'Foto tidak ditemukan.');
}
$path = $paths['photos'] . '/' . $name;
$real = realpath($path);
if ($real === false || dirname($real) !== $paths['photos'] || !is_file($real)) {
    presensi_error(404, 'photo_not_found', 'Foto tidak ditemukan.');
}
$allowed = ['image/jpeg', 'image/png', 'image/webp'];
$mime = (string) $event['photo_mime'];
if (!in_array($mime, $allowed, true)) {
    presensi_error(404, 'photo_not_found', 'Foto tidak ditemukan.');
}
header('Content-Type: ' . $mime);
header('Content-Length: ' . (string) filesize($real));
header('Content-Disposition: inline; filename="presensi-' . $eventId . '"');
header('Cache-Control: private, no-store');
header('X-Content-Type-Options: nosniff');
header('Content-Security-Policy: default-src \'none\'; sandbox');
readfile($real);
