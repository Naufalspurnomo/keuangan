# Hollawall Presensi — Operations

## Boundary

`/absen/presensi/` is a production-oriented attendance workflow without full employee accounts. Employees authenticate with a unique employee code and a PIN whose hash lives only in the private hosting config. Camera/GPS still do not provide hardware attestation, so records require operational review before payroll disputes.

Each accepted Check-in/Check-out is durable before WhatsApp delivery starts. The private JPEG and coordinates appear in the admin dashboard. A bounded outbox sends the same JPEG to the configured WhatsApp group. Delivery failures never remove the attendance record; the dashboard exposes `Menunggu`, `Terkirim`, `Gagal`, or `Perlu dicek` with attempt count.

## Private configuration

1. Copy `docs/PRESENSI_CONFIG.example.php` outside `public_html` as `.hollawall-presensi.php`.
2. Generate a distinct PIN hash for every employee using `password_hash`; never store plaintext PINs.
3. Generate a random `outbox_shared_secret` of at least 32 characters.
4. Set `delivery_trigger_url` to the backend HTTPS endpoint `/internal/presensi/deliver`.
5. Keep employee IDs, codes, names, and active project identities unique.
6. Set owner-only mode `0600`. Private data/session directories use `0700`.

Missing, malformed, duplicate, symlinked, wrong-owner, or wrong-mode configuration fails closed.

## Backend worker environment

Configure the Koyeb service with owner-scoped secrets:

- `PRESENSI_OUTBOX_BASE_URL=https://hollawall.com/absen/api`
- `PRESENSI_OUTBOX_SHARED_SECRET=<same private shared secret>`
- `PRESENSI_WHATSAPP_GROUP_JID=<exact Presensi group JID ending @g.us>`
- existing `WUZAPI_DOMAIN` and `WUZAPI_TOKEN`

The employee submission calls the internal trigger once. The worker claims one event with a lease, validates the JPEG, sends `/chat/send/image` with event ID as stable provider ID, then ACKs `sent`, `failed`, or `unknown`. Ambiguous transport/provider outcomes become `unknown` and are not blindly retried because the group may already have received the photo.

Manual bounded recovery:

```bash
python presensi_delivery_worker.py --max-items 5
```

Do not run another daemon. A periodic scheduler may execute that same bounded command to recover `failed` events after backoff.

## Build and verification

```bash
python3 scripts/build_rumahweb_presensi_release.py
python3 scripts/build_rumahweb_admin_release.py
for f in deploy/rumahweb-presensi/api/*.php deploy/rumahweb-presensi/presensi/*.php deploy/rumahweb-presensi/bin/*.php; do php -l "$f"; done
python -m pytest -q tests/presensi_delivery_worker_test.py tests/presensi_integration_test.py tests/presensi_release_test.py tests/presensi_deploy_test.py
npm --prefix dashboard test -- --run
npm --prefix dashboard run build
npm --prefix dashboard audit
```

Release payloads:

- `artifacts/rumahweb-presensi-release/absen` → `public_html/absen`
- `artifacts/rumahweb-admin-release/admin` → `public_html/admin`

Runtime config, sessions, events, photos, PIN hashes, secrets, JIDs, and provider credentials are excluded.

## Atomic deployment

Deploy the backend first and require `/api/health/release` to show the reviewed commit. Then deploy coupled Rumahweb admin/absen paths:

```bash
python scripts/deploy_rumahweb_presensi_atomic.py \
  --admin-release artifacts/rumahweb-admin-release/admin \
  --absen-release artifacts/rumahweb-presensi-release/absen \
  --tag <commit> --evidence <private-evidence-path>/deploy.json
```

The deployer stages and byte-verifies both paths, activates them together, and restores both previous paths on failure. Preserve `.hollawall-presensi`, `.hollawall-presensi.php`, and session directories.

## Live acceptance

- Anonymous bootstrap exposes no employee list or projects.
- Wrong code/PIN returns one generic error; repeated failures lock briefly.
- Valid code/PIN rotates the session and reveals only the authenticated employee plus active projects.
- The attendance screen has project selection only; no employee dropdown.
- Camera/GPS denial keeps submit disabled.
- A Check-in writes one event and private JPEG; duplicate Check-in returns 409.
- Check-out requires the same project and closes the pair.
- Anonymous admin data/photo endpoints return 401.
- Authenticated dashboard shows both private photos, coordinates, and WhatsApp delivery status.
- The configured WhatsApp Presensi group receives the same photo with employee, action, project, time, and accuracy caption.
- Provider ambiguity creates `unknown`, never duplicate auto-send.
- Public artifact hashes match the candidate manifest; desktop and mobile have no overflow, failed requests, or console errors.

## Retention and rollback

Daily retention:

```bash
php /home/<hosting-user>/public_html/absen/bin/purge.php
```

Rollback application directories only. Never delete private attendance evidence, private config, or sessions during application rollback. If submission must be disabled, remove/rename only public `/absen`; retain `/admin` and private evidence for readback.
