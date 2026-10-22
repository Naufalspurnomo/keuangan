import type { DashboardMeta, Overview, QualityRow, Transaction } from './types'

export interface WalletSnapshot { source_key: string; name: string; balance: number }
export interface DebtSnapshot { source_key: string; date: string | null; amount: number; notes: string; borrower: string; lender: string; status: string }
export interface CashTrendPoint { month: string; balance: number; net_movement: number }
export interface ProjectSummary { name: string; net_cashflow: number }
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

export async function loadSnapshot(local = false): Promise<DashboardSnapshot> {
  const url = local ? '/data/dashboard-snapshot.json' : '/live-api/snapshot'
  const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) throw new Error(`Snapshot unavailable (${response.status})`)
  return response.json() as Promise<DashboardSnapshot>
}
