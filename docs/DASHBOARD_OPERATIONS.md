# Hollawall Financial Command Center — Operations

## Current state

- Entrypoint: `https://hollawall.46.250.238.167.nip.io`
- Hosting: Naufal VPS, Apache static site
- Access: HTTPS + Apache Basic Auth, owner-only
- Mode: owner Google Drive workbook snapshot, read-only
- Data through: `2026-09-02`
- Snapshot rows: 843 valid, 15 invalid
- Freshness: deliberately `stale`; never rendered as current
- Existing Koyeb bot/webhooks: unchanged

The site serves a sanitized JSON snapshot generated from Naufal's `Keuangan.xlsx` workbook. It does not write to the workbook, Google Drive, PostgreSQL, Koyeb, or the bot. The source workbook and generated JSON must never enter Git or public artifacts.

## Provenance

```text
naufal-drive:Keuangan.xlsx
  -> owner-scoped rclone download
  -> scripts/build_dashboard_snapshot.py
  -> private dist/data/dashboard-snapshot.json
  -> Apache Basic Auth + HTTPS
```

The generator defines the accounting boundary:

- cash balance: sum of the three `Saldo Sistem` wallet balances;
- operating cash flow: transactions excluding internal debt movements;
- open internal debt: only rows with `Status=OPEN` in `HUTANG`;
- freshness: worst case of Drive file age and newest transaction date;
- invalid rows: counted and excluded, never coerced to zero;
- traceability: every transaction retains its source message ID as `source_key`.

## Files

- Source: `dashboard/`
- Snapshot generator: `scripts/build_dashboard_snapshot.py`
- Generator tests: `tests/dashboard_snapshot_test.py`
- Build output: `dashboard/dist/` (ignored by Git)
- Live root: `/var/www/hollawall-command-center`
- Previous deployment: `/var/www/hollawall-command-center.previous`
- Apache source: `deploy/hollawall-command-center*.conf`
- Basic Auth file: `/etc/apache2/.htpasswd-hollawall-preview`
- Owner credential: `/root/.hermes/profiles/naufal/vault/hollawall-preview-basic-auth`
- TLS certificate: `/etc/letsencrypt/live/hollawall.46.250.238.167.nip.io/`

Secrets and financial snapshot bytes must not enter Git, logs, screenshots, reports, or unencrypted cloud artifacts.

## Refresh snapshot

1. Download the source through Naufal's profile-scoped rclone config:

```bash
rclone copyto 'naufal-drive:Keuangan.xlsx' /secure/path/Keuangan.xlsx \
  --config /root/.hermes/profiles/naufal/cloud/rclone.conf
```

2. Record the Drive modification timestamp.
3. Build and test:

```bash
cd /root/workspaces/naufal/projects/keuangan-agent-evolution/worktrees/hollawall-command-center
python -m unittest tests.dashboard_snapshot_test -v
python scripts/build_dashboard_snapshot.py \
  /secure/path/Keuangan.xlsx \
  /tmp/hollawall-dashboard-snapshot.json \
  --source-modified-at '<DRIVE_TIMESTAMP>'
cd dashboard
npm ci
npm test
VITE_SNAPSHOT_PREVIEW=true npm run build
npm audit --audit-level=high
install -d -m 0750 dist/data
install -o root -g root -m 0640 \
  /tmp/hollawall-dashboard-snapshot.json \
  dist/data/dashboard-snapshot.json
```

4. Deploy atomically.
5. Compare rendered KPI, all wallet balances, transaction count, freshness, and source period against the generated JSON.
6. Remove the downloaded workbook and temporary JSON after verified deployment.

## Atomic deployment

```bash
rm -rf /var/www/hollawall-command-center.new
install -d -o root -g www-data -m 0750 /var/www/hollawall-command-center.new
cp -a dashboard/dist/. /var/www/hollawall-command-center.new/
chown -R root:www-data /var/www/hollawall-command-center.new
find /var/www/hollawall-command-center.new -type d -exec chmod 0750 {} +
find /var/www/hollawall-command-center.new -type f -exec chmod 0640 {} +
rm -rf /var/www/hollawall-command-center.previous
mv /var/www/hollawall-command-center /var/www/hollawall-command-center.previous
mv /var/www/hollawall-command-center.new /var/www/hollawall-command-center
apachectl configtest
systemctl reload apache2
```

## Rollback

```bash
mv /var/www/hollawall-command-center /var/www/hollawall-command-center.failed
mv /var/www/hollawall-command-center.previous /var/www/hollawall-command-center
apachectl configtest
systemctl reload apache2
```

## Acceptance

Without credentials:

- HTTP `401`;
- HSTS, CSP, noindex, DENY framing.

Authenticated:

- HTTP `200`;
- snapshot JSON uses `Cache-Control: private, no-store`;
- exact KPI and wallet parity with generated JSON;
- all 843 transactions render;
- stale badge and `data through` date remain visible;
- no demo label, console error, or horizontal overflow;
- all seven navigation views render.

## Koyeb production boundary

PR #32 must not merge into `main` yet. GitHub deployment metadata proves Koyeb deployment `renewed-loreen/keuangan` tracks `main`, so merging is production-affecting. The currently authenticated Koyeb organization `testttads` is not the organization owning that deployment.

Future live API promotion requires access to the correct Koyeb organization, read-only database parity at Rp0, owner session secrets, and authenticated API readback. Until then, the owner snapshot is the truthful production-data view and the bot remains untouched.
