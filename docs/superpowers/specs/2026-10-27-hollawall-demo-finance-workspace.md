# Hollawall Demo Finance Workspace

**Status:** frozen implementation contract
**Owner:** Naufal Spurnomo
**Mode:** browser-local demo; no production ledger writes

## Objective

Turn the current read-only showcase into a complete, realistic finance workspace for UI/UX validation. The demo must let the Boss and finance admin add, review, correct, and remove demo records while preserving the distinctions that will later protect real money.

## Company model

| Wallet | Companies |
|---|---|
| CV HB | Holla, Hojja |
| TX SBY | Texturin Surabaya |
| TX Bali | Texturin Bali |

A project belongs to exactly one company and one compatible wallet. `Operasional Kantor` is a separate activity scope, never a project, company, portfolio, or project status. Office spending may select any wallet.

## Safety model

- All mutations stay in browser `localStorage` under a versioned demo key.
- Every page displays `Data demo` and provides `Reset data demo`.
- The demo never calls a production write endpoint, Google Sheets write path, or finance ledger mutation path.
- Mutations create an audit event with action, entity type, entity ID, timestamp, and summary.
- Financial values are finite non-negative integers in rupiah.
- Project names are unique per company, not globally.
- A project cannot move to a company incompatible with its wallet.
- Office transactions cannot reference a project.
- Project transactions require an active or completed project and inherit its company/wallet.
- Internal wallet transfers are outside this iteration and never masquerade as income/expense.
- Deleting demo data requires confirmation. Reset is explicit and recoverable by reseeding.

## Demo entities

### Project

`id`, `name`, `company`, `wallet`, `status`, `started_on`, `completed_on`, `client`, `contract_value`, `notes`, timestamps.

Statuses: `planned`, `active`, `completed`.

### Transaction

`id`, `date`, `direction`, `amount`, `scope`, `wallet`, `company`, optional `project_id`, optional `office_category`, `notes`, timestamps.

Scopes:

- `project`: project is required; wallet/company come from the project.
- `office`: category and wallet are required; project is absent.

### Audit event

Append-only local record for create/update/delete/reset actions. This is product-behavior proof, not a production audit ledger.

## Navigation

- Ringkasan
- Arus Kas
- Dompet
- Transaksi
- Proyek
- Operasional Kantor
- Hutang Internal
- Laporan

Global demo actions provide `Tambah transaksi`, `Tambah proyek`, and `Catat biaya kantor`.

## Project command center

- Default year is the newest year with data.
- The year navigator has keyboard-accessible previous/next controls and a direct year rail.
- Header format: `2024 · 120/120 selesai`.
- Summary separates `Selesai`, `Aktif`, and `Direncanakan`.
- A selected year controls every count, filter, chart, and list below it.
- Candles include active and completed projects. Active candles use continuous green→yellow→orange→red age color. Completed candles use a distinct completed treatment and stop on their completion date.
- Chart legend explains candle, age color, completed treatment, and white transaction range.
- Clicking or keyboard-activating a candle opens exact project transactions.
- Filters: company, status, search. Pagination stays stable across equivalent rerenders.
- Empty years/statuses explain what is empty and how to add data.

## CRUD flows

### Add/edit project

Name → company → compatible wallet (derived and displayed) → status → dates → optional client/value/notes → validation preview → save.

Completion requires `completed_on`; non-completed projects have no completion date.

### Add/edit transaction

Date → direction → activity scope.

Project scope: choose project; company/wallet are derived and locked.
Office scope: choose wallet and category; project is absent and company is `Kantor` only in office views.

Amount and notes are required. Save updates every derived total immediately.

### Delete

Delete is available only in demo mode, requires confirmation, and records an audit event. Deleting a project with transactions is blocked until its transactions are removed or reassigned.

## Reports

Filters:

- report content: overview, projects, office operations, transactions;
- date range;
- wallet;
- company;
- project;
- direction;
- project status.

Preview and PDF use one derived `ReportModel`. The PDF includes identity, demo watermark, generated timestamp, filters, totals, and tabular detail. PDF rows and totals must exactly match the preview. Export uses a dynamically loaded PDF library so normal dashboard startup remains small.

## Copy rules

- Use short professional Indonesian.
- No generic AI prose, marketing language, unexplained English, or decorative labels.
- Use `Arus kas bersih`, not profit, when cost/revenue completeness is unknown.
- Use `Operasional Kantor` only for the separate office-spending scope.
- Never use `Operasional` as a project portfolio, company, project type, or project label.

## Acceptance

1. Demo CRUD persists through reload and resets cleanly.
2. Wallet/company/scope invariants cannot be violated through UI or store methods.
3. Project year completion ratios are exact for seeded 2024/2025 data.
4. Every project and report filter changes the same visible dataset and counts.
5. PDF model equals preview model; generated bytes start with `%PDF`.
6. No project UI contains the word `Operasional`.
7. Keyboard, mouse, drag, resize, overflow, empty data, long names, and malformed persisted state are covered.
8. Chromium: 1024×768 through 1920×1080. WebKit: 1024×768, 1440×900, 1512×982. Mobile smoke: 390×844.
9. Zero serious/critical accessibility findings; no console errors or failed asset/API requests.
10. Production deployment remains blocked until owner approves the visual result and Rumahweb authentication succeeds.
