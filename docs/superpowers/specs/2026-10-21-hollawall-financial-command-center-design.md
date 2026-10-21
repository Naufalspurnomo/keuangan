# Hollawall Financial Command Center — Product Design

**Status:** Reviewed draft for owner approval  
**Product:** Custom company-wide finance system  
**Primary user:** Boss / company owner  
**Input channel:** WhatsApp remains primary  
**Control surface:** Private responsive web application  
**AI runtime:** Hermes, behind deterministic finance tools  
**Infrastructure target:** Rp0 recurring incremental cost during pilot

## 1. Product decision

Hollawall will not use Odoo as its primary user interface or operating model.

The product will be a custom financial command center designed around the company's actual structure:

- `CV HB(101)` serves HOLLA and HOJJA;
- `TX SBY(216)` serves TEXTURIN Surabaya;
- `TX BALI(087)` serves TEXTURIN Bali;
- office operations may draw from all three wallets;
- inter-wallet debt remains visible per wallet but cancels at consolidated-company level;
- WhatsApp remains the fastest capture channel;
- the website becomes the authoritative place to understand, review, organize, and control company finances.

This is not a decorative dashboard over Google Sheets. The long-term product is a custom finance system whose visual model, workflows, permissions, AI, and audit trail are owned by Hollawall.

## 2. Why this product exists

WhatsApp is effective for sending transaction facts but poor for seeing the whole company:

- important entries are mixed with chat noise;
- balances, trends, debts, and project health cannot be scanned together;
- repeated questions create chat spam;
- corrections and unresolved issues are difficult to track;
- there is no stable visual hierarchy from company to wallet to project to source evidence.

The website must answer, within seconds:

1. How much cash does the company actually have now?
2. Where is that money held?
3. What changed today, this week, and this month?
4. Which projects make or lose money?
5. What must be paid or collected next?
6. Which transactions are incomplete, suspicious, duplicated, or unsupported?
7. What needs the Boss's decision now?
8. Can every number be traced to its transaction and original source?

## 3. Product principles

### 3.1 One system, two interfaces

- **WhatsApp:** capture transactions, receipts, notes, and quick questions.
- **Web:** see the full company, investigate details, resolve exceptions, approve decisions, manage structured records, and generate reports.

Both interfaces operate on the same finance core. They must not become separate ledgers.

### 3.2 Company truth before visual polish

Every headline number must have:

- a precise definition;
- a period and scope;
- a last-updated timestamp;
- a drill-down to contributing records;
- a warning when incomplete or stale.

### 3.3 Cash is not profit

The interface must never blur:

- wallet balance;
- consolidated cash;
- project cash flow;
- project contribution/margin;
- receivables;
- payables;
- inter-wallet debt;
- owner-safe spend.

If required inputs do not yet exist, the product shows `Belum dapat dihitung`, not a fabricated estimate.

### 3.4 AI explains; deterministic tools calculate and mutate

Hermes may:

- interpret natural-language questions;
- choose safe read tools;
- explain changes and anomalies;
- summarize evidence;
- prepare draft actions.

Hermes may not invent financial values or directly alter the ledger. Calculations come from deterministic queries. Mutations require the finance API, authorization, idempotency, validation, and an audit event.

### 3.5 Progressive disclosure

The home screen shows the company-wide picture and urgent decisions. Detail lives on dedicated pages. Do not place every chart on one endless page.

## 4. Current foundation to reuse

The current repository already contains useful production foundations:

- working WhatsApp/WuzAPI input flow;
- OCR and transaction parsing;
- three canonical wallet mappings;
- project resolution and operational-expense handling;
- debt flow;
- durable transaction inbox and retry queue;
- PostgreSQL-backed state support;
- cross-replica advisory locking;
- idempotent `financial_ledger` mirror;
- `financial_projects` index;
- historical Google Sheets-to-PostgreSQL importer;
- deterministic query engine with allowed filters and groupings.

Therefore, this product extends the working system. It does not replace the bot or rewrite transaction capture first.

### Verified implementation gaps

The current repository does **not** yet contain:

- authenticated dashboard routes or finance APIs beyond health/webhooks;
- a web frontend application;
- receivable, payable, invoice, evidence-object, reconciliation, or approval domain tables;
- immutable correction/reversal semantics for the existing Sheets ledger;
- a verified browser authentication flow.

The current revision flow can update amounts and delete Sheet rows. Therefore, the web pilot remains read-only. No web correction action may be enabled until reversal/replacement events, authorization, and audit readback exist.

The existing chat dashboard also labels `pemasukan - pengeluaran` as profit/loss. The custom dashboard must not repeat that accounting claim. Until commercial inputs are modeled, it is labeled **pergerakan kas bersih** or **kontribusi tercatat**, depending on scope.

## 5. Information architecture

### Primary navigation

1. **Ringkasan**
2. **Arus Kas**
3. **Dompet**
4. **Transaksi**
5. **Proyek**
6. **Piutang**
7. **Tagihan**
8. **Hutang Antar-Dompet**
9. **Rekonsiliasi**
10. **Bukti & Audit**
11. **Laporan**
12. **Tanya Hollawall AI**
13. **Pengaturan**

### Persistent global controls

Every data page shares:

- period selector;
- company/business-unit selector;
- wallet selector;
- project selector;
- data-freshness indicator;
- global search;
- notification/Decision Inbox count;
- user/role menu.

Filters are represented in the URL so views can be bookmarked and shared between authorized users.

## 6. Screen design

## 6.1 Ringkasan — Financial Command Center

**Single job:** Let the Boss understand company health and urgent action in under 30 seconds.

### Desktop composition at 1440px

- fixed left navigation: approximately 232px;
- sticky top filter/status bar;
- 12-column content grid;
- maximum useful width approximately 1600px;
- no giant marketing hero;
- important values remain above the fold at 900px viewport height.

### Row A — Company position

Six compact headline metrics for the read-only launch:

1. **Kas terkonsolidasi**
2. **Pemasukan periode**
3. **Pengeluaran periode**
4. **Pergerakan kas bersih**
5. **Hutang antar-dompet terbuka**
6. **Kelengkapan data**

Each card includes:

- current value;
- comparison to previous matching period;
- scope label;
- freshness timestamp;
- click-through drill-down.

`Kas tersedia`, `piutang terbuka`, and `tagihan terbuka` are not shown as headline values until reserved obligations, receivables, and payables are modeled reliably. After Phase 3, the owner may pin any six supported metrics.

### Row B — Main analytical view

- **8 columns:** cash-flow chart with income, expense, and net movement over time;
- **4 columns:** current wallet position for `CV HB`, `TX SBY`, and `TX BALI`, including internal debt adjustments.

The chart supports day/week/month grouping without changing the meaning of totals.

### Row C — What needs attention

- **Decision Inbox:** ambiguous transaction, missing wallet/project, missing evidence, suspected duplicate, correction request, sync failure, reconciliation mismatch;
- **Due soon:** receivables and payables grouped by due date;
- **Data health:** stale source, incomplete mapping, invalid row, delayed projection.

Urgency is expressed with icon, label, count, and text—not color alone.

### Row D — Performance

- project contribution ranking;
- operational spending by category;
- company/business-unit comparison;
- largest unusual movements;
- recent confirmed transactions.

Every chart opens the exact contributing transaction set.

## 6.2 Arus Kas

**Single job:** Explain where money came from, where it went, and how cash changed.

Views:

- inflow vs outflow timeline;
- net movement;
- opening and closing cash;
- breakdown by wallet, company, project, and category;
- period comparison;
- cumulative cash curve;
- largest drivers.

The page distinguishes transfer/internal movement from external inflow/outflow so moving money between wallets does not inflate company revenue or expense.

## 6.3 Dompet

**Single job:** Show the actual position and movement of each cash source.

Each wallet page shows:

- current balance;
- external inflow/outflow;
- internal transfers;
- amount lent/borrowed to other wallets;
- adjusted position;
- linked companies;
- projects funded;
- recent transactions;
- unresolved reconciliation items.

A consolidated view presents all three wallets side by side.

## 6.4 Transaksi

**Single job:** Search, inspect, and safely correct the ledger.

Features:

- server-side filtering;
- saved views;
- full-text search;
- date, amount, type, wallet, company, project, category, user, source, and evidence filters;
- virtualized or paginated table;
- column chooser;
- CSV/XLSX export;
- transaction detail drawer/page;
- correction by reversal plus replacement—not destructive editing;
- duplicate linking;
- source WhatsApp message and receipt evidence;
- audit history.

The table is the operational spine of the web product. It must be fast, dense, keyboard-friendly, and legible.

## 6.5 Proyek

**Single job:** Show financial health per project.

### Project list

- company;
- wallet(s);
- status;
- income recorded;
- expense recorded;
- current contribution;
- receivable;
- payable/commitment;
- evidence completeness;
- latest activity;
- warning state.

### Project cockpit

- project identity and company;
- customer/counterparty;
- budget/contract value when available;
- actual inflow/outflow;
- contribution and margin with explicit definition;
- committed cost;
- billed, collected, and outstanding;
- timeline of financial events;
- category breakdown;
- supporting receipts/invoices;
- unresolved decisions;
- AI explanation with cited records.

Until contract value, budget, and commitments are captured, the UI labels the metric **Kontribusi tercatat**, not final profit.

## 6.6 Piutang

**Single job:** Make money owed to the company visible and collectible.

- customer;
- project;
- invoice/reference;
- original amount;
- collected amount;
- remaining amount;
- due date;
- aging bucket;
- status;
- follow-up history;
- linked payments and evidence.

Dashboard states: draft, issued, partially paid, paid, overdue, void.

## 6.7 Tagihan

**Single job:** Make obligations and upcoming cash needs visible.

- vendor/payee;
- project/operational purpose;
- amount;
- due date;
- planned wallet;
- approval status;
- payment status;
- evidence;
- recurring flag when applicable.

Dashboard states: recorded, awaiting approval, approved, scheduled, partially paid, paid, void.

## 6.8 Hutang Antar-Dompet

**Single job:** Explain internal funding without distorting consolidated results.

- lender wallet;
- borrower wallet;
- original amount;
- repaid amount;
- open balance;
- date and age;
- related project/operation;
- settlement timeline;
- linked source transactions.

Consolidated company views eliminate both sides. Wallet-level views preserve both sides.

## 6.9 Rekonsiliasi

**Single job:** Match ledger entries to bank/wallet statements.

Initial input is manual CSV/XLSX/PDF import. Matching signals:

- amount;
- direction;
- date window;
- reference text;
- wallet;
- counterparty;
- project;
- split or combined payment pattern.

Statuses: exact, probable, unmatched statement, unmatched ledger, duplicate candidate, confirmed, ignored with reason.

## 6.10 Bukti & Audit

**Single job:** Prove where each financial fact came from and who changed it.

Transaction timeline:

1. source WhatsApp event;
2. image/file receipt;
3. OCR result;
4. parser interpretation;
5. clarification;
6. policy/approval;
7. ledger posting;
8. correction/reversal;
9. bank match;
10. actor and timestamp.

Evidence files are private and served through authenticated, expiring access.

## 6.11 Laporan

Initial reports:

- cash position;
- cash movement;
- income and expense by company;
- project contribution;
- operational expenses;
- wallet balances;
- inter-wallet debt;
- receivable aging;
- payable schedule;
- reconciliation status;
- data/evidence completeness.

Reports can be filtered, exported, and reproduced from the same deterministic definitions as the dashboard.

## 6.12 Tanya Hollawall AI

**Single job:** Let the Boss interrogate company finances in normal Indonesian without losing traceability.

Example questions:

- `Kenapa pengeluaran bulan ini naik?`
- `Proyek mana yang paling banyak menyerap kas?`
- `Tampilkan transaksi TX Bali di atas Rp5 juta tanpa bukti.`
- `Apa yang harus saya putuskan hari ini?`
- `Bandingkan TEXTURIN Surabaya dan Bali bulan ini.`

Every answer includes:

- scope and period;
- deterministic totals;
- contributing records/citations;
- assumptions;
- data-completeness warning;
- optional proposed next action.

AI action flow:

```text
Question
→ Hermes interprets intent
→ read-only finance tool executes validated query
→ deterministic result
→ Hermes explains with citations
```

Mutation flow:

```text
Boss asks for action
→ Hermes prepares structured draft
→ dashboard shows exact impact
→ authorized approval
→ finance API validates and commits
→ audit event + realtime refresh
```

No unrestricted SQL, browser-side service key, or direct model write is allowed.

## 7. Responsive behavior

### Desktop

Primary operating environment. Full sidebar, multi-column analysis, dense transaction tables, keyboard shortcuts.

### Tablet

Collapsible sidebar, two-column analytics, horizontally scrollable data tables with pinned identifying columns.

### Mobile/PWA

Mobile is not a crushed desktop dashboard. It prioritizes:

1. company position;
2. Decision Inbox;
3. wallet balances;
4. recent activity;
5. quick project lookup;
6. AI questions;
7. approvals.

Complex reconciliation and wide-table work may show a clear `Lebih nyaman di desktop` notice while remaining accessible.

## 8. Visual direction

**Concept:** calm financial control room—not a generic SaaS template.

- light warm-neutral canvas for long daytime use;
- deep ink text;
- restrained emerald accent for active/confirmed states;
- amber and red reserved for true warning/risk;
- no decorative gradients;
- no glassmorphism;
- no giant rounded cards;
- no fake numbers;
- minimal animation;
- tabular numerals for money;
- one consistent 8px spacing system;
- compact but breathable density;
- charts use direct labels where possible;
- every status combines color with icon/text;
- WCAG 2.2 AA contrast and keyboard accessibility floor.

The visual vocabulary combines Wise-like financial clarity with Linear-like information precision, without cloning either product.

## 9. Technical architecture

```text
WhatsApp / WuzAPI
        │
        ▼
Existing Flask finance service on Koyeb
├── parser/OCR
├── validation
├── idempotency
├── ledger posting
├── approvals/corrections
└── dashboard API
        │
        ▼
Canonical external PostgreSQL
├── existing bot/durable state
├── financial ledger mirror
├── dashboard read models/views
└── later finance domain tables
        │
        ├──────────────► Existing Flask Finance API
        │                    │
        │                    ├──► React + TypeScript PWA on Cloudflare Pages
        │                    └──► private evidence delivery
        │
        └──────────────► Hermes `finance-prod`
                         ├── read-only finance tools
                         ├── cited explanations
                         └── approval-gated action drafts

Identity/realtime provider
├── Supabase Auth + Realtime if the canonical DB is Supabase
└── otherwise an equivalent free, owner-scoped adapter without copying finance data

Google Sheets
└── compatibility ledger during migration, then export/projection

Google Drive
└── encrypted backups and generated report archives
```

### Frontend

- React + TypeScript + Vite;
- PWA shell;
- TanStack Query for server state;
- TanStack Table for transaction-heavy pages;
- lightweight chart library selected during implementation after bundle and accessibility evaluation;
- no global state library unless actual shared-client state requires it.

The browser reads finance data only through the authenticated Flask Finance API. It does not query raw finance tables directly. Realtime transports a version/invalidation signal; the frontend then refetches an authorized API resource. This keeps formulas, authorization, and data-shaping in one server-side boundary.

### Backend

Extend existing Flask service instead of creating a second backend.

API groups:

- `/api/v1/overview`
- `/api/v1/cashflow`
- `/api/v1/wallets`
- `/api/v1/transactions`
- `/api/v1/projects`
- `/api/v1/receivables`
- `/api/v1/payables`
- `/api/v1/interwallet-debts`
- `/api/v1/reconciliation`
- `/api/v1/evidence`
- `/api/v1/reports`
- `/api/v1/decisions`
- `/api/v1/ai/query`
- `/api/v1/ai/drafts`

Only these API groups are required for the read-only launch:

- `/api/v1/overview`
- `/api/v1/cashflow`
- `/api/v1/wallets`
- `/api/v1/transactions`
- `/api/v1/projects`
- `/api/v1/interwallet-debts`
- `/api/v1/reports`

Receivables, payables, reconciliation, evidence mutation, decisions, and AI endpoints are created only in their owning phase. Empty placeholder APIs and pages are prohibited.

### Database evolution

Do not force the current single-row ledger to model the final system indefinitely.

Target domains:

- users and roles;
- companies/business units;
- wallets/accounts;
- projects;
- counterparties;
- source messages;
- financial events;
- journal entries and lines;
- transfers/internal debt;
- receivables/invoices;
- payables/bills;
- payments/allocations;
- evidence objects;
- approvals;
- reconciliation records;
- immutable audit events;
- dashboard read models.

During migration, existing `financial_ledger` remains the compatibility projection. PostgreSQL becomes authoritative only after measured parity and recovery testing.

### Database-provider gate

Before creating any Supabase project, inspect the active Koyeb environment and identify the actual external PostgreSQL provider, ownership, capacity, backups, and production use. Decision order:

1. reuse the existing authorized PostgreSQL if it satisfies the launch requirements;
2. configure or extend it if a small change is enough;
3. migrate it to Supabase Free only when Auth/Realtime/operations benefits exceed migration risk;
4. never run two authoritative PostgreSQL databases or duplicate bot state merely to gain a dashboard.

## 10. Authentication and roles

### Pilot

- invitation-only;
- Boss role only;
- no public registration;
- secure short-lived access token verified by Flask;
- server verifies every request;
- private routes are not indexable.

### Target roles

- **Owner:** all views, approvals, policy, reports, user management.
- **Finance admin:** records, reconciliation, corrections, reports; no owner policy changes.
- **Staff/inputter:** submit and inspect permitted records; no consolidated company view unless granted.
- **Viewer/auditor:** read-only, scoped exports and evidence.

Authorization is enforced server-side and through database policy, not hidden buttons alone.

## 11. Realtime model

Realtime means an already-open dashboard reflects committed financial changes quickly. It does not mean trusting partial chat interpretation.

```text
WhatsApp event received
→ durable inbox
→ parsed and validated
→ source ledger write succeeds
→ PostgreSQL transaction commits
→ read model refresh/version increments
→ realtime invalidation event
→ affected dashboard query refetches
```

The invalidation event contains no sensitive finance payload. Authorization and the latest values are re-evaluated by Flask during refetch.

Targets:

- confirmed transaction visible within 10 seconds under normal operation;
- stale indicator after 60 seconds without a healthy update path;
- automatic reconnect;
- manual refresh always available;
- no optimistic display of uncommitted finance values.

## 12. Zero-rupiah operating stack

Pilot recurring incremental cost target: **Rp0**.

- Cloudflare Pages free: frontend and custom domain;
- existing Koyeb free service: Flask API and WhatsApp bot;
- existing external PostgreSQL where suitable; otherwise Supabase Free after the provider gate;
- Supabase Free may provide Auth/Realtime without creating a second financial source of truth;
- Google Drive: encrypted backup/archive;
- current Hermes installation and configured model routes: AI runtime.

Free-tier limits are treated as operating budgets. Usage alerts are created at 75% and 90%. Paid infrastructure is considered only after observed capacity or reliability evidence.

## 13. Delivery phases

The items below are one platform roadmap, not one big-bang MVP. The first production release ends at Phase 1. Every later phase needs its own acceptance gate before implementation.

### Phase 0 — Metric contract and visual prototype

Deliverables:

- metric dictionary;
- navigation and responsive shell;
- realistic local dataset derived from sanitized schema—not fabricated production claims;
- clickable Ringkasan, Dompet, Transaksi, and Proyek prototype;
- desktop and mobile review.

Exit:

- Boss can identify company position, wallet position, project condition, and urgent decisions without explanation;
- labels match actual business language;
- no ambiguity between cash, contribution, debt, receivable, and payable.

Metric contract minimum:

- exact formula;
- source fields/tables;
- inclusion and exclusion rules;
- period semantics and timezone;
- consolidation behavior;
- null/incomplete behavior;
- drill-down query;
- test fixture with expected value.

### Phase 1 — Read-only live command center

Deliverables:

- authenticated web app;
- PostgreSQL read models populated from current ledger;
- Ringkasan, Arus Kas, Dompet, Transaksi, Proyek, Hutang Antar-Dompet;
- source freshness and parity indicators;
- realtime refresh;
- exports.

Exit:

- dashboard totals equal Google Sheets/current bot reports across all three wallets for agreed periods;
- every total drills into exact contributing records;
- system remains read-only.

Launch scope is frozen to seven views: Ringkasan, Arus Kas, Dompet, Transaksi, Proyek, Hutang Antar-Dompet, and Laporan. Piutang, Tagihan, Rekonsiliasi, evidence mutation, web corrections, and AI actions remain visibly absent—not disabled placeholders.

### Phase 2 — Decision Inbox and evidence

Deliverables:

- exception queue;
- transaction evidence timeline;
- private receipt storage;
- duplicate/missing-data handling;
- correction via reversal/replacement;
- immutable audit trail.

Exit:

- unresolved chat issues appear as owned, finite dashboard work items;
- all corrections preserve originals and reasons.

Before web corrections are enabled, legacy Sheet update/delete behavior must be wrapped or replaced with reversal/replacement events. A correction acceptance test must prove that the original value, reversing event, replacement event, actor, reason, approval, and source reference all remain queryable.

### Phase 3 — Commercial finance

Deliverables:

- customers/vendors;
- receivables/invoices;
- payables/bills;
- commitments and due calendar;
- enhanced Project Cockpit;
- truthful margin/forecast metrics.

Exit:

- project profitability and future cash obligations use complete required inputs;
- absent inputs are visibly incomplete, never silently treated as zero.

### Phase 4 — Reconciliation

Deliverables:

- statement import;
- matching engine;
- reconciliation workspace;
- close blockers.

Exit:

- matching status and unresolved differences are reproducible and audited.

### Phase 5 — Hermes AI CFO

Deliverables:

- `finance-prod` Hermes profile/tool boundary;
- dashboard AI panel;
- cited natural-language analysis;
- anomaly and daily-brief tools;
- approval-gated action drafts.

Exit:

- AI answers match deterministic queries;
- every material claim cites records;
- no AI-originated direct ledger mutation.

### Phase 6 — PostgreSQL authority cutover

Deliverables:

- verified journal model;
- backup/restore drills;
- shadow parity report;
- cutover and rollback runbook;
- Sheets switched to export/projection.

Exit:

- full parity for frozen acceptance periods;
- no duplicate writer;
- restoration proven from downloaded backup bytes;
- owner approves authority cutover.

## 14. Acceptance criteria

### Product

- In a timed owner acceptance run, Boss can identify consolidated cash, all three wallet positions, period inflow/outflow, largest project movement, and unresolved internal debt from a cold dashboard open without opening WhatsApp or Sheets; each task target is 30 seconds.
- Wallet, company, project, operational, and consolidated views remain distinct.
- Chat noise becomes a finite Decision Inbox.
- Every number drills into records and source evidence.
- Mobile provides a useful executive view; desktop supports full operations.

### Data trust

- no internally transferred money counted as external income/expense;
- no inter-wallet debt counted twice in consolidation;
- corrections use reversal/replacement;
- source actor and timestamp exist for every committed event;
- stale and incomplete data are explicit;
- parity tests cover all wallets and agreed periods.

### Security

- invite-only authentication;
- role enforcement on server and database;
- no service role key in browser;
- private evidence access;
- audit events immutable to ordinary users;
- rate limiting and CSRF/JWT protections appropriate to each endpoint.

### Performance

- shell visible quickly on a normal mobile connection;
- primary overview responds within 2 seconds warm and clearly signals cold start;
- interactive feedback within 400ms or shows loading state;
- tables remain usable at expected transaction volume;
- zero horizontal page overflow at supported breakpoints.

### Phase 1 stop conditions

Phase 1 is complete only when:

- the metric contract is frozen;
- parity fixtures cover every wallet, income, expense, office-operation debit, and open/paid/cancelled inter-wallet debt path;
- dashboard totals match the compatibility source for the agreed fixtures and frozen production snapshots;
- every headline value drills down to the exact rows that compose it;
- a stale or failed source cannot silently display zero;
- unauthorized API requests fail closed;
- desktop 1440×900, laptop 1280×720, tablet, and mobile 390×844 acceptance pass;
- an already-open dashboard reflects a newly confirmed test transaction and its reversal within the stated realtime target;
- no production authority or existing WhatsApp behavior changed.

## 15. Explicit non-goals

- cloning Odoo or ERPNext;
- general accounting software for unrelated businesses;
- public customer portal in the first program;
- native mobile application;
- bank scraping or credential-based automation before a safe provider path exists;
- AI-generated ledger calculations;
- replacing the working WhatsApp flow before the web read path proves itself;
- changing production authority during the visual prototype phase.

## 16. Decisions made by the designer

These are implementation/design calls, not owner-supplied requirements:

1. Start desktop-first for operational depth, while shipping a separate mobile executive composition.
2. Use a light financial-control visual system rather than a dark-only dashboard.
3. Keep WhatsApp as primary capture and make web the control/analysis surface.
4. Extend existing Flask instead of creating another backend.
5. Reuse the active external PostgreSQL by default; use Supabase only after the database-provider gate proves it is the simplest authorized Rp0 route.
6. Delay ledger authority cutover until parity, backup, and rollback gates pass.
7. Treat AI as a cited interface over deterministic tools, never as the financial calculator or writer.
8. Remove Odoo from the primary architecture; retain no dependency on it.
