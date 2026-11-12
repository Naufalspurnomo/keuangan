import type { FinanceWorkspace } from './financeWorkspace'
import type { ReportModel } from './financeView'

export type CanonicalReportType =
  | 'cashflow'
  | 'wallet-position'
  | 'project-profitability'
  | 'project-lifecycle'
  | 'office-operations'
  | 'debt-aging'
  | 'transaction-audit'

export const CANONICAL_REPORT_TYPES: ReadonlyArray<{ value: CanonicalReportType; label: string }> = [
  { value: 'cashflow', label: 'Arus kas' },
  { value: 'wallet-position', label: 'Posisi dompet' },
  { value: 'project-profitability', label: 'Profitabilitas proyek' },
  { value: 'project-lifecycle', label: 'Lifecycle proyek' },
  { value: 'office-operations', label: 'Operasional kantor' },
  { value: 'debt-aging', label: 'Aging hutang' },
  { value: 'transaction-audit', label: 'Audit transaksi' },
]

export interface CanonicalReportDataset {
  type: CanonicalReportType
  title: string
  headers: string[]
  rows: string[][]
  totals: Array<[string, string]>
  generatedAt: string
  dataThrough: string | null
  source: string
  scope: string[]
}

const money = (value: number) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(value)
const status = (value: string) => value === 'active' ? 'Aktif' : value === 'completed' ? 'Selesai' : value === 'cancelled' ? 'Dibatalkan' : 'Direncanakan'

function transactionRows(model: ReportModel) {
  return model.rows.map((row) => [
    row.date,
    row.scope === 'office' ? 'Operasional Kantor' : 'Proyek',
    row.wallet,
    row.company ?? '—',
    row.project ?? '—',
    row.direction === 'income' ? 'Pemasukan' : 'Pengeluaran',
    row.notes,
    money(row.amount),
  ])
}

export function buildCanonicalReportDataset(workspace: FinanceWorkspace, model: ReportModel, type: CanonicalReportType): CanonicalReportDataset {
  const base = {
    type,
    generatedAt: model.generatedAt,
    dataThrough: workspace.live_data_through ?? null,
    source: workspace.live_source ?? (workspace.mode === 'live' ? 'PostgreSQL canonical ledger' : 'Data demo lokal'),
    scope: model.scopeText,
  }
  if (type === 'wallet-position') {
    const rows = (workspace.live_wallets ?? []).map((wallet) => [wallet.name, money(wallet.balance)])
    return { ...base, title: 'Posisi Dompet', headers: ['Dompet', 'Saldo'], rows, totals: [['Total kas', money((workspace.live_wallets ?? []).reduce((sum, row) => sum + row.balance, 0))]] }
  }
  if (type === 'project-profitability') {
    const rows = workspace.projects.map((project) => {
      const transactions = workspace.transactions.filter((row) => row.project_id === project.id)
      const income = transactions.filter((row) => row.direction === 'income').reduce((sum, row) => sum + row.amount, 0)
      const expense = transactions.filter((row) => row.direction === 'expense').reduce((sum, row) => sum + row.amount, 0)
      return [project.id, project.name, project.company, project.wallet, money(income), money(expense), money(income - expense)]
    })
    return { ...base, title: 'Profitabilitas Proyek', headers: ['UUID', 'Proyek', 'Unit', 'Dompet', 'Pemasukan', 'Pengeluaran', 'Profit'], rows, totals: [['Jumlah proyek', String(rows.length)]] }
  }
  if (type === 'project-lifecycle') {
    const rows = workspace.projects.map((project) => [project.id, project.name, status(project.status), project.started_on, project.completed_on ?? '—', project.company, project.wallet])
    return { ...base, title: 'Lifecycle Proyek', headers: ['UUID', 'Proyek', 'Status', 'Mulai', 'Selesai', 'Unit', 'Dompet'], rows, totals: [['Jumlah proyek', String(rows.length)]] }
  }
  if (type === 'debt-aging') {
    const today = new Date(`${workspace.live_data_through ?? new Date().toISOString().slice(0, 10)}T00:00:00Z`).getTime()
    const rows = workspace.debts.map((debt) => {
      const due = debt.due_at ? new Date(`${debt.due_at}T00:00:00Z`).getTime() : null
      const age = due == null ? 'Tanpa jatuh tempo' : due < today ? `${Math.floor((today - due) / 86_400_000)} hari lewat` : `${Math.ceil((due - today) / 86_400_000)} hari lagi`
      const project = workspace.projects.find((item) => item.id === debt.project_id)
      return [debt.id, debt.date, debt.due_at ?? '—', age, debt.lender, debt.borrower, project?.name ?? '—', money(debt.amount), money(debt.repaid), money(debt.amount - debt.repaid)]
    })
    return { ...base, title: 'Aging Hutang', headers: ['UUID', 'Pencairan', 'Jatuh tempo', 'Aging', 'Pemberi dana', 'Peminjam', 'Proyek', 'Principal', 'Terbayar', 'Outstanding'], rows, totals: [['Outstanding', money(workspace.debts.reduce((sum, debt) => sum + debt.amount - debt.repaid, 0))]] }
  }
  if (type === 'transaction-audit') {
    const rows = workspace.transactions.map((row) => [row.canonical_transaction_id ?? row.id, String(row.transaction_version ?? 1), row.date, row.scope, row.wallet, row.company ?? '—', row.direction, money(row.amount), row.recorded_by ?? '—', row.evidence_source ?? '—', row.notes])
    return { ...base, title: 'Audit Transaksi', headers: ['UUID', 'Versi', 'Tanggal', 'Scope', 'Dompet', 'Unit', 'Jenis', 'Jumlah', 'Actor', 'Evidence', 'Keterangan'], rows, totals: [['Jumlah record efektif', String(rows.length)]] }
  }
  const scoped = type === 'office-operations' ? { ...model, rows: model.rows.filter((row) => row.scope === 'office') } : model
  const rows = transactionRows(scoped)
  const income = scoped.rows.filter((row) => row.direction === 'income').reduce((sum, row) => sum + row.amount, 0)
  const expense = scoped.rows.filter((row) => row.direction === 'expense').reduce((sum, row) => sum + row.amount, 0)
  return {
    ...base,
    title: type === 'office-operations' ? 'Operasional Kantor' : 'Arus Kas',
    headers: ['Tanggal', 'Aktivitas', 'Dompet', 'Unit', 'Proyek', 'Jenis', 'Keterangan', 'Jumlah'],
    rows,
    totals: [['Pemasukan', money(income)], ['Pengeluaran', money(expense)], ['Bersih', money(income - expense)], ['Jumlah record', String(rows.length)]],
  }
}

export async function canonicalDatasetHash(dataset: CanonicalReportDataset) {
  const canonical = JSON.stringify(dataset, Object.keys(dataset).sort())
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical))
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}
