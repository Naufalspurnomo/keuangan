# Backend canonical finance core report

Base: backend foundation `87ab0cb` on plan commit `4446c2d`; required immutable baseline `0ee6a95e253bdb616382fca86a8c7285f7d02fd4`.

## Delivered

- Immutable canonical transaction service: create, correction, reversal, effective chain/history, idempotency, optimistic concurrency, balanced postings, atomic export-outbox contract.
- In-memory deterministic repository plus PostgreSQL transaction repository.
- Inter-wallet debt domain: disbursement, partial/full repayment, correction/reversal replay, project linkage, balanced internal postings, group-cash and P&L neutrality.
- Fail-closed actor assertion trust: no compiled default proxy-token hash; short-lived HMAC claims bind actor, role, audience, method, path, body hash, expiry, nonce.
- Canonical transaction/debt API blueprint contracts with validation, idempotency, sanitized errors, role-gated reversals.
- Canonical Base64URL enforcement prevents alternate encodings/padding-bit mutation from bypassing tamper rejection.

## TDD evidence

- RED: missing canonical finance/debt modules and routes.
- RED: debt replay selected incorrect aggregate; corrected.
- RED: actor assertion functions absent; implemented fail closed.
- RED during main review: a non-canonical final Base64URL character decoded to identical bytes and passed HMAC. Canonical re-encoding enforcement added.
- GREEN core/routes/trust: `61 passed, 34 subtests passed`.
- GREEN related schema/migration/legacy transaction contracts: `128 passed`.
- Python compile and `git diff --check`: PASS.
- Targeted secret scan: only synthetic test secrets; no runtime credential values.

## Deliberately dormant / not claimed

- New canonical blueprints are not registered in production yet. This prevents an in-memory fallback or incomplete repository from appearing online.
- PostgreSQL debt repository is not implemented.
- Production transaction repository wiring/feature flag is not implemented.
- PG-206 versioned metric oracle remains incomplete.
- Authority remains Sheets; no migration, activation, deploy, push, or production write occurred.
