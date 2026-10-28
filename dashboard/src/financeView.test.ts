import { describe, expect, it } from 'vitest'

import { buildReportModel, defaultReportFilters } from './financeView'
import { seedFinanceWorkspace } from './financeWorkspace'

describe('finance report model', () => {
  it('uses one filtered model for preview and PDF with complete scope metadata', () => {
    const workspace = seedFinanceWorkspace()
    const filters = { ...defaultReportFilters(workspace), scope: 'office' as const, wallet: 'TX Bali' as const, direction: 'expense' as const }
    const model = buildReportModel(workspace, filters, '2026-10-27T10:00:00.000Z')
    expect(model.rows).toHaveLength(1)
    expect(model.rows[0]).toMatchObject({ scope: 'office', wallet: 'TX Bali', direction: 'expense' })
    expect(model.totals.expense).toBe(model.rows[0].amount)
    expect(model.totals.officeExpense).toBe(model.rows[0].amount)
    expect(model.scopeText).toHaveLength(7)
    expect(model.scopeText).toContain('TX Bali')
    expect(model.scopeText).toContain('Operasional Kantor')
    expect(model.scopeText).toContain('Pengeluaran')
  })

  it('keeps report totals reconciled for all transactions', () => {
    const workspace = seedFinanceWorkspace()
    const model = buildReportModel(workspace, defaultReportFilters(workspace), '2026-10-27T10:00:00.000Z')
    expect(model.totals.net).toBe(model.totals.income - model.totals.expense)
    expect(model.totals.expense).toBe(model.totals.projectExpense + model.totals.officeExpense)
    expect(model.rows).toHaveLength(workspace.transactions.length)
  })
})
