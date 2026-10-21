# Hollawall Financial Command Center — Operations

## Current state

- Public entrypoint: `https://hollawall.46.250.238.167.nip.io`
- Hosting: Naufal VPS, Apache static site
- Access: HTTPS + Apache Basic Auth, owner-only
- Current mode: **private preview with synthetic demo data**
- Production finance API: not connected in the VPS preview
- Existing Koyeb bot/webhook behavior: unchanged

The preview is deliberately labeled `PRATINJAU · DATA DEMO`. Never remove the label until live API authentication, provider readiness, source parity, and readback gates pass.

## Files

- Source: `dashboard/`
- Production build: `dashboard/dist/` (ignored by Git)
- Live document root: `/var/www/hollawall-command-center`
- Previous deployment rollback: `/var/www/hollawall-command-center.rollback`
- HTTP vhost source: `deploy/hollawall-command-center.conf`
- HTTPS vhost source: `deploy/hollawall-command-center-le-ssl.conf`
- Installed Apache vhosts: `/etc/apache2/sites-available/hollawall-command-center*.conf`
- Basic Auth file: `/etc/apache2/.htpasswd-hollawall-preview`
- Owner-scoped preview credential: `/root/.hermes/profiles/naufal/vault/hollawall-preview-basic-auth`
- TLS certificate: `/etc/letsencrypt/live/hollawall.46.250.238.167.nip.io/`

Secrets must never enter Git, logs, screenshots, reports, or cloud artifacts.

## Build and verify

```bash
cd /root/workspaces/naufal/projects/keuangan-agent-evolution/worktrees/hollawall-command-center/dashboard
npm ci
npm test
VITE_DEMO_PREVIEW=true npm run build
npm audit --audit-level=high
cd ..
python -m unittest tests.browser.dashboard_visual_acceptance_test -v
```

The preview build must have:

- component tests passing;
- TypeScript production build passing;
- `npm audit` returning zero high/critical findings;
- desktop/tablet/mobile browser acceptance in light and dark modes;
- no horizontal overflow;
- no console errors;
- visible `PRATINJAU · DATA DEMO` label.

## Atomic preview deployment

```bash
cd /root/workspaces/naufal/projects/keuangan-agent-evolution/worktrees/hollawall-command-center
rm -rf /var/www/hollawall-command-center.new
install -d -o root -g www-data -m 0750 /var/www/hollawall-command-center.new
cp -a dashboard/dist/. /var/www/hollawall-command-center.new/
chown -R root:www-data /var/www/hollawall-command-center.new
find /var/www/hollawall-command-center.new -type d -exec chmod 0750 {} +
find /var/www/hollawall-command-center.new -type f -exec chmod 0640 {} +
rm -rf /var/www/hollawall-command-center.rollback
mv /var/www/hollawall-command-center /var/www/hollawall-command-center.rollback
mv /var/www/hollawall-command-center.new /var/www/hollawall-command-center
apachectl configtest
systemctl reload apache2
```

## Rollback

```bash
mv /var/www/hollawall-command-center /var/www/hollawall-command-center.failed
mv /var/www/hollawall-command-center.rollback /var/www/hollawall-command-center
apachectl configtest
systemctl reload apache2
```

Verify after rollback:

```bash
curl -I https://hollawall.46.250.238.167.nip.io/
# Expected without credentials: HTTP 401
```

## External acceptance

Without credentials:

```bash
curl -I https://hollawall.46.250.238.167.nip.io/
```

Expected:

- `401 Unauthorized`
- `Strict-Transport-Security`
- `Content-Security-Policy`
- `X-Robots-Tag: noindex, nofollow, noarchive`
- `X-Frame-Options: DENY`

Authenticated owner readback must return `200`, load both JavaScript chunks, render two financial charts, preserve theme switching, and expose no console errors.

## Live-data cutover gate

Do not convert the preview into a live dashboard until all conditions hold:

1. Koyeb service ownership and deployment mapping are verified.
2. `STATE_DATABASE_URL` or authorized equivalent is available through Koyeb environment management without copying it to the VPS.
3. `scripts/check_dashboard_database.py` proves PostgreSQL connectivity, SSL, ledger access, and provider readiness.
4. Wallet/type/month aggregate difference is exactly Rp0.
5. Valid source-key coverage is 100%.
6. Invalid historic rows are excluded from totals and counted.
7. Three KPI drill-down spot checks match exact source rows.
8. The owner-only API session is configured with production secrets.
9. The frontend is rebuilt without `VITE_DEMO_PREVIEW=true`.
10. The demo badge disappears only after authenticated live API readback succeeds.

The existing WhatsApp bot, webhook endpoints, Google Sheets authority, and Koyeb runtime remain unchanged until this gate passes.
