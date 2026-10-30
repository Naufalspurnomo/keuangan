import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectTransactionsWorkspace from './ProjectTransactionsWorkspace'
import { seedFinanceWorkspace } from './financeWorkspace'

afterEach(cleanup)

describe('ProjectTransactionsWorkspace', () => {
  it('renders exact project identity and strict project-owned rows', () => {
    const seeded = seedFinanceWorkspace()
    const project = seeded.projects.find((item) => seeded.transactions.some((row) => row.project_id === item.id))!
    const workspace = {
      ...seeded,
      transactions: seeded.transactions.map((row) => ({
        ...row,
        notes: row.project_id === project.id ? `Milik proyek ${row.id}` : `Milik proyek lain ${row.id}`,
      })),
    }
    const ownRows = workspace.transactions.filter((row) => row.project_id === project.id)
    const foreignRow = workspace.transactions.find((row) => row.project_id && row.project_id !== project.id)!
    render(<ProjectTransactionsWorkspace workspace={workspace} project={project} onBack={vi.fn()} onAdd={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />)

    expect(screen.getByRole('heading', { name: project.name })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Kembali ke Proyek' })).toBeTruthy()
    expect(screen.queryByLabelText('Filter aktivitas')).toBeNull()
    expect(screen.queryByLabelText('Filter proyek')).toBeNull()
    for (const row of ownRows) expect(screen.getByText(row.notes)).toBeTruthy()
    expect(screen.queryByText(foreignRow.notes)).toBeNull()
  })

  it('searches within the project and forwards project and row actions', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => workspace.transactions.filter((row) => row.project_id === item.id).length > 1)!
    const rows = workspace.transactions.filter((row) => row.project_id === project.id)
    const onAdd = vi.fn()
    const onEdit = vi.fn()
    const onDelete = vi.fn()
    render(<ProjectTransactionsWorkspace workspace={workspace} project={project} onBack={vi.fn()} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />)

    fireEvent.click(screen.getByRole('button', { name: 'Tambah transaksi' }))
    expect(onAdd).toHaveBeenCalledWith(project)
    fireEvent.change(screen.getByLabelText('Cari transaksi'), { target: { value: rows[0].notes } })
    expect(screen.getByText(rows[0].notes)).toBeTruthy()
    if (rows[1]) expect(screen.queryByText(rows[1].notes)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: `Ubah transaksi ${rows[0].notes}` }))
    expect(onEdit).toHaveBeenCalledWith(rows[0])
    fireEvent.click(screen.getByRole('button', { name: `Hapus transaksi ${rows[0].notes}` }))
    expect(onDelete).toHaveBeenCalledWith(rows[0])
  })

  it('shows a project-specific empty state', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => !workspace.transactions.some((row) => row.project_id === item.id))!
    render(<ProjectTransactionsWorkspace workspace={workspace} project={project} onBack={vi.fn()} onAdd={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />)
    expect(screen.getByText(`Belum ada transaksi untuk ${project.name}`)).toBeTruthy()
    expect(within(screen.getByLabelText(`Ringkasan ${project.name}`)).getByText('0')).toBeTruthy()
  })
})
