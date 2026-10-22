export type Freshness = 'fresh' | 'aging' | 'stale'

export interface DashboardMeta {
  as_of: string
  data_through?: string | null
  source?: string
  freshness: Freshness
  data_completeness: {
    valid_rows: number
    invalid_rows: number
    completeness_pct: number
  }
}

export interface Transaction {
  id: number
  source_key?: string
  transaction_date: string
  transaction_type: string
  amount: number
  wallet: string
  company: string
  project: string
  notes?: string
  internal_movement?: boolean
  transfer_scope?: 'internal' | 'external'
  invalid_reason?: string
  updated_at?: string
}

export interface QualityRow {
  source_key: string
  invalid_reason: string
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
