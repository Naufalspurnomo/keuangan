import { describe, expect, it } from 'vitest'

import {
  calculateDocumentTotals,
  createEmptyDocumentDraft,
  createEmptyProjectDraft,
  projectDocumentRoute,
  readProjectDocumentRoute,
  validateDocumentDraft,
  validateProjectDraft,
} from './projectDocuments'

describe('project document domain', () => {
  it('creates explicit production identities and supports cancelled projects', () => {
    const draft = createEmptyProjectDraft('2026-11-03')
    expect(draft.id).toBeNull()
    expect(draft.status).toBe('active')
    expect(draft.started_on).toBe('2026-11-03')

    const clean = validateProjectDraft({
      ...draft,
      name: '  Lobby Marvell  ',
      client_name: '  PT Marvell  ',
      issuer_key: 'cv-holla-berkreasi',
      wallet: 'CV HB(101)',
      company: 'HOLLA',
      status: 'cancelled',
    })
    expect(clean.name).toBe('Lobby Marvell')
    expect(clean.client_name).toBe('PT Marvell')
    expect(clean.status).toBe('cancelled')
  })

  it('rejects wallet labels as business units and mismatched project bindings', () => {
    const draft = {
      ...createEmptyProjectDraft('2026-11-03'),
      name: 'Lobby Marvell', client_name: 'PT Marvell', issuer_key: 'hollawall', wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya',
    }
    expect(() => validateProjectDraft(draft)).not.toThrow()
    expect(() => validateProjectDraft({ ...draft, company: 'TX SBY' })).toThrow('Unit usaha tidak sesuai')
    expect(() => validateProjectDraft({ ...draft, company: 'HOLLA' })).toThrow('Unit usaha tidak sesuai')
  })

  it('calculates integer rupiah with half-up rounding and one document discount mode', () => {
    const draft = createEmptyDocumentDraft('project-uuid', 'invoice', '2026-11-03')
    const totals = calculateDocumentTotals({
      ...draft,
      lines: [
        { id: 'line-1', description: 'Panel', quantity: '2.5', unit: 'm²', unit_price: 1001, discount_percent: '10' },
        { id: 'line-2', description: 'Instalasi', quantity: '1', unit: 'ls', unit_price: 1000, discount_percent: '0' },
      ],
      discount_mode: 'percent',
      discount_value: '10',
      tax_percent: '11',
    })
    expect(totals.lines.map((line) => line.total)).toEqual([2253, 1000])
    expect(totals.subtotal).toBe(3253)
    expect(totals.document_discount).toBe(325)
    expect(totals.taxable_base).toBe(2928)
    expect(totals.tax).toBe(322)
    expect(totals.total).toBe(3250)
  })

  it('derives receipt totals only from authoritative positive allocations without discount or tax', () => {
    const draft = createEmptyDocumentDraft('project-uuid', 'receipt', '2026-11-03')
    const totals = calculateDocumentTotals({
      ...draft,
      allocations: [{ transaction_id: 'income-1', source_key: 'income-1', amount: 100_000, available_amount: 100_000 }],
      discount_mode: 'fixed',
      discount_value: '5000',
      tax_percent: '11',
    })

    expect(totals).toMatchObject({
      subtotal: 100_000,
      document_discount: 0,
      taxable_base: 100_000,
      tax: 0,
      total: 100_000,
    })
  })

  it('rejects unsafe commercial drafts before a write', () => {
    const draft = createEmptyDocumentDraft('project-uuid', 'invoice', '2026-11-03')
    expect(() => validateDocumentDraft({ ...draft, lines: [] })).toThrow('Tambahkan minimal satu item')
    expect(() => validateDocumentDraft({
      ...draft,
      lines: [{ id: 'line-1', description: 'Panel', quantity: '1', unit: 'm²', unit_price: 1000, discount_percent: '101' }],
    })).toThrow('Diskon item')
  })

  it('rejects zero, invalid, and over-available receipt allocations', () => {
    const draft = createEmptyDocumentDraft('project-uuid', 'receipt', '2026-11-03')
    const allocation = { transaction_id: 'income-1', source_key: 'income-1', amount: 100, available_amount: 100 }

    expect(() => validateDocumentDraft({ ...draft, allocations: [{ ...allocation, amount: 0 }] })).toThrow('lebih dari nol')
    expect(() => validateDocumentDraft({ ...draft, allocations: [{ ...allocation, amount: Number.NaN }] })).toThrow('valid')
    expect(() => validateDocumentDraft({ ...draft, allocations: [{ ...allocation, available_amount: Number.NaN }] })).toThrow('valid')
    expect(() => validateDocumentDraft({ ...draft, allocations: [{ ...allocation, amount: 101 }] })).toThrow('melebihi nilai transaksi')
  })

  it('rejects remote, malformed, and oversized project images', () => {
    const draft = createEmptyDocumentDraft('project-uuid', 'invoice', '2026-11-03')
    const valid = { ...draft, lines: [{ id: 'line-1', description: 'Panel', quantity: '1', unit: 'unit', unit_price: 1, discount_percent: '0' }] }

    expect(() => validateDocumentDraft({ ...valid, project_image_url: 'https://example.com/project.png' })).toThrow('data PNG atau JPEG')
    expect(() => validateDocumentDraft({ ...valid, project_image_url: 'data:image/gif;base64,Zm9v' })).toThrow('data PNG atau JPEG')
    expect(() => validateDocumentDraft({ ...valid, project_image_url: `data:image/png;base64,${'A'.repeat(196_609)}` })).toThrow('terlalu besar')
    expect(() => validateDocumentDraft({ ...valid, project_image_url: 'data:image/png;base64,Zm9v' })).not.toThrow()
    expect(() => validateDocumentDraft({ ...valid, project_image_url: 'data:image/jpeg;base64,Zm9v' })).not.toThrow()
  })

  it('round-trips canonical project, tab, and document hash routes', () => {
    const hash = projectDocumentRoute({ projectId: '018f9ca2-355a-7d66-b1d5-4d4be6e2f321', tab: 'documents', document: 'new', type: 'sales_order' })
    expect(hash).toBe('#projects?project=018f9ca2-355a-7d66-b1d5-4d4be6e2f321&tab=documents&document=new&type=sales-order')
    expect(readProjectDocumentRoute(hash)).toEqual({
      projectId: '018f9ca2-355a-7d66-b1d5-4d4be6e2f321',
      tab: 'documents',
      document: 'new',
      type: 'sales_order',
    })
  })
})
