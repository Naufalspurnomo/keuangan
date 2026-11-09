# Hollawall Production Acceptance Contract

Status: frozen before release verification on 2026-11-09.

## Scope

This contract covers the existing production system only:

- WhatsApp and Telegram finance ingestion;
- Bot Keuangan processing and finance replies;
- Hollawall owner dashboard;
- dashboard transaction creation;
- project and commercial-document lifecycle;
- employee Presensi and private evidence;
- durable inbox exception review;
- backup, isolated restore, monitoring, CI, deployment, and rollback.

Hermes/Finance Jarvis remains a later phase and is not a dependency of this production release.

## Required production flows

### 1. WhatsApp finance capture

- The webhook authenticates the provider request and rejects disallowed senders/events.
- A normalized inbound event is durably stored before successful acknowledgement when durability is required.
- Provider message ID and canonical payload prevent duplicate processing.
- Text, receipt image, and follow-up context enter the shared finance flow.
- Wallet, company, project, amount, date, and evidence are validated before posting.
- The cash writer appends to Google Sheets and reads the authoritative result back.
- PostgreSQL projection is repaired or updated without becoming a second cash authority.
- Recovery never creates a second financial transaction for the same event.

### 2. Dashboard

- Anonymous users cannot read owner data or call write endpoints.
- Owner login, session, CSRF, and server-held upstream credentials remain enforced.
- Dashboard data loads from live authoritative projections, not browser-local demo state.
- Transaction creation uses one stable idempotency key and verifies the authoritative Sheet row.
- Concurrent identical requests produce one transaction and one duplicate-safe response.
- Project and document actions preserve optimistic locking, command idempotency, audit events, immutable issued snapshots, exact PDF bytes, and official numbering.
- Posted cash edit, hard delete, and correction/reversal remain disabled unless a separately verified contract is shipped.

### 3. Presensi

- Employee identity requires code/PIN; no public employee directory is exposed.
- Session, CSRF, and one-use capture-token checks are enforced.
- Check-in/check-out requires a fresh camera capture and fresh actual location.
- Geofence, accuracy, event order, and server time are validated.
- Event JSON and re-encoded JPEG evidence are stored privately before delivery starts.
- Delivery to WhatsApp uses a leased outbox, bounded retry, provider message ID, and acknowledgement.
- Delivery failure does not lose an accepted attendance event.
- Owner dashboard can read attendance and authorized photos; anonymous users cannot.

### 4. Durable inbox owner review

- Only an authenticated owner with valid CSRF may review an event.
- Lists and health output never expose message body, media bytes, or credentials.
- Every mutation requires exact event identity, expected current status, enumerated action, reason, and compare-and-set semantics.
- Retry is allowed only when idempotency and financial-ledger/write evidence prove it cannot duplicate a transaction.
- Ignore and confirm-processed actions require durable audit evidence.
- Concurrent or stale review requests fail closed.
- Live `needs_review` is resolved only from exact evidence; no arbitrary status update is accepted.

### 5. Backup and recovery

- The production PostgreSQL stores, Google Sheets authority/export, project documents/PDFs, and private Presensi evidence are covered by an explicit backup inventory.
- Every backup has a manifest, checksum, timestamp, source identity, and encrypted handling where required.
- Downloaded backup bytes are verified.
- Restore runs only into isolated disposable targets; it never writes to live production.
- Restored schema, row counts, key invariants, files, hashes, and representative reads match the backup.
- Recovery instructions and RPO/RTO observations are recorded.

### 6. Release and operations

- The exact candidate commit passes focused tests, full relevant suites, dashboard tests/build, browser acceptance, compile/static checks, dependency audit, and diff/secret hygiene.
- GitHub CI passes on the pushed candidate.
- Deployment reports the exact merged SHA through `/api/health/release`.
- Public dashboard, Presensi, backend health, provider connectivity, schema readiness, and anonymous-denial probes pass after deployment.
- Production smoke alerts on inbox backlog/review, provider failure, health failure, or release mismatch.
- A rollback artifact and procedure exist before cutover.

## Stop rule

The release is accepted only when every applicable criterion above has fresh evidence. Tests that are intentionally skipped because they require unavailable production-only integrations must be listed explicitly and must not hide a launch-critical gap.

## Explicit non-goals

- Hermes as a production runtime dependency;
- autonomous bank transfer or direct money movement;
- self-approval by an AI system;
- web hard-delete of posted cash transactions;
- universal cash correction/reversal without a separate immutable accounting design;
- automatic payroll derived from Presensi.
