# Finance v13 disposable migration rehearsal

## Scope

Disposable PostgreSQL 16 container only. Production databases, Sheets authority, Koyeb, Rumahweb, and live financial records were not changed.

## Procedure

1. Initialized legacy `financial_ledger` and `transaction_inbox` through production schema initializers.
2. Applied additive application migrations `001`–`008`.
3. Applied canonical migrations `009`–`013` through `apply_financial_migrations()` under the advisory lock.
4. Re-ran the canonical migrator and verified an empty applied set.
5. Verified exact migration filenames/checksums and schema compatibility v13.
6. Inserted disposable wallets, business units, opening balance, adjustment, external inflow, and inter-wallet debt through production services/repositories.
7. Executed `canonical.finance.metrics.v1` through psycopg named parameters at one inclusive cutoff.
8. Created a custom-format `pg_dump`, restored into a second empty disposable database, and compared metric output and application row counts.
9. Removed the disposable container and local dump/script artifacts.

## Observed evidence

```json
{"archive_bytes":172567,"first_apply":{"applied":[9,10,11,12,13],"current_version":13,"ready":true},"metric_rows":4,"restored_counts":{"debt_events":1,"debts":1,"postings":6,"transactions":2},"restored_metric_match":true,"second_apply":{"applied":[],"current_version":13,"ready":true},"verified":{"checksums_verified":5,"compatible_max":13,"compatible_min":13,"current_version":13,"ready":true}}
```

## Defects found and corrected during rehearsal

- SQL oracle originally used server-style `$1`/`$2` placeholders and was not executable through psycopg. It now uses named `%(cutoff)s` and `%(monthly_operating_outflow)s` parameters, protected by regression tests.
- Rehearsal cutoff initially preceded state creation time and correctly excluded those states. The final rehearsal used one cutoff after all disposable state creation.

## Verdict

Migration apply/rerun, durable debt persistence, metric query execution, backup, restore, and application-level readback passed in the disposable environment. This is pre-activation evidence only; it does not authorize production cutover.