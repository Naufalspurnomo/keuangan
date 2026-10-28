import { createElement } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectCommandCenter, { projectAsOf, projectSnapshotYear, projectYearOptions } from './ProjectCommandCenter'
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
    workspace.updated_at = '2027-02-03T10:00:00.000Z'
    workspace.projects = workspace.projects.filter((project) => !project.started_on.startsWith('2027-'))
    expect(projectSnapshotYear(workspace)).toBe(2027)
    expect(projectYearOptions(workspace)).toContain(2027)
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))
    expect(screen.getByText('TAHUN PROYEK').parentElement?.textContent).toContain('2027')
    for (const company of ['Holla', 'Hojja', 'Texturin Bali', 'Texturin Surabaya']) {
      expect(screen.getByRole('region', { name: `Chart lifecycle ${company}` })).toBeTruthy()
    }
  })
})
