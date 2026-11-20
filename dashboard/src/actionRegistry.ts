export type OwnerRoute = 'dashboard' | 'cashflow' | 'wallets' | 'projects' | 'office' | 'debts' | 'reports' | 'shell'
export type ActionKind = 'navigate' | 'mutate' | 'filter' | 'export' | 'preference'

export interface RegisteredAction {
  owner: OwnerRoute
  kind: ActionKind
  label: string
}

export const ACTION_REGISTRY = {
  'nav.dashboard': { owner: 'dashboard', kind: 'navigate', label: 'Buka Dashboard' },
  'nav.cashflow': { owner: 'cashflow', kind: 'navigate', label: 'Buka Arus Kas' },
  'nav.wallets': { owner: 'wallets', kind: 'navigate', label: 'Buka Dompet' },
  'nav.projects': { owner: 'projects', kind: 'navigate', label: 'Buka Project' },
  'nav.office': { owner: 'office', kind: 'navigate', label: 'Buka Operasional Kantor' },
  'nav.debts': { owner: 'debts', kind: 'navigate', label: 'Buka Hutang' },
  'nav.reports': { owner: 'reports', kind: 'navigate', label: 'Buka Laporan' },
  'shell.navigation-open': { owner: 'shell', kind: 'navigate', label: 'Buka navigasi' },
  'shell.navigation-close': { owner: 'shell', kind: 'navigate', label: 'Tutup navigasi' },
  'shell.theme-toggle': { owner: 'shell', kind: 'preference', label: 'Ubah tema' },
  'dashboard.projects-view': { owner: 'projects', kind: 'navigate', label: 'Lihat semua Project' },
  'dashboard.office-view': { owner: 'office', kind: 'navigate', label: 'Lihat Operasional Kantor' },
  'dashboard.reviews-view': { owner: 'dashboard', kind: 'navigate', label: 'Lihat item perlu ditinjau' },
  'cashflow.year-filter': { owner: 'cashflow', kind: 'filter', label: 'Filter tahun' },
  'cashflow.period-filter': { owner: 'cashflow', kind: 'filter', label: 'Filter periode' },
  'cashflow.company-filter': { owner: 'cashflow', kind: 'filter', label: 'Filter perusahaan' },
  'wallets.wallet-select': { owner: 'wallets', kind: 'filter', label: 'Pilih dompet' },
  'wallets.movement-filter': { owner: 'wallets', kind: 'filter', label: 'Filter mutasi' },
  'projects.create': { owner: 'projects', kind: 'mutate', label: 'Buat Project' },
  'projects.open': { owner: 'projects', kind: 'navigate', label: 'Buka detail Project' },
  'projects.edit': { owner: 'projects', kind: 'mutate', label: 'Ubah Project' },
  'projects.status-change': { owner: 'projects', kind: 'mutate', label: 'Ubah status Project' },
  'projects.delete': { owner: 'projects', kind: 'mutate', label: 'Hapus Project permanen' },
  'projects.year-filter': { owner: 'projects', kind: 'filter', label: 'Filter tahun Project' },
  'projects.transaction-create': { owner: 'projects', kind: 'mutate', label: 'Catat transaksi Project' },
  'projects.transaction-correct': { owner: 'projects', kind: 'mutate', label: 'Koreksi transaksi Project' },
  'projects.transaction-reverse': { owner: 'projects', kind: 'mutate', label: 'Balik transaksi Project' },
  'projects.tab-overview': { owner: 'projects', kind: 'navigate', label: 'Buka tab ringkasan Project' },
  'projects.tab-transactions': { owner: 'projects', kind: 'navigate', label: 'Buka tab transaksi Project' },
  'projects.tab-debts': { owner: 'projects', kind: 'navigate', label: 'Buka tab pinjaman Project' },
  'projects.tab-profitability': { owner: 'projects', kind: 'navigate', label: 'Buka tab profitabilitas Project' },
  'projects.tab-presensi': { owner: 'projects', kind: 'navigate', label: 'Buka tab presensi Project' },
  'projects.tab-documents': { owner: 'projects', kind: 'navigate', label: 'Buka tab Quotation & Invoice Project' },
  'projects.tab-audit': { owner: 'projects', kind: 'navigate', label: 'Buka tab audit Project' },
  'office.transaction-create': { owner: 'office', kind: 'mutate', label: 'Catat biaya kantor' },
  'office.transaction-correct': { owner: 'office', kind: 'mutate', label: 'Koreksi biaya kantor' },
  'office.transaction-reverse': { owner: 'office', kind: 'mutate', label: 'Balik biaya kantor' },
  'debts.create': { owner: 'debts', kind: 'mutate', label: 'Catat hutang' },
  'debts.repay': { owner: 'debts', kind: 'mutate', label: 'Catat pembayaran hutang' },
  'debts.correct': { owner: 'debts', kind: 'mutate', label: 'Koreksi hutang' },
  'debts.reverse': { owner: 'debts', kind: 'mutate', label: 'Balik hutang' },
  'reports.filters-reset': { owner: 'reports', kind: 'filter', label: 'Reset filter laporan' },
  'reports.export-csv': { owner: 'reports', kind: 'export', label: 'Ekspor CSV' },
  'reports.export-pdf': { owner: 'reports', kind: 'export', label: 'Ekspor PDF' },
} as const satisfies Record<string, RegisteredAction>

export type ActionId = keyof typeof ACTION_REGISTRY

export function actionProps(id: ActionId) {
  return {
    'data-action-id': id,
    'data-owner-route': ACTION_REGISTRY[id].owner,
  } as const
}
