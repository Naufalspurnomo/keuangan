# Brand-aware commercial documents — design

## Intent

Hollawall finance must produce quotations and invoices that preserve the real visual identity, commercial language, calculations, and lifecycle of each business unit. The output must not be a generic Hollawall preview with different text.

Source of truth:

- `projects/keuangan-agent-evolution/work/template-intake/hollawall/hollawall-reference.pdf`
- `.../hojja/hojja-reference.pdf`
- `.../texturin-a/texturin-a-reference.pdf`
- `.../texturin-b/texturin-b-reference.pdf`

The original PDFs are visual references, not unquestioned accounting truth. Their arithmetic and semantic inconsistencies must be corrected.

## Users and success

Finance/admin staff create a document from a project without translating the brand's business model into generic quantity/price fields. The editor explains what is billed, the live preview matches the downloaded PDF, and a sent/issued artifact stays byte-stable.

Success means:

1. Holla, Hojja, and Texturin visibly differ in editor preview and PDF.
2. Each brand exposes the correct pricing model and terminology.
3. Every formula reconciles before save/send/issue.
4. The same authoritative template identity drives browser preview and server PDF.
5. Historical generic/Canva records still load.
6. Existing issued PDF artifacts never change.

## Non-goals

- Pixel-copy known mistakes from old PDFs.
- Replace the existing document lifecycle, quotation revision model, or canonical PDF download.
- Infer tax when it is not supplied.
- Force every brand into area pricing.
- Turn browser print into the authoritative PDF path.

## Anti-goals

The feature fails if:

- Hojja is billed per m² only because Holla is.
- `QTY/LUAS` is stored as one ambiguous number.
- width × height and billed area disagree silently.
- an Invoice uses quotation-validity language without explicit pro-forma semantics.
- payment terms say one DP while Deal creates another.
- preview and downloaded PDF show different brands or totals.
- a sent quotation can produce different PDF bytes after a renderer update.

## Evidence-led brand contracts

### Hollawall

- Visual: near-A5 portrait, turquoise/orange mural-studio identity, Futura/Roboto/Century Gothic family, legal/contact header, project images, organic footer art.
- Pricing mode: `area_rate`.
- Inputs: description, optional width/height, raw derived area, billed area, price per m², optional line discount, image.
- Formula: `billed_area_m2 × unit_price_per_m2`, then discounts.
- Table labels: `DESCRIPTION`, `AREA`, `HARGA/M²`, `JUMLAH`.
- Default acceptance payment: DP 30% of grand total.
- Quotation validity: 7 days unless explicitly changed.
- Display title follows lifecycle: Quotation before acceptance, Invoice/DP Invoice only when created as an invoice. Do not preserve the old hybrid title conflict.

### Hojja

- Visual: A4 portrait, ivory/sage/taupe, Open Sauce One, ornamental wordmark, artwork image and sparse gallery-like layout.
- Pricing mode: `fixed_artwork`.
- Inputs: description, optional artwork dimensions, display quantity, original price, agreed/final fixed price, artwork image.
- Formula: final fixed unit/line price × monetary quantity; dimensions are technical metadata, not the billing basis.
- Table labels: `Description`, `Qty`, `Total`.
- Default acceptance payment: DP 50% of grand total.
- Original price may render struck-through when a revised price exists.
- Legal payment identity must remain explicit when HOJJA routes payment to CV Holla Berkreasi.

### Texturin

- Visual: A4 portrait, white/greige/charcoal, HK Grotesk, lowercase wordmark, script signature asset, optional technical dimension diagram, red discount treatment.
- Pricing mode: `ppm_area`.
- `PPM` is the brand display label for canonical `unit_price_per_m2`.
- Inputs: description, width/height, raw derived area, billed area, PPM, optional discount, diagram.
- Formula: `billed_area_m2 × unit_price_per_m2`.
- Table labels: `NO.`, `DESCRIPTION`, `PPM`, `LUAS`, `TOTAL`; never one persisted `QTY/LUAS` field.
- Default acceptance payment/signature fee: 30% of grand total.
- Default validity: 14 days unless explicitly changed.
- Terms include ready-to-paint surface, separately billed repairs, handmade/sample variance, and post-completion revision charges.
- Known old arithmetic error (`200,000 × 6 m² = 600,000`) must fail validation; correct result is `1,200,000`.

## Area and rounding policy

Store both:

- `raw_area_m2`: Decimal result of normalized width × height.
- `billed_area_m2`: the quantity used for money.
- `area_rounding`: `exact`, `half_up`, `truncate`, or `manual_override`.
- `area_override_reason`: required for manual override.

Default for new Holla/Texturin lines: half-up to two decimal places for billed area. Raw area remains available for audit. Existing legacy lines without metadata keep their stored quantity and are marked legacy; no silent backfill.

Frontend and backend accept at most four fractional digits in canonical quantity/area fields.

## Canonical data model

Keep existing monetary fields for compatibility:

- `description`
- `quantity`
- `unit`
- `unit_price`
- `line_discount_percent`

Add semantic metadata:

```json
{
  "pricing_mode": "area_rate | ppm_area | fixed_artwork | fixed_fee | legacy_generic",
  "width": "decimal|null",
  "height": "decimal|null",
  "dimension_unit": "mm | cm | m|null",
  "raw_area_m2": "decimal|null",
  "billed_area_m2": "decimal|null",
  "area_rounding": "exact | half_up | truncate | manual_override|null",
  "area_override_reason": "string|null",
  "display_quantity": "decimal|null",
  "original_price": "integer|null",
  "asset_ref": "string|null"
}
```

Quotation lines can preserve this in JSONB immediately. Add nullable/default-empty `commercial_meta JSONB` to relational project-document lines so semantics survive Deal handoff, Sales Order, invoice, snapshot, and PDF rendering.

Document/quotation render identity:

- canonical `template_key`: `hollawall | hojja | texturin`
- `template_version`
- `renderer_version`
- explicit legal issuer/profile
- `deposit_rate`, `deposit_basis`, `deposit_amount`
- `valid_until`
- structured payment/bank/signature policy

Absent metadata means `legacy_generic` and must continue to work.

## Authoritative template-policy registry

Create one shared policy contract represented equivalently in TypeScript and Python, with fixture tests proving parity. It contains:

- canonical company/brand mappings
- pricing mode and field labels
- page size/design key
- default DP/signature fee
- default validity
- bank/legal identity profile
- terms blocks
- allowed document semantics
- renderer/template version

Explicit stored `template_key` wins. Heuristic company/issuer matching is historical fallback only.

## Editor behavior

- Header shows the brand/template as immutable project context, not a disabled generic input.
- Fields change by pricing mode.
- Area mode: width/height optional, computed raw area visible, billed area editable only through an explicit override flow, price labelled `Harga/m²` or `PPM`.
- Fixed artwork: dimensions remain descriptive; original and agreed price are separate; quantity does not mutate the displayed dimensions.
- Each line shows immediate line total and formula explanation.
- Live totals and DP/signature fee update immediately.
- Validation focuses the exact invalid field and never falls back to Rp0.
- Deal defaults to the brand policy and warns/blocks when free-text payment terms conflict.

## Preview and PDF

- Browser preview and server PDF consume the same normalized commercial-document view model.
- Preview must use correct page ratio, logo, colors, labels, bank/legal identity, terms, images, and signature treatment.
- Canonical export remains server-generated PDF.
- Golden/raster visual fixtures compare each new renderer against the original reference at stable regions, while allowing corrected text/formulas.
- Existing issued artifacts remain unchanged.
- When a quotation is marked sent, persist an immutable PDF artifact with SHA-256, template version, renderer version, and exact bytes. Revisions produce new artifacts.

## Validation gates

- title/lifecycle semantics agree
- explicit template identity valid
- dimensions normalize correctly
- raw and billed area reconcile with rounding policy
- line totals, subtotal, discount, tax, total reconcile
- DP/signature fee basis and amount reconcile
- bank profile matches brand/legal entity
- payment terms and Deal DP agree
- sent quotation artifact is byte-identical on subsequent downloads
- legacy records still load and render

## Migration and compatibility

- Additive migration only.
- Existing API version and payload names remain.
- Old lines without metadata remain valid.
- Backfill only unambiguous template identities; never rewrite historical money.
- New quotation revisions are required to change sent/accepted commercial terms.
- Update schema health hashes and migration manifests as required by repository readiness checks.

## Verification

1. RED/GREEN tests for one vertical slice at a time.
2. Numeric replay: Holla area, Hojja fixed artwork, Texturin PPM, discounts, DP.
3. API/persistence round-trip through quotation → Deal → Sales Order → invoice → issued snapshot.
4. Brand policy parity tests TypeScript/Python.
5. PDF content/page size/determinism plus golden raster comparison.
6. Browser preview desktop/mobile for all brands.
7. Full test/typecheck/build/diff/secret gates.
8. Deploy exact SHA and read back both release manifest and production pixels/PDF bytes.

## Resolved lifecycle and authority decisions

- Brand-aware rendering applies to quotation, Sales Order, all invoice kinds, and receipt. Each document type retains its own semantic title and content hierarchy.
- Accepted quotations are immutable. A commercial change creates a revision. Existing Sales Orders, invoices, receipts, and schedules remain immutable and must be explicitly voided/superseded before replacement; no cascade rewrite.
- A signature fee is treated as a DP against the grand total, reduces outstanding balance, and can generate a DP invoice. It is not an extra fee line.
- Pro-forma invoice is not introduced. Quotation validity copy is invalid on any invoice.
- Legacy Canva/generic sent records are exempt from retroactive byte-stability. New structured quotations become byte-stable from their first sent artifact onward.
- Hojja `display_quantity` and monetary quantity are the same unless pricing mode is `fixed_artwork`, where each artwork line has an explicit integer display quantity and an agreed unit price. Original price is per unit; document/line discount is not applied again when an agreed revised price is present.
- `raw_area_m2` keeps up to eight decimal places for audit. Canonical `billed_area_m2` and monetary quantity keep up to four; default displayed/billed rounding is half-up to two decimals. `exact` still persists the billed value to four decimals while retaining the eight-decimal raw result.
- A structured deposit mismatch blocks send, Deal, and issue; draft save may proceed with a visible warning.
- Default validity is derived from the send/release date. Draft preview may show the projected date, but the immutable sent artifact uses the actual send date.
- Official quotation numbering is allocated atomically on first send, scoped by brand/template and year. Drafts display “Nomor diberikan saat dikirim”. Numbers are never reused.
- Bank/legal payment identity is not inferred from the visual template. A project/brand must select an explicit authoritative payment profile. Missing or conflicting profiles block send/issue rather than printing an account copied from a historical PDF.

## Builder calls

These defaults are engineering decisions based on the supplied evidence:

- new area lines use half-up to two decimals; legacy values are untouched
- Holla DP defaults 30%
- Hojja DP defaults 50%
- Texturin signature fee defaults 30%
- PPM canonical meaning is price per m²
- tax remains nullable/unset unless explicitly provided
- original PDFs guide identity, while known arithmetic/semantic mistakes are corrected
- the canonical renderer remains server-side; browser preview mirrors its view model but is not an accounting artifact
- explicit stored template/payment identities win; string heuristics exist only for historical fallback
- rollout occurs in independently verifiable vertical slices, but no brand is considered complete until editor, persistence, preview, PDF, lifecycle, and production readback all agree
