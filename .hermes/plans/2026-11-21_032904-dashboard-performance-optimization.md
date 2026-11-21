# Hollawall Dashboard Performance Optimization Plan

> **For Hermes:** Execute this plan incrementally with TDD, one active writer, evidence-gated decisions, and production readback after deployment.

**Goal:** Make ordinary admin work—opening the dashboard, entering Projects, Transactions, and Documents, then creating or updating records—feel fast without weakening correctness, auditability, authentication, idempotency, or authoritative readback.

**Architecture:** Measure the complete browser → Rumahweb PHP proxy → Koyeb Flask service → PostgreSQL/Google Sheets path before changing it. Fix the dominant measured bottleneck first, using the smallest existing component change. Preserve authoritative post-commit reads; optimize unnecessary waiting and duplicate reads, not correctness controls.

**Tech stack:** React/Vite, Playwright, PHP/cURL proxy, Flask/Python, psycopg/PostgreSQL, Google Sheets live projection, GitHub Actions, Rumahweb, Koyeb.

---

## Mission contract

- **Objective:** Reduce production latency for routine dashboard operations.
- **Current baseline:** Production SHA `9b345bfb9d30e0ff3fa94849aedb376fb90c6f66`.
- **Authority:** Inspect, benchmark, modify code, test locally/disposable PostgreSQL, open PR, deploy after all gates, run non-destructive production QA.
- **Owner boundary:** Naufal-owned Hollawall development/repository resources only. This VPS remains development-only; production runtime stays on managed/external hosting.
- **Invariant:** Financial correctness, idempotency, optimistic locking, audit events, transaction correction/reversal policy, authentication, CSRF, and fresh post-commit authoritative readback remain intact.
- **Production QA constraint:** GET-only until the optimized release is deployed. Mutation benchmarks use local/disposable PostgreSQL and controlled fixtures; do not create, edit, reverse, or delete real production records.
- **Stop condition:** All frozen latency budgets and regression gates pass on the exact production SHA, or a measured external provider boundary is proven and documented.

## Observed baseline — 21 November 2026

Three authenticated production samples, no business mutation:

- DOMContentLoaded median: `0.263 s`
- Dashboard usable median: `9.208 s`
- Transactions tab ready median: `13.727 s`
- Documents tab ready median: `5.892 s`
- `snapshot.php`: `8.420–9.016 s`
- `projects.php`: `4.264–4.431 s`
- `documents.php`: `4.782–5.721 s`
- Request failures: `0`
- Business mutations: `0`

Initial interpretation—not yet a committed root cause:

1. The static shell is fast; waiting is primarily API/data-path latency.
2. Snapshot polling every five seconds is shorter than the observed snapshot RTT, creating near-continuous or queued reads.
3. Project/document repository reads open a fresh psycopg connection per repository call; connection setup may dominate, but timing must prove this.
4. Documents view performs several authoritative reads; they must remain correct but should run concurrently, reuse safe results, or use a bounded combined read model only when measurements justify it.

## Frozen acceptance budgets

Measure at least 20 warm authenticated samples after one explicit warm-up. Report p50, p95, maximum, request count, payload size, and errors.

- Dashboard usable: p50 `≤ 2.0 s`, p95 `≤ 3.0 s`.
- Transactions tab ready from direct navigation/click: p95 `≤ 2.0 s`.
- Documents tab ready from direct navigation/click: p95 `≤ 2.0 s`.
- Warm JSON APIs (`snapshot.php`, project list, document list/payment summary): p95 `≤ 750 ms`; maximum `≤ 1.5 s`, matching `release/monitoring.v1.json` warning/critical thresholds.
- Create/update Project or Transaction on disposable production-equivalent stack: command acknowledgement p95 `≤ 2.0 s`; authoritative readback p95 `≤ 3.0 s`.
- No duplicate snapshot request while one is active; next background poll is scheduled from completion, not an expired interval tick.
- After a confirmed write, exactly one required fresh authoritative readback remains guaranteed.
- HTTP/network errors, console errors, broken images, horizontal overflow, and unauthorized mutation in production QA: `0`.
- Functional regression suite, browser suite, build, migration verification, release provenance, and production smoke: green.

## Decision policy

Do not preselect caching, pooling, indexing, endpoint aggregation, or frontend memoization. Commit the fix only after timing evidence identifies the dominant component:

- **Connection/TLS dominates:** reuse a bounded DB pool or the configured transaction pooler; preserve per-request transaction boundaries.
- **SQL dominates:** capture `EXPLAIN (ANALYZE, BUFFERS)` on disposable production-equivalent data; optimize query or add one justified migration/index.
- **Google Sheets cold projection dominates:** make last-good snapshot immediately reusable across requests/instances through the smallest safe existing storage mechanism; refresh asynchronously; preserve fail-closed first load and freshness labels.
- **Proxy/network dominates:** reuse upstream connections where hosting supports it, reduce unnecessary hops/requests, or document the external floor.
- **Frontend scheduling dominates:** coalesce duplicate reads, schedule poll from request completion, use visibility-aware backoff, and retain explicit post-write refresh.
- **Multiple independent reads dominate:** run them concurrently or add one bounded aggregate read endpoint only if concurrency cannot meet the budget.

## Task 1: Build a repeatable production-safe performance benchmark

**Objective:** Convert the one-off measurement into a deterministic benchmark and evidence format.

**Files:**
- Create: `scripts/benchmark_dashboard_performance.py`
- Create: `tests/dashboard_performance_contract_test.py`
- Document: `docs/DASHBOARD_PERFORMANCE.md`

**Steps:**
1. Write failing tests for metric aggregation, warm-up exclusion, percentile calculation, mutation guard, and exact SHA capture.
2. Implement a Playwright/HTTP benchmark supporting authenticated GET-only production mode and local controlled-write mode.
3. Record route-ready timing, endpoint TTFB/total duration, payload bytes, request count, duplicate/concurrent requests, errors, and release SHA.
4. Save JSON and Markdown evidence under `artifacts/performance/<sha-or-candidate>/`.
5. Rerun the baseline against SHA `9b345bf`; confirm numbers are comparable to the observed baseline.

**Verification:**
- `python -m pytest -q tests/dashboard_performance_contract_test.py`
- Production mode reports `mutations=0`.
- Repeated run emits deterministic schema and percentile calculations.

## Task 2: Attribute latency across proxy, upstream, database, and source projection

**Objective:** Identify the dominant wait instead of optimizing by assumption.

**Files likely touched:**
- Modify: `deploy/rumahweb-admin/api/snapshot.php`
- Modify: `deploy/rumahweb-admin/api/project-document-proxy.php`
- Modify: `dashboard_api/live_source.py`
- Modify: `dashboard_api/project_document_routes.py`
- Modify: `services/project_document_repository.py`
- Test: `tests/rumahweb_admin_release_test.py`
- Test: `tests/rumahweb_admin_document_proxy_test.py`
- Test: `tests/dashboard_live_source_test.py`
- Test: `tests/project_document_routes_test.py`

**Steps:**
1. Add tests for sanitized `Server-Timing`/structured timing fields that expose only phase names and durations—never URLs with secrets, DSNs, tokens, SQL values, or user data.
2. Measure PHP auth/session, DNS/connect/TLS, upstream TTFB, and total cURL time.
3. Measure snapshot source phases: spreadsheet acquisition, worksheet verification, raw rows, wallet balances, debts, projection, and cache path.
4. Measure repository connection checkout/connect, query, mapping, and response serialization separately.
5. Benchmark warm and cold paths; produce a phase breakdown for `snapshot`, `projects`, `documents`, `payment-summary`, and controlled create/update commands.
6. Freeze one root-cause decision and reject non-dominant changes unless new evidence appears.

**Verification:**
- Timing metadata contains no secret or business record values.
- Existing response contracts and cache-control remain unchanged.
- A written root-cause note identifies the dominant phase and expected gain.

## Task 3: Remove the dominant backend latency

**Objective:** Bring warm API p95 below `750 ms` using the smallest evidence-supported change.

**Possible files—select only the proven path:**
- `dashboard_api/live_source.py`
- `services/project_document_repository.py`
- `dashboard_api/project_document_routes.py`
- `deploy/rumahweb-admin/api/project-document-proxy.php`
- `dashboard_api/migrations/032_<measured-index-name>.sql` only if query-plan evidence requires it
- Focused tests matching the chosen component

**Steps:**
1. Write a failing latency/behavior contract around the measured root cause using deterministic fakes or disposable PostgreSQL—not flaky wall-clock assertions against the internet.
2. Implement one minimal fix:
   - bounded connection pooling/transaction pooler use;
   - one query/index correction;
   - persistent last-good snapshot reuse with asynchronous refresh;
   - or proxy/upstream request reduction.
3. Preserve fail-closed behavior, transaction isolation, cache freshness metadata, and error semantics.
4. Run focused functional tests and the benchmark.
5. Stop if the API budget is met; do not add a second mechanism merely because it is possible.

**Verification:**
- Warm API p95 `≤750 ms`, max `≤1.5 s` over 20 samples locally/staging.
- Cold behavior remains explicit and truthful.
- No stale post-write data is presented as fresh.

## Task 4: Eliminate duplicate frontend fetches and request waterfalls

**Objective:** Make route transitions fast without sacrificing authoritative reads.

**Files likely touched:**
- Modify: `dashboard/src/liveSnapshotView.tsx`
- Modify: `dashboard/src/liveSnapshotView.test.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/App.live.test.tsx`
- Modify: `dashboard/src/ProjectDocumentsWorkspace.tsx`
- Modify: `dashboard/src/ProjectDocumentsWorkspace.test.tsx`
- Modify only if measured: `dashboard/src/ProjectQuotationPanel.tsx` and its tests

**Steps:**
1. Add failing tests proving slow requests do not cause an immediate queued poll, focus/visibility events coalesce, and post-write readback still executes once after the active pre-commit request.
2. Replace fixed overlapping interval semantics with completion-based scheduling plus visibility-aware backoff.
3. Keep manual refresh and post-write refresh higher priority than background polling.
4. Run independent document reads concurrently when safe; reuse already-returned project/document records within the same route generation.
5. Avoid a broad client cache library; use the existing request-generation and stale-response guards.
6. Add request-count assertions for dashboard, Transactions, and Documents navigation.

**Verification:**
- No concurrent duplicate snapshot calls.
- No stale response overwrites a newer project/route.
- One confirmed command causes one required authoritative readback.
- Route request counts match the frozen contract.

## Task 5: Optimize controlled write responsiveness

**Objective:** Ensure creating/updating Projects and Transactions is fast and visibly responsive.

**Files likely touched, only if measurement requires:**
- `dashboard/src/App.tsx`
- `dashboard/src/projectDocumentApi.ts`
- `deploy/rumahweb-admin/api/write-session.php`
- `deploy/rumahweb-admin/api/transactions.php`
- `deploy/rumahweb-admin/api/project-document-proxy.php`
- backend command/repository files identified by Task 2
- corresponding unit, proxy, PostgreSQL integration, and browser tests

**Steps:**
1. Benchmark controlled create/update paths with disposable PostgreSQL and non-production fixtures.
2. Separate command acknowledgement from optional background refresh in the UI while retaining the authoritative readback promise and visible stale/readback-failed state.
3. Remove redundant session/API calls only when they do not weaken CSRF, capability, idempotency, or concurrency gates.
4. If PDF rendering dominates only document issuance, keep it as a separate documented budget rather than distorting ordinary Project/Transaction targets.

**Verification:**
- Command acknowledgement p95 `≤2.0 s`.
- Authoritative readback p95 `≤3.0 s`.
- Retried idempotency key creates one record.
- Uncertain outcomes remain recoverable and never falsely reported as failed or duplicated.

## Task 6: Full regression, candidate review, and production release

**Objective:** Ship only after performance and correctness pass together.

**Steps:**
1. Run focused performance-contract tests.
2. Run frontend tests/build and backend verifier sequentially to avoid shared test-harness process interference.
3. Run disposable PostgreSQL integration tests and migration identity checks.
4. Run independent blocker-only review against the frozen diff.
5. Commit, PR, require all CI checks, merge with expected head SHA.
6. Verify Production Gate, managed deployment, exact frontend/backend release SHA, and Production Smoke.
7. Run the benchmark on exact production SHA: 20 warm samples plus documented cold-start sample.
8. Run authenticated desktop/mobile GET-only QA; confirm mutations `0`.
9. Store JSON, Markdown, screenshots, workflow metadata, and source provenance in an encrypted owner-scoped Drive archive; verify downloaded bytes, decrypt, tar, and manifest hashes.

**Final verification:**
- `hermes verify --json`
- Performance budgets all pass or the objective remains open.
- Production source SHA equals deployed SHA.
- No P0/P1 review blockers.
- Workspace clean.

## Risks and mitigations

- **Fast but stale data:** Preserve freshness labels and mandatory post-write readback; never cache mutation responses as authoritative list state.
- **Connection pool exhaustion:** Bound pool size, use per-request context management, expose saturation timing, and test cleanup.
- **Google Sheets quota/load:** Completion-based polling and last-good snapshot reuse reduce—not increase—source reads.
- **Timing instrumentation leaks:** Permit phase names and milliseconds only; secret scan evidence before release.
- **Provider cold start:** Report cold separately from warm. If external scale-to-zero is the remaining floor, evaluate provider configuration only after app-level budgets are exhausted.
- **Synthetic benchmark optimism:** Final gate uses the real authenticated production route and exact deployed SHA.

## Definition of done

The task is not done when code is faster locally. It is done only when exact production SHA meets the frozen p95 budgets, routine desktop/mobile flows have zero functional regressions, write correctness remains authoritative, production smoke is green, and encrypted evidence passes restore verification.
