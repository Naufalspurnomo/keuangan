<?php
declare(strict_types=1);
header("Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
header('Permissions-Policy: camera=(self), geolocation=(self), microphone=()');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
header('X-Frame-Options: DENY');
header('X-Robots-Tag: noindex, nofollow, noarchive');
header('Cache-Control: no-store');
?>
<!doctype html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#FB9202" />
  <link rel="icon" href="/absen/brand/hollawall-logo.png" />
  <title>Presensi Hollawall</title>
  <link rel="stylesheet" href="/absen/assets/presensi.css" />
  <script src="/absen/assets/presensi.js" defer></script>
</head>
<body>
  <header class="site-head">
    <img src="/absen/brand/hollawall-logo.png" alt="Hollawall" />
    <span>Presensi</span>
  </header>
  <main class="compact-main">
    <section id="login-card" class="login-card" aria-labelledby="login-title">
      <h1 id="login-title">Masuk Presensi</h1>
      <div id="login-notice" class="notice" role="alert" aria-live="polite" hidden></div>
      <form id="login-form" novalidate>
        <label><span>Kode pegawai</span><input id="employee-code" name="code" autocomplete="username" autocapitalize="characters" maxlength="32" required /></label>
        <label><span>PIN</span><input id="employee-pin" name="pin" type="password" inputmode="numeric" autocomplete="current-password" maxlength="128" required /></label>
        <button id="login-button" type="submit" class="submit-button"><span>Masuk</span></button>
      </form>
    </section>

    <section id="presensi-card" class="presensi-card" aria-labelledby="form-title" hidden>
      <div class="card-head">
        <div><p id="employee-greeting" class="eyebrow"></p><h1 id="form-title">Presensi</h1></div>
        <div class="session-actions"><span id="action-badge" class="action-badge">CHECK-IN</span><button id="logout-button" type="button" class="text-button">Keluar</button></div>
      </div>
      <div id="notice" class="notice" role="status" aria-live="polite" hidden></div>
      <form id="presensi-form" novalidate>
        <div class="field-grid single-field">
          <label><span>Proyek aktif</span><select id="project" name="project_id" required disabled><option value="">Pilih proyek</option></select></label>
        </div>
        <section class="proof-panel" aria-labelledby="camera-title">
          <div class="proof-head"><div><span class="step-number">1</span><div><h2 id="camera-title">Selfie langsung</h2><p>Pastikan wajah terlihat jelas.</p></div></div><span id="camera-state" class="state-pill">Belum siap</span></div>
          <div class="camera-frame">
            <video id="camera" autoplay muted playsinline hidden></video>
            <img id="selfie-preview" alt="Pratinjau selfie presensi" hidden />
            <div id="camera-placeholder" class="camera-placeholder"><span aria-hidden="true">◉</span><strong>Kamera belum dibuka</strong></div>
          </div>
          <div class="camera-actions">
            <button id="open-camera" type="button" class="secondary-button" disabled>Aktifkan kamera</button>
            <button id="capture-selfie" type="button" class="primary-button" disabled>Ambil selfie & lokasi</button>
            <button id="retake-selfie" type="button" class="text-button" hidden>Ambil ulang</button>
          </div>
          <p id="camera-requirements" class="proof-requirements">Pilih proyek terlebih dahulu.</p>
        </section>
        <section class="proof-panel" aria-labelledby="location-title">
          <div class="proof-head"><div><span class="step-number">2</span><div><h2 id="location-title">Lokasi aktual</h2><p>Dibaca saat selfie diambil.</p></div></div><span id="location-state" class="state-pill">Belum siap</span></div>
          <div class="location-card"><span class="location-dot" aria-hidden="true"></span><div><strong id="location-copy">Aktifkan GPS untuk melanjutkan</strong><small id="location-detail">Koordinat dan akurasi tersimpan bersama selfie.</small></div></div>
        </section>
        <input type="hidden" id="action" name="action" value="check_in" />
        <button id="submit-presensi" type="submit" class="submit-button" disabled><span>Kirim Check-in</span><small>Selfie dan lokasi wajib lengkap</small></button>
      </form>
    </section>
  </main>
</body>
</html>
