import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ProjectProfitabilityWorkspace from './ProjectProfitabilityWorkspace'
import type { FinanceProject, FinanceTransaction } from './financeWorkspace'
import type { ProjectDocumentApi } from './projectDocumentApi'

const project: FinanceProject = {
  id: '11111111-1111-4111-8111-111111111111', name: 'Surabaya Office', client: 'Client',
  company: 'Holla', wallet: 'CV HB', status: 'active', started_on: '2026-11-01',
  completed_on: null, contract_value: 1_000_000, notes: '', created_at: '2026-11-01', updated_at: '2026-11-01',
}

const row = (input: Partial<FinanceTransaction> & Pick<FinanceTransaction, 'id' | 'direction' | 'amount' | 'date'>): FinanceTransaction => ({
  scope: 'project', wallet: 'CV HB', company: 'Holla', project_id: project.id,
  office_category: null, notes: '', created_at: input.date, updated_at: input.date, ...input,
})

const rows = [
  row({ id: 'income', date: '2026-11-01', direction: 'income', amount: 400_000, notes: 'DP', evidence_source: 'media_ocr', ocr_mode: 'vision', recorded_by: 'Admin' }),
  row({ id: 'salary', date: '2026-11-02', direction: 'expense', amount: 100_000, category: 'Gaji', notes: 'Upah tukang' }),
  row({ id: 'material', date: '2026-11-03', direction: 'expense', amount: 200_000, category: 'Bahan Alat', notes: 'Cat dan kuas' }),
]

const evidenceApi = {
  list: vi.fn(async () => []), upload: vi.fn(), review: vi.fn(), download: vi.fn(),
}

const api = {
  getPaymentSummary: vi.fn(async () => ({
    project_id: project.id, contract_total: 1_000_000, invoiced_total: 400_000, unbilled_total: 600_000,
    paid_total: 400_000, contract_outstanding: 600_000, overpaid_total: 0, unapplied_total: 0,
    payment_status: 'PARTIALLY_PAID', invoices: [],
  })),
} as unknown as ProjectDocumentApi

describe('ProjectProfitabilityWorkspace', () => {
  it('renders contract margin, cash P&L, salary, cost categories, and evidence provenance', async () => {
    render(<ProjectProfitabilityWorkspace project={project} rows={rows} projects={[project]} api={api} evidenceApi={evidenceApi} />)

    await waitFor(() => expect(api.getPaymentSummary).toHaveBeenCalledWith(project.id))
    const metrics = within(screen.getByRole('region', { name: 'Ringkasan kas Surabaya Office' }))
    expect(metrics.getByText('Nilai kontrak').parentElement).toHaveTextContent(/1\.000\.000/)
    expect(metrics.getByText('Kas masuk').parentElement).toHaveTextContent(/400\.000/)
    expect(metrics.getByText('Pengeluaran proyek tercatat').parentElement).toHaveTextContent(/300\.000/)
    expect(metrics.getByText('Gaji/upah tercatat').parentElement).toHaveTextContent(/100\.000/)
    expect(metrics.getByText('Arus kas bersih').parentElement).toHaveTextContent(/100\.000/)
    expect(metrics.getByText('Sisa kontrak setelah kas keluar').parentElement).toHaveTextContent(/700\.000/)
    expect(metrics.getByText('Sisa kontrak setelah kas keluar').parentElement).toHaveTextContent('70%')
    expect(screen.getByText('Gaji')).toBeTruthy()
    expect(screen.getByText('Bahan Alat')).toBeTruthy()
    expect(screen.getByText(/Media OCR · vision/)).toBeTruthy()
    expect(screen.getByText('File privat · review manual')).toBeTruthy()
    expect(screen.getByText(/Bukan laba akuntansi/)).toBeTruthy()
    const monthly = screen.getByRole('table', { name: 'Data tren bulanan' })
    expect(monthly).toHaveTextContent('Nov 26')
    expect(monthly).toHaveTextContent(/400\.000/)
    expect(monthly).toHaveTextContent(/300\.000/)
  })

  it('uploads evidence once, reloads authoritative status, and keeps review manual', async () => {
    const item = {
      id: '44444444-4444-4444-8444-444444444444', project_id: project.id, ledger_source_key: 'income',
      mime_type: 'image/png' as const, byte_size: 12, sha256: 'a'.repeat(64), original_name: 'bukti.png',
      review_status: 'pending' as const, review_note: null, reviewed_at: null,
      created_at: '2026-11-10T00:00:00Z', lock_version: 0,
    }
    const evidence = {
      list: vi.fn().mockResolvedValueOnce([]).mockResolvedValue([item]),
      upload: vi.fn(async () => item), review: vi.fn(), download: vi.fn(),
    }
    const session = {
      csrfToken: 'csrf-token-that-is-long-enough',
      capabilities: { projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false },
    }
    render(<ProjectProfitabilityWorkspace project={project} rows={rows} projects={[project]} api={api} evidenceApi={evidence} session={session} />)

    const file = new File([new Uint8Array([137, 80, 78, 71])], 'bukti.png', { type: 'image/png' })
    fireEvent.change(await screen.findByLabelText('Unggah bukti DP'), { target: { files: [file] } })

    await waitFor(() => expect(evidence.upload).toHaveBeenCalledWith(project.id, 'income', file, session))
    expect(await screen.findByText(/Menunggu review/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Setujui' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tolak' })).toBeTruthy()
  })

  it('does not invent contract remainder when authoritative summary is unavailable', async () => {
    const unavailable = { getPaymentSummary: vi.fn(async () => { throw new Error('offline') }) } as unknown as ProjectDocumentApi
    render(<ProjectProfitabilityWorkspace project={project} rows={rows} projects={[project]} api={unavailable} evidenceApi={evidenceApi} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Nilai kontrak dan sisa kontrak belum dapat dimuat')
    expect(screen.getByText('Sisa kontrak setelah kas keluar').parentElement).toHaveTextContent('—')
  })
})
