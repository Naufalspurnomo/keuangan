# Hollawall Project Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver authoritative production projects plus branded A5 Sales Orders, installment invoices, and transaction-backed receipts without changing Google Sheets cash authority.

**Architecture:** PostgreSQL owns project/document workflow, numbering, immutable snapshots, allocations, audit events, and issued PDF bytes. Google Sheets remains cash authority and `financial_ledger` remains its projection. React adds a Documents tab to project detail and uses same-origin Rumahweb proxies; both write gates default OFF.

**Tech Stack:** Python 3.11, Flask, PostgreSQL/psycopg, ReportLab, React 18, TypeScript, Vite, Vitest, Testing Library, PHP proxy, Playwright browser acceptance.

**Spec:** `docs/superpowers/specs/2026-11-03-project-documents-design.md`

## Global Constraints

- No issued document or posted cash record is hard-deleted or silently edited.
- Document issuance never creates a Google Sheets cash row.
- Receipt issuance requires reverified project-income projection rows.
- IDR is integer rupiah; decimal quantities use fixed precision and half-up rounding.
- Tax defaults to `0%`; never infer legal tax treatment.
- Official numbers are allocated server-side only during issuance.
- All new write gates default OFF.
- Production UI/PDF contains no demo, DATA LIVE, or architecture chatter.
- Preserve existing routes, finance flows, Presensi, theme, and responsive shell.
- Production website must expose the complete safe operational lifecycle; backend-only commands do not satisfy acceptance.
- Project UI supports create, read/detail, update, status transition, and archive/cancel with audit. Project hard delete is forbidden once documents or transactions exist.
- Posted Google Sheets cash rows are not silently edited or hard-deleted. Transaction UI maps “edit/delete” intent to explicit auditable correction, reversal, or void workflows while preserving the original authoritative row.
- Draft documents support create/read/update; issued documents are immutable and use void/revision actions instead of delete/edit.
- Every mutation UI must provide loading, success, validation, conflict, retry-safe idempotency, stale-version, and write-gate states; destructive lifecycle actions require explicit confirmation.
- Responsive desktop/mobile UI, keyboard navigation, focus management, accessible labels, empty states, and deterministic readback are acceptance requirements.

## Review Focus

- Concurrent issue/retry must allocate one number and one immutable artifact.
- Project aliases/legacy projected identities must not split one production project or bind a wrong project.
- Receipt allocation must fail if a Sheets-backed income row disappears or is already fully allocated.
- Long line items/Indonesian text/images must paginate within A5 without clipping.
- Zero-data state must contain no fabricated customer, price, signature, document, or tax.

---

### Task 1: PostgreSQL project/document schema

**Files:**
- Create: `dashboard_api/migrations/003_project_documents.sql`
- Create: `services/project_document_repository.py`
- Test: `tests/project_document_repository_test.py`
- Test: `tests/project_document_postgres_integration_test.py`

**Interfaces:**
- Produces `ProjectDocumentRepository` with project CRUD, draft lifecycle, atomic numbering, immutable issuance, void/revise, artifact storage, allocation locking, and audit replay.

- [ ] Write failing repository and PostgreSQL constraint tests.
- [ ] Run focused tests and confirm RED.
- [ ] Add normalized tables for projects, scopes, documents, lines, allocations, counters, events, artifacts, and issuer profile.
- [ ] Add immutability/transition constraints and indexes.
- [ ] Implement repository with idempotency and optimistic locking.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit `feat: add project document persistence`.

### Task 2: Domain calculations and project/document service

**Files:**
- Create: `services/project_documents.py`
- Create: `services/project_document_models.py`
- Modify: `services/dashboard_transaction_service.py`
- Test: `tests/project_document_service_test.py`
- Test: `tests/project_document_reconciler_test.py`

**Interfaces:**
- Consumes `ProjectDocumentRepository`.
- Produces `ProjectDocumentService` commands/results and `calculate_document_totals()`.

- [ ] Write failing calculation, project creation, invoice, receipt-allocation, void, revision, and replay tests.
- [ ] Run focused tests and confirm RED.
- [ ] Implement exact decimal/IDR rules and lifecycle commands.
- [ ] Create one Sales Order draft atomically with project creation.
- [ ] Revalidate receipt source rows and exclude expense/office/internal-transfer rows.
- [ ] Permit transaction writes to reference stable project UUID while preserving legacy identity validation.
- [ ] Run focused and transaction regression tests.
- [ ] Commit `feat: add project document lifecycle`.

### Task 3: A5 PDF renderer and immutable artifact issuance

**Files:**
- Create: `services/project_document_pdf.py`
- Create: `assets/project-documents/` branded assets or copy existing verified logo/fonts
- Test: `tests/project_document_pdf_test.py`

**Interfaces:**
- Produces `render_project_document_pdf(snapshot, issuer_profile) -> bytes` and renderer version.

- [ ] Write failing A5 dimension, branding, content, pagination, watermark, and deterministic-byte tests.
- [ ] Run focused tests and confirm RED.
- [ ] Implement branded ReportLab renderer with continuation pages and safe image handling.
- [ ] Store exact PDF bytes/hash atomically during issue.
- [ ] Render test PDFs, re-extract text, rasterize, and visually inspect.
- [ ] Commit `feat: render immutable A5 project documents`.

### Task 4: Flask APIs and Rumahweb proxy

**Files:**
- Create: `dashboard_api/project_document_routes.py`
- Modify: `dashboard_api/__init__.py`
- Modify: `main.py`
- Create: `deploy/rumahweb-admin/api/projects.php`
- Create: `deploy/rumahweb-admin/api/documents.php`
- Modify: `deploy/rumahweb-admin/config.example.php`
- Test: `tests/project_document_routes_test.py`
- Test: `tests/rumahweb_admin_document_proxy_test.py`

**Interfaces:**
- Produces authenticated project/document JSON APIs and PDF download through allowlisted same-origin proxies.

- [ ] Write failing auth, CSRF, gate, idempotency, If-Match, envelope, PDF, and proxy tests.
- [ ] Run focused tests and confirm RED.
- [ ] Add list/create/update/issue/void/revise/download endpoints and response contracts.
- [ ] Add owner-only project create/read/update/status/archive contracts and auditable transaction correction/reversal contracts; never expose hard-delete for posted cash or issued documents.
- [ ] Add feature-gate health/readiness fields; default OFF.
- [ ] Add hardened PHP proxy allowlists, body limits, no-store, and binary PDF handling.
- [ ] Run focused and existing route/proxy regression tests.
- [ ] Commit `feat: expose project document APIs`.

### Task 5: Frontend data contracts and project detail shell

**Files:**
- Create: `dashboard/src/projectDocuments.ts`
- Create: `dashboard/src/projectDocumentApi.ts`
- Create: `dashboard/src/ProjectDetailWorkspace.tsx`
- Create: `dashboard/src/ProjectPresensiPanel.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/ProjectTransactionsWorkspace.tsx` or replace its imports
- Test: `dashboard/src/projectDocuments.test.ts`
- Test: `dashboard/src/projectDocumentApi.test.ts`
- Test: `dashboard/src/ProjectDetailWorkspace.test.tsx`

**Interfaces:**
- Consumes backend contracts.
- Produces URL-driven three-tab project shell and typed document/project state.

- [ ] Write failing pure calculation/validation/API/routing/tab tests.
- [ ] Run focused tests and confirm RED.
- [ ] Implement types, zero-value factories, calculations, validation, API wrapper, and routing.
- [ ] Replace local/demo project mutations with live owner-only project lifecycle APIs and authoritative readback.
- [ ] Model posted transaction correction/reversal explicitly; do not present unsafe silent edit/delete semantics.
- [ ] Extract Presensi without behavior change; add Dokumen tab and keyboard navigation.
- [ ] Run focused and existing App/Presensi tests.
- [ ] Commit `feat: add project document workspace`.

### Task 6: Document center, composer, and A5 preview

**Files:**
- Create: `dashboard/src/ProjectDocumentsWorkspace.tsx`
- Create: `dashboard/src/ProjectDocumentComposer.tsx`
- Create: `dashboard/src/ProjectDocumentPreview.tsx`
- Create: `dashboard/src/project-documents.css`
- Modify: `dashboard/src/main.tsx`
- Modify: `dashboard/src/hollawall-brand.css`
- Test: `dashboard/src/ProjectDocumentsWorkspace.test.tsx`
- Test: `dashboard/src/ProjectDocumentComposer.test.tsx`

**Interfaces:**
- Consumes project/document API and pure domain functions.
- Produces list/composer/preview/issue/void/revise/download UI.

- [ ] Write failing empty/loading/error/permissions/item CRUD/calculation/validation/dirty-state/accessibility tests.
- [ ] Run focused tests and confirm RED.
- [ ] Implement concise document center and responsive composer.
- [ ] Implement project create/edit/status/archive and transaction create/correct/reverse UI states with confirmations, optimistic-lock conflicts, idempotent retry, and authoritative readback.
- [ ] Implement semantic A5 preview, image/signature controls, totals, and issued-state actions.
- [ ] Verify keyboard/focus/aria behavior and 44 px mobile controls.
- [ ] Commit `feat: build project document composer`.

### Task 7: Professional dashboard copy and visual polish

**Files:**
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/FinancePages.tsx`
- Modify: `dashboard/src/ProjectCommandCenter.tsx`
- Modify: `dashboard/src/ProjectTransactionsWorkspace.tsx`
- Modify: `dashboard/src/ReportsWorkspace.tsx`
- Modify: `dashboard/src/App.live.test.tsx`

**Interfaces:**
- Preserves all existing behavior while simplifying labels and action placement.

- [ ] Add regression assertions that production routes contain no demo/DATA LIVE/architecture chatter.
- [ ] Run test and confirm RED.
- [ ] Remove repeated mode labels, global write warning, redundant descriptions, and stale `DemoApp` naming.
- [ ] Keep write-disabled explanations adjacent to disabled actions only.
- [ ] Run full frontend tests/build and confirm GREEN.
- [ ] Commit `refactor: sharpen finance dashboard UX`.

### Task 8: Full verification and independent review

**Files:**
- Modify: `tests/browser/dashboard_visual_acceptance_test.py`
- Create: `artifacts/project-documents-verification/`

**Interfaces:**
- Produces verified test, screenshot, PDF, and review evidence.

- [ ] Run full Python regression.
- [ ] Run full frontend tests/typecheck/build.
- [ ] Apply migration in an isolated PostgreSQL verifier and run concurrency tests.
- [ ] Exercise project → Sales Order → invoice → income → receipt → expense flow with controlled fixtures.
- [ ] Verify no document command changes Sheets transaction count except explicit income/expense writes.
- [ ] Capture 390, 768, 1024, 1440 px light/dark screenshots and inspect pixels.
- [ ] Rasterize and inspect A5 PDFs; assert dimensions/text/hash.
- [ ] Run fresh independent whole-branch review; resolve P0/P1.
- [ ] Commit `test: verify project document workflow`.

### Task 9: Production rollout and rollback proof

**Files:**
- Update: deployment evidence and `STORAGE.md`

**Interfaces:**
- Produces production deployment with zero-data baseline preserved and verified rollback artifacts.

- [ ] Merge reviewed branch.
- [ ] Deploy Koyeb code with all new writes OFF.
- [ ] Apply migration and read back every table/index/trigger.
- [ ] Build and atomically deploy Rumahweb release with backup/readback.
- [ ] Enable project/document writes only; execute controlled E2E and clean/void test state.
- [ ] Enable transaction writes only after shared project reference path passes.
- [ ] Verify WhatsApp ingress, dashboard create, Sheets authority, PostgreSQL projection, snapshot, receipt, and reply.
- [ ] Verify fresh-zero baseline contains no synthetic financial rows.
- [ ] Upload cloud-eligible evidence and verify remote hash/readback.
- [ ] Record exact rollback paths and final acceptance.
