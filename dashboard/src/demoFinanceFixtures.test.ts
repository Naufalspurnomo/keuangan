import { describe, expect, it } from 'vitest'

import { COMPANIES, PROJECT_STATUSES, projectTotals } from './financeWorkspace'
import { DEMO_SNAPSHOT_AT, seedDemoFinanceWorkspace } from './demoFinanceFixtures'

const DAY = 86_400_000
const ageBand = (days: number) => days <= 14 ? 0 : days <= 30 ? 1 : days <= 60 ? 2 : days <= 90 ? 3 : 4
const daysBetween = (start: string, end: string) => Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / DAY)

describe('explicit demo finance fixtures', () => {
  it('covers the diverse 2024–2026 portfolio without generated duplicate identities', () => {
    const workspace = seedDemoFinanceWorkspace()
    expect(workspace.projects.length).toBeGreaterThanOrEqual(36)
    expect(new Set(workspace.projects.map((project) => project.name)).size).toBe(workspace.projects.length)
    expect([...new Set(workspace.projects.map((project) => project.started_on.slice(0, 4)))]).toEqual(['2024', '2025', '2026'])
    for (const year of ['2024', '2025', '2026']) expect(workspace.projects.filter((project) => project.started_on.startsWith(year)).length).toBeGreaterThanOrEqual(12)
    for (const company of COMPANIES) expect(workspace.projects.some((project) => project.company === company)).toBe(true)
    for (const status of PROJECT_STATUSES) expect(workspace.projects.some((project) => project.status === status)).toBe(true)
    expect(workspace.projects.some((project) => project.started_on < '2025-01-01' && (project.completed_on ?? '9999') >= '2025-01-01')).toBe(true)
    expect(workspace.projects.some((project) => !workspace.transactions.some((transaction) => transaction.project_id === project.id))).toBe(true)
  })

  it('covers every active age and completed duration band at the fixed snapshot', () => {
    const workspace = seedDemoFinanceWorkspace()
    const snapshotDate = DEMO_SNAPSHOT_AT.slice(0, 10)
    const activeBands = new Set(workspace.projects.filter((project) => project.status === 'active').map((project) => ageBand(daysBetween(project.started_on, snapshotDate))))
    const completedBands = new Set(workspace.projects.filter((project) => project.status === 'completed').map((project) => ageBand(daysBetween(project.started_on, project.completed_on!))))
    expect([...activeBands].sort()).toEqual([0, 1, 2, 3, 4])
    expect([...completedBands].sort()).toEqual([0, 1, 2, 3, 4])
  })

  it('contains sparse and dense valid transaction histories with positive and negative project net', () => {
    const workspace = seedDemoFinanceWorkspace()
    const counts = workspace.projects.map((project) => workspace.transactions.filter((transaction) => transaction.project_id === project.id).length)
    expect(Math.min(...counts)).toBe(0)
    expect(Math.max(...counts)).toBe(5)
    expect(counts.every((count) => count >= 0 && count <= 5)).toBe(true)
    const nets = workspace.projects.map((project) => projectTotals(project, workspace.transactions).net)
    expect(nets.some((net) => net > 0)).toBe(true)
    expect(nets.some((net) => net < 0)).toBe(true)
    expect(workspace.projects.some((project) => {
      const rows = workspace.transactions.filter((transaction) => transaction.project_id === project.id)
      return rows.length > 0 && rows.every((transaction) => transaction.direction === 'income')
    })).toBe(true)
    for (const transaction of workspace.transactions.filter((row) => row.scope === 'project')) {
      const project = workspace.projects.find((candidate) => candidate.id === transaction.project_id)!
      expect(transaction.date >= project.started_on).toBe(true)
      expect(transaction.date <= (project.completed_on ?? DEMO_SNAPSHOT_AT.slice(0, 10))).toBe(true)
      expect(project.status).not.toBe('planned')
    }
  })

  it('returns isolated deterministic workspaces', () => {
    const first = seedDemoFinanceWorkspace()
    const second = seedDemoFinanceWorkspace()
    expect(first).toEqual(second)
    expect(first.updated_at).toBe(DEMO_SNAPSHOT_AT)
    first.projects[0].name = 'Mutated fixture'
    expect(second.projects[0].name).not.toBe('Mutated fixture')
  })
})
