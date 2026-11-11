# Release reliability slice

## Delivered

- Production Gate now exposes exactly the ten promotion-contract job IDs with real backend, browser E2E, visual, security, frontend, PostgreSQL, PHP, container, performance, and accessibility checks.
- Versioned numeric monitoring contract covers inbox, export, error, API, backup, review, WuzAPI, and presensi signals with fail-closed synthetic evaluation.
- Backup manifest v2 records PostgreSQL LSN/cutoff, schema hash, migration version, and application totals/hashes.
- Restore drill validates the manifest before mutation, restores only to a confirmed disposable database, then reads back application totals/hashes.
- Tool subprocesses receive allowlisted environment variables only.

## Verification

- `pytest tests/release_reliability_test.py tests/hollawall_backup_restore_test.py tests/promotion_guard_test.py`: 32 passed.
- Python compileall: passed.
- YAML parse and exact job-ID equality: passed.
- `git diff --check`: passed.

## Activation boundary

No backup, restore, provider, database, deployment, authority, or production mutation was executed. Real PITR rehearsal and alert delivery remain release gates.
