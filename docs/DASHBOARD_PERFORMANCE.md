# Hollawall Dashboard Performance

## Objective

Keep routine owner work responsive without weakening financial correctness, authentication, CSRF, idempotency, optimistic locking, audit events, or authoritative post-write readback.

## Production budgets

Warm authenticated measurements use one explicit warm-up followed by at least 20 samples.

| Surface | Budget |
|---|---:|
| Dashboard usable | p50 ≤ 2,000 ms; p95 ≤ 3,000 ms |
| Transactions route ready | p95 ≤ 2,000 ms |
| Documents route ready | p95 ≤ 2,000 ms |
| Warm JSON APIs | p95 ≤ 750 ms; max ≤ 1,500 ms |
| Controlled Project/Transaction command acknowledgement | p95 ≤ 2,000 ms |
| Authoritative post-write readback | p95 ≤ 3,000 ms |

Cold-start measurements are reported separately. A cold start cannot be hidden inside warm percentiles.

## Benchmark contract

`scripts/benchmark_dashboard_performance.py`:

- verifies the exact admin and backend release SHA before measuring;
- permits the normal login POST before authentication;
- fails closed on any non-GET/HEAD/OPTIONS request after authentication;
- excludes explicit warm-up samples from percentiles;
- records browser route-ready timings, API duration, payload bytes, request counts, status codes, request failures, console errors, and business mutations;
- writes stable JSON and Markdown evidence without credentials, cookies, tokens, or response bodies.

Credentials must come from the owner-scoped runtime environment. Never pass them as command-line arguments or persist them in evidence.

Example structure:

```bash
export HOLLAWALL_ADMIN_USERNAME='OWNER_USERNAME'
export HOLLAWALL_ADMIN_PASSWORD="$(<OWNER_SCOPED_PASSWORD_FILE)"
python scripts/benchmark_dashboard_performance.py \
  --release-sha <40-character-production-sha> \
  --project-id <controlled-project-uuid> \
  --samples 20 \
  --warmups 1 \
  --output-dir /owner-scoped/artifacts/performance/<sha>/baseline-20
```

## Baseline release

Baseline SHA: `9b345bfb9d30e0ff3fa94849aedb376fb90c6f66`.

Canonical browser baseline: 20 measured samples after one excluded warm-up.

- DOM content loaded: p50 `0.286 s`; p95 `0.410 s`.
- Dashboard ready: p50 `9.640 s`; p95 `10.592 s`.
- Transactions ready: p50 `4.434 s`; p95 `4.992 s`.
- Documents ready: p50 `5.471 s`; p95 `6.921 s`.
- Snapshot API: p50 `8.989 s`; p95 `10.153 s`.
- Projects API: p50 `4.546 s`; p95 `4.933 s`.
- Document APIs: p50 `5.258 s`; p95 `7.117 s`.
- Tracked API requests: p50 `7`; p95 `8` per measured sample.
- Request failures, console errors, and post-login business mutations: zero.

Canonical evidence:

- `/root/workspaces/naufal/projects/keuangan/artifacts/performance/9b345bf/baseline-20/dashboard-performance.json`
- `/root/workspaces/naufal/projects/keuangan/artifacts/performance/9b345bf/baseline-20/dashboard-performance.md`

A separate direct Koyeb GET-only probe measured snapshot p50 `9.072 s`, projects p50 `5.265 s`, and payment summary p50 `5.690 s`. Comparable direct-backend timing proves the dominant latency is inside the backend/database path, not the Rumahweb proxy. The direct probe also performed zero business mutations.

## Phase 1 — pooled PostgreSQL sessions

Release SHA: `ef686313bc69dbe0b4756cad1957769e09e5b188`.

Canonical 20-sample production benchmark after introducing one bounded pool per worker:

- Dashboard ready p95: `10.592 s → 6.759 s` (`36.2%` lower).
- Transactions ready p95: `4.992 s → 3.996 s` (`20.0%` lower).
- Documents ready p95: `6.921 s → 5.161 s` (`25.4%` lower).
- Snapshot API p95: `10.153 s → 5.726 s` (`43.6%` lower).
- Projects API p95: `4.933 s → 4.112 s` (`16.6%` lower).
- Document APIs p95: `7.117 s → 4.598 s` (`35.4%` lower).
- Request failures, console errors, and business mutations: zero.

Canonical evidence:

- `/root/workspaces/naufal/projects/keuangan/artifacts/performance/ef68631/post-pool-20/dashboard-performance.json`
- `/root/workspaces/naufal/projects/keuangan/artifacts/performance/ef68631/post-pool-20/dashboard-performance.md`

The result is material but remains over budget. Psycopg documents that a pool `check` callback executes before every checkout and adds network time. Phase 2 therefore removes that per-checkout round trip while retaining startup warm-up, bounded pool size, fail-closed query errors, broken-session discard, and bounded connection lifetime/idle recycling.

## Optimization rules

1. Profile browser → Rumahweb proxy → Koyeb → data source before choosing a fix.
2. Fix the largest measured phase first.
3. Prefer reuse/configuration over new infrastructure.
4. Do not cache a mutation response as authoritative list state.
5. Preserve exactly one required fresh readback after a confirmed write.
6. Keep background refresh lower priority than manual and post-write refresh.
7. Stop adding mechanisms when the frozen budgets pass.

## Release gate

A performance release is complete only when:

- focused performance contracts pass;
- `hermes verify --json` passes;
- frontend tests/build and PostgreSQL integration tests pass;
- independent blocker review is clean;
- Production Gate, deploy, and Production Smoke pass on the exact merge SHA;
- the exact production SHA passes the 20-sample benchmark;
- authenticated desktop/mobile GET-only QA reports zero business mutations and regressions;
- encrypted evidence passes download, decrypt, archive, and manifest-hash readback.
