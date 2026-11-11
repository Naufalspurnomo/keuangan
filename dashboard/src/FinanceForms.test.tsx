import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TransactionForm } from './FinanceForms'
import { seedFinanceWorkspace } from './financeWorkspace'

afterEach(cleanup)

describe('TransactionForm project lock', () => {
  it('pins creation to one project and submits immutable context', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'active')!
    const onSave = vi.fn()
    render(<TransactionForm projects={workspace.projects} lockedProjectId={project.id} onSave={onSave} onClose={vi.fn()} />)
    const dialog = screen.getByRole('dialog')

    expect(within(dialog).getByRole('heading', { name: `Tambah transaksi · ${project.name}` })).toBeTruthy()
    expect(within(dialog).queryByRole('group', { name: 'Pilih aktivitas' })).toBeNull()
    expect(within(dialog).queryByLabelText('Proyek *')).toBeNull()
    expect((within(dialog).getByLabelText('Perusahaan') as HTMLInputElement).value).toBe(project.company)
    expect((within(dialog).getByLabelText('Dompet') as HTMLInputElement).value).toBe(project.wallet)

    fireEvent.change(within(dialog).getByLabelText('Jumlah *'), { target: { value: '1250000' } })
    fireEvent.change(within(dialog).getByLabelText('Keterangan *'), { target: { value: 'Biaya terkunci QA' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan transaksi' }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ scope: 'project', project_id: project.id, company: project.company, wallet: project.wallet, notes: 'Biaya terkunci QA' }))
  })

  it('keeps editing pinned to the row project', () => {
    const workspace = seedFinanceWorkspace()
    const row = workspace.transactions.find((item) => item.scope === 'project')!
    const project = workspace.projects.find((item) => item.id === row.project_id)!
    const onSave = vi.fn()
    render(<TransactionForm projects={workspace.projects} transaction={row} lockedProjectId={project.id} onSave={onSave} onClose={vi.fn()} />)
    expect(screen.getByRole('heading', { name: `Ubah transaksi · ${project.name}` })).toBeTruthy()
    expect(screen.queryByLabelText('Proyek *')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Simpan perubahan' }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ scope: 'project', project_id: project.id }))
  })

  it('submits the selected wallet for office spending', () => {
    const workspace = seedFinanceWorkspace()
    const onSave = vi.fn()
    render(<TransactionForm projects={workspace.projects} initialScope="office" onSave={onSave} onClose={vi.fn()} />)

    expect(screen.queryByRole('group', { name: 'Pilih aktivitas' })).toBeNull()
    fireEvent.change(screen.getByLabelText('Dompet *'), { target: { value: 'TX Bali' } })
    fireEvent.change(screen.getByLabelText('Jumlah *'), { target: { value: '500000' } })
    fireEvent.change(screen.getByLabelText('Keterangan *'), { target: { value: 'Biaya kantor Bali' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan transaksi' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ scope: 'office', wallet: 'TX Bali', company: null, project_id: null }))
  })

  it('fails closed when a live project has no authoritative wallet and unit mapping', () => {
    const workspace = seedFinanceWorkspace()
    const projects = workspace.projects.map(({ write_mapping: _mapping, ...project }) => project)
    const onSave = vi.fn()
    render(<TransactionForm projects={projects} initialScope="project" liveWrite currentDate="2026-11-10" onSave={onSave} onClose={vi.fn()} />)

    expect(screen.queryByRole('group', { name: 'Pilih aktivitas' })).toBeNull()
    expect(screen.queryByText(/Belum ada proyek aktif/)).toBeNull()

    expect(screen.getByLabelText('Dompet proyek')).toHaveValue('')
    expect(screen.getByLabelText('Unit usaha proyek')).toHaveValue('')
    fireEvent.change(screen.getByLabelText('Jumlah *'), { target: { value: '500000' } })
    fireEvent.change(screen.getByLabelText('Keterangan *'), { target: { value: 'Bahan proyek pertama' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan transaksi' }))

    expect(screen.getByText('Pencatatan belum tersedia untuk pilihan ini.')).toBeTruthy()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('pins a live project transaction to its authoritative wallet and unit', () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'active')!
    const mapped = { ...project, write_mapping: { wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya', project: project.id } }
    const onSave = vi.fn()
    render(<TransactionForm projects={[mapped]} lockedProjectId={mapped.id} liveWrite currentDate="2026-11-10" onSave={onSave} onClose={vi.fn()} />)

    expect(screen.getByLabelText('Dompet proyek')).toHaveValue('TX SBY(216)')
    expect(screen.getByLabelText('Unit usaha proyek')).toHaveValue('TEXTURIN-Surabaya')
    expect(screen.queryByText('TX SBY', { selector: 'option' })).toBeNull()
    fireEvent.change(screen.getByLabelText('Jumlah *'), { target: { value: '500000' } })
    fireEvent.change(screen.getByLabelText('Keterangan *'), { target: { value: 'Bahan proyek pertama' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan transaksi' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya', project_id: mapped.id }))
  })

  it('selects the first active project when production projects arrive after the modal opens', () => {
    const workspace = seedFinanceWorkspace()
    const projects = workspace.projects.filter((project) => project.status === 'active')
    const onSave = vi.fn()
    const view = render(
      <TransactionForm projects={[]} initialScope="project" liveWrite currentDate="2026-11-10" onSave={onSave} onClose={vi.fn()} />,
    )
    expect(screen.getByText('Belum ada proyek aktif. Buat atau aktifkan proyek sebelum mencatat transaksi proyek.')).toBeTruthy()

    view.rerender(
      <TransactionForm projects={projects} initialScope="project" liveWrite currentDate="2026-11-10" onSave={onSave} onClose={vi.fn()} />,
    )

    expect((screen.getByLabelText('Proyek *') as HTMLSelectElement).value).toBe(projects[0].id)
  })

  it('rejects a missing locked project visibly', () => {
    const workspace = seedFinanceWorkspace()
    const onSave = vi.fn()
    render(<TransactionForm projects={workspace.projects} lockedProjectId="missing" onSave={onSave} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Jumlah *'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Keterangan *'), { target: { value: 'Tidak boleh' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan transaksi' }))
    expect(screen.getByRole('alert').textContent).toContain('Proyek terkunci tidak tersedia')
    expect(onSave).not.toHaveBeenCalled()
  })
})
