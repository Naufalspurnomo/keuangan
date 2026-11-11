# Backend foundation slice report

Base: `4446c2d14ea9f9a3a089348a490186c8cb8d1456` (parent baseline `0ee6a95e253bdb616382fca86a8c7285f7d02fd4`)

## Scope

- PG-101 partial: additive migrations `009`–`012` for wallets/business units, opening balances, adjustments, immutable transactions/postings, inter-wallet debt, protected export outbox, reconciliation checkpoints/manifests, schema checksum ledger.
- PG-102 partial: deterministic source identity, quarantine-by-default mapping, zero-tolerance reconciliation contracts.
- PG-103 partial: protected one-way idempotent Sheets export contract and manual-drift detection.
- No authority activation. Current production Sheets authority remains unchanged.

## TDD evidence

RED:
- `tests/canonical_financial_schema_test.py` initially failed because `services.financial_schema` did not exist.
- `tests/financial_authority_migration_test.py` initially failed because migration/export services did not exist.
- Added regression tests exposed privileged extension use, unsafe lock fallback, fractional coordinates/sequences, reserved metadata overrides, missing balanced-posting and same-debt correction constraints.

GREEN:
- `.venv/bin/pytest -q tests/canonical_financial_schema_test.py tests/financial_authority_migration_test.py` → `11 passed in 0.50s`.
- `git diff --check` → pass.
- Targeted secret scan over all nine slice files → zero findings.

## Safety invariants

- One-shot advisory migration lock fails closed.
- Application cannot migrate over a newer schema ledger.
- Migration checksums are recorded and verified.
- Transaction/debt history is immutable; hard delete forbidden.
- Balanced postings enforced with deferred constraint triggers.
- Correction/reversal references are constrained and debt-local.
- Source row and export revision identifiers are integral and deterministic.
- Sheets export metadata cannot override reserved canonical identity fields.

## Remaining plan work

- PG-100 ADR/authority contract completion.
- PG-200 transaction service/API.
- PG-201 debt lifecycle service/API.
- PG-202 project context validation integration.
- PG-203 WhatsApp canonical integration.
- PG-204 legacy Sheets business-access guard.
- PG-205 actor trust.
- PG-206 metric oracle.
- PostgreSQL integration/rehearsal and historical manifest execution.
