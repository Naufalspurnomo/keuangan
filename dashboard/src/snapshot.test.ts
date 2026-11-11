import { describe, expect, it } from 'vitest'

import { snapshotFinanceWorkspace, type DashboardSnapshot } from './snapshot'

const PROJECT_ID = '00000000-0000-4000-8000-000000000001'

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
      project_id: PROJECT_ID,
      scope: 'project',
      category: 'Gaji',
      recorded_by: 'Admin',
      input_source: 'WhatsApp',
      evidence_source: 'media_ocr',
      ocr_mode: 'vision',
      ocr_confidence: '0.98',
      notes: 'Termin',
    }],
    debts: [],
    cash_trend: [],
    project_summaries: [{
      name: 'Surabaya Office',
      project_id: PROJECT_ID,
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

  it('preserves cost category and evidence provenance after reload', () => {
    const transaction = snapshotFinanceWorkspace(snapshot('HOLLA')).transactions[0]

    expect(transaction).toMatchObject({
      category: 'Gaji', recorded_by: 'Admin', input_source: 'WhatsApp',
      evidence_source: 'media_ocr', ocr_mode: 'vision', ocr_confidence: '0.98',
    })
  })

  it('keeps office spending outside every project business unit', () => {
    const source = snapshot('HOLLA')
    source.transactions[0] = {
      ...source.transactions[0],
      scope: 'office', project: 'Operasional', company: 'HOLLA', office_category: 'ListrikAir',
    }
    source.project_summaries = []

    const transaction = snapshotFinanceWorkspace(source).transactions[0]
    expect(transaction).toMatchObject({ scope: 'office', company: null, project_id: null, wallet: 'CV HB(101)' })
  })

  it('keeps the canonical project UUID for project routes and transaction relations after reload', () => {
    const source = snapshot('HOLLA')
    const projectId = '00000000-0000-4000-8000-000000000001'
    source.project_summaries[0].project_id = projectId
    source.transactions[0].project_id = projectId

    const workspace = snapshotFinanceWorkspace(source)

    expect(workspace.projects[0].id).toBe(projectId)
    expect(workspace.transactions[0].project_id).toBe(projectId)
  })

  it('normalizes unambiguous historical wallet labels without creating duplicate units', () => {
    const source = snapshot('TX SBY')
    source.transactions[0].wallet = 'TX SBY'
    const project = snapshotFinanceWorkspace(source).projects[0]

    expect(project.write_mapping).toEqual({ wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya', project: 'Surabaya Office' })
  })

  it('uses exact project UUIDs when names are duplicated or renamed', () => {
    const source = snapshot('HOLLA')
    const secondId = '00000000-0000-4000-8000-000000000002'
    source.project_summaries = [
      { ...source.project_summaries[0], name: 'Renamed Project' },
      { ...source.project_summaries[0], project_id: secondId, name: 'Renamed Project' },
    ]
    source.transactions = [
      { ...source.transactions[0], project: 'Old Project Name' },
      { ...source.transactions[0], id: 2, source_key: 'row:2', project_id: secondId },
    ]

    const workspace = snapshotFinanceWorkspace(source)

    expect(workspace.projects.map((project) => project.id)).toEqual([PROJECT_ID, secondId])
    expect(workspace.transactions.map((row) => row.project_id)).toEqual([PROJECT_ID, secondId])
  })

  it('excludes project rows without a canonical UUID instead of coercing them to office', () => {
    const source = snapshot('HOLLA')
    delete source.transactions[0].project_id

    const workspace = snapshotFinanceWorkspace(source)

    expect(workspace.transactions).toEqual([])
  })

  it('excludes project summaries without canonical UUIDs from routable projects', () => {
    const source = snapshot('HOLLA')
    delete source.project_summaries[0].project_id

    const workspace = snapshotFinanceWorkspace(source)

    expect(workspace.projects).toEqual([])
    expect(workspace.transactions).toEqual([])
  })

  it('keeps explicit office rows while rejecting unresolved project rows', () => {
    const source = snapshot('HOLLA')
    source.transactions = [
      { ...source.transactions[0], id: 1, source_key: 'row:1', scope: 'project', project_id: '00000000-0000-4000-8000-999999999999' },
      { ...source.transactions[0], id: 2, source_key: 'row:2', scope: 'office', project_id: undefined, office_category: 'Administrasi' },
    ]

    const workspace = snapshotFinanceWorkspace(source)

    expect(workspace.transactions).toHaveLength(1)
    expect(workspace.transactions[0]).toMatchObject({ id: 'row:2', scope: 'office', project_id: null })
  })

  it('preserves cancelled lifecycle semantics', () => {
    const source = snapshot('HOLLA')
    source.project_summaries[0].lifecycle_status = 'cancelled'
    source.project_summaries[0].completed_on = '2026-10-22'

    const project = snapshotFinanceWorkspace(source).projects[0]

    expect(project.status).toBe('cancelled')
    expect(project.completed_on).toBe('2026-10-22')
  })
})
