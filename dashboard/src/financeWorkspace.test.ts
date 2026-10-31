import { describe, expect, it } from 'vitest'

import {
  COMPANY_WALLET,
  FinanceValidationError,
  createDebt,
  createProject,
  createTransaction,
  deleteProject,
  isFinanceWorkspace,
  projectTotals,
  projectYear,
  resetFinanceWorkspace,
  seedFinanceWorkspace,
  updateProject,
  validateTransactionInput,
  workspaceTotals,
  type ProjectInput,
} from './financeWorkspace'

const newProject = (overrides: Partial<ProjectInput> = {}): ProjectInput => ({
  name: 'Kantor Baru',
  company: 'Holla',
  status: 'active',
  started_on: '2026-06-01',
  completed_on: null,
  client: 'PT Contoh',
  contract_value: 75_000_000,
  notes: '',
  ...overrides,
})

describe('demo finance workspace', () => {
  it('seeds exact multi-year completion ratios and canonical wallet ownership', () => {
    const workspace = seedFinanceWorkspace()
    const summary = [2024, 2025, 2026].map((year) => {
      const projects = workspace.projects.filter((project) => projectYear(project) === year)
      return [year, projects.filter((project) => project.status === 'completed').length, projects.length]
    })
    expect(summary).toEqual([[2024, 12, 12], [2025, 9, 12], [2026, 5, 12]])
    expect(workspace.projects.every((project) => project.wallet === COMPANY_WALLET[project.company])).toBe(true)
  })

  it('creates projects with a derived compatible wallet and rejects duplicate names per company', () => {
    const workspace = seedFinanceWorkspace()
    const next = createProject(workspace, newProject())
    const created = next.projects.at(-1)!
    expect(created.wallet).toBe('CV HB')
    expect(next.audit.at(-1)?.entity).toBe('project')
    expect(() => createProject(next, newProject({ name: ' kantor baru ' }))).toThrow(FinanceValidationError)
    expect(() => createProject(next, newProject({ company: 'Texturin Bali' }))).not.toThrow()
  })

  it('requires completion dates only for completed projects', () => {
    const workspace = seedFinanceWorkspace()
    expect(() => createProject(workspace, newProject({ status: 'completed' }))).toThrow('Tanggal selesai wajib diisi')
    expect(() => createProject(workspace, newProject({ status: 'completed', completed_on: '2026-05-01' }))).toThrow('sebelum tanggal mulai')
    expect(createProject(workspace, newProject({ status: 'completed', completed_on: '2026-06-30' })).projects.at(-1)?.completed_on).toBe('2026-06-30')
  })

  it('rejects impossible calendar dates instead of normalizing them', () => {
    const workspace = seedFinanceWorkspace()
    expect(() => createProject(workspace, newProject({ started_on: '2026-02-31' }))).toThrow('tidak valid')
    const project = workspace.projects.find((item) => item.status === 'active')!
    expect(() => createTransaction(workspace, {
      date: '2026-04-31', direction: 'expense', amount: 500_000, scope: 'project', wallet: project.wallet,
      company: project.company, project_id: project.id, office_category: null, notes: 'Tanggal salah',
    })).toThrow('tidak valid')
  })

  it('derives project transaction company and wallet, never trusting supplied mismatches', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.company === 'Texturin Bali')!
    const clean = validateTransactionInput({
      date: project.started_on, direction: 'expense', amount: 500_000, scope: 'project', wallet: 'CV HB', company: 'Holla',
      project_id: project.id, office_category: null, notes: 'Material',
    }, workspace)
    expect(clean.wallet).toBe('TX Bali')
    expect(clean.company).toBe('Texturin Bali')
    expect(clean.office_category).toBeNull()
  })

  it('separates office spending from projects and limits it to expenses', () => {
    const workspace = seedFinanceWorkspace()
    const next = createTransaction(workspace, {
      date: '2026-10-02', direction: 'expense', amount: 500_000, scope: 'office', wallet: 'TX SBY', company: 'Holla',
      project_id: workspace.projects[0].id, office_category: 'Listrik & utilitas', notes: 'Listrik kantor',
    })
    const created = next.transactions.at(-1)!
    expect(created.project_id).toBeNull()
    expect(created.company).toBeNull()
    expect(created.wallet).toBe('TX SBY')
    expect(() => createTransaction(workspace, { ...created, direction: 'income' })).toThrow('hanya mencatat pengeluaran')
  })

  it('propagates project company changes to linked transactions without breaking ownership', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'active')!
    const next = updateProject(workspace, project.id, { ...project, company: 'Texturin Surabaya' })
    expect(next.projects.find((item) => item.id === project.id)?.wallet).toBe('TX SBY')
    expect(next.transactions.filter((item) => item.project_id === project.id).every((item) => item.wallet === 'TX SBY' && item.company === 'Texturin Surabaya')).toBe(true)
  })

  it('prevents planned projects from carrying actual transactions', () => {
    const workspace = seedFinanceWorkspace()
    const active = workspace.projects.find((item) => item.status === 'active' && workspace.transactions.some((row) => row.project_id === item.id))!
    expect(() => updateProject(workspace, active.id, { ...active, status: 'planned' })).toThrow('tidak dapat berstatus Direncanakan')
    const planned = workspace.projects.find((item) => item.status === 'planned')!
    expect(() => createTransaction(workspace, {
      date: planned.started_on, direction: 'expense', amount: 500_000, scope: 'project', wallet: planned.wallet,
      company: planned.company, project_id: planned.id, office_category: null, notes: 'Belum boleh',
    })).toThrow('belum dapat memiliki transaksi')
  })

  it('cannot complete a project before its latest transaction', () => {
    const created = createProject(seedFinanceWorkspace(), newProject({ name: 'Batas Selesai' }))
    const project = created.projects.at(-1)!
    const withTransaction = createTransaction(created, {
      date: '2026-06-10', direction: 'income', amount: 500_000, scope: 'project', wallet: project.wallet,
      company: project.company, project_id: project.id, office_category: null, notes: 'Pembayaran terakhir',
    })

    expect(() => updateProject(withTransaction, project.id, {
      ...project, status: 'completed', completed_on: '2026-06-09',
    })).toThrow('Tanggal selesai tidak boleh sebelum transaksi terakhir.')
    expect(() => updateProject(withTransaction, project.id, {
      ...project, status: 'completed', completed_on: '2026-06-10',
    })).not.toThrow()
  })

  it('rejects project transactions after completion', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'completed')!

    expect(() => createTransaction(workspace, {
      date: '2026-12-31', direction: 'income', amount: 500_000, scope: 'project', wallet: project.wallet,
      company: project.company, project_id: project.id, office_category: null, notes: 'Pembayaran terlambat',
    })).toThrow('Tanggal transaksi tidak boleh setelah proyek selesai.')
  })

  it('blocks deletion of a project that still has financial records', () => {
    const workspace = seedFinanceWorkspace()
    const linked = workspace.projects.find((project) => workspace.transactions.some((transaction) => transaction.project_id === project.id))!
    expect(() => deleteProject(workspace, linked.id)).toThrow('masih memiliki transaksi')
  })

  it('keeps integer totals deterministic', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'completed')!
    const projectSummary = projectTotals(project, workspace.transactions)
    expect(projectSummary.net).toBe(projectSummary.income - projectSummary.expense)
    const total = workspaceTotals(workspace)
    expect(total.net).toBe(total.income - total.expense)
    expect(Number.isSafeInteger(total.office)).toBe(true)
  })

  it('validates internal debt without changing consolidated cash', () => {
    const workspace = seedFinanceWorkspace()
    const next = createDebt(workspace, { date: '2026-10-03', borrower: 'TX Bali', lender: 'CV HB', amount: 5_000_000, repaid: 1_000_000, notes: 'Dana sementara' })
    expect(next.debts.at(-1)?.amount).toBe(5_000_000)
    expect(() => createDebt(workspace, { date: '2026-10-03', borrower: 'CV HB', lender: 'CV HB', amount: 5_000_000, repaid: 0, notes: 'Tidak valid' })).toThrow('harus berbeda')
    expect(() => createDebt(workspace, { date: '2026-10-03', borrower: 'TX Bali', lender: 'CV HB', amount: 5_000_000, repaid: 6_000_000, notes: 'Tidak valid' })).toThrow('melebihi hutang')
    expect(workspaceTotals(next)).toEqual(workspaceTotals(workspace))
  })

  it('rejects malformed and relationally inconsistent persisted workspaces', () => {
    const workspace = seedFinanceWorkspace()
    expect(isFinanceWorkspace(workspace)).toBe(true)
    expect(isFinanceWorkspace({ ...workspace, projects: [{ ...workspace.projects[0], wallet: 'TX Bali' }] })).toBe(false)
    expect(isFinanceWorkspace({ ...workspace, projects: [{ ...workspace.projects[0], name: '   ' }] })).toBe(false)
    expect(isFinanceWorkspace({ ...workspace, projects: [...workspace.projects, { ...workspace.projects[0], id: 'duplicate-name' }] })).toBe(false)
    expect(isFinanceWorkspace({ ...workspace, transactions: [{ ...workspace.transactions[0], project_id: 'missing-project' }] })).toBe(false)
    expect(isFinanceWorkspace({ ...workspace, transactions: [{ ...workspace.transactions[0], wallet: 'TX Bali' }] })).toBe(false)
    expect(isFinanceWorkspace({ ...workspace, transactions: [{ ...workspace.transactions[0], company: 'Texturin Bali' }] })).toBe(false)
    const completed = workspace.projects.find((project) => project.status === 'completed')!
    const completedTransaction = workspace.transactions.find((transaction) => transaction.project_id === completed.id)!
    expect(isFinanceWorkspace({ ...workspace, transactions: workspace.transactions.map((transaction) => transaction.id === completedTransaction.id
      ? { ...transaction, date: '2026-12-31' }
      : transaction) })).toBe(false)
    expect(isFinanceWorkspace({ ...workspace, debts: [{ ...workspace.debts[0], repaid: workspace.debts[0].amount + 1 }] })).toBe(false)
    expect(isFinanceWorkspace({ ...workspace, transactions: [{ ...workspace.transactions[0], amount: Number.MAX_SAFE_INTEGER + 1 }] })).toBe(false)
  })

  it('rejects aggregate totals that exceed safe integer precision', () => {
    const workspace = { ...seedFinanceWorkspace(), transactions: [] }
    const first = createTransaction(workspace, {
      date: '2026-10-01', direction: 'expense', amount: Number.MAX_SAFE_INTEGER, scope: 'office', wallet: 'CV HB',
      company: null, project_id: null, office_category: 'Lainnya', notes: 'Batas aman pertama',
    })
    expect(() => createTransaction(first, {
      date: '2026-10-02', direction: 'expense', amount: Number.MAX_SAFE_INTEGER, scope: 'office', wallet: 'TX Bali',
      company: null, project_id: null, office_category: 'Lainnya', notes: 'Batas aman kedua',
    })).toThrow('melebihi batas aman')
    expect(first.transactions.filter((row) => row.notes.startsWith('Batas aman')).length).toBe(1)
  })

  it('keeps every mutation immutable and appends exactly one audit event', () => {
    const workspace = seedFinanceWorkspace()
    const next = createProject(workspace, newProject({ name: 'Audit Baru' }))
    expect(workspace.projects).toHaveLength(36)
    expect(workspace.audit).toHaveLength(0)
    expect(next.projects).toHaveLength(37)
    expect(next.audit).toHaveLength(1)
    expect(next.audit[0]).toMatchObject({ action: 'create', entity: 'project' })
  })

  it('resets demo data without deleting the append-only audit history', () => {
    const changed = createProject(seedFinanceWorkspace(), newProject({ name: 'Sebelum Reset' }))
    const reset = resetFinanceWorkspace(changed)
    expect(reset.projects).toHaveLength(36)
    expect(reset.audit).toHaveLength(2)
    expect(reset.audit.map((event) => event.action)).toEqual(['create', 'reset'])
  })

  it('keeps audit events beyond the former 500-event limit', () => {
    const workspace = { ...seedFinanceWorkspace(), audit: Array.from({ length: 500 }, (_, index) => ({ id: `event-${index}`, action: 'update' as const, entity: 'workspace' as const, entity_id: 'demo', at: new Date(2026, 0, 1, 0, 0, index).toISOString(), summary: `Event ${index}` })) }
    const next = resetFinanceWorkspace(workspace)
    expect(next.audit).toHaveLength(501)
    expect(next.audit[0].id).toBe('event-0')
    expect(next.audit.at(-1)?.action).toBe('reset')
  })
})
