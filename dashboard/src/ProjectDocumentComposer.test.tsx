import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('ProjectDocumentComposer', () => {
  it('presents direct billed area with a live invoice total', () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={vi.fn()} onClose={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'Buat invoice' })).toBeTruthy()
    expect(screen.queryByRole('list', { name: /Alur pembuatan/ })).toBeNull()
    expect(screen.queryByLabelText(/Lebar|Tinggi/)).toBeNull()

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Panel akustik' } })
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('HARGA/M² item 1'), { target: { value: '100000' } })
    expect(screen.getByLabelText('Total invoice')).toHaveTextContent('Rp100.000')
  })

  it('keeps a 10000 unit price in its field and never moves it into notes', () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={vi.fn()} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Panel akustik' } })
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '1' } })
    const price = screen.getByLabelText('HARGA/M² item 1')
    const notes = screen.getByLabelText('Catatan')
    fireEvent.change(price, { target: { value: '10000' } })

    expect(price).toHaveValue('Rp 10.000')
    expect(notes).toHaveValue('')
    expect(screen.getByLabelText('Total invoice')).toHaveTextContent('Rp10.000')
    expect(screen.getByRole('article', { name: 'Pratinjau A5 Invoice' })).toHaveTextContent('Rp10.000')
  })

  it('shows a calculation error instead of presenting invalid input as Rp0', () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={vi.fn()} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: 'abc' } })

    expect(screen.getByLabelText('Total invoice')).toHaveTextContent('Periksa nilai item')
    expect(screen.queryByRole('article', { name: 'Pratinjau A5 Invoice' })).toBeNull()
    expect(screen.getByRole('heading', { name: 'Pratinjau perlu diperbaiki' })).toBeTruthy()
  })

  it('edits line items and renders a semantic A5 preview with calculated totals', () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={vi.fn()} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Panel akustik' } })
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '2.5' } })
    fireEvent.change(screen.getByLabelText('HARGA/M² item 1'), { target: { value: '100000' } })
    fireEvent.change(screen.getByLabelText('Pajak persen'), { target: { value: '11' } })

    const preview = screen.getByRole('article', { name: 'Pratinjau A5 Invoice' })
    expect(preview).toHaveTextContent('Lobby Marvell')
    expect(preview).toHaveTextContent('PT Marvell')
    expect(preview).toHaveTextContent('Panel akustik')
    expect(preview).toHaveTextContent('Rp277.500')
    expect(preview).toHaveAttribute('data-template', 'hollawall')
    expect(preview).toHaveAttribute('data-page-size', 'A5')
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
    expect(within(preview).queryByText('Subtotal')).toBeNull()
    expect(within(preview).queryByText('Total')).toBeNull()
    expect(within(preview).getByText('Telah diterima dari', { exact: false })).toBeTruthy()
    expect(within(preview).getByText('Diterima oleh')).toBeTruthy()
    expect(within(preview).queryByText('Persetujuan klien')).toBeNull()
  })

  it('blocks an empty receipt before showing a misleading Rp0 document', () => {
    const draft = createEmptyDocumentDraft(project.id, 'receipt', '2026-11-03')
    render(<ProjectDocumentComposer
      project={project}
      document={draft}
      writesEnabled
      receiptOptions={{ invoices: [], transactions: [] }}
      onSave={vi.fn()}
      onClose={vi.fn()}
      onOpenTransactions={vi.fn()}
    />)

    expect(screen.getByRole('heading', { name: 'Kuitansi belum bisa dibuat' })).toBeTruthy()
    expect(screen.getByText(/Nominal kuitansi selalu diambil dari transaksi pemasukan/)).toBeTruthy()
    expect(screen.queryByRole('article', { name: 'Pratinjau A5 Kuitansi' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Simpan draf' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Buka transaksi Project' })).toBeTruthy()
  })

  it('shows a receipt preview only after an income transaction is selected', () => {
    const draft = createEmptyDocumentDraft(project.id, 'receipt', '2026-11-03')
    const options = {
      invoices: [],
      transactions: [{
        transaction_id: 'income-1',
        source_key: 'income-1',
        amount: 100_000,
        available_amount: 100_000,
        description: 'Transfer DP',
        transaction_date: '2026-11-03',
      }],
    }
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled receiptOptions={options} onSave={vi.fn()} onClose={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'Pilih pembayaran untuk kuitansi' })).toBeTruthy()
    expect(screen.queryByRole('article', { name: 'Pratinjau A5 Kuitansi' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Simpan draf' })).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('article', { name: 'Pratinjau A5 Kuitansi' })).toHaveTextContent('Rp100.000')
    expect(screen.getByRole('button', { name: 'Simpan draf' })).toBeEnabled()
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

  it('rejects unsupported files and stores a compressed PNG/JPEG preview', async () => {
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    const onSave = vi.fn()
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={onSave} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Panel' } })
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Gambar Project'), {
      target: { files: [new File(['svg'], 'project.svg', { type: 'image/svg+xml' })] },
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('PNG atau JPEG')
    expect(onSave).not.toHaveBeenCalled()

    const imageDataUrl = 'data:image/jpeg;base64,/9j/2Q=='
    class MockImage {
      naturalWidth = 1
      naturalHeight = 1
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      set src(_value: string) { this.onload?.() }
    }
    vi.stubGlobal('Image', MockImage)
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(imageDataUrl)
    fireEvent.change(screen.getByLabelText('Gambar Project'), {
      target: { files: [new File(['jpeg'], 'project.jpg', { type: 'image/jpeg' })] },
    })
    await screen.findByAltText('Pratinjau gambar Project')
    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ project_image_url: imageDataUrl })))
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

  it('keeps local changes dirty when the server does not confirm the save', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const onSave = vi.fn(async () => false)
    const onClose = vi.fn()
    const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
    render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={onSave} onClose={onClose} />)

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Panel akustik' } })
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('HARGA/M² item 1'), { target: { value: '100000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    await waitFor(() => expect(onSave).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: 'Tutup penyusun dokumen' }))
    expect(confirm).toHaveBeenCalledWith('Tutup penyusun dan buang perubahan yang belum disimpan?')
    expect(onClose).not.toHaveBeenCalled()
  })
})
