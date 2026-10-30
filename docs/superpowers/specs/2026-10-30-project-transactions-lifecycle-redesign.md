# Project-owned transactions and lifecycle redesign

This specification supersedes standalone project-transaction navigation and the wheel/color rules in the 2026-10-28 lifecycle specification.

## Product contract

- Project detail route: `#projects?project=<id>`.
- The sidebar has seven pages. There is no standalone Transactions menu/page.
- A legacy `#transactions` URL canonicalizes to `#projects`; `#transactions?project=<id>` preserves the project query.
- Project detail uses the exact project name as its title, contains only transactions whose `project_id` matches, and provides `Kembali ke Proyek` plus browser Back support.
- Transaction creation and editing from project detail use a project-pinned modal. Activity and project cannot change there.
- Active projects expose a quick `Selesai` action with a validated completion date.
- Lifecycle bodies use a solid five-band palette: 0–14 green, 15–30 teal, 31–60 amber, 61–90 orange, 91+ red.
- A completed project keeps the age color derived from start-to-completion duration. A separate check/hatch marks completion; completed bodies are never gray.
- Ordinary wheel inside a lifecycle canvas zooms that canvas at the pointer. Wheel outside the canvas scrolls the page. Shift+wheel pans horizontally. Drag pans.
- Registry filters live directly above `DAFTAR PROYEK`; they filter registry/stat results, not chart candles.
- The demo catalog is explicit, deterministic, unique, spans 2024–2026, and is independent of Google Sheets.

## Wire order

```text
Projects list mode
Demo banner
Projects heading
Year selector
Status summary
4 lifecycle canvases
Legend
Registry filters
DAFTAR PROYEK / Rincian {year}
Pagination

Project detail mode
Demo banner
Back + project identity/status
Project title
Project summary
Tambah transaksi
Search
Project-only transaction ledger
```

## Accessibility and responsive behavior

Desktop and mobile expose the same semantic project actions. Back, add, completion, edit, and delete controls remain keyboard reachable and have touch targets of at least 44px on narrow screens. Month labels remain above candles and visibly separated. Transaction tables remain horizontally reachable.
