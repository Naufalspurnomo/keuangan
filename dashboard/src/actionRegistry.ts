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
  'nav.projects': { owner: 'projects', kind: 'navigate', label: 'Buka Proyek' },
  'nav.office': { owner: 'office', kind: 'navigate', label: 'Buka Operasional Kantor' },
  'nav.debts': { owner: 'debts', kind: 'navigate', label: 'Buka Hutang' },
  'nav.reports': { owner: 'reports', kind: 'navigate', label: 'Buka Laporan' },
  'shell.navigation-open': { owner: 'shell', kind: 'navigate', label: 'Buka navigasi' },
  'shell.navigation-close': { owner: 'shell', kind: 'navigate', label: 'Tutup navigasi' },
  'shell.theme-toggle': { owner: 'shell', kind: 'preference', label: 'Ubah tema' },
  'dashboard.projects-view': { owner: 'projects', kind: 'navigate', label: 'Lihat semua proyek' },
  'dashboard.office-view': { owner: 'office', kind: 'navigate', label: 'Lihat Operasional Kantor' },
  'dashboard.reviews-view': { owner: 'dashboard', kind: 'navigate', label: 'Lihat item perlu ditinjau' },
  'cashflow.year-filter': { owner: 'cashflow', kind: 'filter', label: 'Filter tahun' },
  'cashflow.period-filter': { owner: 'cashflow', kind: 'filter', label: 'Filter periode' },
  'cashflow.company-filter': { owner: 'cashflow', kind: 'filter', label: 'Filter perusahaan' },
  'wallets.wallet-select': { owner: 'wallets', kind: 'filter', label: 'Pilih dompet' },
  'wallets.movement-filter': { owner: 'wallets', kind: 'filter', label: 'Filter mutasi' },
  'projects.create': { owner: 'projects', kind: 'mutate', label: 'Buat proyek' },
  'projects.open': { owner: 'projects', kind: 'navigate', label: 'Buka detail proyek' },
  'projects.edit': { owner: 'projects', kind: 'mutate', label: 'Ubah proyek' },
  'projects.status-change': { owner: 'projects', kind: 'mutate', label: 'Ubah status proyek' },
  'projects.archive': { owner: 'projects', kind: 'mutate', label: 'Arsipkan proyek' },
  'projects.year-filter': { owner: 'projects', kind: 'filter', label: 'Filter tahun proyek' },
  'projects.transaction-create': { owner: 'projects', kind: 'mutate', label: 'Catat transaksi proyek' },
  'projects.transaction-correct': { owner: 'projects', kind: 'mutate', label: 'Koreksi transaksi proyek' },
  'projects.transaction-reverse': { owner: 'projects', kind: 'mutate', label: 'Balik transaksi proyek' },
  'projects.tab-overview': { owner: 'projects', kind: 'navigate', label: 'Buka tab ringkasan proyek' },
  'projects.tab-transactions': { owner: 'projects', kind: 'navigate', label: 'Buka tab transaksi proyek' },
  'projects.tab-debts': { owner: 'projects', kind: 'navigate', label: 'Buka tab pinjaman proyek' },
  'projects.tab-profitability': { owner: 'projects', kind: 'navigate', label: 'Buka tab profitabilitas proyek' },
  'projects.tab-presensi': { owner: 'projects', kind: 'navigate', label: 'Buka tab presensi proyek' },
  'projects.tab-documents': { owner: 'projects', kind: 'navigate', label: 'Buka tab dokumen proyek' },
  'projects.tab-audit': { owner: 'projects', kind: 'navigate', label: 'Buka tab audit proyek' },
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
