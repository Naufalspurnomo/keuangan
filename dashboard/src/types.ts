export type Freshness = 'fresh' | 'aging' | 'stale'

export interface DashboardMeta {
  as_of: string
  freshness: Freshness
  data_completeness: {
    valid_rows: number
    invalid_rows: number
    completeness_pct: number
  }
}

export interface DashboardEnvelope<T> {
  version: 'dashboard.v1'
  data: T
  meta: DashboardMeta
  error: null | { code: string; message: string }
}

export interface Transaction {
  id: number
  transaction_date: string
  transaction_type: string
  amount: number
  wallet: string
  company: string
  project: string
  notes?: string
  internal_movement?: boolean
  invalid_reason?: string
  updated_at?: string
}

export interface Overview {
  metrics: {
    cash_balance: number
    operating_inflow: number
    operating_outflow: number
    net_operating_cashflow: number
    open_internal_debt: number
    project_cashflow: number
  }
  counts: { valid_rows: number; invalid_rows: number }
  labels: Record<string, string>
  drilldowns: Record<string, string>
}

export interface TransactionPage {
  items: Transaction[]
  next_cursor: string | null
}
