import {
  COMPANIES,
  WALLETS,
  projectTotals,
  sumMoney,
  type CompanyId,
  type FinanceProject,
  type FinanceTransaction,
  type FinanceWorkspace,
  type ProjectStatus,
  type TransactionDirection,
  type TransactionScope,
  type WalletId,
} from './financeWorkspace'

export const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
export const DATE = new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })

export function dateLabel(value: string) {
  const date = new Date(`${value.slice(0, 10)}T00:00:00`)
  return Number.isNaN(date.getTime()) ? 'Tanggal tidak valid' : DATE.format(date)
}

export function projectLabel(project: FinanceProject | undefined) {
  return project?.name ?? 'Proyek tidak ditemukan'
}

export function projectStatusLabel(status: ProjectStatus) {
  return status === 'completed' ? 'Selesai' : status === 'active' ? 'Aktif' : 'Direncanakan'
}

export function directionLabel(direction: TransactionDirection) {
  return direction === 'income' ? 'Pemasukan' : 'Pengeluaran'
}

export function scopeLabel(scope: TransactionScope) {
  return scope === 'project' ? 'Proyek' : 'Operasional Kantor'
}

export function walletBalances(workspace: FinanceWorkspace) {
  return WALLETS.map((wallet) => {
    const rows = workspace.transactions.filter((row) => row.wallet === wallet)
    const income = sumMoney(rows.filter((row) => row.direction === 'income').map((row) => row.amount), `pemasukan ${wallet}`)
    const expense = sumMoney(rows.filter((row) => row.direction === 'expense').map((row) => row.amount), `pengeluaran ${wallet}`)
    const lent = sumMoney(workspace.debts.filter((debt) => debt.lender === wallet).map((debt) => debt.amount - debt.repaid), `piutang ${wallet}`)
    const borrowed = sumMoney(workspace.debts.filter((debt) => debt.borrower === wallet).map((debt) => debt.amount - debt.repaid), `hutang ${wallet}`)
    const balance = income - expense
    const adjusted = sumMoney([balance, lent, -borrowed], `saldo penyesuaian ${wallet}`)
    return { wallet, income, expense, balance, lent, borrowed, adjusted }
  })
}

export function projectView(project: FinanceProject, workspace: FinanceWorkspace) {
  const totals = projectTotals(project, workspace.transactions)
  return { ...project, ...totals }
}

export interface ReportFilters {
  dateFrom: string
  dateTo: string
  wallet: 'all' | WalletId
  company: 'all' | CompanyId
  projectId: 'all' | string
  scope: 'all' | TransactionScope
  direction: 'all' | TransactionDirection
  projectStatus: 'all' | ProjectStatus
}

export const defaultReportFilters = (workspace: FinanceWorkspace): ReportFilters => {
  const dates = workspace.transactions.map((row) => row.date).sort()
  return {
    dateFrom: dates[0] ?? '',
    dateTo: dates.at(-1) ?? '',
    wallet: 'all', company: 'all', projectId: 'all', scope: 'all', direction: 'all', projectStatus: 'all',
  }
}

export interface ReportRow {
  id: string
  date: string
  direction: TransactionDirection
  amount: number
  scope: TransactionScope
  wallet: WalletId
  company: CompanyId | null
  project: string | null
  status: ProjectStatus | null
  category: string | null
  notes: string
}

export interface ReportModel {
  generatedAt: string
  filters: ReportFilters
  rows: ReportRow[]
  totals: { income: number; expense: number; net: number; projectExpense: number; officeExpense: number }
  scopeText: string[]
}

export function buildReportModel(workspace: FinanceWorkspace, filters: ReportFilters, generatedAt = new Date().toISOString()): ReportModel {
  const projects = new Map(workspace.projects.map((project) => [project.id, project]))
  const rows = workspace.transactions.filter((row) => {
    const project = row.project_id ? projects.get(row.project_id) : undefined
    if (filters.dateFrom && row.date < filters.dateFrom) return false
    if (filters.dateTo && row.date > filters.dateTo) return false
    if (filters.wallet !== 'all' && row.wallet !== filters.wallet) return false
    if (filters.company !== 'all' && row.company !== filters.company) return false
    if (filters.projectId !== 'all' && row.project_id !== filters.projectId) return false
    if (filters.scope !== 'all' && row.scope !== filters.scope) return false
    if (filters.direction !== 'all' && row.direction !== filters.direction) return false
    if (filters.projectStatus !== 'all' && project?.status !== filters.projectStatus) return false
    return true
  }).sort((left, right) => right.date.localeCompare(left.date) || left.id.localeCompare(right.id))
    .map((row): ReportRow => {
      const project = row.project_id ? projects.get(row.project_id) : undefined
      return {
        id: row.id, date: row.date, direction: row.direction, amount: row.amount, scope: row.scope,
        wallet: row.wallet, company: row.company, project: project?.name ?? null, status: project?.status ?? null,
        category: row.office_category, notes: row.notes,
      }
    })
  const income = sumMoney(rows.filter((row) => row.direction === 'income').map((row) => row.amount), 'pemasukan laporan')
  const expense = sumMoney(rows.filter((row) => row.direction === 'expense').map((row) => row.amount), 'pengeluaran laporan')
  const projectExpense = sumMoney(rows.filter((row) => row.scope === 'project' && row.direction === 'expense').map((row) => row.amount), 'biaya proyek laporan')
  const officeExpense = sumMoney(rows.filter((row) => row.scope === 'office').map((row) => row.amount), 'biaya kantor laporan')
  const scopeText = [
    filters.dateFrom || filters.dateTo ? `${filters.dateFrom ? dateLabel(filters.dateFrom) : 'Awal'} – ${filters.dateTo ? dateLabel(filters.dateTo) : 'Sekarang'}` : 'Semua tanggal',
    filters.wallet === 'all' ? 'Semua dompet' : filters.wallet,
    filters.company === 'all' ? 'Semua perusahaan' : filters.company,
    filters.scope === 'all' ? 'Semua aktivitas' : scopeLabel(filters.scope),
    filters.projectId === 'all' ? 'Semua proyek' : `Proyek: ${workspace.projects.find((project) => project.id === filters.projectId)?.name ?? 'Tidak ditemukan'}`,
    filters.direction === 'all' ? 'Pemasukan & pengeluaran' : directionLabel(filters.direction),
    filters.projectStatus === 'all' ? 'Semua status proyek' : `Status: ${projectStatusLabel(filters.projectStatus)}`,
  ]
  return { generatedAt, filters, rows, totals: { income, expense, net: income - expense, projectExpense, officeExpense }, scopeText }
}

export function availableReportOptions(workspace: FinanceWorkspace) {
  return { wallets: WALLETS, companies: COMPANIES, projects: [...workspace.projects].sort((a, b) => a.name.localeCompare(b.name, 'id-ID')) }
}

export function monthlyCashflow(rows: FinanceTransaction[], year: number) {
  return Array.from({ length: 12 }, (_, month) => {
    const prefix = `${year}-${String(month + 1).padStart(2, '0')}`
    const monthRows = rows.filter((row) => row.date.startsWith(prefix))
    const income = sumMoney(monthRows.filter((row) => row.direction === 'income').map((row) => row.amount), 'pemasukan bulanan')
    const expense = sumMoney(monthRows.filter((row) => row.direction === 'expense').map((row) => row.amount), 'pengeluaran bulanan')
    return { month, income, expense, net: income - expense }
  })
}
