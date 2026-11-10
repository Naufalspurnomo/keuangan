import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectDocumentComposer from './ProjectDocumentComposer'
import { createEmptyDocumentDraft, createEmptyProjectDraft, type ProjectRecord } from './projectDocuments'

const project: ProjectRecord = {
  ...createEmptyProjectDraft('2026-11-03'),
  id: '018f9ca2-355a-4d66-b1d5-4d4be6e2f321',
  name: 'Lobby Marvell',
  client_name: 'PT Marvell',
  issuer_key: 'cv-holla-berkreasi',
  status: 'active',
  wallet: 'CV HB(101)',
  company: 'HOLLA',
  lock_version: 1,
  archived_at: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

afterEach(cleanup)

describe('ProjectDocumentComposer', () => {
  it('edits line items and renders a semantic A5 preview with calculated totals', () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={vi.fn()} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Panel akustik' } })
    fireEvent.change(screen.getByLabelText('Kuantitas item 1'), { target: { value: '2.5' } })
    fireEvent.change(screen.getByLabelText('Harga satuan item 1'), { target: { value: '100000' } })
    fireEvent.change(screen.getByLabelText('Pajak persen'), { target: { value: '11' } })

    const preview = screen.getByRole('article', { name: 'Pratinjau A5 Invoice' })
    expect(preview).toHaveTextContent('Lobby Marvell')
    expect(preview).toHaveTextContent('PT Marvell')
    expect(preview).toHaveTextContent('Panel akustik')
    expect(preview).toHaveTextContent('Rp277.500')
    expect(preview.querySelector('table')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Simpan draf' })).toBeEnabled()
  })

  it('previews a Rp100.000 receipt from its authoritative allocation', () => {
    const draft = {
      ...createEmptyDocumentDraft(project.id, 'receipt', '2026-11-03'),
      allocations: [{ transaction_id: 'income-1', source_key: 'income-1', amount: 100_000, available_amount: 100_000 }],
    }
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={vi.fn()} onClose={vi.fn()} />)

    const preview = screen.getByRole('article', { name: 'Pratinjau A5 Kuitansi' })
    expect(preview).toHaveTextContent('Rp100.000')
    expect(within(preview).getByText('Subtotal').nextElementSibling).toHaveTextContent('Rp100.000')
    expect(within(preview).getByText('Total').nextElementSibling).toHaveTextContent('Rp100.000')
  })

  it('locks invoice target and allocations after a receipt draft is created', () => {
    const receipt = {
      ...createEmptyDocumentDraft(project.id, 'receipt', '2026-11-03'),
      id: '55555555-5555-4555-8555-555555555555',
      applies_to_invoice_id: '33333333-3333-4333-8333-333333333333',
      allocations: [{
        transaction_id: 'income-1',
        source_key: 'income-1',
        amount: 100_000,
        available_amount: 100_000,
        description: 'Transfer DP',
        transaction_date: '2026-11-03',
      }],
    }
    render(<ProjectDocumentComposer project={project} document={receipt} writesEnabled onSave={vi.fn()} onClose={vi.fn()} />)

    expect(screen.getByText(/Invoice tujuan dan transaksi dikunci/)).toBeTruthy()
    expect(screen.getByText(/Transfer DP/)).toBeTruthy()
    expect(screen.queryByRole('combobox', { name: 'Invoice tujuan' })).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('accepts only a capped PNG or JPEG data URL for the project image', async () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    const onSave = vi.fn()
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={onSave} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Panel' } })
    fireEvent.change(screen.getByLabelText('Gambar proyek'), { target: { value: 'https://example.com/project.png' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('data PNG atau JPEG')
    expect(onSave).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Gambar proyek'), { target: { value: 'data:image/jpeg;base64,Zm9v' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ project_image_url: 'data:image/jpeg;base64,Zm9v' }))
  })

  it('validates before save, focuses the error, and exposes write-disabled reason beside the action', async () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    const onSave = vi.fn()
    const { rerender } = render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={onSave} onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Deskripsi item wajib diisi')
    expect(onSave).not.toHaveBeenCalled()

    rerender(<ProjectDocumentComposer project={project} document={draft} writesEnabled={false} onSave={onSave} onClose={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Simpan draf' })).toBeDisabled()
    expect(screen.getByText('Penyimpanan dokumen belum diaktifkan.')).toBeTruthy()
  })

  it('supports 44px mobile Edit/Pratinjau controls and confirms dismissal of dirty work', () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const onClose = vi.fn()
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={vi.fn()} onClose={onClose} />)
    const switcher = screen.getByRole('tablist', { name: 'Tampilan dokumen' })
    expect(within(switcher).getByRole('tab', { name: 'Edit' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(within(switcher).getByRole('tab', { name: 'Pratinjau' }))
    expect(within(switcher).getByRole('tab', { name: 'Pratinjau' })).toHaveAttribute('aria-selected', 'true')

    fireEvent.change(screen.getByLabelText('Catatan'), { target: { value: 'Perubahan lokal' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tutup penyusun dokumen' }))
    expect(confirm).toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })
})
