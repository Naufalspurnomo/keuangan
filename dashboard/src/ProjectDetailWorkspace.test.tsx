import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectDetailWorkspace from './ProjectDetailWorkspace'
import { createEmptyProjectDraft, type ProjectRecord } from './projectDocuments'

const project: ProjectRecord = {
  ...createEmptyProjectDraft('2026-11-03'),
  id: '018f9ca2-355a-7d66-b1d5-4d4be6e2f321',
  name: 'Lobby Marvell',
  client_name: 'PT Marvell',
  issuer_key: 'cv-holla-berkreasi',
  wallet: 'CV HB(101)',
  company: 'HOLLA',
  status: 'active',
  lock_version: 2,
  archived_at: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

afterEach(cleanup)

describe('ProjectDetailWorkspace', () => {
  it('renders URL-controlled Transaksi, Presensi, and Dokumen tabs', () => {
    const onRouteChange = vi.fn()
    render(<ProjectDetailWorkspace project={project} tab="transactions" onRouteChange={onRouteChange} onBack={vi.fn()} transactions={<p>Ledger proyek</p>} presensi={<p>Bukti presensi</p>} documents={<p>Pusat dokumen</p>} />)
    expect(screen.getByText('Ledger proyek')).toBeTruthy()
    expect(screen.queryByText(project.id!)).toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: 'Dokumen' }))
    expect(onRouteChange).toHaveBeenCalledWith({ tab: 'documents' })
  })

  it('supports keyboard tab navigation without local route drift', () => {
    const onRouteChange = vi.fn()
    render(<ProjectDetailWorkspace project={project} tab="presensi" onRouteChange={onRouteChange} onBack={vi.fn()} transactions={<p>Ledger</p>} presensi={<p>Presensi</p>} documents={<p>Dokumen</p>} />)
    const tab = screen.getByRole('tab', { name: 'Presensi' })
    tab.focus()
    fireEvent.keyDown(tab, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Dokumen' })).toHaveFocus()
    expect(onRouteChange).toHaveBeenCalledWith({ tab: 'documents' })
  })

  it('offers lifecycle actions only when project writes are advertised', () => {
    const onEdit = vi.fn()
    const onStatusChange = vi.fn()
    const onArchive = vi.fn()
    const { rerender } = render(<ProjectDetailWorkspace project={project} tab="documents" onRouteChange={vi.fn()} onBack={vi.fn()} transactions={null} presensi={null} documents={null} capabilities={{ projectWrites: false, documentWrites: false, transactionCorrections: false, transactionReversals: false }} onEdit={onEdit} onStatusChange={onStatusChange} onArchive={onArchive} />)
    expect(screen.queryByRole('button', { name: 'Ubah proyek' })).toBeNull()
    expect(screen.getByText('Perubahan proyek belum diaktifkan.')).toBeTruthy()

    rerender(<ProjectDetailWorkspace project={project} tab="documents" onRouteChange={vi.fn()} onBack={vi.fn()} transactions={null} presensi={null} documents={null} capabilities={{ projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false }} onEdit={onEdit} onStatusChange={onStatusChange} onArchive={onArchive} />)
    fireEvent.click(screen.getByRole('button', { name: 'Ubah proyek' }))
    fireEvent.click(screen.getByRole('button', { name: 'Batalkan proyek' }))
    fireEvent.click(screen.getByRole('button', { name: 'Arsipkan proyek' }))
    expect(onEdit).toHaveBeenCalledWith(project)
    expect(onStatusChange).toHaveBeenCalledWith('cancelled')
    expect(onArchive).toHaveBeenCalled()
  })
})
