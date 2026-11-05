<?php
declare(strict_types=1);

const PRESENSI_PUBLIC_PATH = '/absen/';
const PRESENSI_ADMIN_PATH = '/admin/';
const PRESENSI_MAX_SELFIE_BYTES = 3_145_728;
const PRESENSI_MIN_SELFIE_BYTES = 1_024;
const PRESENSI_SESSION_LIFETIME = 43_200;
const PRESENSI_SESSION_IDLE_LIFETIME = 1_800;
const PRESENSI_ADMIN_SESSION_LIFETIME = 2_592_000;
const PRESENSI_ADMIN_RENEW_AFTER = 86_400;
const PRESENSI_RATE_LIMIT_WINDOW = 600;
const PRESENSI_RATE_LIMIT_MAX = 12;
const PRESENSI_LOCATION_MAX_AGE_SECONDS = 120;
const PRESENSI_LOGIN_WINDOW = 900;
const PRESENSI_LOGIN_MAX_FAILURES = 5;
const PRESENSI_LOGIN_SOURCE_MAX_FAILURES = 25;
const PRESENSI_LOGIN_LOCK_SECONDS = 900;
const PRESENSI_LOGIN_MAX_BUCKETS = 256;
const PRESENSI_LOGIN_MAX_FILE_BYTES = 131_072;
const PRESENSI_OUTBOX_LEASE_SECONDS = 120;
const PRESENSI_OUTBOX_MAX_ATTEMPTS = 5;

final class PresensiStorageException extends RuntimeException
{
    public function __construct(
        public readonly int $httpStatus,
        public readonly string $publicCode,
        public readonly string $publicMessage,
    ) {
        parent::__construct($publicCode);
    }
}

function presensi_json_response(int $status, array $payload): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=UTF-8');
    header('Cache-Control: no-store, private');
    header('X-Content-Type-Options: nosniff');
    header('X-Robots-Tag: noindex, nofollow, noarchive');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function presensi_error(int $status, string $code, string $message): never
{
    presensi_json_response($status, ['error' => ['code' => $code, 'message' => $message]]);
}

function presensi_require_method(string $method): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== $method) {
        header('Allow: ' . $method);
        presensi_error(405, 'method_not_allowed', 'Metode tidak diizinkan.');
    }
}

function presensi_require_same_origin(): void
{
    $origin = (string) ($_SERVER['HTTP_ORIGIN'] ?? '');
    $originParts = $origin === '' ? false : parse_url($origin);
    $requestHost = strtolower((string) ($_SERVER['HTTP_HOST'] ?? ''));
    $originHost = is_array($originParts) ? strtolower((string) ($originParts['host'] ?? '')) : '';
    $originPort = is_array($originParts) && isset($originParts['port']) ? ':' . (int) $originParts['port'] : '';
    $originScheme = is_array($originParts) ? strtolower((string) ($originParts['scheme'] ?? '')) : '';
    $loopback = in_array($originHost, ['127.0.0.1', 'localhost', '::1'], true);
    $fetchSite = strtolower((string) ($_SERVER['HTTP_SEC_FETCH_SITE'] ?? 'same-origin'));
    if ($originHost . $originPort !== $requestHost
        || (!($loopback && $originScheme === 'http') && $originScheme !== 'https')
        || !in_array($fetchSite, ['same-origin', 'none'], true)) {
        presensi_error(403, 'origin_invalid', 'Asal permintaan tidak valid.');
    }
}

function presensi_require_fresh_observation(mixed $value, string $code, string $message): int
{
    $observedAtMs = filter_var($value, FILTER_VALIDATE_INT);
    $nowMs = (int) floor(microtime(true) * 1000);
    if ($observedAtMs === false
        || $observedAtMs < $nowMs - PRESENSI_LOCATION_MAX_AGE_SECONDS * 1000
        || $observedAtMs > $nowMs + 10_000) {
        presensi_error(422, $code, $message);
    }
    return (int) $observedAtMs;
}

function presensi_config(): array
{
    $accountRoot = presensi_account_root();
    $path = getenv('HOLLAWALL_PRESENSI_CONFIG') ?: $accountRoot . '/.hollawall-presensi.php';
    if (is_link($path)) {
        presensi_error(503, 'configuration_insecure', 'Konfigurasi presensi tidak aman.');
    }
    $real = realpath($path);
    if ($real === false
        || !is_file($real)
        || dirname($real) !== $accountRoot
        || fileowner($real) !== fileowner($accountRoot)
        || (((int) fileperms($real)) & 0777) !== 0600) {
        presensi_error(503, 'configuration_unavailable', 'Konfigurasi presensi belum tersedia.');
    }
    $config = require $real;
    if (!is_array($config)) {
        presensi_error(503, 'configuration_invalid', 'Konfigurasi presensi tidak valid.');
    }
    $retentionDays = filter_var($config['retention_days'] ?? null, FILTER_VALIDATE_INT);
    $outboxSecret = (string) ($config['outbox_shared_secret'] ?? '');
    $deliveryTriggerUrl = trim((string) ($config['delivery_trigger_url'] ?? ''));
    $deliveryTriggerParts = $deliveryTriggerUrl === '' ? false : parse_url($deliveryTriggerUrl);
    if (!isset($config['employees'], $config['projects'])
        || !is_array($config['employees'])
        || !is_array($config['projects'])
        || strlen($outboxSecret) < 32
        || ($deliveryTriggerUrl !== '' && (
            !is_array($deliveryTriggerParts)
            || strtolower((string) ($deliveryTriggerParts['scheme'] ?? '')) !== 'https'
            || trim((string) ($deliveryTriggerParts['host'] ?? '')) === ''
            || array_key_exists('user', $deliveryTriggerParts)
            || array_key_exists('pass', $deliveryTriggerParts)
            || array_key_exists('query', $deliveryTriggerParts)
            || array_key_exists('fragment', $deliveryTriggerParts)
        ))
        || $retentionDays === false || $retentionDays < 1 || $retentionDays > 365) {
        presensi_error(503, 'configuration_invalid', 'Konfigurasi presensi tidak valid.');
    }
    $employees = [];
    $employeeIds = [];
    $employeeNames = [];
    $employeeCodes = [];
    foreach ($config['employees'] as $row) {
        $employeeId = is_array($row) ? trim((string) ($row['id'] ?? '')) : '';
        $employeeName = is_array($row) ? trim((string) ($row['name'] ?? '')) : '';
        $employeeCode = is_array($row) ? strtoupper(trim((string) ($row['code'] ?? ''))) : '';
        $pinHash = is_array($row) ? (string) ($row['pin_hash'] ?? '') : '';
        $passwordInfo = password_get_info($pinHash);
        if (!is_array($row)
            || !preg_match('/^[a-z0-9][a-z0-9-]{1,63}$/D', $employeeId)
            || $employeeName === '' || strlen($employeeName) > 100
            || !preg_match('/^[A-Z0-9][A-Z0-9-]{2,31}$/D', $employeeCode)
            || ($passwordInfo['algoName'] ?? 'unknown') === 'unknown') {
            presensi_error(503, 'configuration_invalid', 'Konfigurasi pegawai tidak valid.');
        }
        $employeeIds[] = strtolower($employeeId);
        $employeeNames[] = strtolower($employeeName);
        $employeeCodes[] = $employeeCode;
        $employees[] = ['id' => $employeeId, 'name' => $employeeName, 'code' => $employeeCode, 'pin_hash' => $pinHash];
    }
    if (!$employees
        || count(array_unique($employeeIds)) !== count($employeeIds)
        || count(array_unique($employeeNames)) !== count($employeeNames)
        || count(array_unique($employeeCodes)) !== count($employeeCodes)) {
        presensi_error(503, 'configuration_invalid', 'Konfigurasi presensi memiliki identitas ganda atau tidak sesuai.');
    }

    $projects = [];
    $allProjectIds = [];
    $allProjectNames = [];
    foreach ($config['projects'] as $row) {
        $projectId = is_array($row) ? (string) ($row['id'] ?? '') : '';
        $projectName = is_array($row) ? trim((string) ($row['name'] ?? '')) : '';
        if (!is_array($row)
            || !preg_match('/^[a-z0-9][a-z0-9-]{1,63}$/', $projectId)
            || $projectName === ''
            || !array_key_exists('active', $row)
            || !is_bool($row['active'])) {
            presensi_error(503, 'configuration_invalid', 'Konfigurasi proyek tidak valid.');
        }
        $allProjectIds[] = $projectId;
        $allProjectNames[] = strtolower($projectName);
        if ($row['active'] !== true) {
            continue;
        }
        if (trim((string) ($row['company'] ?? '')) === '') {
            presensi_error(503, 'configuration_invalid', 'Konfigurasi proyek tidak valid.');
        }
        $projects[] = [
            'id' => $projectId,
            'name' => $projectName,
            'company' => trim((string) $row['company']),
        ];
    }
    if (count(array_unique($allProjectIds)) !== count($allProjectIds)
        || count(array_unique($allProjectNames)) !== count($allProjectNames)) {
        presensi_error(503, 'configuration_invalid', 'Konfigurasi presensi memiliki identitas ganda atau tidak sesuai.');
    }
    return [
        'employees' => $employees,
        'projects' => $projects,
        'retention_days' => (int) $retentionDays,
        'outbox_shared_secret' => $outboxSecret,
        'delivery_trigger_url' => $deliveryTriggerUrl,
    ];
}

function presensi_trigger_delivery(array $config): void
{
    $url = (string) ($config['delivery_trigger_url'] ?? '');
    if ($url === '') return;
    $headers = [
        'Accept: application/json',
        'Content-Length: 0',
        'X-Presensi-Secret: ' . (string) $config['outbox_shared_secret'],
    ];
    $context = stream_context_create([
        'http' => [
            'method' => 'POST',
            'header' => implode("\r\n", $headers),
            'content' => '',
            'timeout' => 1.5,
            'ignore_errors' => true,
            'follow_location' => 0,
            'max_redirects' => 0,
        ],
        'ssl' => ['verify_peer' => true, 'verify_peer_name' => true],
    ]);
    // The record is already durable. Delivery is best-effort here; the outbox
    // remains authoritative and can be retried safely by the bounded worker.
    @file_get_contents($url, false, $context, 0, 1);
}

function presensi_find_named(array $rows, string $id): ?array
{
    foreach ($rows as $row) {
        if (isset($row['id']) && hash_equals((string) $row['id'], $id)) {
            return $row;
        }
    }
    return null;
}

function presensi_account_root(): string
{
    $root = dirname(__DIR__, 3);
    $real = realpath($root);
    if ($real === false || !is_dir($real)) {
        presensi_error(503, 'storage_unavailable', 'Penyimpanan presensi belum tersedia.');
    }
    return $real;
}

function presensi_private_directory(string $name): string
{
    $accountRoot = presensi_account_root();
    $path = $accountRoot . '/' . $name;
    if (is_link($path)) {
        presensi_error(503, 'storage_insecure', 'Penyimpanan presensi tidak aman.');
    }
    if (!file_exists($path) && !mkdir($path, 0700, false)) {
        presensi_error(503, 'storage_unavailable', 'Penyimpanan presensi belum tersedia.');
    }
    clearstatcache(true, $path);
    $real = realpath($path);
    if ($real === false
        || !is_dir($real)
        || dirname($real) !== $accountRoot
        || fileowner($real) !== fileowner($accountRoot)
        || (((int) fileperms($real)) & 0777) !== 0700
        || !is_writable($real)) {
        presensi_error(503, 'storage_insecure', 'Penyimpanan presensi tidak aman.');
    }
    return $real;
}

function presensi_store_paths(): array
{
    $root = presensi_private_directory('.hollawall-presensi');
    $photos = $root . '/photos';
    if (is_link($photos)) {
        presensi_error(503, 'storage_insecure', 'Penyimpanan foto tidak aman.');
    }
    if (!file_exists($photos) && !mkdir($photos, 0700, false)) {
        presensi_error(503, 'storage_unavailable', 'Penyimpanan foto belum tersedia.');
    }
    clearstatcache(true, $photos);
    $realPhotos = realpath($photos);
    if ($realPhotos === false
        || !is_dir($realPhotos)
        || dirname($realPhotos) !== $root
        || (((int) fileperms($realPhotos)) & 0777) !== 0700
        || !is_writable($realPhotos)) {
        presensi_error(503, 'storage_insecure', 'Penyimpanan foto tidak aman.');
    }
    return [
        'root' => $root,
        'photos' => $realPhotos,
        'events' => $root . '/events.json',
        'lock' => $root . '/events.lock',
        'login_attempts' => $root . '/login-attempts.json',
        'login_lock' => $root . '/login-attempts.lock',
    ];
}

function presensi_read_events(array $paths): array
{
    if (!is_file($paths['events'])) {
        return [];
    }
    $raw = file_get_contents($paths['events']);
    $decoded = $raw === false ? null : json_decode($raw, true);
    if (!is_array($decoded)) {
        presensi_error(503, 'storage_corrupt', 'Data presensi tidak dapat dibaca.');
    }
    return $decoded;
}

function presensi_write_events(array $paths, array $events): void
{
    $json = json_encode($events, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    if ($json === false) {
        throw new PresensiStorageException(500, 'encode_failed', 'Presensi belum dapat disimpan.');
    }
    $temporary = $paths['root'] . '/events.' . bin2hex(random_bytes(8)) . '.tmp';
    try {
        if (getenv('HOLLAWALL_PRESENSI_FAULT') === 'event_write'
            || file_put_contents($temporary, $json . "\n", LOCK_EX) === false) {
            throw new PresensiStorageException(503, 'storage_unavailable', 'Presensi belum dapat disimpan.');
        }
        chmod($temporary, 0600);
        if (getenv('HOLLAWALL_PRESENSI_FAULT') === 'event_rename'
            || !rename($temporary, $paths['events'])) {
            throw new PresensiStorageException(503, 'storage_unavailable', 'Presensi belum dapat disimpan.');
        }
        chmod($paths['events'], 0600);
    } finally {
        if (is_file($temporary)) {
            @unlink($temporary);
        }
    }
}

function presensi_lock(array $paths)
{
    $lock = fopen($paths['lock'], 'c+');
    if ($lock === false) {
        presensi_error(503, 'storage_unavailable', 'Presensi belum dapat disimpan.');
    }
    chmod($paths['lock'], 0600);
    if (!flock($lock, LOCK_EX)) {
        fclose($lock);
        presensi_error(503, 'storage_busy', 'Presensi sedang diproses. Coba lagi.');
    }
    return $lock;
}

function presensi_unlock($lock): void
{
    flock($lock, LOCK_UN);
    fclose($lock);
}


function presensi_rate_limit(array $events, string $employeeId, int $now): void
{
    $recent = 0;
    foreach ($events as $event) {
        if (!is_array($event) || !isset($event['employee_id'], $event['occurred_at']) || !hash_equals((string) $event['employee_id'], $employeeId)) {
            continue;
        }
        $at = strtotime((string) $event['occurred_at']);
        if ($at !== false && $now - $at <= PRESENSI_RATE_LIMIT_WINDOW) {
            $recent++;
        }
    }
    if ($recent >= PRESENSI_RATE_LIMIT_MAX) {
        header('Retry-After: ' . PRESENSI_RATE_LIMIT_WINDOW);
        presensi_error(429, 'rate_limited', 'Terlalu banyak presensi untuk pegawai ini. Coba lagi nanti.');
    }
}

function presensi_open_event(array $events, string $employeeId): ?array
{
    $open = [];
    foreach ($events as $event) {
        if (!is_array($event) || ($event['employee_id'] ?? null) !== $employeeId) {
            continue;
        }
        $pair = (string) ($event['pair_id'] ?? '');
        if (($event['action'] ?? null) === 'check_in') {
            $open[$pair] = $event;
        } elseif (($event['action'] ?? null) === 'check_out') {
            unset($open[$pair]);
        }
    }
    if (!$open) {
        return null;
    }
    $latest = end($open);
    return is_array($latest) ? $latest : null;
}

function presensi_validate_selfie(array $upload): array
{
    if (($upload['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK || !isset($upload['tmp_name'])) {
        presensi_error(422, 'selfie_required', 'Selfie dari kamera wajib diambil.');
    }
    $size = (int) ($upload['size'] ?? 0);
    if ($size < PRESENSI_MIN_SELFIE_BYTES || $size > PRESENSI_MAX_SELFIE_BYTES) {
        presensi_error(422, 'selfie_invalid', 'Ukuran selfie tidak valid.');
    }
    $sourceBytes = file_get_contents((string) $upload['tmp_name']);
    if ($sourceBytes === false || strlen($sourceBytes) !== $size) {
        presensi_error(422, 'selfie_invalid', 'Selfie tidak dapat dibaca.');
    }
    $finfo = new finfo(FILEINFO_MIME_TYPE);
    $mime = (string) $finfo->buffer($sourceBytes);
    $dimensions = getimagesizefromstring($sourceBytes);
    $allowed = ['image/jpeg', 'image/png', 'image/webp'];
    if ($dimensions === false || !in_array($mime, $allowed, true) || ($dimensions['mime'] ?? '') !== $mime) {
        presensi_error(415, 'selfie_invalid', 'Format selfie harus JPEG, PNG, atau WebP.');
    }
    $width = (int) $dimensions[0];
    $height = (int) $dimensions[1];
    if ($width < 320 || $height < 240 || $width > 4096 || $height > 4096) {
        presensi_error(422, 'selfie_invalid', 'Resolusi selfie tidak valid.');
    }
    if (!extension_loaded('gd') || !function_exists('imagecreatefromstring')) {
        presensi_error(503, 'image_processor_unavailable', 'Pemroses selfie belum tersedia.');
    }
    $source = @imagecreatefromstring($sourceBytes);
    if ($source === false) {
        presensi_error(415, 'selfie_invalid', 'Selfie tidak dapat diproses.');
    }
    $scale = min(1.0, 1280 / max($width, $height));
    $targetWidth = max(1, (int) round($width * $scale));
    $targetHeight = max(1, (int) round($height * $scale));
    $target = imagecreatetruecolor($targetWidth, $targetHeight);
    if ($target === false || !imagecopyresampled($target, $source, 0, 0, 0, 0, $targetWidth, $targetHeight, $width, $height)) {
        imagedestroy($source);
        if (is_object($target) || is_resource($target)) imagedestroy($target);
        presensi_error(422, 'selfie_invalid', 'Selfie tidak dapat diproses.');
    }
    $minimumLuma = 255.0;
    $maximumLuma = 0.0;
    $totalLuma = 0.0;
    $samples = 0;
    $stepX = max(1, intdiv($targetWidth, 32));
    $stepY = max(1, intdiv($targetHeight, 24));
    for ($y = 0; $y < $targetHeight; $y += $stepY) {
        for ($x = 0; $x < $targetWidth; $x += $stepX) {
            $rgb = imagecolorat($target, $x, $y);
            $red = ($rgb >> 16) & 0xff;
            $green = ($rgb >> 8) & 0xff;
            $blue = $rgb & 0xff;
            $luma = 0.2126 * $red + 0.7152 * $green + 0.0722 * $blue;
            $minimumLuma = min($minimumLuma, $luma);
            $maximumLuma = max($maximumLuma, $luma);
            $totalLuma += $luma;
            $samples++;
        }
    }
    if ($samples === 0 || $totalLuma / $samples < 20 || $maximumLuma - $minimumLuma < 12) {
        imagedestroy($source);
        imagedestroy($target);
        presensi_error(422, 'selfie_unusable', 'Selfie terlalu gelap atau tidak memiliki detail. Ambil ulang di tempat terang.');
    }
    ob_start();
    $encoded = imagejpeg($target, null, 85);
    $bytes = ob_get_clean();
    imagedestroy($source);
    imagedestroy($target);
    if (!$encoded || !is_string($bytes) || strlen($bytes) < 1024) {
        presensi_error(422, 'selfie_invalid', 'Selfie tidak dapat diproses.');
    }
    return ['bytes' => $bytes, 'mime' => 'image/jpeg', 'extension' => 'jpg', 'width' => $targetWidth, 'height' => $targetHeight];
}

function presensi_issue_capture_token(): string
{
    $token = bin2hex(random_bytes(24));
    $_SESSION['capture_token_hash'] = hash('sha256', $token);
    $_SESSION['capture_token_expires'] = time() + 300;
    return $token;
}

function presensi_validate_capture_token(string $token): void
{
    $expected = (string) ($_SESSION['capture_token_hash'] ?? '');
    $expires = (int) ($_SESSION['capture_token_expires'] ?? 0);
    if ($token === '' || $expected === '' || $expires < time() || !hash_equals($expected, hash('sha256', $token))) {
        presensi_error(403, 'capture_expired', 'Sesi pengambilan bukti berakhir. Muat ulang halaman.');
    }
}

function presensi_consume_capture_token(): string
{
    unset($_SESSION['capture_token_hash'], $_SESSION['capture_token_expires']);
    return presensi_issue_capture_token();
}

function presensi_public_employee(bool $required = true): ?array
{
    $employeeId = (string) ($_SESSION['presensi_employee_id'] ?? '');
    $employeeName = (string) ($_SESSION['presensi_employee_name'] ?? '');
    $now = time();
    $authenticatedAt = (int) ($_SESSION['presensi_authenticated_at'] ?? 0);
    $lastSeen = (int) ($_SESSION['presensi_last_seen'] ?? 0);
    if ($employeeId === '' || $employeeName === '' || $authenticatedAt <= 0
        || $now - $authenticatedAt > PRESENSI_SESSION_LIFETIME
        || ($lastSeen > 0 && $now - $lastSeen > PRESENSI_SESSION_IDLE_LIFETIME)) {
        unset($_SESSION['presensi_employee_id'], $_SESSION['presensi_employee_name'], $_SESSION['presensi_authenticated_at'], $_SESSION['presensi_last_seen']);
        if ($required) {
            presensi_error(401, 'authentication_required', 'Masuk sebagai pegawai diperlukan.');
        }
        return null;
    }
    $_SESSION['presensi_last_seen'] = $now;
    return ['id' => $employeeId, 'name' => $employeeName];
}

function presensi_login_keys(string $code): array
{
    $remote = strtolower((string) ($_SERVER['REMOTE_ADDR'] ?? 'unknown'));
    $source = hash('sha256', 'source|' . $remote);
    $normalizedCode = preg_match('/^[A-Z0-9][A-Z0-9-]{2,31}$/D', $code) ? $code : '__INVALID__';
    $credential = hash('sha256', 'credential|' . $remote . '|' . $normalizedCode);
    return [$source => PRESENSI_LOGIN_SOURCE_MAX_FAILURES, $credential => PRESENSI_LOGIN_MAX_FAILURES];
}

function presensi_read_login_rows(array $paths): array
{
    if (!is_file($paths['login_attempts'])) return [];
    $size = filesize($paths['login_attempts']);
    if ($size === false || $size > PRESENSI_LOGIN_MAX_FILE_BYTES) {
        presensi_error(503, 'authentication_unavailable', 'Masuk belum dapat diproses.');
    }
    $decoded = json_decode((string) file_get_contents($paths['login_attempts']), true);
    if (!is_array($decoded)) presensi_error(503, 'authentication_unavailable', 'Masuk belum dapat diproses.');
    return $decoded;
}

function presensi_login_attempts(array $paths, array $keys, bool $success): int
{
    $handle = fopen($paths['login_lock'], 'c+');
    if ($handle === false || !flock($handle, LOCK_EX)) {
        if (is_resource($handle)) fclose($handle);
        presensi_error(503, 'authentication_unavailable', 'Masuk belum dapat diproses.');
    }
    chmod($paths['login_lock'], 0600);
    try {
        $rows = presensi_read_login_rows($paths);
        $now = time();
        foreach ($rows as $rowKey => $row) {
            if (!is_array($row) || (int) ($row['updated_at'] ?? 0) < $now - PRESENSI_LOGIN_LOCK_SECONDS * 2) unset($rows[$rowKey]);
        }
        $retryAfter = 0;
        foreach ($keys as $key => $failureLimit) {
            $row = is_array($rows[$key] ?? null) ? $rows[$key] : ['failures' => [], 'locked_until' => 0];
            $failures = array_values(array_filter((array) ($row['failures'] ?? []), static fn($at): bool => is_int($at) && $at >= $now - PRESENSI_LOGIN_WINDOW));
            $lockedUntil = (int) ($row['locked_until'] ?? 0);
            if ($success) {
                unset($rows[$key]);
            } elseif ($lockedUntil <= $now) {
                $failures[] = $now;
                if (count($failures) >= (int) $failureLimit) $lockedUntil = $now + PRESENSI_LOGIN_LOCK_SECONDS;
                $rows[$key] = ['failures' => array_slice($failures, -(int) $failureLimit), 'locked_until' => $lockedUntil, 'updated_at' => $now];
            }
            $retryAfter = max($retryAfter, $lockedUntil - $now);
        }
        if (count($rows) > PRESENSI_LOGIN_MAX_BUCKETS) {
            uasort($rows, static fn(array $a, array $b): int => (int) ($b['updated_at'] ?? 0) <=> (int) ($a['updated_at'] ?? 0));
            $rows = array_slice($rows, 0, PRESENSI_LOGIN_MAX_BUCKETS, true);
        }
        $temporary = $paths['root'] . '/login-attempts.' . bin2hex(random_bytes(8)) . '.tmp';
        $encoded = json_encode($rows, JSON_UNESCAPED_SLASHES);
        if ($encoded === false || strlen($encoded) > PRESENSI_LOGIN_MAX_FILE_BYTES || file_put_contents($temporary, $encoded . "\n", LOCK_EX) === false) {
            presensi_error(503, 'authentication_unavailable', 'Masuk belum dapat diproses.');
        }
        chmod($temporary, 0600);
        if (!rename($temporary, $paths['login_attempts'])) {
            @unlink($temporary);
            presensi_error(503, 'authentication_unavailable', 'Masuk belum dapat diproses.');
        }
        chmod($paths['login_attempts'], 0600);
        return max(0, $retryAfter);
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
}

function presensi_login_locked(array $paths, array $keys): int
{
    $handle = fopen($paths['login_lock'], 'c+');
    if ($handle === false || !flock($handle, LOCK_SH)) {
        if (is_resource($handle)) fclose($handle);
        presensi_error(503, 'authentication_unavailable', 'Masuk belum dapat diproses.');
    }
    try {
        $rows = presensi_read_login_rows($paths);
        $until = 0;
        foreach (array_keys($keys) as $key) $until = max($until, (int) ($rows[$key]['locked_until'] ?? 0));
        return max(0, $until - time());
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
}

function presensi_require_internal_secret(array $config): void
{
    $provided = trim((string) ($_SERVER['HTTP_X_PRESENSI_SECRET'] ?? ''));
    $expected = (string) ($config['outbox_shared_secret'] ?? '');
    if ($provided === '' || $expected === '' || !hash_equals($expected, $provided)) {
        presensi_error(401, 'authentication_required', 'Autentikasi internal diperlukan.');
    }
}

function presensi_delivery(array $event): array
{
    $delivery = is_array($event['whatsapp_delivery'] ?? null) ? $event['whatsapp_delivery'] : [];
    $state = (string) ($delivery['status'] ?? 'unknown');
    if (!in_array($state, ['pending', 'sent', 'failed', 'unknown'], true)) $state = 'unknown';
    return [
        'status' => $state,
        'attempts' => max(0, (int) ($delivery['attempts'] ?? 0)),
        'next_retry_at' => isset($delivery['next_retry_at']) ? (string) $delivery['next_retry_at'] : null,
        'provider_message_id' => isset($delivery['provider_message_id']) ? (string) $delivery['provider_message_id'] : null,
        'last_error' => isset($delivery['last_error']) ? (string) $delivery['last_error'] : null,
        'lease_token_hash' => isset($delivery['lease_token_hash']) ? (string) $delivery['lease_token_hash'] : null,
        'lease_expires_at' => isset($delivery['lease_expires_at']) ? (string) $delivery['lease_expires_at'] : null,
    ];
}

function presensi_public_session(): void
{
    $sessionPath = presensi_private_directory('.hollawall-presensi-sessions');
    $requestedId = (string) ($_COOKIE['hollawall_presensi'] ?? '');
    if (session_status() === PHP_SESSION_ACTIVE
        && (session_name() !== 'hollawall_presensi' || realpath(session_save_path()) !== $sessionPath)) {
        session_write_close();
        session_id('');
    }
    if (session_status() !== PHP_SESSION_ACTIVE) {
        if (session_name('hollawall_presensi') === false
            || ini_set('session.use_strict_mode', '1') === false
            || ini_set('session.use_only_cookies', '1') === false
            || ini_set('session.gc_maxlifetime', (string) PRESENSI_SESSION_LIFETIME) === false
            || session_save_path($sessionPath) === false
            || !session_set_cookie_params([
                'lifetime' => PRESENSI_SESSION_LIFETIME,
                'path' => PRESENSI_PUBLIC_PATH,
                'secure' => true,
                'httponly' => true,
                'samesite' => 'Strict',
            ])) {
            presensi_error(503, 'session_unavailable', 'Sesi presensi belum tersedia.');
        }
        if ($requestedId !== '') {
            if (!preg_match('/^[A-Za-z0-9,-]{16,256}$/D', $requestedId) || session_id($requestedId) === false) {
                presensi_error(400, 'session_invalid', 'Sesi presensi tidak valid.');
            }
        }
        if (!session_start()) {
            presensi_error(503, 'session_unavailable', 'Sesi presensi belum tersedia.');
        }
    }
    if (empty($_SESSION['presensi_csrf'])) {
        $_SESSION['presensi_csrf'] = bin2hex(random_bytes(24));
    }
    if (empty($_SESSION['presensi_recovery_key'])) {
        $_SESSION['presensi_recovery_key'] = bin2hex(random_bytes(32));
    }
}

function presensi_admin_session(): void
{
    $sessionPath = presensi_private_directory('.hollawall-admin-sessions');
    $requestedId = (string) ($_COOKIE['hollawall_admin'] ?? '');
    if (session_status() === PHP_SESSION_ACTIVE
        && (session_name() !== 'hollawall_admin' || realpath(session_save_path()) !== $sessionPath)) {
        session_write_close();
        session_id('');
    }
    if (session_status() !== PHP_SESSION_ACTIVE) {
        if (session_name('hollawall_admin') === false
            || ini_set('session.use_strict_mode', '1') === false
            || ini_set('session.use_only_cookies', '1') === false
            || ini_set('session.gc_maxlifetime', (string) PRESENSI_ADMIN_SESSION_LIFETIME) === false
            || session_save_path($sessionPath) === false
            || !session_set_cookie_params([
                'lifetime' => PRESENSI_ADMIN_SESSION_LIFETIME,
                'path' => PRESENSI_ADMIN_PATH,
                'secure' => true,
                'httponly' => true,
                'samesite' => 'Strict',
            ])) {
            presensi_error(503, 'session_unavailable', 'Sesi admin belum tersedia.');
        }
        if ($requestedId !== '') {
            if (!preg_match('/^[A-Za-z0-9,-]{16,256}$/D', $requestedId) || session_id($requestedId) === false) {
                presensi_error(400, 'session_invalid', 'Sesi admin tidak valid.');
            }
        }
        if (!session_start()) {
            presensi_error(503, 'session_unavailable', 'Sesi admin belum tersedia.');
        }
    }
    $now = time();
    if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > PRESENSI_ADMIN_SESSION_LIFETIME) {
        $_SESSION = [];
        session_regenerate_id(true);
        presensi_error(401, 'session_expired', 'Masuk sebagai admin diperlukan.');
    }
    if (empty($_SESSION['hollawall_admin_user'])) {
        presensi_error(401, 'authentication_required', 'Masuk sebagai admin diperlukan.');
    }
    $_SESSION['last_seen'] = $now;
    if ($now - (int) ($_SESSION['cookie_renewed_at'] ?? 0) >= PRESENSI_ADMIN_RENEW_AFTER) {
        $_SESSION['cookie_renewed_at'] = $now;
        setcookie(session_name(), session_id(), [
            'expires' => $now + PRESENSI_ADMIN_SESSION_LIFETIME,
            'path' => PRESENSI_ADMIN_PATH,
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Strict',
        ]);
    }
}

function presensi_build_records(array $events, ?string $projectId = null): array
{
    $records = [];
    foreach ($events as $event) {
        if (!is_array($event) || ($projectId !== null && ($event['project_id'] ?? null) !== $projectId)) {
            continue;
        }
        $pair = (string) ($event['pair_id'] ?? '');
        if ($pair === '') {
            continue;
        }
        if (!isset($records[$pair])) {
            $records[$pair] = [
                'id' => $pair,
                'employee_id' => (string) ($event['employee_id'] ?? ''),
                'employee_name' => (string) ($event['employee_name'] ?? ''),
                'project_id' => (string) ($event['project_id'] ?? ''),
                'project_name' => (string) ($event['project_name'] ?? ''),
                'check_in' => null,
                'check_out' => null,
            ];
        }
        $latitude = filter_var($event['latitude'] ?? null, FILTER_VALIDATE_FLOAT);
        $longitude = filter_var($event['longitude'] ?? null, FILTER_VALIDATE_FLOAT);
        $delivery = presensi_delivery($event);
        $evidence = [
            'id' => (string) ($event['id'] ?? ''),
            'occurred_at' => (string) ($event['occurred_at'] ?? ''),
            'latitude' => $latitude === false ? null : (float) $latitude,
            'longitude' => $longitude === false ? null : (float) $longitude,
            'accuracy_m' => (float) ($event['accuracy_m'] ?? 0),
            'photo_url' => PRESENSI_ADMIN_PATH . 'api/presensi-photo.php?id=' . rawurlencode((string) ($event['id'] ?? '')),
            'whatsapp_delivery' => [
                'status' => $delivery['status'],
                'attempts' => $delivery['attempts'],
            ],
        ];
        if (($event['action'] ?? null) === 'check_in') {
            $records[$pair]['check_in'] = $evidence;
        } elseif (($event['action'] ?? null) === 'check_out') {
            $records[$pair]['check_out'] = $evidence;
        }
    }
    $result = [];
    foreach ($records as $record) {
        if (!is_array($record['check_in'])) {
            continue;
        }
        $duration = null;
        if (is_array($record['check_out'])) {
            $started = strtotime((string) $record['check_in']['occurred_at']);
            $ended = strtotime((string) $record['check_out']['occurred_at']);
            if ($started !== false && $ended !== false) {
                $duration = max(0, (int) floor(($ended - $started) / 60));
            }
        }
        $record['status'] = $record['check_out'] === null ? 'active' : 'completed';
        $record['duration_minutes'] = $duration;
        $result[] = $record;
    }
    usort($result, static function (array $left, array $right): int {
        return strcmp((string) $right['check_in']['occurred_at'], (string) $left['check_in']['occurred_at']);
    });
    return $result;
}
