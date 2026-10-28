# Project Lifecycle Market Chart — Approved Specification

## Intent

Replace the paginated project-age timeline with four year-scale interactive lifecycle canvases that behave like a market chart while preserving the real semantics of project data.

## Approved structure

Exactly four canvases:

1. Holla
2. Hojja
3. Texturin Bali
4. Texturin Surabaya

Desktop uses a 2×2 comparison grid. Narrow screens stack the canvases. All canvases share the same year, time scale, legend, colors, and interaction model.

## Data contract

The `/Proyek` workspace already stores the four canonical companies directly on every project. The chart groups by the existing `FinanceProject.company` values:

- `Holla`
- `Hojja`
- `Texturin Bali`
- `Texturin Surabaya`

No backend snapshot split or inferred classification is needed. Project identity remains source-grounded. No synthetic split of balances, revenue, or project activity is allowed.

## Canvas semantics

- One selected calendar year per chart set; default year follows the snapshot date.
- Left axis shows January–December for the selected year.
- Newer projects sort to the right; the initial horizontal viewport is anchored at the newest/right edge.
- Every project in the unit and year is drawn in one canvas. No previous/next pagination.
- Candle body spans the real lifecycle interval clipped to the selected year:
  - active project: start date through snapshot date;
  - completed project: start date through completion date.
- White wick spans first through last transaction.
- Active age uses the existing continuous green→yellow→orange→red scale.
- Completed projects use a calm completed tone without losing their lifecycle interval.
- Header summary is `active / total`, scoped to the selected year and unit.
- Accessible tooltip/readout exposes unit, status, start, end/snapshot, age, first/last transaction, transaction count, and net cashflow.
- Clicking or keyboard-activating a candle opens the existing project detail flow.

## Interaction

- Pointer drag pans horizontally and vertically.
- Mouse wheel/trackpad and pinch gestures zoom.
- `+`, `−`, `Reset`, and `Terbaru` controls are visible.
- Month axis remains readable while panning horizontally.
- Horizontal pan is independent per unit because project counts differ.
- Vertical year scale and zoom level are synchronized across the four canvases.
- Zoom is bounded so marks remain usable.
- Keyboard controls and non-hover labels preserve accessibility.

## Acceptance

- Four named unit canvases are rendered consistently, including empty units.
- No pagination controls or `Sebelumnya/Berikutnya` remain.
- Latest project is the rightmost mark and initial view is right-anchored.
- Header uses `active / total` for the selected year.
- Pan, vertical pan, zoom, reset, and latest controls work without opening a project accidentally.
- Existing filters, project table/detail navigation, CRUD, persistence, audit, reporting, and PDF remain intact.
- Unit projection is covered by backend tests.
- Frontend semantic and interaction behavior is covered by Vitest.
- TypeScript, build, canonical Hermes verification, release tests, and browser desktop/mobile acceptance pass before deployment.
- Production deployment is atomic and verified by public byte hashes plus authenticated visual/readback checks.
