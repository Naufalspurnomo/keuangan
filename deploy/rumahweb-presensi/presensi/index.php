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
  <meta name="theme-color" content="#f97316" />
  <link rel="icon" href="/absen/brand/hollawall-logo.png" />
  <title>Presensi Hollawall</title>
  <link rel="stylesheet" href="/absen/assets/presensi.css" />
  <script src="/absen/assets/presensi.js" defer></script>
</head>
<body>
  <header class="site-head">
    <a href="https://hollawall.com/" aria-label="Kembali ke Hollawall"><img src="/absen/brand/hollawall-logo.png" alt="Hollawall" /></a>
    <span>Presensi lapangan</span>
  </header>
  <main>
    <section class="hero" aria-labelledby="page-title">
      <p class="eyebrow">HOLLAWALL CREW</p>
      <h1 id="page-title">Presensi proyek,<br /><em>langsung dari lokasi.</em></h1>
      <p>Setiap Check-in dan Check-out membutuhkan selfie baru serta lokasi presisi di area proyek.</p>
      <div class="trust-row" aria-label="Bukti presensi">
        <span><b>01</b> Kamera langsung</span>
        <span><b>02</b> GPS presisi</span>
        <span><b>03</b> Waktu server</span>
      </div>
    </section>

    <section class="presensi-card" aria-labelledby="form-title">
      <div class="card-head">
        <div><p class="eyebrow">LANGKAH PRESENSI</p><h2 id="form-title">Siapkan bukti kehadiran</h2></div>
        <span id="action-badge" class="action-badge">CHECK-IN</span>
      </div>

      <div id="notice" class="notice" role="status" aria-live="polite" hidden></div>
      <form id="presensi-form" novalidate>
        <div class="field-grid">
          <label>
            <span>Nama pegawai</span>
            <select id="employee" name="employee_id" required disabled>
              <option value="">Pilih pegawai</option>
            </select>
          </label>
          <label>
            <span>Proyek aktif</span>
            <select id="project" name="project_id" required disabled>
              <option value="">Pilih proyek</option>
            </select>
          </label>
        </div>

        <section class="proof-panel" aria-labelledby="camera-title">
          <div class="proof-head">
            <div><span class="step-number">1</span><div><h3 id="camera-title">Selfie langsung</h3><p>Buka kamera depan, pastikan wajah terlihat jelas.</p></div></div>
            <span id="camera-state" class="state-pill">Belum siap</span>
          </div>
          <div class="camera-frame">
            <video id="camera" autoplay muted playsinline hidden></video>
            <img id="selfie-preview" alt="Pratinjau selfie presensi" hidden />
            <div id="camera-placeholder" class="camera-placeholder">
              <span aria-hidden="true">◉</span>
              <strong>Kamera belum dibuka</strong>
              <small>Selfie hanya diambil dari kamera langsung.</small>
            </div>
          </div>
          <div class="camera-actions">
            <button id="open-camera" type="button" class="secondary-button">Aktifkan kamera</button>
            <button id="capture-selfie" type="button" class="primary-button" disabled>Ambil selfie & lokasi</button>
            <button id="retake-selfie" type="button" class="text-button" hidden>Ambil ulang</button>
          </div>
        </section>

        <section class="proof-panel" aria-labelledby="location-title">
          <div class="proof-head">
            <div><span class="step-number">2</span><div><h3 id="location-title">Lokasi proyek</h3><p>Lokasi dibaca satu kali saat selfie diambil, bukan dilacak terus.</p></div></div>
            <span id="location-state" class="state-pill">Belum siap</span>
          </div>
          <div class="location-card">
            <span class="location-dot" aria-hidden="true"></span>
            <div><strong id="location-copy">Aktifkan GPS untuk melanjutkan</strong><small id="location-detail">Akurasi dan radius akan diverifikasi server.</small></div>
          </div>
        </section>

        <input type="hidden" id="action" name="action" value="check_in" />
        <button id="submit-presensi" type="submit" class="submit-button" disabled>
          <span>Kirim Check-in</span><small>Selfie dan lokasi wajib lengkap</small>
        </button>
      </form>
      <p class="privacy-note"><strong>Mode demo:</strong> pilihan nama belum memverifikasi identitas pegawai dan bukan bukti payroll. Foto tersimpan privat dan hanya dapat dibuka dari dashboard admin.</p>
    </section>
  </main>
  <footer>© Hollawall · Sistem presensi proyek</footer>
</body>
</html>
