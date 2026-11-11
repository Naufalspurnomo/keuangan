import type { DashboardMeta, Overview, QualityRow, Transaction } from './types'
import type { CompanyId, FinanceWorkspace, OfficeCategory, WalletId } from './financeWorkspace'
import { normalizeCanonicalPair } from './transactionMappings'

export interface WalletSnapshot { source_key: string; name: string; balance: number }
export interface DebtSnapshot { source_key: string; date: string | null; amount: number; notes: string; borrower: string; lender: string; status: string; project_id?: string | null }
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
  lifecycle_status?: 'active' | 'completed' | 'cancelled' | 'unmarked'
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
  const projects = snapshot.project_summaries
    .filter((project): project is ProjectSummary & { project_id: string } => Boolean(project.project_id))
    .map((project) => {
    const matching = snapshot.transactions.filter((row) => row.project_id === project.project_id)
    const first = matching[0]
    const mappings = new Map(
      matching
        .map((row) => normalizeCanonicalPair(row.wallet, row.company))
        .filter((pair) => pair !== undefined)
        .map((pair) => [`${pair.wallet}\u0000${pair.company}`, { wallet: pair.wallet, company: pair.company, project: project.name }]),
    )
    const writeMapping = mappings.size === 1 ? [...mappings.values()][0] : undefined
    const startedOn = project.started_on || project.first_activity_on || matching.map((row) => row.transaction_date).sort()[0]
      || snapshot.meta.data_through || updatedAt.slice(0, 10)
    const status = project.lifecycle_status === 'completed'
      ? 'completed' as const
      : project.lifecycle_status === 'cancelled'
        ? 'cancelled' as const
        : project.lifecycle_status === 'active'
          ? 'active' as const
          : 'planned' as const
    const terminal = status === 'completed' || status === 'cancelled'
    return {
      id: project.project_id,
      name: project.name,
      company: uiCompany(first?.company || ''),
      wallet: (first?.wallet || '') as WalletId,
      status,
      started_on: startedOn,
      completed_on: terminal ? (project.completed_on || project.last_activity_on || null) : null,
      client: '', contract_value: null, notes: '', created_at: updatedAt, updated_at: updatedAt,
      presensi_project_id: project.project_id,
      ...(writeMapping ? { write_mapping: writeMapping } : {}),
    }
  })
  const projectsById = new Map(projects.map((project) => [project.id, project]))
  const transactions = snapshot.transactions.flatMap((row) => {
    if (row.scope === 'internal_transfer' || row.internal_movement) return []
    const office = row.scope === 'office'
    const project = !office && row.project_id ? projectsById.get(row.project_id) : undefined
    if (!office && !project) return []
    return [{
      id: row.source_key || `live-transaction-${row.id}`,
      date: row.transaction_date.slice(0, 10),
      direction: row.transaction_type === 'Pemasukan' ? 'income' as const : 'expense' as const,
      amount: row.amount,
      scope: office ? 'office' as const : 'project' as const,
      wallet: row.wallet as WalletId,
      company: office ? null : uiCompany(row.company),
      project_id: project?.id ?? null,
      office_category: office ? (row.office_category || 'Lainnya') as OfficeCategory : null,
      category: row.category ?? null,
      recorded_by: row.recorded_by ?? null,
      input_source: row.input_source ?? null,
      evidence_source: row.evidence_source,
      ocr_mode: row.ocr_mode ?? null,
      ocr_confidence: row.ocr_confidence ?? null,
      notes: row.notes || '', created_at: row.updated_at || updatedAt, updated_at: row.updated_at || updatedAt,
    }]
  })
  const debts = snapshot.debts.flatMap((row, index) => row.date ? [{
    id: row.source_key || `live-debt-${index + 1}`, date: row.date.slice(0, 10),
    borrower: row.borrower as WalletId, lender: row.lender as WalletId, amount: row.amount,
    repaid: row.status.toLocaleLowerCase('id-ID') === 'open' ? 0 : row.amount,
    project_id: row.project_id ?? null,
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
