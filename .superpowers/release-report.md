# Release foundation report

Base: `4446c2d14ea9f9a3a089348a490186c8cb8d1456` (required baseline parent `0ee6a95e253bdb616382fca86a8c7285f7d02fd4`).

## Provenance slice — commit `53a8528`

- Exact baseline ancestry and clean-tree provenance validator.
- Deterministic immutable release manifest with payload hashes and self-digest.
- Provenance-bound Koyeb, Rumahweb Admin, and Rumahweb Presensi builders.
- Compatibility SHA256SUMS generation.
- Test evidence: 10 focused tests passed; integration branch replay also passed 10/10.

## Promotion guard slice

RED:
- Required-check tests first failed before guard implementation.
- Artifact parity failed because `validate_artifact_sha_parity` did not exist.
- Rollback eligibility tests failed before implementation.

GREEN:
- `python -m pytest -q tests/promotion_guard_test.py tests/release_provenance_test.py tests/release_manifest_test.py tests/release_builders_contract_test.py -o addopts=''` → `17 passed in 0.48s`.
- `git diff --check` → pass.

Invariants:
- Ten required CI jobs must all exist and report exact `success`.
- Every artifact revision and clean source provenance SHA must equal the exact candidate SHA.
- Missing, duplicate, dirty, malformed, or mismatched artifacts fail closed.
- After canonical authority activation, rollback to a non-canonical-aware/Sheets-primary artifact is forbidden.
- Before activation, a valid full-SHA legacy rollback remains eligible.

## Remaining plan work

- Independent CI workflow job split and provider branch protection.
- Promotion guard CLI/provider integration.
- Dormant/activate workflow state artifact.
- Monitoring numeric threshold verifier.
- Backup LSN/cutoff/PITR contract and restore drill.
- Full release, PHP, workflow, security, browser, a11y, and performance gates.

No deployment, push, provider mutation, or production write occurred.
