# Frontend canonical shell/project slice report

Base: `4446c2d14ea9f9a3a089348a490186c8cb8d1456` (required baseline parent `0ee6a95e253bdb616382fca86a8c7285f7d02fd4`).

## Delivered

- Exactly seven top-level menus: Dashboard, Arus Kas, Dompet, Proyek, Operasional Kantor, Hutang, Laporan.
- Canonical action ownership registry and action metadata.
- CSV/PDF export ownership moved to Laporan.
- Production Proyek route reuses the annual trading-style project lifecycle/candlestick and year selector.
- Project open/create routes land on Transaksi, preserving the requested project-first transaction flow.
- Project detail tabs expanded for Ringkasan, Transaksi, Pinjaman, Profitabilitas, Presensi, Dokumen, Audit.
- `cancelled` remains a real lifecycle state and is represented by an explicit demo fixture; it is never coerced to completed.
- Report preview retains project/company structure and all source-grounded rows.
- Baseline light-theme filled-surface contrast defect fixed at the final design-system override.
- Unreachable `LiveFinanceApp` removed.

## TDD/regression evidence

- Initial RED: missing action registry; canonical menu names/action ownership failed.
- Intermediate RED: production project opened Ringkasan, hiding `Tambah transaksi`; report preview lost structured company text; old route-heading assertions stale.
- Intermediate RED: cancelled lifecycle expanded fixture and exposed hardcoded count tests.
- GREEN focused live production suite: 18/18.
- GREEN full frontend suite: 32 files, 226/226 tests.
- GREEN TypeScript + Vite production build.
- GREEN known browser contrast regression: `test_light_filled_color_surfaces_use_white_text` 1/1.
- `git diff --check` required before commit.

## Deliberately not claimed

- Backend canonical transaction/debt persistence.
- Production correction/reversal capabilities.
- Full responsive/a11y/browser matrix.
- Deployment or authority activation.
