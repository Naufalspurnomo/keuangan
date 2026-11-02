import type { DashboardMeta, Overview, QualityRow, Transaction } from './types'
import type { CompanyId, FinanceWorkspace, OfficeCategory, WalletId } from './financeWorkspace'
import { isCanonicalWalletCompanyPair } from './transactionMappings'

export interface WalletSnapshot { source_key: string; name: string; balance: number }
export interface DebtSnapshot { source_key: string; date: string | null; amount: number; notes: string; borrower: string; lender: string; status: string }
export interface CashTrendPoint { month: string; balance: number; net_movement: number }
export type ProjectHealth = 'healthy' | 'watch' | 'overdue' | 'completed' | 'unmarked'
export interface ProjectSummary {
  name: string
  /** Canonical presensi project identity. Absent means presensi cannot be queried safely. */
  project_id?: string
  portfolio?: 'Hollawall' | 'Texturin' | 'Belum ditandai' | 'Lintas portfolio'
  net_cashflow: number
  transaction_count?: number
  first_activity_on?: string
  last_activity_on?: string
  started_on?: string | null
  completed_on?: string | null
  age_days?: number | null
  lifecycle_status?: 'active' | 'completed' | 'unmarked'
  health?: ProjectHealth
  source_key_first?: string
  source_key_latest?: string
}
export interface DashboardSnapshot {
  version: string
  meta: DashboardMeta
  overview: Overview
  wallets: WalletSnapshot[]
  transactions: Transaction[]
  debts: DebtSnapshot[]
  quality_rows?: QualityRow[]
  cash_trend: CashTrendPoint[]
  project_summaries: ProjectSummary[]
}

function liveProjectRouteId(project: ProjectSummary, index: number) {
  return project.source_key_first || project.source_key_latest || `live-project-${index + 1}`
}

function uiCompany(company: string): CompanyId {
  const key = company.trim().toLocaleLowerCase('id-ID').replaceAll('-', ' ')
  if (key === 'holla' || key === 'hollawall') return 'Holla'
  if (key === 'hojja') return 'Hojja'
  if (key === 'texturin bali' || key === 'tx bali') return 'Texturin Bali'
  if (key === 'texturin surabaya' || key === 'tx sby') return 'Texturin Surabaya'
  return company as CompanyId
}

/** Adapt authenticated snapshot data to the existing shell without making it writable. */
export function snapshotFinanceWorkspace(snapshot: DashboardSnapshot): FinanceWorkspace {
  const updatedAt = snapshot.meta.as_of
  const projects = snapshot.project_summaries.map((project, index) => {
    const matching = snapshot.transactions.filter((row) => row.project === project.name)
    const first = matching[0]
    const mappings = new Map(
      matching
        .filter((row) => isCanonicalWalletCompanyPair(row.wallet, row.company))
        .map((row) => [`${row.wallet}\u0000${row.company}`, { wallet: row.wallet, company: row.company, project: project.name }]),
    )
    const writeMapping = mappings.size === 1 ? [...mappings.values()][0] : undefined
    const startedOn = project.started_on || project.first_activity_on || matching.map((row) => row.transaction_date).sort()[0]
      || snapshot.meta.data_through || updatedAt.slice(0, 10)
    const completed = project.lifecycle_status === 'completed'
    return {
      id: liveProjectRouteId(project, index),
      name: project.name,
      company: uiCompany(first?.company || ''),
      wallet: (first?.wallet || '') as WalletId,
      status: completed ? 'completed' as const : 'active' as const,
      started_on: startedOn,
      completed_on: completed ? (project.completed_on || project.last_activity_on || null) : null,
      client: '', contract_value: null, notes: '', created_at: updatedAt, updated_at: updatedAt,
      ...(project.project_id ? { presensi_project_id: project.project_id } : {}),
      ...(writeMapping ? { write_mapping: writeMapping } : {}),
    }
  })
  const projectsByName = new Map(projects.map((project) => [project.name, project]))
  const transactions = snapshot.transactions.flatMap((row) => {
    if (row.scope === 'internal_transfer' || row.internal_movement) return []
    const project = row.project ? projectsByName.get(row.project) : undefined
    const office = row.scope === 'office' || !project
    return [{
      id: row.source_key || `live-transaction-${row.id}`,
      date: row.transaction_date.slice(0, 10),
      direction: row.transaction_type === 'Pemasukan' ? 'income' as const : 'expense' as const,
      amount: row.amount,
      scope: office ? 'office' as const : 'project' as const,
      wallet: row.wallet as WalletId,
      company: uiCompany(row.company),
      project_id: project?.id ?? null,
      office_category: office ? (row.office_category || 'Lainnya') as OfficeCategory : null,
      notes: row.notes || '', created_at: row.updated_at || updatedAt, updated_at: row.updated_at || updatedAt,
    }]
  })
  const debts = snapshot.debts.flatMap((row, index) => row.date ? [{
    id: row.source_key || `live-debt-${index + 1}`, date: row.date.slice(0, 10),
    borrower: row.borrower as WalletId, lender: row.lender as WalletId, amount: row.amount,
    repaid: row.status.toLocaleLowerCase('id-ID') === 'open' ? 0 : row.amount,
    notes: row.notes, created_at: updatedAt, updated_at: updatedAt,
  }] : [])
  return {
    version: 3, mode: 'live', projects, transactions, debts, audit: [], updated_at: updatedAt,
    live_wallets: snapshot.wallets, live_cash_trend: snapshot.cash_trend,
  }
}

export async function loadSnapshot(local = false): Promise<DashboardSnapshot> {
  const url = local ? '/data/dashboard-snapshot.json' : (import.meta.env.VITE_SNAPSHOT_URL || '/live-api/snapshot')
  const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) throw new Error(`Snapshot unavailable (${response.status})`)
  return response.json() as Promise<DashboardSnapshot>
}
