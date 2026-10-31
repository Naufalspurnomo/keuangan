# Hollawall Presensi Demo — Operations

## Boundary

`/absen/presensi/` is a demo workflow. The employee dropdown does not authenticate an employee and browser camera/GPS cannot provide cryptographic device attestation. Do not treat these records as authoritative payroll evidence. The server still enforces fresh one-time proof submission, valid GPS coordinates, project pairing, sequence, server time, and private evidence storage.

## Prerequisites

- HTTPS on `hollawall.com` (camera/geolocation require a secure context).
- PHP 8.1+ with `json`, `session`, `fileinfo`, and `gd`; existing admin additionally needs `curl`.
- Account-root private files/directories owned by the hosting account:
  - `.hollawall-presensi.php` mode `0600`;
  - `.hollawall-presensi` mode `0700`;
  - `.hollawall-presensi-sessions` mode `0700`;
  - existing `.hollawall-admin-sessions` mode `0700`.
- `upload_max_filesize >= 4M`, `post_max_size >= 5M`; application limit remains lower.
- The active project IDs, names, and companies from the dashboard source of truth.

## Private configuration

1. Copy `docs/PRESENSI_CONFIG.example.php` to `/home/<hosting-user>/.hollawall-presensi.php`.
2. Keep the exact demo employee IDs/names and unique project IDs/names.
3. Run `chmod 0600 /home/<hosting-user>/.hollawall-presensi.php`.
4. Do not place the config in `public_html`, release archives, Git, logs, or screenshots.

Missing, malformed, duplicate, symlinked, wrong-owner, or wrong-mode configuration fails closed with HTTP 503.

## Build and local verification

```bash
python3 scripts/build_rumahweb_presensi_release.py
python3 scripts/build_rumahweb_admin_release.py
npm --prefix dashboard test -- --run
npm --prefix dashboard run build
GROQ_API_KEY=test-only-not-a-real-key python -m pytest -q \
  tests/presensi_release_test.py \
  tests/presensi_integration_test.py \
  tests/presensi_deploy_test.py \
  tests/rumahweb_admin_release_test.py \
  tests/rumahweb_admin_session_integration_test.py \
  tests/security_hardening_test.py
/usr/local/lib/hermes-agent/venv/bin/python scripts/qa_presensi_browser.py
```

Release payloads:

- `artifacts/rumahweb-presensi-release/absen` → `public_html/absen`
- `artifacts/rumahweb-admin-release/admin` → `public_html/admin`

Runtime config, sessions, events, and photos are deliberately excluded.

## Atomic deployment order

1. Verify PHP extensions and private-directory permissions.
2. Install the final private config; request `/absen/api/bootstrap.php` and require a valid response before exposure.
3. Run the coupled deployer:

```bash
python scripts/deploy_rumahweb_presensi_atomic.py \
  --admin-release artifacts/rumahweb-admin-release/admin \
  --absen-release artifacts/rumahweb-presensi-release/absen \
  --tag <commit> --evidence <private-evidence-path>/deploy.json
```

4. The deployer uploads both paths to unique staging directories and byte-verifies every staged file.
5. It renames current `/admin` and `/absen` to timestamped rollback directories.
6. It activates both releases. Any activation/readback failure preserves failed bytes and restores both previous paths in reverse order.
7. Do not touch the WordPress document root outside `/admin` and `/absen`.
8. Keep private attendance data across application rollback.

## Live smoke acceptance

- Anonymous `/absen/presensi/` returns 200 over HTTPS.
- Bootstrap returns exactly Pegawai 1/2/3 and configured active projects, without attendance coordinates.
- Camera denial and GPS denial keep submit disabled.
- Check-in from any valid GPS location writes exactly one event containing the captured coordinates, accuracy, and one private JPEG.
- Duplicate Check-in and mismatched-project Check-out return 409.
- Check-out creates the matching second event.
- Anonymous admin data/photo endpoints return 401.
- Authenticated project Presensi tab shows both photos, captured coordinates, accuracy, and map links; Transaksi remains default.
- Desktop and 320/390 px mobile have no overflow, failed requests, console errors, or targets below 44 px.
- Public artifact hashes match the candidate manifest.

## Retention

Default demo retention is 90 days. The purge removes only completed attendance pairs older than the configured retention. Open Check-ins are preserved.

Daily cron, using the account's PHP binary:

```bash
php /home/<hosting-user>/public_html/absen/bin/purge.php
```

A successful run prints JSON. A failed run exits non-zero and restores quarantined photos. Run it once manually and verify downloaded/readback evidence before enabling cron.

## Rollback

1. Rename the live `/admin` and `/absen` directories out of service.
2. Restore both timestamped previous directories.
3. Verify admin login, snapshot, and anonymous API boundaries.
4. Preserve `.hollawall-presensi`, `.hollawall-presensi.php`, and both session directories.
5. Never delete attendance evidence during application rollback.
6. If submission must be disabled while preserving admin readback, remove/rename only public `/absen` and keep `/admin` plus private data.
