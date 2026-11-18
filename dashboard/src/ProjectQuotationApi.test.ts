import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createProjectQuotationApi } from './projectQuotationApi'
import type { ProjectQuotation, ProjectQuotationValues } from './projectDocuments'

const projectId = '11111111-1111-4111-8111-111111111111'
const quotationId = '44444444-4444-4444-8444-444444444444'
const salesOrderId = '22222222-2222-4222-8222-222222222222'
const dpInvoiceId = '33333333-3333-4333-8333-333333333333'
const session = {
  csrfToken: 'csrf-token-that-is-long-enough',
  capabilities: { projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false },
}
const values: ProjectQuotationValues = {
  template_key: 'hollawall', template_version: 'commercial-v3', payment_profile_key: 'cv-holla-berkreasi',
  recipient_name: 'Ibu Rani', recipient_company: 'PT Klien', recipient_address: 'Surabaya', recipient_contact: '0812',
  project_name: 'Backdrop Expo', subject: 'Penawaran backdrop', valid_until: '2026-12-10',
  project_image_url: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  lines: [{ id: 'line-1', description: 'Backdrop', quantity: '1', unit: 'set', unit_price: 10_000_000, discount_percent: '0' }],
  discount_mode: 'none', discount_value: '0', tax_percent: '0', deposit_percent: 30, payment_terms: '', content_notes: '', amount: 10_000_000,
}
const wireValues = {
  ...values,
  lines: values.lines.map(({ discount_percent, ...line }) => ({
    ...line,
    line_discount_percent: discount_percent,
  })),
}

const quotation: ProjectQuotation = {
  id: quotationId, project_id: projectId, version: 1, canva_url: '', status: 'draft', channel: 'other',
  negotiation_notes: null, ...values, sent_at: null, decided_at: null, sales_order_id: null,
  created_at: '2026-11-10T00:00:00Z', updated_at: '2026-11-10T00:00:00Z', lock_version: 2,
}

function response(data: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify({
    api_version: 'dashboard.v1',
    data,
    meta: { capabilities: { reads_enabled: true, project_document_writes_enabled: true, transaction_correction_reversal: false, hard_delete: false } },
  }), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init })
}

function errorResponse(status: number, code: string, message: string) {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('projectQuotationApi production proxy contract', () => {
  const request = vi.fn()
  const api = createProjectQuotationApi({ request, keyFactory: () => 'idem-key-1234567890' })

  beforeEach(() => request.mockReset())

  it('lists quotations from the authoritative REST collection', async () => {
    request.mockResolvedValue(response({ items: [quotation] }))

    await expect(api.list(projectId)).resolves.toEqual([expect.objectContaining({ id: quotationId })])
    expect(request).toHaveBeenCalledWith(`/admin/api/documents.php?action=quotations&project_id=${projectId}`, {
      credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' },
    })
  })

  it('preserves explicit render/payment identity and commercial line metadata on read and save', async () => {
    const commercialLine = {
      ...values.lines[0],
      commercial_meta: {
        pricing_mode: 'area_rate', width: '2.5', height: '4', dimension_unit: 'm',
        raw_area_m2: '10', billed_area_m2: '10', area_rounding: 'half_up',
        area_override_reason: null, display_quantity: null, original_price: null,
        asset_ref: 'asset://mural-1',
      },
    }
    const stored = { ...quotation, ...values, lines: [commercialLine] }
    request.mockResolvedValueOnce(response({ items: [stored] })).mockResolvedValueOnce(response(stored))

    const [loaded] = await api.list(projectId)
    expect(loaded).toMatchObject({
      template_key: 'hollawall',
      template_version: 'commercial-v3',
      payment_profile_key: 'cv-holla-berkreasi',
      lines: [expect.objectContaining({
        pricing_mode: 'area_rate', width: '2.5', billed_area_m2: '10', asset_ref: 'asset://mural-1',
      })],
    })
    await api.saveDraft(quotation, { ...values, lines: [loaded.lines![0]] }, session)
    const body = JSON.parse(String(request.mock.calls[1][1]?.body)) as { changes: ProjectQuotationValues }
    expect(body.changes).toMatchObject({
      template_key: 'hollawall', template_version: 'commercial-v3', payment_profile_key: 'cv-holla-berkreasi',
      lines: [expect.objectContaining({ pricing_mode: 'area_rate', width: '2.5', asset_ref: 'asset://mural-1' })],
    })
  })

  it('sends exact REST create and draft-save methods, paths, headers, and bodies', async () => {
    request.mockImplementation(async () => response(quotation))
    await api.create(projectId, values, session)
    await api.saveDraft(quotation, { ...values, subject: 'Revisi subjek' }, session)

    expect(request).toHaveBeenNthCalledWith(1, '/admin/api/documents.php', expect.objectContaining({
      method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: expect.objectContaining({
        Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken,
        'If-Match': '*', 'Idempotency-Key': 'idem-key-1234567890',
      }),
      body: JSON.stringify({ action: 'create_quotation', idempotency_key: 'idem-key-1234567890', project_id: projectId, values: wireValues }),
    }))
    expect(request).toHaveBeenNthCalledWith(2, '/admin/api/documents.php', expect.objectContaining({
      method: 'POST', headers: expect.objectContaining({ 'If-Match': '"2"', 'Idempotency-Key': 'idem-key-1234567890' }),
      body: JSON.stringify({
        action: 'update_quotation', idempotency_key: 'idem-key-1234567890', quotation_id: quotationId, expected_version: 2,
        changes: { ...wireValues, subject: 'Revisi subjek' },
      }),
    }))
  })

  it('serializes quotation line discounts with the backend canonical key', async () => {
    request.mockImplementation(async () => response(quotation))

    await api.create(projectId, {
      ...values,
      lines: [{ ...values.lines[0], discount_percent: '5' }],
    }, session)

    const body = JSON.parse(String(request.mock.calls[0][1]?.body)) as {
      values: { lines: Array<Record<string, unknown>> }
    }
    expect(body.values.lines).toEqual([
      expect.objectContaining({ line_discount_percent: '5' }),
    ])
    expect(body.values.lines[0]).not.toHaveProperty('discount_percent')
  })

  it('uses explicit revision and atomic Deal REST routes including Sales Order version', async () => {
    request
      .mockResolvedValueOnce(response({ ...quotation, version: 2 }))
      .mockResolvedValueOnce(response({
        quotation: { ...quotation, status: 'accepted', sales_order_id: salesOrderId, dp_invoice_id: dpInvoiceId },
        sales_order: { id: salesOrderId, lock_version: 5 },
        dp_invoice: { id: dpInvoiceId, lock_version: 0 },
        installment_schedule: [
          { sequence: 1, kind: 'dp', label: 'DP 30%', amount: 3_000_000, percent: 30 },
          { sequence: 2, kind: 'installment', label: 'Pelunasan 1', amount: 3_500_000 },
          { sequence: 3, kind: 'installment', label: 'Pelunasan 2', amount: 3_500_000 },
        ],
      }))

    await api.revise(quotation, values, session)
    const result = await api.deal(quotation, {
      sales_order_id: salesOrderId,
      sales_order_version: 4,
      dp_percent: 30,
      remaining_installments: 2,
    }, session)

    expect(request).toHaveBeenNthCalledWith(1, '/admin/api/documents.php', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'If-Match': '"2"' }),
      body: JSON.stringify({
        action: 'revise_quotation', idempotency_key: 'idem-key-1234567890', quotation_id: quotationId, expected_version: 2, changes: wireValues,
      }),
    }))
    expect(request).toHaveBeenNthCalledWith(2, '/admin/api/documents.php', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'If-Match': '"2"' }),
      body: JSON.stringify({
        action: 'deal_quotation', idempotency_key: 'idem-key-1234567890', quotation_id: quotationId, expected_version: 2,
        sales_order_id: salesOrderId, sales_order_version: 4, dp_percent: 30, remaining_installments: 2,
      }),
    }))
    expect(result).toEqual(expect.objectContaining({
      sales_order_id: salesOrderId,
      dp_invoice_id: dpInvoiceId,
      installment_schedule: [
        expect.objectContaining({ kind: 'DP', amount: 3_000_000 }),
        expect.objectContaining({ kind: 'INSTALLMENT', amount: 3_500_000 }),
        expect.objectContaining({ kind: 'INSTALLMENT', amount: 3_500_000 }),
      ],
    }))
  })

  it('preserves the transition REST route and optimistic concurrency contract', async () => {
    request.mockResolvedValue(response({ ...quotation, status: 'sent', lock_version: 3 }))

    await api.transition(quotation, 'sent', '', session)

    expect(request).toHaveBeenCalledWith('/admin/api/documents.php', expect.objectContaining({
      method: 'POST', headers: expect.objectContaining({ 'If-Match': '"2"' }),
      body: JSON.stringify({
        action: 'transition_quotation', idempotency_key: 'idem-key-1234567890', quotation_id: quotationId, expected_version: 2, status: 'sent', note: '',
      }),
    }))
  })

  it('downloads the selected stored quotation version through the production proxy', async () => {
    request.mockResolvedValue(new Response('%PDF-', { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
    const pdf = await api.download(quotation)

    expect(pdf.type).toBe('application/pdf')
    expect(request).toHaveBeenCalledWith(`/admin/api/documents.php?action=download_quotation&quotation_id=${quotationId}`, expect.objectContaining({
      credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/pdf' },
    }))
  })

  it('requires the exact dashboard.v1 envelope', async () => {
    request.mockResolvedValue(new Response(JSON.stringify({ data: { items: [] } }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))

    await expect(api.list(projectId)).rejects.toMatchObject({ code: 'invalid_response' })
  })

  it('classifies stale responses and ambiguous write failures', async () => {
    request.mockResolvedValueOnce(errorResponse(412, 'if_match_failed', 'Versi berubah.'))
    await expect(api.saveDraft(quotation, values, session)).rejects.toMatchObject({ stale: true, uncertain: false })

    request.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(api.create(projectId, values, session)).rejects.toMatchObject({
      uncertain: true,
      retryable: true,
    })
  })

  it('supports a configurable same-origin proxy and rejects cross-origin endpoints', async () => {
    const custom = createProjectQuotationApi({ endpoint: '/custom/documents.php', request, keyFactory: () => 'idem-key-1234567890' })
    request.mockResolvedValue(response({ items: [] }))

    await custom.list(projectId)
    expect(request).toHaveBeenCalledWith(`/custom/documents.php?action=quotations&project_id=${projectId}`, expect.any(Object))
    expect(() => createProjectQuotationApi({ endpoint: 'https://other.example/api' })).toThrow('same-origin')
  })
})
