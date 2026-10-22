# Hollawall Financial Command Center — Operations

## Deployment state

- Entrypoint: `https://hollawall.46.250.238.167.nip.io`
- Frontend: static React on Naufal VPS, Apache HTTPS
- Browser boundary: Apache Basic Auth, owner-only
- Upstream: Koyeb app `renewed-loreen/keuangan`
- API path: same-origin `GET /live-api/snapshot`
- Mode: read-only; no dashboard route writes to Google Sheets, PostgreSQL, or bot state
- Existing `/health`, `/webhook_wuzapi`, and `/telegram`: unchanged

Live promotion completed on 2026-10-22. GitHub `main` commit `22497305673d769479e5f47df3c5280193e94a6b` and Koyeb deployment `7241468302` were verified `success`; the VPS serves the live frontend without a bundled snapshot JSON.

## Live data provenance

```text
existing Hollawall Google Sheets
  -> existing canonical bot read helpers
  -> strict read-only dashboard source
  -> dashboard.snapshot.v1 projection
  -> authenticated Koyeb GET /api/dashboard/v1/snapshot
  -> Apache same-origin reverse proxy
  -> owner browser
```

Accounting boundary:

- cash balance: exact `get_wallet_balances(strict=True)` formula used by `/saldo`;
- operating inflow/outflow: valid source transactions excluding internal transfers and debt settlements;
- open internal debt: only `HUTANG` rows with `Status=OPEN`;
- source rows: existing wallet and `Operasional Ktr` sheets;
- invalid rows: counted and excluded, never coerced into financial values;
- freshness: newest valid transaction date, not request time;
- traceability: every row has a stable sheet/block/row source key;
- trend: ends at current authoritative cash balance;
- cached projection: 60 seconds by default, bounded to 1–120 seconds.

`get_raw_rows_for_audit()` and strict wallet reads are lookup-only. Every required worksheet is verified first. Missing/partial sources return sanitized HTTP `503`; they do not create sheets, return partial zero balances, or fall back to demo figures.

## Authentication design

Two independent boundaries apply:

1. Apache Basic Auth protects the browser-facing site.
2. Apache removes incoming `Authorization` and `X-Hollawall-Proxy-Token`, then injects the owner proxy token from a root-only include before forwarding the one allowlisted snapshot path.

Koyeb stores only the SHA-256 verifier in source/config. The 384-bit plaintext token remains only in owner-scoped files:

- `/root/.hermes/profiles/naufal/vault/hollawall-live-api-proxy-token`
- `/etc/apache2/hollawall-live-api-secret.conf` (`0600`)

The token must never enter Git, browser JavaScript, responses, screenshots, logs, reports, or cloud artifacts.

## Relevant files

- Frontend: `dashboard/`
- Live projection: `dashboard_api/live_snapshot.py`
- Strict live source: `dashboard_api/live_source.py`
- Auth: `dashboard_api/auth.py`
- Routes: `dashboard_api/routes.py`
- Apache source: `deploy/hollawall-command-center-le-ssl.conf`
- Live document root: `/var/www/hollawall-command-center`
- Rollback document root: `/var/www/hollawall-command-center.previous`
- Basic Auth: `/etc/apache2/.htpasswd-hollawall-preview`
- TLS: `/etc/letsencrypt/live/hollawall.46.250.238.167.nip.io/`

## Verification gates

```bash
cd /root/workspaces/naufal/projects/keuangan-agent-evolution/worktrees/hollawall-command-center
python -m unittest \
  tests.dashboard_live_snapshot_test \
  tests.dashboard_live_source_test \
  tests.dashboard_routes_test \
  tests.dashboard_service_test \
  tests.sheets_cache_test -v

cd dashboard
npm test
npm run build
npm audit --audit-level=high
cd ..
python -m unittest tests.browser.dashboard_visual_acceptance_test -v
GROQ_API_KEY=verification-only-not-a-live-key hermes verify --json
```

Required evidence before promotion:

- all tests/build/audit pass;
- Apache candidate and active config both pass `apachectl configtest`;
- plaintext token scan returns zero repository hits;
- Koyeb deployment for merged commit reports success;
- direct upstream without proxy token returns `401`;
- same-origin path without Basic Auth returns `401`;
- authenticated same-origin snapshot returns `200` and `dashboard.snapshot.v1`;
- KPI and all wallet balances equal the authoritative source projection exactly;
- stale/freshness date is visible and truthful;
- seven views, search, type filter, CSV export, light/dark, mobile/tablet/desktop pass;
- browser console is clean and no horizontal overflow exists;
- bot health and webhook endpoints remain healthy.

## Atomic frontend deployment

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
install -o root -g root -m 0644 \
  deploy/hollawall-command-center-le-ssl.conf \
  /etc/apache2/sites-available/hollawall-command-center-le-ssl.conf
apachectl configtest
systemctl reload apache2
```

Do not include `data/dashboard-snapshot.json` in a live build.

## Rollback

Frontend and Apache:

```bash
mv /var/www/hollawall-command-center /var/www/hollawall-command-center.failed
mv /var/www/hollawall-command-center.previous /var/www/hollawall-command-center
# restore the pre-live Apache vhost from its verified backup
apachectl configtest
systemctl reload apache2
```

Backend:

- revert the merge commit on `main`;
- wait for Koyeb deployment readback;
- verify `/health`, `/webhook_wuzapi`, and `/telegram` behavior;
- never rotate bot/webhook/Google credentials as a dashboard rollback.

## Token rotation

1. Generate a new random token with at least 384 bits.
2. Write plaintext only to the two owner/root files above.
3. Update the SHA-256 verifier via `DASHBOARD_PROXY_TOKEN_HASH` or source fallback.
4. Deploy backend first; verify direct authenticated read.
5. Reload Apache with the new include.
6. Verify same-origin readback.
7. Remove the old token from owner files; do not record it in history.
