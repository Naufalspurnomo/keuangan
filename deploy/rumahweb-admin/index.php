<?php
declare(strict_types=1);

const ADMIN_PATH = '/admin/';
const SESSION_KEY = 'hollawall_admin_user';

function fail_closed(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: text/plain; charset=UTF-8');
    header('Cache-Control: no-store');
    echo $message;
    exit;
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

session_name('hollawall_admin');
session_set_cookie_params([
    'lifetime' => 0,
    'path' => ADMIN_PATH,
    'secure' => true,
    'httponly' => true,
    'samesite' => 'Strict',
]);
session_start();

$now = time();
if (isset($_SESSION['last_seen']) && $now - (int) $_SESSION['last_seen'] > 28800) {
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
        session_regenerate_id(true);
        header('Location: ' . ADMIN_PATH, true, 303);
        exit;
    }

    $blockedUntil = (int) ($_SESSION['blocked_until'] ?? 0);
    if ($blockedUntil > $now) {
        $loginError = 'Terlalu banyak percobaan. Coba lagi sebentar.';
    } else {
        $username = trim((string) ($_POST['username'] ?? ''));
        $password = (string) ($_POST['password'] ?? '');
        $validUser = hash_equals((string) $config['username'], $username);
        $validPassword = password_verify($password, (string) $config['password_hash']);

        if ($validUser && $validPassword) {
            session_regenerate_id(true);
            $_SESSION[SESSION_KEY] = (string) $config['username'];
            $_SESSION['last_seen'] = $now;
            $_SESSION['attempts'] = 0;
            $_SESSION['csrf'] = bin2hex(random_bytes(24));
            header('Location: ' . ADMIN_PATH, true, 303);
            exit;
        }

        $_SESSION['attempts'] = (int) ($_SESSION['attempts'] ?? 0) + 1;
        if ($_SESSION['attempts'] >= 5) {
            $_SESSION['blocked_until'] = $now + 60;
            $_SESSION['attempts'] = 0;
        }
        usleep(400000);
        $loginError = 'Username atau password tidak cocok.';
    }
}

if (!isset($_SESSION[SESSION_KEY])):
?>
<!doctype html>
<html lang="id" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow, noarchive">
  <meta name="theme-color" content="#080a0f">
  <title>Masuk — Hollawall Financial Command Center</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2212%22 fill=%22%23101416%22/><text x=%2232%22 y=%2244%22 text-anchor=%22middle%22 font-size=%2240%22 fill=%22%23f06a43%22>H</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,600&display=swap" rel="stylesheet">
  <style>
    :root{color-scheme:dark;--canvas:#080a0f;--surface:#101416;--raised:#171c1f;--border:#272d30;--text:#f2f4ef;--muted:#929a9c;--brand:#f06a43}
    *{box-sizing:border-box}html,body{min-height:100%;margin:0}body{font-family:'DM Sans',sans-serif;background:var(--canvas);color:var(--text);display:grid;place-items:center;padding:24px;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:48px 48px}
    main{width:min(100%,420px)}.brand{display:flex;align-items:center;gap:12px;margin-bottom:28px}.mark{display:grid;place-items:center;width:38px;height:38px;border:1px solid #4a352f;background:#1c1513;color:var(--brand);font:700 18px/1 'DM Sans';border-radius:8px}.brand strong{display:block;font-size:13px;letter-spacing:.12em}.brand span{display:block;color:var(--muted);font-size:12px;margin-top:3px}
    section{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:30px;box-shadow:0 24px 70px rgba(0,0,0,.28)}.eyebrow{color:var(--brand);font-size:10px;font-weight:700;letter-spacing:.16em;margin:0 0 10px}h1{font:600 34px/1.05 'Newsreader',serif;margin:0 0 10px}header>p:last-child{color:var(--muted);font-size:14px;line-height:1.55;margin:0 0 28px}
    label{display:block;font-size:12px;font-weight:600;margin:0 0 8px}.field{margin-bottom:17px}input{width:100%;height:46px;border:1px solid #333b3e;border-radius:8px;background:var(--raised);color:var(--text);font:500 14px 'DM Sans';padding:0 14px;outline:none}input:focus{border-color:var(--brand);box-shadow:0 0 0 3px rgba(240,106,67,.13)}button{width:100%;height:46px;border:0;border-radius:8px;background:var(--brand);color:#180d09;font:700 13px 'DM Sans';cursor:pointer;margin-top:6px}button:hover{filter:brightness(1.06)}.error{border-left:2px solid #e06464;color:#f0b0b0;background:#1b1214;font-size:12px;line-height:1.45;padding:10px 12px;margin:0 0 17px}.meta{display:flex;justify-content:space-between;color:#737d7f;font-size:10px;letter-spacing:.08em;margin-top:18px;text-transform:uppercase}@media(max-width:480px){body{padding:16px;place-items:center stretch}section{padding:24px 20px}h1{font-size:30px}}
  </style>
</head>
<body>
<main>
  <div class="brand"><div class="mark">H</div><div><strong>HOLLAWALL</strong><span>Financial Command Center</span></div></div>
  <section>
    <header><p class="eyebrow">OWNER ACCESS</p><h1>Masuk ke ruang kerja</h1><p>Dashboard finansial privat, baca-saja, dan teraudit.</p></header>
    <?php if (isset($loginError)): ?><p class="error" role="alert"><?= htmlspecialchars($loginError, ENT_QUOTES, 'UTF-8') ?></p><?php endif; ?>
    <form method="post" action="<?= ADMIN_PATH ?>" autocomplete="on">
      <input type="hidden" name="csrf" value="<?= htmlspecialchars((string) $_SESSION['csrf'], ENT_QUOTES, 'UTF-8') ?>">
      <div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" required autofocus></div>
      <div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required></div>
      <button type="submit">Masuk</button>
    </form>
    <div class="meta"><span>Private workspace</span><span>Read-only</span></div>
  </section>
</main>
</body>
</html>
<?php
exit;
endif;

define('HOLLAWALL_AUTHENTICATED', true);
require __DIR__ . '/app-shell.php';