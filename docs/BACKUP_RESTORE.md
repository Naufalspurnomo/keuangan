# Hollawall coordinated backup and restore verification

## Safety boundary

This runbook covers three coordinated inputs:

1. PostgreSQL, captured by `pg_dump --format=custom`.
2. A completed Google Sheets export/copy directory. The backup tool does **not** authenticate to Google or modify a Sheet.
3. The private Presensi tree (`.hollawall-presensi`), copied while holding its `events.lock` exclusive lock.

Both CLIs are non-mutating by default. Backup writes require `--apply`. Restore verification requires both `--verify` and the literal confirmation `VERIFY_DISPOSABLE_DATABASE`. There is no production restore mode. Restore verification accepts only a disposable PostgreSQL DSN, rejects a target with the source database fingerprint, and never invokes `createdb` or `dropdb`; provisioning and destruction of the disposable database remain external operator actions.

Never place a DSN or archive key on the command line. Supply DSNs through named environment variables. Supply the owner-scoped archive key through an environment variable or owner-only key file. Tool output and JSON results omit these values.

## Recovery objectives and run record

| Field | Hollawall target / required record value |
|---|---|
| `backup_schedule` | Daily at **02:15 Asia/Jakarta** (`15 2 * * *` with `CRON_TZ=Asia/Jakarta`) after the Sheets export job has completed |
| `rpo_target` | **24 hours** for the coordinated set |
| `rto_target` | **4 hours** from declared recovery start to verified disposable restore plus approved production recovery handoff |
| `retention_daily` | **35 days** |
| `retention_monthly` | **12 month-end copies** |
| `offsite_copies` | At least one owner-scoped off-host rclone destination; local-only completion is not a disaster-recovery copy |
| `restore_drill_frequency` | Monthly, first Monday, **09:00 Asia/Jakarta** |
| `backup_id` | Encrypted archive basename, e.g. `hollawall-backup-YYYYMMDDTHHMMSSZ.tar.enc` |
| `backup_started_at` / `backup_finished_at` | UTC timestamps from the scheduler |
| `archive_sha256` | Exact SHA-256 returned by the backup command |
| `offsite_readback_verified` | Must be `true` when offsite upload is enabled; proves downloaded bytes, decrypt, and tar readback |
| `restore_drill_started_at` / `restore_drill_finished_at` | UTC timestamps from the drill runner |
| `rpo_observed` | Age of `manifest.created_at` at recovery/drill start |
| `rto_observed` | Drill finish minus drill start |
| `disposable_database_id` | Non-secret ticket/resource identifier; never the DSN |
| `result` | `PASS` only when all component checks and `pg_restore` complete |
| `operator` / `evidence_path` | Owner-scoped operator ID and private run record location |

The values above are initial operational targets. Change them only through an approved operations change with matching scheduler and retention updates.

## Inputs and prerequisites

Required external tools:

- PostgreSQL client tools compatible with the source (`pg_dump`, `pg_restore`).
- OpenSSL with `enc`, AES-256-CBC, and PBKDF2 support.
- `rclone` only when offsite upload is requested.

Prepare inputs outside this repository:

```text
<run-root>/
  sheets-export/       # completed, immutable export/copy input
    *.csv|*.json|...   # all exported files are hashed; format is not rewritten
  .hollawall-presensi/
    events.json
    events.lock
    photos/*.jpg
```

The Presensi tree must be the private runtime tree, not a public release payload. `events.lock` is mandatory. The tool refuses symlinks and unsupported filesystem entries. It does not include the separate `.hollawall-presensi.php` credential/config file.

Use an existing owner-scoped archive key. Independent secure backup of that key is mandatory: losing it makes every encrypted backup unrecoverable. Example permission for a key file:

```bash
chmod 0600 /owner/private/hollawall-archive.key
```

An rclone destination requires both an explicit config path and explicit remote destination. The scripts never use implicit/default rclone configuration.

## Backup

### 1. Create a completed Sheets export/copy input

Use the owner-approved Google export mechanism before the backup window. Write into a run-specific directory, finish all exports, then make that directory immutable to the backup process. The backup tool intentionally consumes a local export/copy input instead of embedding Google credentials or invoking mutable Google APIs.

The export job must fail the overall scheduled run if any expected Sheet/tab is absent. Preserve the export job's source spreadsheet IDs in its private run record; the backup manifest stores only a redacted identifier and SHA-256 source fingerprint.

### 2. Dry-run (default)

No credentials are needed. This prints a plan and does not validate sources, execute commands, create the output directory, or upload anything:

```bash
python3 scripts/hollawall_backup.py \
  --output-dir /owner/backups/hollawall \
  --sheets-source /owner/staging/hollawall/sheets-export \
  --presensi-source /owner/private/.hollawall-presensi
```

Expected JSON includes:

```json
{"action":"dry-run","components":["postgres","sheets","presensi"],"mutation":false,"offsite_upload":false}
```

### 3. Apply locally

Export secrets in the private scheduler/wrapper process, not in crontab and not as command arguments:

```bash
export HOLLAWALL_BACKUP_DATABASE_URL='<source PostgreSQL URI>'
export HOLLAWALL_ARCHIVE_KEY='<existing owner-scoped archive key>'
python3 scripts/hollawall_backup.py \
  --apply \
  --output-dir /owner/backups/hollawall \
  --sheets-source /owner/staging/hollawall/sheets-export \
  --presensi-source /owner/private/.hollawall-presensi
```

Key-file alternative:

```bash
export HOLLAWALL_BACKUP_DATABASE_URL='<source PostgreSQL URI>'
python3 scripts/hollawall_backup.py \
  --apply \
  --archive-key-file /owner/private/hollawall-archive.key \
  --output-dir /owner/backups/hollawall \
  --sheets-source /owner/staging/hollawall/sheets-export \
  --presensi-source /owner/private/.hollawall-presensi
```

The tool creates a PostgreSQL custom-format dump, inventories every component file with size and SHA-256, writes a UTC timestamped manifest, redacts source identifiers, encrypts the tar, decrypts it into temporary storage, and reads the complete tar member set back before returning success. Final local archive mode is `0600`. Plaintext tar and copied source data remain only in an automatically removed temporary directory.

### 4. Apply with offsite upload

```bash
export HOLLAWALL_BACKUP_DATABASE_URL='<source PostgreSQL URI>'
python3 scripts/hollawall_backup.py \
  --apply \
  --archive-key-file /owner/private/hollawall-archive.key \
  --rclone-config /owner/private/rclone.conf \
  --rclone-destination 'owner-remote:Hollawall/Backups' \
  --output-dir /owner/backups/hollawall \
  --sheets-source /owner/staging/hollawall/sheets-export \
  --presensi-source /owner/private/.hollawall-presensi
```

The upload is accepted only after the exact remote object is downloaded to temporary storage, its encrypted-byte SHA-256 matches the local archive, and downloaded decrypt/tar readback matches the expected member inventory. Required success fields:

```json
{"verified":true,"uploaded":true,"downloaded_byte_verified":true}
```

A failed upload/readback leaves the already verified local encrypted archive intact and exits nonzero. Do not mark the offsite copy complete.

## Exact scheduling

Install a private wrapper owned by the backup principal. The wrapper must:

1. set `umask 077`;
2. obtain the source DSN and owner archive key from the approved secret store;
3. run the completed Sheets export/copy job;
4. verify the expected export inventory;
5. invoke `hollawall_backup.py --apply` with explicit sources, output, rclone config, and destination;
6. capture only returned JSON plus timestamps into the private run record;
7. alert on any nonzero exit or when `uploaded`, `downloaded_byte_verified`, or `verified` is not `true`.

Crontab entry (the wrapper contains no literal secret):

```cron
CRON_TZ=Asia/Jakarta
15 2 * * * /owner/bin/run-hollawall-backup >>/owner/private/log/hollawall-backup.log 2>&1
```

Monthly drill entry:

```cron
CRON_TZ=Asia/Jakarta
0 9 * * 1 /owner/bin/run-hollawall-restore-drill >>/owner/private/log/hollawall-restore-drill.log 2>&1
```

The drill wrapper must immediately exit unless the Asia/Jakarta day of month is `1..7`. Combined with the Monday-only cron expression, this gives exactly the first Monday at 09:00 Asia/Jakarta and avoids day-of-month/day-of-week OR ambiguity.

Do not overlap backup runs. The scheduler/wrapper must hold an owner-scoped single-run lock for the complete Sheets-export plus backup operation. A skipped overlap is an alert because it threatens the 24-hour RPO.

## Retention

Retention applies only after a newer offsite archive has passed downloaded-byte and decrypt/tar readback verification.

- Keep all daily verified archives for 35 days.
- Keep one verified month-end archive for 12 months.
- Keep the latest successful monthly restore-drill archive until a newer drill passes.
- Delete neither the last known-good local archive nor last known-good offsite archive.
- Use one-way explicit deletion commands approved by the operator; never use bidirectional sync.
- Record every deletion by archive basename and SHA-256 in the private retention log.
- Never delete the archive key as part of archive retention. Maintain an independent secure key backup.

The Python backup tool deliberately performs no retention deletion.

## Isolated restore verification

### 1. Provision a disposable database externally

Create an empty, isolated PostgreSQL database with no route to production data and credentials dedicated to the drill. The verifier does not create or drop databases. Set a resource-level expiry so the platform destroys it after the drill.

The disposable DSN must not identify the manifest source host/port/database. Source comparison ignores usernames, passwords, and query parameters, so changing credentials cannot bypass the guard. DNS aliases cannot be proven equivalent offline; the operator must independently ensure the disposable host is not a production alias, proxy, or replica endpoint.

### 2. Dry-run (default)

```bash
python3 scripts/hollawall_restore_verify.py \
  --archive /owner/backups/hollawall/hollawall-backup-YYYYMMDDTHHMMSSZ.tar.enc
```

This does not decrypt, extract, call `pg_restore`, or require secrets.

### 3. Run the drill

```bash
export HOLLAWALL_RESTORE_VERIFY_DATABASE_URL='<disposable PostgreSQL URI>'
python3 scripts/hollawall_restore_verify.py \
  --verify \
  --confirm-disposable-database VERIFY_DISPOSABLE_DATABASE \
  --archive-key-file /owner/private/hollawall-archive.key \
  --archive /owner/backups/hollawall/hollawall-backup-YYYYMMDDTHHMMSSZ.tar.enc
```

The verifier performs these gates in order:

1. decrypt to an automatically removed temporary directory;
2. reject unsafe, duplicate, or non-file tar members;
3. validate manifest schema and exact archive/member inventory;
4. validate size and SHA-256 for every PostgreSQL, Sheets, and Presensi file;
5. reject a disposable database fingerprint matching the source;
6. require exactly `postgres/database.dump` and run `pg_restore --list`;
7. parse Presensi `events.json`, require a one-to-one event/photo mapping, require `image/jpeg`, `.jpg`/`.jpeg`, JPEG SOI/EOI, Start Of Frame, and Start Of Scan markers;
8. run `pg_restore --exit-on-error --clean --if-exists --no-owner --no-privileges` against only `HOLLAWALL_RESTORE_VERIFY_DATABASE_URL`.

The source DSN and disposable DSN are child-process environment values, never command arguments. A successful JSON result includes:

```json
{
  "action": "verify",
  "database_restored": true,
  "presensi_events_verified": 1,
  "presensi_photos_verified": 1,
  "sheets_files_verified": 2,
  "verified": true
}
```

Counts vary by archive. `verified:true` is the sole pass signal. After recording evidence, destroy the disposable database using the external platform procedure and verify it no longer exists.

## Failure handling

- Any command failure exits nonzero with a bounded error that excludes command stderr, DSNs, and key material.
- Never retry `pg_dump`, encryption, upload, or restore by reusing a partial output archive. Start a new timestamped run after correcting the cause.
- Never treat local archive creation as offsite success.
- Never restore into production from these scripts. Production recovery requires a separate approved change, outage decision, target validation, and human-controlled database procedure.
- If Presensi bijection or JPEG validation fails, preserve the encrypted archive and investigate the source/run privately; do not edit evidence inside the archive.
- If Sheets hashes fail, discard the extracted temporary copy, regenerate a complete export, and create a new backup.

## Test command

Tests use temporary files and injected fake `pg_dump`, `pg_restore`, OpenSSL, and rclone runners. They do not access production, Google, a real database, or an offsite remote.

```bash
python -m pytest -q tests/hollawall_backup_restore_test.py
```
