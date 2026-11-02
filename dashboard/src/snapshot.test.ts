import { describe, expect, it } from 'vitest'

import { snapshotFinanceWorkspace, type DashboardSnapshot } from './snapshot'

function snapshot(company: string): DashboardSnapshot {
  return {
    version: 'dashboard.snapshot.v1',
    meta: { as_of: '2026-10-21T12:00:00Z', freshness: 'fresh', data_completeness: { valid_rows: 1, invalid_rows: 0, completeness_pct: 100 } },
    overview: {
      metrics: { cash_balance: 0, operating_inflow: 0, operating_outflow: 0, net_operating_cashflow: 0, open_internal_debt: 0, project_cashflow: 0 },
      counts: { valid_rows: 1, invalid_rows: 0 },
      labels: { cash_balance: '', operating_inflow: '', operating_outflow: '', net_operating_cashflow: '', open_internal_debt: '', project_cashflow: '' },
      drilldowns: {},
    },
    wallets: [],
    transactions: [{
      id: 1,
      source_key: 'row:1',
      transaction_date: '2026-10-21',
      transaction_type: 'Pemasukan',
      amount: 100_000,
      wallet: 'CV HB(101)',
      company,
      project: 'Surabaya Office',
      scope: 'project',
      notes: 'Termin',
    }],
    debts: [],
    cash_trend: [],
    project_summaries: [{
      name: 'Surabaya Office',
      net_cashflow: 100_000,
      lifecycle_status: 'active',
      started_on: '2026-10-01',
    }],
  } as DashboardSnapshot
}

describe('snapshotFinanceWorkspace', () => {
  it.each([
    ['HOLLA', 'Holla'],
    ['Hollawall', 'Holla'],
    ['HOJJA', 'Hojja'],
    ['TEXTURIN-Surabaya', 'Texturin Surabaya'],
    ['TEXTURIN-Bali', 'Texturin Bali'],
  ])('normalizes backend company %s into the existing UI company %s', (source, expected) => {
    expect(snapshotFinanceWorkspace(snapshot(source)).projects[0].company).toBe(expected)
  })
})
