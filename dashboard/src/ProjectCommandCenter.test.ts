import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectCommandCenter, { projectAsOf, projectOverlapsYear, projectSnapshotDate, projectSnapshotYear, projectYearOptions } from './ProjectCommandCenter'
import { seedFinanceWorkspace } from './financeWorkspace'

afterEach(() => {
  cleanup()
  sessionStorage.clear()
})

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
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onComplete: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))
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
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onComplete: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))
    expect(screen.getAllByRole('button', { name: /Carry Over/ }).length).toBeGreaterThanOrEqual(2)
    expect(document.querySelector('[data-project-candle="Carry Over"]')).toBeTruthy()
  })

  it('paginates the project registry independently from the four lifecycle canvases', () => {
    const workspace = seedFinanceWorkspace()
    const onOpen = vi.fn()
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onComplete: vi.fn(), onDelete: vi.fn(), onOpen }))

    expect(screen.getByRole('navigation', { name: 'Pagination proyek' })).toBeTruthy()
    expect(screen.getByText('Halaman 1 / 2')).toBeTruthy()
    expect(screen.getAllByRole('region', { name: /Chart lifecycle/ })).toHaveLength(4)

    fireEvent.click(screen.getByRole('button', { name: 'Halaman proyek berikutnya' }))
    expect(screen.getByText('Halaman 2 / 2')).toBeTruthy()
    expect(screen.getAllByRole('region', { name: /Chart lifecycle/ })).toHaveLength(4)
  })

  it('places registry filters after the lifecycle chart and directly before the project registry', () => {
    const workspace = seedFinanceWorkspace()
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onComplete: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))

    const chart = screen.getByRole('region', { name: /Project lifecycle market/ })
    const filters = screen.getByRole('region', { name: 'Filter daftar proyek' })
    const registry = screen.getByRole('region', { name: /Daftar proyek/ })
    expect(chart.compareDocumentPosition(filters) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(filters.compareDocumentPosition(registry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('filters registry rows and count without changing lifecycle candles', () => {
    const workspace = seedFinanceWorkspace()
    const snapshotYear = projectSnapshotYear(workspace)
    const snapshotDate = workspace.updated_at.slice(0, 10)
    const yearProjects = workspace.projects.filter((project) => projectOverlapsYear(project, snapshotYear, snapshotDate))
    const company = yearProjects[0].company
    const expected = yearProjects.filter((project) => project.company === company).length
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onComplete: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))

    const candleCount = document.querySelectorAll('[data-project-candle]').length
    fireEvent.change(screen.getByRole('combobox', { name: 'Perusahaan' }), { target: { value: company } })

    const filters = screen.getByRole('region', { name: 'Filter daftar proyek' })
    const registry = screen.getByRole('region', { name: `Daftar proyek ${snapshotYear}` })
    expect(filters.textContent).toContain(`${expected} proyek`)
    expect(registry.querySelectorAll(':scope > article')).toHaveLength(Math.min(expected, 12))
    expect(document.querySelectorAll('[data-project-candle]')).toHaveLength(candleCount)
  })

  it('gives every registry row and action an explicit accessible label', () => {
    const workspace = seedFinanceWorkspace()
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onComplete: vi.fn(), onDelete: vi.fn(), onOpen: vi.fn() }))

    const registry = screen.getByRole('region', { name: /Daftar proyek/ })
    for (const row of registry.querySelectorAll(':scope > article')) {
      const projectName = row.querySelector('.project-register-main strong')?.textContent ?? ''
      expect(within(row as HTMLElement).getByRole('button', { name: `Buka proyek ${projectName}` })).toBeTruthy()
      expect(within(row as HTMLElement).getByRole('button', { name: `Ubah ${projectName}` })).toBeTruthy()
      expect(within(row as HTMLElement).getByRole('button', { name: `Hapus ${projectName}` })).toBeTruthy()
      const completion = within(row as HTMLElement).queryByRole('button', { name: `Selesaikan ${projectName}` })
      if (row.querySelector('.status-chip.active')) expect(completion).toBeTruthy()
      else expect(completion).toBeNull()
    }
  })

  it('exposes exactly one quick-completion action only for active registry rows', () => {
    const workspace = seedFinanceWorkspace()
    const active = workspace.projects.find((project) => project.status === 'active' && project.started_on.startsWith('2026'))!
    const completed = workspace.projects.find((project) => project.status === 'completed' && project.started_on.startsWith('2026'))!
    const planned = workspace.projects.find((project) => project.status === 'planned' && project.started_on.startsWith('2026'))!
    workspace.projects = [active, completed, planned]
    workspace.updated_at = `${active.started_on.slice(0, 4)}-12-31T10:00:00.000Z`
    const onComplete = vi.fn()
    render(createElement(ProjectCommandCenter, { workspace, onAdd: vi.fn(), onEdit: vi.fn(), onComplete, onDelete: vi.fn(), onOpen: vi.fn() }))

    const action = screen.getByRole('button', { name: `Selesaikan ${active.name}` })
    expect(screen.getAllByRole('button', { name: `Selesaikan ${active.name}` })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: `Selesaikan ${completed.name}` })).toBeNull()
    expect(screen.queryByRole('button', { name: `Selesaikan ${planned.name}` })).toBeNull()
    fireEvent.click(action)
    expect(onComplete).toHaveBeenCalledWith(active)
  })
})
