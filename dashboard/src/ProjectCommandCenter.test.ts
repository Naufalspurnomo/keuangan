import { createElement } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectCommandCenter, { projectAsOf, projectOverlapsYear, projectSnapshotDate, projectSnapshotYear, projectYearOptions } from './ProjectCommandCenter'
import { seedFinanceWorkspace } from './financeWorkspace'

afterEach(cleanup)

describe('projectAsOf', () => {
  it('stops a current-year active project at today instead of future year-end', () => {
    const now = new Date('2026-10-28T12:00:00+07:00')
    expect(projectAsOf(2026, now).getTime()).toBe(now.getTime())
  })

  it('uses year-end for historical project cohorts', () => {
    const now = new Date('2026-10-28T12:00:00+07:00')
    const historical = projectAsOf(2025, now)
    expect(historical.getFullYear()).toBe(2025)
    expect(historical.getMonth()).toBe(11)
    expect(historical.getDate()).toBe(31)
  })

  it('includes and selects the snapshot year even when that year has no projects', () => {
    const workspace = seedFinanceWorkspace()
    workspace.updated_at = '2026-01-01T00:30:00.000Z'
    workspace.projects = workspace.projects.filter((project) => !project.started_on.startsWith('2026-'))
    expect(projectSnapshotYear(workspace)).toBe(2026)
    expect(projectSnapshotDate(workspace).getFullYear()).toBe(2026)
    expect(projectSnapshotDate(workspace).getMonth()).toBe(0)
    expect(projectSnapshotDate(workspace).getDate()).toBe(1)
    expect(projectYearOptions(workspace)).toContain(2026)
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))
    expect(screen.getByText('TAHUN PROYEK').parentElement?.textContent).toContain('2026')
    for (const company of ['Holla', 'Hojja', 'Texturin Bali', 'Texturin Surabaya']) {
      expect(screen.getByRole('region', { name: `Chart lifecycle ${company}` })).toBeTruthy()
    }
  })

  it('carries projects into every selected year their lifecycle overlaps', () => {
    const workspace = seedFinanceWorkspace()
    workspace.updated_at = '2026-10-28T10:00:00.000Z'
    const carry = { ...workspace.projects[0], id: 'carry-over', name: 'Carry Over', status: 'active' as const, started_on: '2025-12-20', completed_on: null }
    workspace.projects = [carry]
    expect(projectYearOptions(workspace)).toEqual([2025, 2026])
    expect(projectOverlapsYear(carry, 2026, '2026-10-28')).toBe(true)
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))
    expect(screen.getAllByRole('button', { name: /Carry Over/ }).length).toBeGreaterThanOrEqual(2)
    expect(document.querySelector('[data-project-candle="Carry Over"]')).toBeTruthy()
  })
})
