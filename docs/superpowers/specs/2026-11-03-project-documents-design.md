# Hollawall Project Documents Design

## Intent

Upgrade the production Hollawall finance dashboard so an administrator can create a project before cash activity, prepare branded commercial documents, issue installment invoices, and generate receipts from verified income without duplicating the Google Sheets cash ledger.

The supplied spreadsheet is a content reference, not a visual template. The production UI and PDFs use Hollawall branding, clear hierarchy, and concise Indonesian copy.

## Goals

- Add an authoritative production project record independent of transaction activity.
- Create one editable Sales Order draft automatically for every new project.
- Support invoices for `DP`, `PROGRESS`, and `FINAL` installments.
- Create receipts only from verified project-income transactions.
- Keep project expenses separate from customer billing while showing project cash contribution.
- Export immutable, branded A5 portrait PDFs.
- Support draft editing, issuance, voiding, and revision with complete audit history.
- Remove demo/source-status chatter and redundant explanatory copy from the dashboard.
- Preserve the existing WhatsApp → Google Sheets → PostgreSQL → Dashboard transaction flow.

## Non-goals

- Full double-entry accounting, tax filing, customer CRM, procurement, inventory, payroll, or general-ledger replacement.
- Automatic legal tax assumptions.
- Automatic final issuance without an administrator review.
- Reconstructing historical receivables from old cash descriptions.

## Authority boundaries

- **PostgreSQL project records:** authoritative project/customer/commercial metadata.
- **PostgreSQL project documents:** authoritative draft/issued/void/revision lifecycle, numbering, immutable snapshots, allocations, audit events, and PDF bytes.
- **Google Sheets:** authoritative cash transactions only.
- **PostgreSQL `financial_ledger`:** rebuildable projection of Google Sheets transactions.
- Issuing Sales Orders or invoices never creates cash transactions.
- A receipt can be issued only against a still-verifiable project-income ledger row.
- Project expenses affect recorded cash contribution; they never increase billable totals.

## Production project record

A project has:

- stable UUID;
- name, client name/company/address/contact;
- issuer key and wallet/company mapping;
- status: `planned`, `active`, `completed`, `cancelled`;
- start and optional completion dates;
- contract notes;
- created/updated actor, timestamps, and optimistic `lock_version`.

Creating a project creates exactly one Sales Order draft atomically. No Google Sheets row is created.

A transaction write may reference either an authoritative project UUID or a legacy projected project identity. New production UI writes use the UUID.

## Document lifecycle

### Types

- `sales_order`
- `invoice`
- `receipt`

### Statuses

- `draft`
- `issued`
- `void`
- `superseded`

Drafts are editable and have no official number. Issuance allocates a number atomically, freezes an immutable JSON snapshot, renders/stores exact PDF bytes, stores content hash and renderer version, and writes an audit event.

Issued documents cannot be edited. Revision creates a new draft linked to the original. Issuing the revision marks the previous version superseded. Void requires a reason; numbers are never reused.

### Invoice kinds

- `DP`
- `PROGRESS`
- `FINAL`

Invoices may be created for planned or active projects. FINAL is the residual commercial amount and is unique per project unless the previous final invoice is void. Issuance does not create a cash row or complete a project.

### Receipt rules

A receipt is created from one or more verified project-income ledger rows for the same project and issuer. Allocation may not exceed the authoritative income amount after existing allocations. Issuance does not create another cash row.

## Calculations

All IDR values are integer rupiah. Quantities/area use decimal fixed precision. Rounding is half-up to one rupiah.

For each line:

```text
line_gross = round(quantity × unit_price)
line_discount = round(line_gross × line_discount_percent / 100)
line_total = line_gross - line_discount
```

Document:

```text
subtotal = sum(line_total)
document_discount = fixed amount OR percentage, never both
taxable_base = subtotal - document_discount
tax = round(taxable_base × tax_percent / 100)
total = taxable_base + tax
```

Defaults:

- tax `0%` until legal/tax profile is confirmed;
- discount `0`;
- 50% DP and final residual are suggested, not silently issued;
- invoice due date defaults to seven days;
- Sales Order validity defaults to fourteen days.

The 2% tax seen in the reference is not treated as a rule.

## Numbering

Per issuer, document type, and Jakarta calendar year:

- `SO/HW/YYYY/000001`
- `INV/HW/YYYY/000001`
- `KWT/HW/YYYY/000001`

Drafts use UUIDs. Sequence allocation happens only during issuance under a database lock. Gaps are acceptable; duplicates and reuse are forbidden.

## Issuer profile

Version one ships with a configurable `CV Holla Berkreasi` profile using verified information already present in the supplied reference/project assets. Tax identity and bank destination remain optional fields. Issuance is blocked only when required display identity is missing; tax defaults to zero rather than guessed.

Issuer profile is server configuration, never browser-only authority.

## A5 document design

- A5 portrait, 148 × 210 mm, approximately 8 mm safe margins.
- White paper independent of dashboard dark mode.
- Hollawall transparent logo, Montserrat, navy body ink, orange/cyan accents.
- Header: logo, type, official number or DRAFT, issue/due/validity date.
- Client/project metadata.
- Optional project image.
- Item table: description, quantity/area, unit, unit price, discount, total.
- Totals block.
- Notes/payment terms.
- Prepared-by/client signature slots.
- Page number and reference footer.
- Automatic continuation pages; repeat table header.
- DRAFT, VOID, or SUPERSEDED watermark where applicable.
- Issued PDF bytes remain byte-identical after template upgrades.

## Dashboard UX

Keep the seven global sidebar destinations. Documents live inside project detail.

Project detail tabs:

- Transaksi
- Presensi
- Dokumen

Canonical hash routes retain the current routing system:

```text
#projects?project=<projectId>&tab=transactions
#projects?project=<projectId>&tab=presensi
#projects?project=<projectId>&tab=documents
#projects?project=<projectId>&tab=documents&document=new&type=sales-order
#projects?project=<projectId>&tab=documents&document=<documentId>
```

The documents panel provides:

- concise status/total strip;
- document list with type, number/status/date/total;
- primary actions to create invoice or receipt;
- automatic Sales Order draft shown first;
- composer and live A5 preview;
- issue/void/revise/download actions where allowed.

Desktop uses editor + sticky preview. Tablet stacks. Mobile uses 44 px Edit/Pratinjau segmented controls and item cards.

No production screen says demo, DATA LIVE, workspace live, or repeats architecture explanations. Disabled actions explain only the immediate reason.

## Security and correctness

- Owner session and CSRF required.
- Separate document feature gate, default OFF.
- All state-changing requests require `Idempotency-Key` and `If-Match`/expected version.
- Issuance, void, revision, and receipt allocation run in PostgreSQL transactions with locks.
- Audit events are append-only.
- PDFs and uploads have explicit size/MIME limits.
- Receipt allocation revalidates authoritative ledger identity at issue time.
- No hard deletion of issued documents.

## Rollout

1. Deploy code with transaction/document writes OFF.
2. Apply/read back PostgreSQL migration.
3. Verify zero-data dashboard and document empty state.
4. Enable document/project writes.
5. Create one controlled project/document E2E, verify PDF, then delete only draft test state or void issued test state.
6. Enable existing transaction writes only after the shared project path passes.
7. Preserve the fresh-zero financial ledger and encrypted pre-reset backup.

## Acceptance

- A project can be created with no transaction and gets one Sales Order draft.
- Invoice issuance changes no Sheets balance/count.
- Expenses change project cash contribution, not billed totals.
- A receipt cannot be issued without verified income.
- Retries create no duplicates.
- Issued content/PDF remains immutable and downloadable.
- A5 dimensions and visual output pass image inspection.
- Project Documents work at 390, 768, 1024, and 1440 px with keyboard navigation.
- No demo/bullshit copy appears in the production dashboard or PDFs.
- Existing WhatsApp/Sheets/dashboard transaction behavior remains regression-green.
