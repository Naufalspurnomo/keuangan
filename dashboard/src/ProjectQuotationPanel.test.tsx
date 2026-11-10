import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ProjectQuotationPanel from './ProjectQuotationPanel'
import { createEmptyProjectDraft, type ProjectDocumentRecord, type ProjectQuotation, type ProjectRecord } from './projectDocuments'

const project: ProjectRecord = {
  ...createEmptyProjectDraft('2026-11-10'), id: '11111111-1111-4111-8111-111111111111',
  name: 'Backdrop Expo', client_name: 'PT Klien', issuer_key: 'hollawall',
  wallet: 'CV HB(101)', company: 'HOLLA', status: 'planned', lock_version: 1,
  archived_at: null, created_at: '2026-11-10T00:00:00Z', updated_at: '2026-11-10T00:00:00Z',
}
const item: ProjectQuotation = {
  id: '44444444-4444-4444-8444-444444444444', project_id: project.id, version: 1,
  canva_url: 'https://canva.com/design/test', amount: 12_500_000, status: 'accepted',
  channel: 'whatsapp', negotiation_notes: 'Final', sent_at: '2026-11-10T00:00:00Z',
  decided_at: '2026-11-10T01:00:00Z', sales_order_id: null, created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T01:00:00Z', lock_version: 3,
}
const salesOrder = {
  id: '22222222-2222-4222-8222-222222222222', project_id: project.id, issuer_key: 'hollawall',
  type: 'sales_order', invoice_kind: null, applies_to_invoice_id: null, status: 'draft', number: null,
  issue_date: '2026-11-10', due_date: null, valid_until: null, subject: '', introduction: '', notes: '',
  payment_terms: '', prepared_by: '', client_signatory: '', project_image_url: null,
  document_discount_amount: 0, document_discount_percent: '0', tax_percent: '0',
  revision_of_id: null, void_reason: null, lock_version: 4, lines: [], allocations: [],
  totals: { subtotal: 0, line_discount: 0, document_discount: 0, tax: 0, total: 0, lines: [] },
  created_at: '2026-11-10T00:00:00Z', updated_at: '2026-11-10T00:00:00Z',
} as unknown as ProjectDocumentRecord
const session = { csrfToken: 'csrf-token-that-is-long-enough', capabilities: { projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false } }

describe('ProjectQuotationPanel', () => {
  it('applies only the accepted quotation to the draft Sales Order', async () => {
    const api = { list: vi.fn(async () => [item]), create: vi.fn(), transition: vi.fn(), apply: vi.fn(async () => salesOrder.id) }
    const applied = vi.fn()
    render(<ProjectQuotationPanel project={project} salesOrder={salesOrder} session={session} api={api} onApplied={applied} />)
    expect(await screen.findByText(/Rp\s*12\.500\.000/)).toBeTruthy()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Terapkan ke Sales Order' }))
    await waitFor(() => expect(api.apply).toHaveBeenCalledWith(item, 4, session))
    expect(applied).toHaveBeenCalledWith(salesOrder.id)
  })

  it('creates a Canva quotation version without issuing a document', async () => {
    const api = { list: vi.fn().mockResolvedValueOnce([]).mockResolvedValue([item]), create: vi.fn(async () => item), transition: vi.fn(), apply: vi.fn() }
    render(<ProjectQuotationPanel project={project} salesOrder={salesOrder} session={session} api={api} onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Versi baru' }))
    fireEvent.change(screen.getByLabelText('Link desain Canva'), { target: { value: item.canva_url } })
    fireEvent.change(screen.getByLabelText('Nilai penawaran'), { target: { value: '12500000' } })
    fireEvent.change(screen.getByLabelText('Catatan negosiasi'), { target: { value: 'Final' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan versi' }))
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(project.id, {
      canva_url: item.canva_url, amount: 12_500_000, channel: 'whatsapp', negotiation_notes: 'Final',
    }, session))
    expect(await screen.findByText(/Versi 1/)).toBeTruthy()
  })
})
