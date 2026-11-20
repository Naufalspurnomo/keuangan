import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectQuotationPanel, { calculateInstallmentSchedule } from './ProjectQuotationPanel'
import { createEmptyDocumentDraft, createEmptyProjectDraft, type ProjectQuotation, type ProjectRecord } from './projectDocuments'
import type { ProjectQuotationApi } from './projectQuotationApi'

const project: ProjectRecord = {
  ...createEmptyProjectDraft('2026-11-10'),
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Backdrop Expo',
  client_name: 'Ibu Rani',
  client_company: 'PT Klien',
  client_address: 'Surabaya',
  client_contact: '08123456789',
  issuer_key: 'hollawall',
  wallet: 'CV HB(101)',
  company: 'HOLLA',
  status: 'active',
  lock_version: 1,
  archived_at: null,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
}

const item: ProjectQuotation = {
  id: '44444444-4444-4444-8444-444444444444',
  project_id: project.id,
  version: 1,
  canva_url: '',
  amount: 12_500_001,
  status: 'sent',
  channel: 'whatsapp',
  negotiation_notes: null,
  template_key: 'hollawall',
  recipient_name: 'Ibu Rani',
  recipient_company: 'PT Klien',
  recipient_address: 'Surabaya',
  recipient_contact: '08123456789',
  project_name: 'Backdrop Expo',
  subject: 'Penawaran backdrop expo',
  valid_until: '2026-12-10',
  project_image_url: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  lines: [{ id: 'line-1', description: 'Backdrop', quantity: '1', unit: 'set', unit_price: 12_500_001, discount_percent: '0', pricing_mode: 'legacy_generic' }],
  discount_mode: 'none',
  discount_value: '0',
  tax_percent: '0',
  payment_terms: 'DP sebelum produksi',
  content_notes: 'Harga termasuk pemasangan.',
  accepted_snapshot: null,
  installment_schedule: [],
  sent_at: '2026-11-10T00:00:00Z',
  decided_at: null,
  sales_order_id: null,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T01:00:00Z',
  lock_version: 3,
}

const salesOrder = {
  ...createEmptyDocumentDraft(project.id, 'sales_order', '2026-11-10'),
  id: '22222222-2222-4222-8222-222222222222',
  status: 'draft' as const,
  number: null,
  currency: 'IDR' as const,
  totals: { lines: [], subtotal: 0, document_discount: 0, taxable_base: 0, tax: 0, total: 0 },
  lock_version: 7,
  revised_from_id: null,
  superseded_by_id: null,
  void_reason: null,
  issued_at: null,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
}

const session = {
  csrfToken: 'csrf-token-that-is-long-enough',
  capabilities: { projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false },
}

function api(items: ProjectQuotation[] = []) {
  return {
    list: vi.fn<ProjectQuotationApi['list']>(async () => items),
    create: vi.fn<ProjectQuotationApi['create']>(async () => item),
    saveDraft: vi.fn<ProjectQuotationApi['saveDraft']>(async (source, values) => ({ ...source, ...values })),
    revise: vi.fn<ProjectQuotationApi['revise']>(async () => ({ ...item, id: '55555555-5555-4555-8555-555555555555', version: 2, status: 'draft' })),
    transition: vi.fn<ProjectQuotationApi['transition']>(async () => item),
    deal: vi.fn<ProjectQuotationApi['deal']>(async () => ({
      quotation: { ...item, status: 'accepted' as const },
      sales_order_id: '22222222-2222-4222-8222-222222222222',
      dp_invoice_id: '33333333-3333-4333-8333-333333333333',
      installment_schedule: calculateInstallmentSchedule(item.amount, 30, 3),
    })),
    download: vi.fn<ProjectQuotationApi['download']>(async () => new Blob(['%PDF-'], { type: 'application/pdf' })),
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('ProjectQuotationPanel', () => {
  it('uses direct billed area and keeps the live commercial summary visible', async () => {
    render(<ProjectQuotationPanel project={project} session={session} api={api()} onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Buat quotation' }))

    expect(screen.getByRole('heading', { name: 'Buat quotation' })).toBeTruthy()
    expect(screen.queryByRole('list', { name: /Alur pembuatan/ })).toBeNull()
    expect(screen.queryByLabelText(/Lebar|Tinggi/)).toBeNull()

    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Backdrop premium' } })
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('HARGA/M² item 1 *'), { target: { value: '5000000' } })
    expect(screen.getByRole('complementary', { name: 'Ringkasan quotation' })).toHaveTextContent(/Rp\s*5\.000\.000/)
  })

  it('creates a structured draft from project-derived recipient data and confirms authoritative readback', async () => {
    const subject = api()
    subject.list.mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('Readback terputus')).mockResolvedValue([item])
    render(<ProjectQuotationPanel project={project} session={session} api={subject} onApplied={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Buat quotation' }))
    expect(screen.getByLabelText('Template merek')).toHaveValue('HOLLAWALL · A5')
    expect(screen.getByLabelText('Nama penerima')).toHaveValue('Ibu Rani')
    expect(screen.queryByLabelText(/pilih.*merek/i)).toBeNull()
    expect(screen.getByLabelText('Gambar Project')).toBeRequired()
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

    fireEvent.change(screen.getByLabelText('Subjek'), { target: { value: 'Penawaran backdrop premium' } })
    expect(screen.getByLabelText('Berlaku sampai')).toHaveValue('Ditetapkan 7 hari dari tanggal kirim')
    fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Backdrop premium' } })
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('HARGA/M² item 1 *'), { target: { value: '5000000' } })
    fireEvent.change(screen.getByLabelText('Diskon item 1 (%)'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('Pajak (%)'), { target: { value: '11' } })
    expect(screen.getAllByText(/Rp\s*9\.990\.000/)).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    await waitFor(() => expect(subject.create).toHaveBeenCalledWith(project.id, expect.objectContaining({
      recipient_name: 'Ibu Rani',
      project_name: 'Backdrop Expo',
      subject: 'Penawaran backdrop premium',
      valid_until: null,
      template_key: 'hollawall',
      template_version: 'commercial-v3',
      payment_profile_key: 'hollawall',
      lines: [expect.objectContaining({ description: 'Backdrop premium', pricing_mode: 'area_rate', billed_area_m2: '2', quantity: '2', unit: 'm²', unit_price: 5_000_000, discount_percent: '10' })],
      tax_percent: '11',
      deposit_percent: 30,
    }), session, expect.any(String)))
    expect(JSON.stringify(subject.create.mock.calls[0])).toContain('commercial-v3')
    await waitFor(() => expect(screen.getAllByRole('alert').some((alert) => alert.textContent?.includes('Readback terputus'))).toBe(true))
    expect(subject.create).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Muat ulang' }))
    await waitFor(() => expect(subject.list).toHaveBeenCalledTimes(3))
    expect(subject.create).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('heading', { name: 'Buat quotation' })).toBeNull()
    expect(await screen.findByText('Quotation tersimpan dan berhasil dipulihkan.')).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/Quotation Canva|Link desain Canva/i)
  })

  it('saves an existing draft in place and creates an explicit revision as a new version', async () => {
    const draft = { ...item, status: 'draft' as const }
    const subject = api([draft])
    render(<ProjectQuotationPanel project={project} session={session} api={subject} onApplied={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Edit versi 1' }))
    fireEvent.change(screen.getByLabelText('Subjek'), { target: { value: 'Draf diperbarui' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    await waitFor(() => expect(subject.saveDraft).toHaveBeenCalledWith(draft, expect.objectContaining({ subject: 'Draf diperbarui' }), session))

    fireEvent.click(screen.getByRole('button', { name: 'Buat revisi versi 1' }))
    expect(screen.getByText('Revisi dari versi 1')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Simpan sebagai revisi' }))
    await waitFor(() => expect(subject.revise).toHaveBeenCalledWith(expect.objectContaining({ id: draft.id }), expect.objectContaining({ subject: 'Draf diperbarui' }), session))
  })

  it('edits historical billed area without requiring dimension overrides', async () => {
    const draft = { ...item, status: 'draft' as const, lines: [{ ...item.lines![0], pricing_mode: 'area_rate' as const, quantity: '6', billed_area_m2: '6', width: '3', height: '2', unit_price: 100000 }] }
    const subject = api([draft])
    render(<ProjectQuotationPanel project={project} session={session} api={subject} onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit versi 1' }))
    fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '5.5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
    await waitFor(() => expect(subject.saveDraft).toHaveBeenCalledWith(draft, expect.objectContaining({ amount: 550000, lines: [expect.objectContaining({ quantity: '5.5', billed_area_m2: '5.5', width: null, height: null })] }), session))
    expect(subject.deal).not.toHaveBeenCalled()
    expect(subject.transition).not.toHaveBeenCalled()
  })

  it('shows exact DP allocation including rupiah remainder before creating deal documents', async () => {
    const subject = api([item])
    const applied = vi.fn()
    render(<ProjectQuotationPanel project={project} salesOrder={salesOrder} session={session} api={subject} onApplied={applied} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Tandai Deal versi 1' }))
    const dialog = screen.getByRole('dialog', { name: 'Setup DP dan cicilan' })
    expect(within(dialog).getByText(/mengikuti quotation terkirim/)).toHaveTextContent('DP 30%')
    expect(within(dialog).queryByRole('radio', { name: /DP/ })).toBeNull()
    fireEvent.click(within(dialog).getByRole('radio', { name: '3 kali pelunasan' }))

    expect(within(dialog).getAllByText(/DP 30%/).at(-1)?.parentElement).toHaveTextContent('Rp3.750.000')
    expect(within(dialog).getByText('Pelunasan 1').parentElement).toHaveTextContent('Rp2.916.667')
    expect(within(dialog).getByText('Pelunasan 2').parentElement).toHaveTextContent('Rp2.916.667')
    expect(within(dialog).getByText('Pelunasan 3').parentElement).toHaveTextContent('Rp2.916.667')
    expect(within(dialog).getByText(/Tidak ada selisih pembagian/)).toBeTruthy()
    expect(within(dialog).getByText(/Total alokasi/)).toHaveTextContent('Rp12.500.001')
    expect(within(dialog).queryByText(/sudah (?:lunas|dibayar)|telah (?:lunas|dibayar)/i)).toBeNull()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Konfirmasi Deal & Buat Draf DP' }))
    await waitFor(() => expect(subject.deal).toHaveBeenCalledWith(item, {
      sales_order_id: salesOrder.id, sales_order_version: 7, dp_percent: 30, remaining_installments: 3,
    }, session))
    await waitFor(() => expect(applied).toHaveBeenCalledWith('22222222-2222-4222-8222-222222222222'))
  })

  it('does not dismiss a deal dialog with Escape while its write is in flight', async () => {
    const subject = api([item])
    const pending = deferred<Awaited<ReturnType<ProjectQuotationApi['deal']>>>()
    vi.mocked(subject.deal).mockImplementationOnce(() => pending.promise)
    render(<ProjectQuotationPanel project={project} salesOrder={salesOrder} session={session} api={subject} onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Tandai Deal versi 1' }))
    const dialog = screen.getByRole('dialog', { name: 'Setup DP dan cicilan' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Konfirmasi Deal & Buat Draf DP' }))
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Mengonfirmasi…' })).toBeDisabled())

    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.getByRole('dialog', { name: 'Setup DP dan cicilan' })).toBeTruthy()

    await act(async () => {
      pending.resolve({
        quotation: { ...item, status: 'accepted' },
        sales_order_id: salesOrder.id,
        dp_invoice_id: '33333333-3333-4333-8333-333333333333',
        installment_schedule: calculateInstallmentSchedule(item.amount, 30, 1),
      })
      await pending.promise
    })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Setup DP dan cicilan' })).toBeNull())
  })

  it('locks DP to the sent quotation while keeping installments bounded', async () => {
    const subject = api([item])
    render(<ProjectQuotationPanel project={project} salesOrder={salesOrder} session={session} api={subject} onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Tandai Deal versi 1' }))
    const dialog = screen.getByRole('dialog', { name: 'Setup DP dan cicilan' })

    expect(within(dialog).getByText(/mengikuti quotation terkirim/)).toHaveTextContent('DP 30%')
    expect(within(dialog).queryByText('DP kustom')).toBeNull()
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Jumlah pelunasan kustom' }))
    fireEvent.change(within(dialog).getAllByLabelText('Jumlah pelunasan kustom').at(-1)!, { target: { value: '25' } })
    expect(within(dialog).getByRole('alert')).toHaveTextContent('maksimal 24')
    expect(within(dialog).getByRole('button', { name: 'Konfirmasi Deal & Buat Draf DP' })).toBeDisabled()
  })

  it('rejects non PNG/JPEG project images before upload', async () => {
    render(<ProjectQuotationPanel project={project} session={session} api={api()} onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Buat quotation' }))
    const file = new File(['hello'], 'project.svg', { type: 'image/svg+xml' })
    fireEvent.change(screen.getByLabelText('Gambar Project'), { target: { files: [file] } })
    expect(await screen.findByRole('alert')).toHaveTextContent('PNG atau JPEG')
  })

  it('requires and forwards a rejection reason for sent quotations', async () => {
    const subject = api([item])
    render(<ProjectQuotationPanel project={project} salesOrder={salesOrder} session={session} api={subject} onApplied={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Tandai ditolak' }))
    const dialog = screen.getByRole('dialog', { name: 'Catat alasan penolakan' })
    const confirm = within(dialog).getByRole('button', { name: 'Konfirmasi ditolak' })
    expect(confirm).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Alasan penolakan'), { target: { value: 'Anggaran klien berubah' } })
    fireEvent.click(confirm)

    await waitFor(() => expect(subject.transition).toHaveBeenCalledWith(item, 'rejected', 'Anggaran klien berubah', session))
  })

  it('hides generated PDF download for legacy Canva-only quotation history', async () => {
    const legacy = { ...item, lines: [], project_image_url: null, canva_url: 'https://www.canva.com/design/legacy' }
    render(<ProjectQuotationPanel project={project} session={session} api={api([legacy])} onApplied={vi.fn()} />)

    await screen.findByText('Referensi desain lama:')
    expect(screen.queryByRole('button', { name: 'Unduh PDF versi 1' })).toBeNull()
  })

  it('offers PDF history download and reports uncertain deal state without claiming success', async () => {
    const subject = api([item])
    vi.mocked(subject.deal).mockRejectedValueOnce(Object.assign(new Error('Hasil Deal belum dapat dipastikan.'), { uncertain: true }))
    const createObjectURL = vi.fn(() => 'blob:quotation')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    render(<ProjectQuotationPanel project={project} salesOrder={salesOrder} session={session} api={subject} onApplied={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Unduh PDF versi 1' }))
    await waitFor(() => expect(subject.download).toHaveBeenCalledWith(item))

    fireEvent.click(screen.getByRole('button', { name: 'Tandai Deal versi 1' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Konfirmasi Deal & Buat Draf DP' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('belum dapat dipastikan')
    expect(screen.queryByText(/berhasil dibuat/i)).toBeNull()
  })
})

describe('calculateInstallmentSchedule', () => {
  it('preserves the exact accepted total with deterministic remainder allocation', () => {
    const schedule = calculateInstallmentSchedule(12_500_001, 30, 3)
    expect(schedule.map((entry) => entry.amount)).toEqual([3_750_000, 2_916_667, 2_916_667, 2_916_667])
    expect(schedule.reduce((total, entry) => total + entry.amount, 0)).toBe(12_500_001)
  })
})
