import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ProjectAuditPanel, ProjectDebtPanel, ProjectOverviewPanel } from './ProjectContextPanels'
import { seedFinanceWorkspace } from './financeWorkspace'

const workspace = seedFinanceWorkspace()
const project = workspace.projects[0]

// Keep project context exact: unrelated data must not leak into a detail route.
const exactWorkspace = {
  ...workspace,
  debts: [
    { ...workspace.debts[0], id: 'linked', project_id: project.id, notes: 'Modal proyek' },
    { ...workspace.debts[0], id: 'other', project_id: 'other-project', notes: 'Tidak terkait' },
  ],
  audit: [
    { ...workspace.audit[0], id: 'audit-linked', entity: 'project' as const, entity_id: project.id, summary: 'Status proyek diperbarui' },
    { ...workspace.audit[0], id: 'audit-other', entity: 'project' as const, entity_id: 'other-project', summary: 'Jangan tampil' },
  ],
}

afterEach(cleanup)

describe('project context panels', () => {
  it('summarizes only transactions bound to the selected canonical project id', () => {
    render(<ProjectOverviewPanel project={project} workspace={exactWorkspace} />)
    expect(screen.getByRole('heading', { name: 'Ringkasan proyek' })).toBeTruthy()
    expect(screen.getByText(project.name)).toBeTruthy()
    expect(screen.getByText(/transaksi tercatat/i)).toBeTruthy()
  })

  it('shows only explicitly project-linked debt and fails closed for unrelated debt', () => {
    render(<ProjectDebtPanel project={project} workspace={exactWorkspace} />)
    expect(screen.getByText('Modal proyek')).toBeTruthy()
    expect(screen.queryByText('Tidak terkait')).toBeNull()
  })

  it('shows only the selected project audit trail', () => {
    render(<ProjectAuditPanel project={project} workspace={exactWorkspace} />)
    expect(screen.getByText('Status proyek diperbarui')).toBeTruthy()
    expect(screen.queryByText('Jangan tampil')).toBeNull()
  })
})
