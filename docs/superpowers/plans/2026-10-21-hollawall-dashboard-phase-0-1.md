# Hollawall Dashboard Phase 0–1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a visually validated owner dashboard prototype and then a private, read-only Financial Command Center backed by Hollawall's existing deterministic finance core and PostgreSQL mirror.

**Architecture:** Phase 0 is a dependency-free browser prototype under `prototypes/financial-command-center/`; it uses clearly labeled synthetic fixture data and never touches production. Phase 1 adds a versioned `/api/dashboard/v1` Flask blueprint that queries the existing `financial_ledger`, then a React/TypeScript/Vite PWA that consumes only that API. Google Sheets remains authoritative until parity gates pass; the dashboard cannot mutate financial state.

**Tech Stack:** Existing Python 3.11/Flask 3.1/PostgreSQL/`psycopg`, React 18+, TypeScript 5+, Vite 5+, semantic HTML/CSS, Chart.js only if hand-written SVG becomes a maintenance burden, Python `unittest`, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-21-hollawall-financial-command-center-design.md`

## Global Constraints

- Additional recurring infrastructure cost must remain Rp0 during Phase 0–1.
- Reuse the existing Koyeb Flask app and `STATE_DATABASE_URL` PostgreSQL when the database-provider gate passes.
- Do not add Odoo, ERPNext, Redis, another ledger writer, or a second operational database.
- Browser finance access is API-only; never expose PostgreSQL credentials or a service-role secret.
- Phase 1 is read-only. No create, edit, delete, correction, approval, or posting endpoint.
- Google Sheets remains source of truth until explicit parity and cutover acceptance.
- Consolidated totals eliminate internal transfers and internal debt.
- Do not label `pemasukan - pengeluaran` as profit.
- All financial values are integer IDR; formatting occurs at the presentation boundary.
- Every API response includes `as_of`, `freshness`, and `data_completeness` metadata.
- Every summary value supports drill-down to the exact transaction filter that produced it.
- Prototype data must be labeled `DATA DEMO`; no real transaction values enter repository fixtures or screenshots.
- Preserve existing WhatsApp ingestion behavior and existing `financial_ledger` idempotency semantics.

## Review Focus

1. **Internal movements:** a paired transfer/debt entry must not inflate consolidated inflow, outflow, or net movement.
2. **Invalid historic rows:** null date/amount rows remain auditable but never enter financial totals.
3. **Mixed wallet/company/project filters:** every card and chart must use the same normalized filter contract and return the same transaction subset.
4. **Stale/partial data:** the UI must visibly warn, retain the last valid payload, and never silently present stale figures as current.
5. **Large transaction history:** filters, pagination, URL state, keyboard navigation, and mobile rendering must remain usable without loading the entire ledger.

---

## File Structure

### Phase 0 — isolated visual prototype

- `prototypes/financial-command-center/index.html` — app shell and semantic content.
- `prototypes/financial-command-center/styles.css` — design tokens, desktop/mobile layout, print/reduced-motion rules.
- `prototypes/financial-command-center/app.js` — fixture filters, navigation, chart/table rendering, mobile drawer.
- `prototypes/financial-command-center/fixture.js` — synthetic company, wallet, project, debt, and transaction data.
- `prototypes/financial-command-center/README.md` — local run and verification instructions.
- `tests/browser/financial_command_center_prototype_test.py` — Playwright visual/interaction smoke test.

### Phase 1 — read-only product

- `dashboard_api/__init__.py` — Flask blueprint factory.
- `dashboard_api/auth.py` — session authentication and role guard.
- `dashboard_api/contracts.py` — filter parsing and response contracts.
- `dashboard_api/repository.py` — parameterized PostgreSQL read queries only.
- `dashboard_api/service.py` — deterministic dashboard calculations and drill-down links.
- `dashboard_api/routes.py` — `/api/dashboard/v1` endpoints.
- `dashboard_api/migrations/001_dashboard_read_indexes.sql` — additive query indexes only.
- `tests/dashboard_api_contract_test.py` — response/filter contracts.
- `tests/dashboard_repository_test.py` — repository query semantics.
- `tests/dashboard_service_test.py` — consolidation and metric semantics.
- `tests/dashboard_routes_test.py` — auth, cache, and HTTP behavior.
- `dashboard/` — React/Vite PWA root.
- `dashboard/src/api/` — typed client and query state.
- `dashboard/src/features/` — overview, cashflow, wallets, transactions, projects, internal debt, reports.
- `dashboard/src/components/` — shell, filters, states, currency/date primitives.
- `dashboard/src/styles/` — tokens, shell, responsive/print styles.
- `dashboard/src/test/` — Vitest component/integration tests.
- `dashboard/e2e/` — Playwright acceptance.

---

### Task 1: Phase 0 dashboard prototype

**Files:**
- Create: `prototypes/financial-command-center/index.html`
- Create: `prototypes/financial-command-center/styles.css`
- Create: `prototypes/financial-command-center/app.js`
- Create: `prototypes/financial-command-center/fixture.js`
- Create: `prototypes/financial-command-center/README.md`
- Test: `tests/browser/financial_command_center_prototype_test.py`

**Interfaces:**
- Consumes: synthetic `window.HOLLAWALL_FIXTURE` with `meta`, `summary`, `cashflow`, `wallets`, `projects`, `debts`, `transactions`.
- Produces: a dependency-free prototype served by `python -m http.server`, with navigation and filters identifiable through stable `data-testid` attributes.

- [ ] **Step 1: Write the failing Playwright smoke test**

Assert:
- page title is `Hollawall — Financial Command Center`;
- `DATA DEMO` is visible;
- six KPI cards exist;
- three wallet cards exist;
- changing wallet filter updates transaction count and URL query;
- clicking a KPI opens a transaction drill-down;
- mobile width 390 has no horizontal overflow;
- no console errors occur.

- [ ] **Step 2: Run prototype test and verify it fails**

Run: `python -m unittest discover -s tests/browser -p 'financial_command_center_prototype_test.py' -v`
Expected: FAIL because the prototype does not exist.

- [ ] **Step 3: Implement the semantic prototype shell and fixture contract**

Use a charcoal/navy command-center shell, off-white data canvas, restrained green for healthy/inflow, amber for attention, red only for real risk/outflow. Use compact Indonesian number formatting and tabular numerals. Avoid decorative gradients, glass cards, oversized radii, and chart-only communication.

- [ ] **Step 4: Implement interactions**

Exact behavior:
- sidebar switches seven launch views without reload;
- global period/wallet/company/project filters update all visible modules;
- URL query reflects filters and reload restores them;
- KPI/wallet/project clicks navigate to filtered transaction rows;
- mobile sidebar is a dismissible drawer;
- charts include textual summaries and tooltips;
- stale banner fixture can be toggled with `?stale=1`.

- [ ] **Step 5: Run browser acceptance**

Run: `python -m unittest discover -s tests/browser -p 'financial_command_center_prototype_test.py' -v`
Expected: PASS.

- [ ] **Step 6: Capture verification screenshots**

Capture:
- `artifacts/dashboard-prototype/overview-1440x900.png`
- `artifacts/dashboard-prototype/transactions-1280x720.png`
- `artifacts/dashboard-prototype/mobile-390x844.png`

- [ ] **Step 7: Commit**

```bash
git add prototypes/financial-command-center tests/browser/financial_command_center_prototype_test.py artifacts/dashboard-prototype
git commit -m "feat: prototype Hollawall financial command center"
```

### Task 2: Freeze metric and filter contracts

**Files:**
- Create: `dashboard_api/contracts.py`
- Create: `dashboard_api/service.py`
- Test: `tests/dashboard_api_contract_test.py`
- Test: `tests/dashboard_service_test.py`

**Interfaces:**
- Consumes: normalized ledger dictionaries matching `services.ledger_store.normalize_row`.
- Produces:
  - `parse_filters(args: Mapping[str, str]) -> DashboardFilters`
  - `build_overview(rows: Sequence[Mapping], filters: DashboardFilters, now: datetime) -> dict`
  - `build_drilldown(filters: DashboardFilters, metric: str) -> dict`

- [ ] **Step 1: Write failing contract tests**

Pin exact allowed values and defaults:
- period default `this_month` in `Asia/Jakarta`;
- `date_from` and `date_to` are inclusive ISO dates;
- unknown wallet/company/project returns HTTP-contract error, not an empty success;
- transfer/internal-debt types are excluded from consolidated operating totals;
- invalid rows count toward completeness issues only;
- summary terms are `cash_position`, `inflow`, `outflow`, `net_movement`, `open_internal_debt`, `data_completeness`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.dashboard_api_contract_test tests.dashboard_service_test -v`
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement immutable filter/result dataclasses and pure calculations**

Do not import Flask or `psycopg` in `contracts.py`/metric calculation functions. Centralize transaction classification constants; do not infer from description strings when normalized type fields exist.

- [ ] **Step 4: Add edge-case tests from Review Focus items 1–3**

Use synthetic rows for transfer pairs, malformed historic data, and mixed filters.

- [ ] **Step 5: Run and commit**

Run: `python -m unittest tests.dashboard_api_contract_test tests.dashboard_service_test -v`
Expected: PASS.

```bash
git add dashboard_api/contracts.py dashboard_api/service.py tests/dashboard_api_contract_test.py tests/dashboard_service_test.py
git commit -m "feat: define dashboard metric contracts"
```

### Task 3: Add parameterized read repository and provider gate

**Files:**
- Create: `dashboard_api/repository.py`
- Create: `dashboard_api/migrations/001_dashboard_read_indexes.sql`
- Create: `scripts/check_dashboard_database.py`
- Test: `tests/dashboard_repository_test.py`

**Interfaces:**
- Consumes: `DashboardFilters`, `STATE_DATABASE_URL`, existing `financial_ledger`.
- Produces:
  - `DashboardRepository.fetch_transactions(filters, *, limit, cursor) -> Page`
  - `DashboardRepository.fetch_filter_options() -> dict`
  - `DashboardRepository.fetch_freshness() -> dict`
  - `check_provider(dsn: str) -> ProviderReport`

- [ ] **Step 1: Write repository tests with a fake cursor**

Assert parameter binding, inclusive dates, stable `(transaction_date, id)` cursor pagination, `is_valid` handling, and zero string interpolation of user filters.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.dashboard_repository_test -v`
Expected: FAIL because repository does not exist.

- [ ] **Step 3: Implement repository and additive indexes**

Repository uses the existing DSN and read-only SQL. Migration may add composite indexes but cannot alter or delete ledger columns.

- [ ] **Step 4: Implement provider gate script**

Report only sanitized facts: connectivity, PostgreSQL version, schema/table access, SSL in use, available storage if provider exposes it, last import, ledger row count, invalid count, and whether a read-only role is available. Never print DSN or credentials.

- [ ] **Step 5: Run tests and static SQL review**

Run: `python -m unittest tests.dashboard_repository_test -v`
Expected: PASS.

Run: `python -m py_compile dashboard_api/repository.py scripts/check_dashboard_database.py`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add dashboard_api/repository.py dashboard_api/migrations/001_dashboard_read_indexes.sql scripts/check_dashboard_database.py tests/dashboard_repository_test.py
git commit -m "feat: add dashboard read repository"
```

### Task 4: Add private, versioned Flask API

**Files:**
- Create: `dashboard_api/__init__.py`
- Create: `dashboard_api/auth.py`
- Create: `dashboard_api/routes.py`
- Modify: `main.py` near Flask initialization
- Modify: `.env.example`
- Test: `tests/dashboard_routes_test.py`

**Interfaces:**
- Consumes: repository and pure service functions from Tasks 2–3.
- Produces:
  - `GET /api/dashboard/v1/overview`
  - `GET /api/dashboard/v1/cashflow`
  - `GET /api/dashboard/v1/wallets`
  - `GET /api/dashboard/v1/transactions`
  - `GET /api/dashboard/v1/projects`
  - `GET /api/dashboard/v1/internal-debts`
  - `GET /api/dashboard/v1/reports`
  - `GET /api/dashboard/v1/options`
  - `GET /api/dashboard/v1/stream` only if the selected zero-cost deployment supports a reliable stream; otherwise use conditional polling.

- [ ] **Step 1: Write failing route/auth tests**

Assert unauthenticated requests return 401, non-owner roles return 403 where applicable, all routes reject unsupported filters with 400, responses have one versioned envelope, write methods return 405, and errors reveal no SQL/DSN.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.dashboard_routes_test -v`
Expected: FAIL because blueprint does not exist.

- [ ] **Step 3: Implement server-side session guard**

Phase 1 supports an invite-only owner account. Cookies must be `Secure`, `HttpOnly`, `SameSite=Lax`, bounded lifetime, rotated on login, and independent of WhatsApp identity. Do not expose a public signup route.

- [ ] **Step 4: Implement versioned GET routes and ETag support**

Each response envelope:

```json
{
  "data": {},
  "meta": {
    "as_of": "ISO-8601",
    "freshness": "fresh|delayed|stale|unknown",
    "data_completeness": 0,
    "filters": {},
    "drilldown": null
  }
}
```

- [ ] **Step 5: Register blueprint without changing webhook routes**

Import/register after `app = Flask(__name__)`; preserve `/health`, `/webhook_wuzapi`, and `/telegram` behavior.

- [ ] **Step 6: Run targeted and regression tests**

Run: `python -m unittest tests.dashboard_routes_test tests.ledger_store_test -v`
Expected: PASS.

Run the full suite in the project environment with dependencies installed. Record pre-existing failures separately; no new failures are allowed.

- [ ] **Step 7: Commit**

```bash
git add dashboard_api main.py .env.example tests/dashboard_routes_test.py
git commit -m "feat: expose private dashboard API"
```

### Task 5: Scaffold the React PWA shell and API client

**Files:**
- Create: `dashboard/package.json`
- Create: `dashboard/vite.config.ts`
- Create: `dashboard/tsconfig.json`
- Create: `dashboard/index.html`
- Create: `dashboard/public/manifest.webmanifest`
- Create: `dashboard/src/main.tsx`
- Create: `dashboard/src/App.tsx`
- Create: `dashboard/src/api/client.ts`
- Create: `dashboard/src/api/contracts.ts`
- Create: `dashboard/src/styles/tokens.css`
- Create: `dashboard/src/styles/shell.css`
- Create: `dashboard/src/components/AppShell.tsx`
- Create: `dashboard/src/components/GlobalFilters.tsx`
- Create: `dashboard/src/components/AsyncState.tsx`
- Test: `dashboard/src/test/app-shell.test.tsx`

**Interfaces:**
- Consumes: `/api/dashboard/v1` response envelope.
- Produces: typed `DashboardClient` and stable routes `/`, `/cashflow`, `/wallets`, `/transactions`, `/projects`, `/debts`, `/reports`.

- [ ] **Step 1: Write failing shell/client tests**

Assert route navigation, filter URL persistence, loading/error/empty/stale states, no raw `fetch` outside `src/api/client.ts`, and one authenticated request policy.

- [ ] **Step 2: Run and verify failure**

Run: `cd dashboard && npm test -- --run`
Expected: FAIL because app files do not exist.

- [ ] **Step 3: Implement minimal typed shell**

Carry Phase 0 tokens and layout forward. Do not add a UI framework unless the prototype proves repeated primitives cannot be maintained locally.

- [ ] **Step 4: Implement caching and stale behavior**

Retain last valid response while revalidating; display delayed/stale state from server metadata; never replace known figures with zero after a transient failure.

- [ ] **Step 5: Run tests/build and commit**

Run: `cd dashboard && npm test -- --run && npm run build`
Expected: PASS and `dist/` generated.

```bash
git add dashboard
git commit -m "feat: scaffold Hollawall dashboard PWA"
```

### Task 6: Implement the seven launch views

**Files:**
- Create/modify: `dashboard/src/features/overview/*`
- Create/modify: `dashboard/src/features/cashflow/*`
- Create/modify: `dashboard/src/features/wallets/*`
- Create/modify: `dashboard/src/features/transactions/*`
- Create/modify: `dashboard/src/features/projects/*`
- Create/modify: `dashboard/src/features/debts/*`
- Create/modify: `dashboard/src/features/reports/*`
- Test: `dashboard/src/test/launch-views.test.tsx`

**Interfaces:**
- Consumes: typed API client and global filter state.
- Produces: all seven launch routes with drill-down links and accessible data alternatives.

- [ ] **Step 1: Write failing view tests**

Cover six overview KPIs, three exact wallet names, cashflow textual alternative, server-side transaction pagination, project `kontribusi tercatat` wording, debt direction/aging, and CSV/XLSX report request links.

- [ ] **Step 2: Run and verify failure**

Run: `cd dashboard && npm test -- --run src/test/launch-views.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement overview, cashflow, and wallets**

Every chart click produces the same filter query used by the transaction route.

- [ ] **Step 4: Implement transactions and projects**

Transactions use semantic table markup, sticky header, keyboard-safe row details, server cursor pagination, and compact mobile cards. Projects never use `profit` until commercial data exists.

- [ ] **Step 5: Implement internal debt and reports**

Debt view shows borrower/lender direction and open balance. Reports expose deterministic downloads generated by the backend—not client-side recomputation.

- [ ] **Step 6: Run tests/build and commit**

Run: `cd dashboard && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add dashboard/src
git commit -m "feat: build dashboard launch views"
```

### Task 7: Add freshness, change notification, and parity verifier

**Files:**
- Create: `dashboard_api/freshness.py`
- Create: `scripts/verify_dashboard_parity.py`
- Modify: `dashboard_api/routes.py`
- Modify: `dashboard/src/api/client.ts`
- Test: `tests/dashboard_freshness_test.py`
- Test: `tests/dashboard_parity_test.py`

**Interfaces:**
- Consumes: Sheets-derived audit rows, PostgreSQL ledger, API ETag.
- Produces:
  - `classify_freshness(last_success, now) -> fresh|delayed|stale|unknown`
  - `compare_snapshots(sheet_rows, database_rows) -> ParityReport`
  - conditional polling or stream invalidation event `ledger.changed`.

- [ ] **Step 1: Write failing freshness/parity tests**

Pin thresholds in configuration; exact defaults: fresh ≤5 minutes, delayed >5 to 30 minutes, stale >30 minutes, unknown without a verified sync. Compare row count, invalid count, aggregate by wallet/type/month, and deterministic source keys.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.dashboard_freshness_test tests.dashboard_parity_test -v`
Expected: FAIL.

- [ ] **Step 3: Implement freshness and parity report**

Mismatch output contains only source keys and aggregate metadata, never full sensitive descriptions by default.

- [ ] **Step 4: Implement zero-cost change strategy**

Prefer ETag conditional polling every 30 seconds. Promote to SSE only after Koyeb behavior is verified. Browser receives no database subscription credentials.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.dashboard_freshness_test tests.dashboard_parity_test -v`
Expected: PASS.

```bash
git add dashboard_api/freshness.py dashboard_api/routes.py dashboard/src/api/client.ts scripts/verify_dashboard_parity.py tests/dashboard_freshness_test.py tests/dashboard_parity_test.py
git commit -m "feat: verify dashboard freshness and parity"
```

### Task 8: End-to-end acceptance and private deployment

**Files:**
- Create: `dashboard/e2e/financial-command-center.spec.ts`
- Create: `docs/DASHBOARD_OPERATIONS.md`
- Modify: deployment config only after runtime inspection confirms exact route.

**Interfaces:**
- Consumes: deployed private API/frontend and sanitized test fixture tenant.
- Produces: verified private dashboard URL, rollback instructions, and acceptance evidence.

- [ ] **Step 1: Write E2E acceptance**

Cover login/logout/session expiry, all seven routes, global filters, KPI drill-down, pagination, stale state, mobile navigation, keyboard path, and unauthorized access.

- [ ] **Step 2: Run locally against production-like env**

Run: `cd dashboard && npx playwright test`
Expected: PASS at 1440×900, 1280×720, and 390×844.

- [ ] **Step 3: Run finance parity gate**

Required:
- 100% valid source keys represented;
- wallet/type/month aggregate difference exactly Rp0;
- internal transfers eliminated from consolidated totals;
- invalid rows excluded and counted;
- three spot-checked KPI drill-down totals exactly match source rows.

- [ ] **Step 4: Deploy frontend/API privately**

Use existing domain, Cloudflare static hosting if the account/session is available, and the existing Koyeb backend. Do not publish a public signup route. If an owner-only account cannot be provisioned without human authentication, stop at that exact owner-only boundary.

- [ ] **Step 5: Verify external state**

Read back:
- TLS and final URL;
- login enforcement;
- active owner account identity;
- each API endpoint;
- real transaction causes dashboard change within the configured freshness budget;
- rollback restores previous backend behavior.

- [ ] **Step 6: Document and commit**

```bash
git add dashboard/e2e docs/DASHBOARD_OPERATIONS.md
git commit -m "test: verify private financial command center"
```

---

## Phase 1 Stop Conditions

Phase 1 is complete only when:

1. the seven views pass local and deployed browser acceptance;
2. API access is invite-only and read-only;
3. parity difference is exactly Rp0 for accepted aggregates;
4. every overview KPI drills into the exact contributing rows;
5. stale/partial data is visibly labeled;
6. existing WhatsApp ingestion still passes targeted regression;
7. production can roll back without losing a WhatsApp transaction;
8. no additional recurring service cost was introduced.

Do not begin write controls, commercial AP/AR, reconciliation, or Hermes actions before these gates pass.
