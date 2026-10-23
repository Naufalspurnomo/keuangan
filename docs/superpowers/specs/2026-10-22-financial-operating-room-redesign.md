# Financial Operating Room — Structural Redesign

## Intent

Rebuild the Hollawall overview as a calm financial operating room. The screen serves an owner who must answer three questions quickly: where the money is, which unit changed it, and what activity requires attention.

## Why the current UI fails

The current overview nests cards inside cards: page heading, status badge, four locked scope boxes, balance hero, four KPI cards, portfolio cards, unit cards, chart card, activity card, matrix card, and timeline cards. On mobile, desktop blocks are stacked rather than recomposed. Color changes cannot solve the resulting flat hierarchy and phishing-template feel.

## Structural thesis

One reading path, one dominant number, one active unit, then evidence.

1. Position: consolidated cash and source freshness.
2. Pulse: four inline operating measures.
3. Unit: compact company/wallet navigator.
4. Trend: selected unit chart.
5. Evidence: selected unit activity.
6. Projects: matrix and timeline after the operating view.

## Art direction

- Native dark workspace inspired by Linear's luminance hierarchy, Revolut's financial confidence, Stripe's controlled data density, and Awwwards fintech case studies' clear narrative.
- Inter/system sans only for the product UI. No decorative serif.
- Background space groups content. Borders are reserved for major separators, tables, and focus states.
- Radius scale: 4px–8px for controls; no oversized rounded panels.
- No decorative gradients, glow, glass, colored card fields, fake badges, or generic icon-card grids.

## Color roles

- Deep navy: application space.
- Slightly lighter navy: active/elevated working surfaces.
- Indigo/lavender: selected navigation and categorical chart data.
- Green: positive cash movement only.
- Red/coral: negative cash movement only.
- Amber: warning or exceptional attention only; never general selection.
- Off-white/gray ramp: all normal hierarchy.

## Desktop composition

- Sidebar remains canonical navigation.
- Topbar remains compact.
- Overview heading is merged into the position block rather than a separate ornamental header.
- Snapshot provenance becomes one quiet line.
- Position block uses no outer card; total cash is the focal point.
- KPIs form an inline ruled strip rather than individual cards.
- Unit navigator is a compact two-group rail.
- Selected unit trend and activity share one workspace split by one vertical rule.
- Project matrix/timeline remain below as a separate analysis chapter.

## Mobile composition

- Compact header.
- Total cash visible immediately.
- Freshness/provenance occupies one line.
- KPI strip uses a 2×2 ruled grid without card shells.
- Company/wallet mode switch followed by compact horizontal unit choices.
- Selected unit, balance, metrics, chart, then activity—no nested panels.
- Project analysis follows after the operating view; desktop containers must not simply stack as cards.

## Behavioral invariants

- Data and calculations remain canonical.
- Hollawall and Texturin remain distinct sections.
- Four companies and three wallets remain independently selectable.
- Chart and activity follow the active selection.
- Shared CV HB balance is never split artificially.
- Dashboard stays read-only.
- Basic Auth, stale-while-revalidate, source provenance, API routes, and drill-down behavior remain unchanged.
- Desktop and mobile project pagination behavior remains intact.

## Acceptance

- Old business-report structures `.portfolio-section`, `.business-chart-card`, and `.business-ledger-card` are absent at runtime.
- New `.unit-navigator`, `.unit-focus-canvas`, and `.activity-stream` structures are present.
- Mobile first viewport shows the cash position and operating pulse without navigating through locked scope cards.
- Mobile has zero page-level horizontal overflow at 320, 375, 390, and 430 px.
- Touch targets are at least 44 px where applicable.
- Borders/boxed containers above the project section are materially reduced relative to baseline.
- Light and dark themes remain readable; dark is the primary art direction.
- Existing behavior tests, typecheck, build, browser matrix, live auth/read-only contract, and screenshot critique pass.
