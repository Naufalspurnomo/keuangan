# Brand-aware Commercial Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce brand-accurate, business-correct Quotations, Sales Orders, Invoices, and Receipts for Hollawall, Hojja, and Texturin from one authoritative template policy and semantic commercial model.

**Architecture:** Preserve the existing quantity × unit-price monetary spine and immutable issued-document lifecycle. Add a canonical brand policy, structured line metadata, authoritative server normalization, explicit render/payment identity, brand-aware React preview, and immutable sent-quotation artifacts. Historical generic/Canva records remain compatible through legacy fallback.

**Tech Stack:** React/TypeScript/Vitest, Flask/Python/pytest, PostgreSQL JSONB, ReportLab PDF, Playwright/raster visual comparison.

**Spec:** `docs/superpowers/specs/2026-11-17-brand-commercial-documents-design.md`

## Global Constraints

- Existing issued document bytes never change.
- Sent/accepted commercial terms are revised, never mutated.
- Explicit template/payment profile wins; heuristics are legacy fallback only.
- Tax remains nullable.
- Area raw precision ≤8 decimals; billed precision ≤4; default half-up two decimals.
- Missing payment profile blocks send/issue, not draft save.
- Browser preview and server PDF consume equivalent policy/view-model semantics.
- No new production runtime on this VPS.

## Review Focus

- Legacy lines without metadata still calculate, load, Deal, and render.
- Width/height unit conversion and manual billed-area override never silently change money.
- Fixed-artwork original/agreed prices do not double-discount.
- Deposit text, structured deposit, invoice, and remaining balance cannot disagree.
- Brand/payment identity cannot drift between editor, API, snapshot, and PDF.

---

### Task 1: Canonical template policy and semantic calculation model

**Files:**
- Create: `dashboard/src/commercialDocumentPolicy.ts`
- Create: `services/commercial_document_policy.py`
- Modify: `dashboard/src/projectDocuments.ts`
- Modify: `services/project_documents.py`
- Test: `dashboard/src/commercialDocumentPolicy.test.ts`
- Test: `dashboard/src/projectDocuments.test.ts`
- Test: `tests/project_document_service_test.py`
- Create: `tests/fixtures/commercial_document_policies.json`

**Interfaces:**
- Produces: `commercialPolicy(templateKey)`, `normalizeCommercialLine(line, policy)`, Python equivalents, parity fixture.

- [ ] Write failing policy parity, Hollawall area, Hojja fixed-artwork, Texturin PPM, precision, mismatch tests.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement minimal policy and normalization functions; legacy lines remain unchanged.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 2: Persistence, explicit identities, and lifecycle invariants

**Files:**
- Create: additive SQL migration(s) under `dashboard_api/migrations/`
- Modify: `services/project_document_repository.py`
- Modify: `dashboard_api/project_document_routes.py`
- Modify: `dashboard/src/projectQuotationApi.ts`
- Modify: `dashboard/src/projectDocumentApi.ts`
- Test: repository, migration, route, API normalization suites.

**Interfaces:**
- Consumes semantic line metadata from Task 1.
- Produces preserved `commercial_meta`, explicit template/payment identity, template/renderer versions, immutable sent artifact contract.

- [ ] Write failing round-trip and invariant tests.
- [ ] Run targeted tests and confirm RED.
- [ ] Add migration and repository/API preservation.
- [ ] Add sent artifact and official-number allocation behavior without rewriting legacy rows.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 3: Brand-correct editor and preview

**Files:**
- Create: focused semantic line editor/preview components as needed under `dashboard/src/`.
- Modify: `ProjectQuotationPanel.tsx`, `ProjectDocumentComposer.tsx`, `ProjectDocumentPreview.tsx`, `finance-workspace-v2.css`.
- Test: quotation/composer/preview tests.

**Interfaces:**
- Consumes policy and normalized view model.
- Produces brand-specific fields, formulas, terms, deposit presentation, and live preview.

- [ ] Write failing tests for all three brand workflows and invalid/mismatch states.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement semantic field groups and brand preview.
- [ ] Add keyboard/mobile/accessibility behavior.
- [ ] Run targeted tests/build and confirm GREEN.
- [ ] Commit.

### Task 4: Server PDF and immutable quotation artifacts

**Files:**
- Modify: `services/project_document_pdf.py`, repository/routes as required.
- Add reference/golden fixtures under tests/artifacts policy-compliant paths.
- Test: `tests/project_document_pdf_test.py` and quotation download tests.

**Interfaces:**
- Consumes explicit template and normalized semantic snapshot.
- Produces brand-correct canonical PDF and byte-stable sent quotation downloads.

- [ ] Write failing content, formula, page-size, identity, determinism, and golden-raster tests.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement renderer updates and artifact persistence.
- [ ] Run targeted tests and confirm GREEN.
- [ ] Commit.

### Task 5: End-to-end verification and production delivery

**Files:**
- Tests/fixtures only if a verified gap appears.

- [ ] Run migration idempotency/startup health tests.
- [ ] Run all backend tests.
- [ ] Run dashboard install, full tests, typecheck, build.
- [ ] Render PDF/raster matrix for Hollawall, Hojja, Texturin and visually compare to references.
- [ ] Run browser desktop/mobile matrix for each brand and pricing mode.
- [ ] Run diff check, secret scan, independent review.
- [ ] Open PR, verify exact SHA and all checks, merge with protection restored.
- [ ] Verify Production Gate, Rumahweb deploy, release manifests, functional data, preview pixels, and downloaded PDF bytes.
