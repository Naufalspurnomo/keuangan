import { describe, expect, it } from 'vitest'

import { buildReportModel, cashTrend, chartProjects, chartTransactions, chartWallets, defaultReportFilters, walletBalances } from './financeView'
import { seedFinanceWorkspace, workspaceTotals } from './financeWorkspace'

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

  it('derives every showcase chart from the same finance workspace', () => {
    const workspace = seedFinanceWorkspace()
    const transactions = chartTransactions(workspace)
    const wallets = chartWallets(workspace)
    const projects = chartProjects(workspace)
    const trend = cashTrend(workspace)

    expect(transactions).toHaveLength(workspace.transactions.length)
    const traceable = chartTransactions(workspace, true)
    expect(traceable).toHaveLength(workspace.transactions.length + 2)
    expect(traceable.filter((row) => row.transfer_scope === 'internal')).toHaveLength(2)
    expect(traceable.filter((row) => row.transfer_scope === 'internal').reduce((sum, row) => sum + (row.transaction_type === 'Pemasukan' ? row.amount : -row.amount), 0)).toBe(0)
    expect(projects).toHaveLength(workspace.projects.length)
    expect(wallets).toEqual(walletBalances(workspace).map((row) => ({
      source_key: `demo-wallet:${row.wallet}`,
      name: row.wallet,
      balance: row.balance,
    })))
    expect(trend).toHaveLength(12)
    expect(trend.at(-1)?.balance).toBe(workspaceTotals(workspace).net)
  })
})
