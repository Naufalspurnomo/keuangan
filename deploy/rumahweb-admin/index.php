<?php
declare(strict_types=1);

const ADMIN_PATH = '/admin/';
const SESSION_KEY = 'hollawall_admin_user';
const SESSION_LIFETIME = 2592000;
const SESSION_RENEW_AFTER = 86400;
const LOGIN_RATE_MAX = 5;
const LOGIN_RATE_BLOCK_SECONDS = 60;
const LOGIN_RATE_RETENTION_SECONDS = 86400;

function fail_closed(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: text/plain; charset=UTF-8');
    header('Cache-Control: no-store');
    echo $message;
    exit;
}

function admin_login_rate(string $path, string $accountRoot, string $key, string $action, int $now): array
{
    if (is_link($path) || !in_array($action, ['inspect', 'failure', 'success'], true)) {
        fail_closed(503, 'Admin login protection unavailable.');
    }
    $created = !file_exists($path);
    $handle = @fopen($path, 'c+b');
    if ($handle === false) {
        fail_closed(503, 'Admin login protection unavailable.');
    }
    if ($created && !chmod($path, 0600)) {
        fclose($handle);
        fail_closed(503, 'Admin login protection unavailable.');
    }
    clearstatcache(true, $path);
    $realPath = realpath($path);
    if ($realPath === false
        || dirname($realPath) !== $accountRoot
        || fileowner($realPath) !== fileowner($accountRoot)
        || ((int) fileperms($realPath) & 0777) !== 0600
        || !flock($handle, LOCK_EX)) {
        fclose($handle);
        fail_closed(503, 'Admin login protection unavailable.');
    }
    rewind($handle);
    $raw = stream_get_contents($handle);
    $ledger = $raw === '' ? [] : json_decode($raw, true);
    if (!is_array($ledger)) {
        flock($handle, LOCK_UN);
        fclose($handle);
        fail_closed(503, 'Admin login protection unavailable.');
    }
    foreach ($ledger as $entryKey => $entry) {
        if (!is_array($entry) || (int) ($entry['updated_at'] ?? 0) < $now - LOGIN_RATE_RETENTION_SECONDS) {
            unset($ledger[$entryKey]);
        }
    }
    $state = $ledger[$key] ?? ['attempts' => 0, 'blocked_until' => 0, 'updated_at' => $now];
    if ($action === 'success') {
        unset($ledger[$key]);
        $state = ['attempts' => 0, 'blocked_until' => 0, 'updated_at' => $now];
    } elseif ($action === 'failure' && (int) ($state['blocked_until'] ?? 0) <= $now) {
        $state['attempts'] = (int) ($state['attempts'] ?? 0) + 1;
        $state['updated_at'] = $now;
        if ($state['attempts'] >= LOGIN_RATE_MAX) {
            $state['attempts'] = 0;
            $state['blocked_until'] = $now + LOGIN_RATE_BLOCK_SECONDS;
        }
        $ledger[$key] = $state;
    }
    $encoded = json_encode($ledger, JSON_UNESCAPED_SLASHES);
    if ($encoded === false
        || !rewind($handle)
        || !ftruncate($handle, 0)
        || fwrite($handle, $encoded . "\n") === false
        || !fflush($handle)) {
        flock($handle, LOCK_UN);
        fclose($handle);
        fail_closed(503, 'Admin login protection unavailable.');
    }
    flock($handle, LOCK_UN);
    fclose($handle);
    return $state;
}

$configPath = getenv('HOLLAWALL_ADMIN_CONFIG') ?: dirname(__DIR__, 2) . '/.hollawall-admin.php';
if (!is_file($configPath)) {
    fail_closed(503, 'Admin configuration unavailable.');
}

$config = require $configPath;
if (!is_array($config)
    || empty($config['username'])
    || empty($config['password_hash'])
    || empty($config['proxy_token'])
    || empty($config['upstream_snapshot_url'])) {
    fail_closed(503, 'Admin configuration invalid.');
}

header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
header('Cache-Control: no-store, private');

$accountRoot = dirname(__DIR__, 2);
$realAccountRoot = realpath($accountRoot);
$sessionPath = $accountRoot . '/.hollawall-admin-sessions';
if ($realAccountRoot === false || is_link($sessionPath)) {
    fail_closed(503, 'Admin session storage unavailable.');
}
if (!file_exists($sessionPath) && !mkdir($sessionPath, 0700, false)) {
    fail_closed(503, 'Admin session storage unavailable.');
}
clearstatcache(true, $sessionPath);
$realSessionPath = realpath($sessionPath);
if (!is_dir($sessionPath)
    || is_link($sessionPath)
    || $realSessionPath === false
    || dirname($realSessionPath) !== $realAccountRoot
    || fileowner($realSessionPath) !== fileowner($realAccountRoot)
    || ((int) fileperms($realSessionPath) & 0777) !== 0700
    || !is_writable($realSessionPath)) {
    fail_closed(503, 'Admin session storage unavailable.');
}
$sessionPath = $realSessionPath;
if (session_name('hollawall_admin') === false
    || ini_set('session.use_strict_mode', '1') === false
    || ini_set('session.use_only_cookies', '1') === false
    || ini_set('session.gc_maxlifetime', (string) SESSION_LIFETIME) === false
    || session_save_path($sessionPath) === false
    || session_save_path() !== $sessionPath
    || !session_set_cookie_params([
    'lifetime' => SESSION_LIFETIME,
    'path' => ADMIN_PATH,
    'secure' => true,
    'httponly' => true,
    'samesite' => 'Strict',
])) {
    fail_closed(503, 'Admin session configuration unavailable.');
}
if (!session_start()) {
    fail_closed(503, 'Admin session unavailable.');
}

$now = time();
if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > SESSION_LIFETIME) {
    $_SESSION = [];
    session_regenerate_id(true);
}
$_SESSION['last_seen'] = $now;
if (empty($_SESSION['csrf'])) {
    $_SESSION['csrf'] = bin2hex(random_bytes(24));
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $csrf = (string) ($_POST['csrf'] ?? '');
    if (!hash_equals((string) $_SESSION['csrf'], $csrf)) {
        fail_closed(400, 'Invalid request.');
    }

    if (isset($_POST['logout'])) {
        $_SESSION = [];
        session_destroy();
        setcookie(session_name(), '', ['expires' => 1, 'path' => ADMIN_PATH, 'secure' => true, 'httponly' => true, 'samesite' => 'Strict']);
        header('Location: ' . ADMIN_PATH, true, 303);
        exit;
    }

    $username = trim((string) ($_POST['username'] ?? ''));
    $password = (string) ($_POST['password'] ?? '');
    $source = (string) ($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    $rateKey = hash_hmac('sha256', strtolower($username) . "\0" . $source, (string) $config['password_hash']);
    $ratePath = $realAccountRoot . '/.hollawall-admin-login-rate.json';
    $rate = admin_login_rate($ratePath, $realAccountRoot, $rateKey, 'inspect', $now);
    if ((int) ($rate['blocked_until'] ?? 0) > $now) {
        $loginError = 'Terlalu banyak percobaan. Coba lagi sebentar.';
    } else {
        $validUser = hash_equals((string) $config['username'], $username);
        $validPassword = password_verify($password, (string) $config['password_hash']);

        if ($validUser && $validPassword) {
            admin_login_rate($ratePath, $realAccountRoot, $rateKey, 'success', $now);
            session_regenerate_id(true);
            $_SESSION[SESSION_KEY] = (string) $config['username'];
            $_SESSION['last_seen'] = $now;
            $_SESSION['csrf'] = bin2hex(random_bytes(24));
            $_SESSION['cookie_renewed_at'] = $now;
            setcookie(session_name(), session_id(), ['expires' => $now + SESSION_LIFETIME, 'path' => ADMIN_PATH, 'secure' => true, 'httponly' => true, 'samesite' => 'Strict']);
            header('Location: ' . ADMIN_PATH, true, 303);
            exit;
        }

        admin_login_rate($ratePath, $realAccountRoot, $rateKey, 'failure', $now);
        usleep(400000);
        $loginError = 'Username atau password tidak cocok.';
    }
}

if (isset($_SESSION[SESSION_KEY]) && $now - (int) ($_SESSION['cookie_renewed_at'] ?? 0) >= SESSION_RENEW_AFTER) {
    $_SESSION['cookie_renewed_at'] = $now;
    setcookie(session_name(), session_id(), ['expires' => $now + SESSION_LIFETIME, 'path' => ADMIN_PATH, 'secure' => true, 'httponly' => true, 'samesite' => 'Strict']);
}

if (!isset($_SESSION[SESSION_KEY])):
?>
<!doctype html>
<html lang="id" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow, noarchive">
  <meta name="theme-color" content="#fb9202">
  <title>Masuk — Hollawall</title>
  <link rel="icon" type="image/png" href="<?= ADMIN_PATH ?>brand/hollawall-logo.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <style>
    :root{color-scheme:light;--orange:#fb9202;--cyan:#18b8c6;--navy:#163746;--cream:#ffecd2;--muted:#607781;--line:#d7e4e6}
    *{box-sizing:border-box}html,body{min-height:100%;margin:0}body{font-family:'Montserrat',sans-serif;background:#fff;color:var(--navy)}
    .site-header{height:100px;display:flex;align-items:center;justify-content:space-between;padding:0 max(6vw,28px);background:#fff}.site-header img{display:block;width:64px;height:64px;object-fit:contain}.back-link{color:var(--orange);font-size:14px;font-weight:800;text-decoration:none}.back-link:hover{text-decoration:underline}.back-link:focus-visible,input:focus-visible,button:focus-visible{outline:3px solid rgba(24,184,198,.32);outline-offset:3px}
    main{min-height:calc(100vh - 100px);display:grid;grid-template-columns:minmax(0,1.08fr) minmax(420px,.92fr)}.story{position:relative;overflow:hidden;display:flex;align-items:center;min-height:620px;padding:64px max(6vw,48px);background:var(--orange) url('<?= ADMIN_PATH ?>brand/waves-background.svg') center/cover no-repeat;color:#fff}.story>div{position:relative;z-index:1;max-width:700px}.story p{max-width:600px;margin:26px 0 0;color:var(--cream);font-size:15px;font-weight:600;line-height:1.7}.story h1{max-width:720px;margin:0;font-size:clamp(54px,7vw,96px);font-weight:900;line-height:.9;letter-spacing:-.055em;text-transform:uppercase}.story h1 span{position:relative;display:inline-block}.story h1 span:after{content:'';position:absolute;left:0;right:-10%;bottom:-14px;height:11px;border-radius:999px;background:var(--cyan);transform:rotate(-1.5deg)}
    .signin{display:grid;place-items:center;padding:56px max(6vw,44px);background:#fff}.signin-inner{width:min(100%,430px)}.eyebrow{margin:0 0 12px;color:var(--cyan);font-size:11px;font-weight:900;letter-spacing:.14em;text-transform:uppercase}.signin h2{margin:0 0 12px;font-size:clamp(34px,4vw,52px);font-weight:900;line-height:1;letter-spacing:-.045em}.intro{margin:0 0 34px;color:var(--muted);font-size:14px;line-height:1.65}.field{margin-bottom:19px}label{display:block;margin:0 0 8px;font-size:12px;font-weight:800}input{width:100%;height:50px;border:1px solid var(--line);border-radius:10px;background:#f7fafb;color:var(--navy);font:600 14px 'Montserrat',sans-serif;padding:0 15px;outline:0}input:focus{border-color:var(--cyan);background:#fff;box-shadow:0 0 0 4px rgba(24,184,198,.1)}button{width:100%;height:52px;margin-top:6px;border:0;border-radius:10px;background:var(--orange);color:var(--navy);font:900 14px 'Montserrat',sans-serif;cursor:pointer}button:hover{background:#ffa11f}.error{margin:0 0 20px;border-left:4px solid #c84d49;background:#fff2f0;color:#923b38;font-size:12px;font-weight:600;line-height:1.5;padding:12px 14px}.session-note{margin:19px 0 0;color:var(--muted);font-size:11px;font-weight:600;line-height:1.55}
    @media(max-width:900px){.site-header{height:82px;padding-inline:24px}.site-header img{width:54px;height:54px}main{min-height:calc(100vh - 82px);grid-template-columns:1fr}.story{min-height:250px;padding:42px 24px}.story h1{font-size:clamp(42px,13vw,66px)}.story p{margin-top:22px;font-size:12px}.signin{place-items:start stretch;padding:42px 24px 54px}.signin-inner{margin:auto}.signin h2{font-size:36px}}
    @media(max-width:900px) and (max-height:520px) and (orientation:landscape){.site-header{height:74px;padding-inline:28px}.site-header img{width:50px;height:50px}main{min-height:calc(100svh - 74px);grid-template-columns:1fr 1.15fr}.story,.signin{min-height:calc(100svh - 74px);padding:18px 32px}.story h1{font-size:38px}.story h1 span:after{bottom:-8px;height:7px}.story p{margin-top:16px;font-size:11px;line-height:1.5}.signin{place-items:start stretch;overflow-y:auto}.signin-inner{margin:auto}.eyebrow{margin-bottom:4px;font-size:10px}.signin h2{margin-bottom:6px;font-size:26px}.intro{margin-bottom:10px;font-size:11px;line-height:1.45}.field{margin-bottom:8px}label{margin-bottom:4px;font-size:11px}input{height:40px}button{height:42px;margin-top:2px}.session-note{display:none}}
  </style>
</head>
<body>
<header class="site-header"><a href="https://hollawall.com/en/" aria-label="Beranda Hollawall"><img src="<?= ADMIN_PATH ?>brand/hollawall-logo.png" alt="Hollawall"></a><a class="back-link" href="https://hollawall.com/en/">Kembali ke situs Hollawall</a></header>
<main>
  <section class="story" aria-label="Ruang finansial Hollawall"><div><h1>Ruang<br><span>Finansial</span></h1><p>Lanjutan dari ruang kerja Hollawall untuk membaca posisi kas, aktivitas unit, dan proyek dalam satu snapshot yang dapat ditelusuri.</p></div></section>
  <section class="signin">
    <div class="signin-inner">
      <header><p class="eyebrow">Hollawall Group</p><h2>Masuk</h2><p class="intro">Gunakan akun ruang kerja finansial Hollawall.</p></header>
      <?php if (isset($loginError)): ?><p class="error" role="alert"><?= htmlspecialchars($loginError, ENT_QUOTES, 'UTF-8') ?></p><?php endif; ?>
      <form method="post" action="<?= ADMIN_PATH ?>" autocomplete="on">
        <input type="hidden" name="csrf" value="<?= htmlspecialchars((string) $_SESSION['csrf'], ENT_QUOTES, 'UTF-8') ?>">
        <div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" required autofocus></div>
        <div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required></div>
        <button type="submit">Masuk ke dashboard</button>
      </form>
      <p class="session-note">Ruang kerja privat · akses baca-saja · aktivitas dapat diaudit</p>
    </div>
  </section>
</main>
</body>
</html>
<?php
exit;
endif;

define('HOLLAWALL_AUTHENTICATED', true);
require __DIR__ . '/app-shell.php';