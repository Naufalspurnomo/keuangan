import { describe, expect, it, vi } from 'vitest'

import {
  ProjectDocumentApiError,
  createProjectDocumentApi,
  type ProjectDocumentSession,
} from './projectDocumentApi'

const session: ProjectDocumentSession = {
  csrfToken: 'csrf-token-with-16-chars',
  capabilities: {
    projectWrites: true,
    documentWrites: true,
    transactionCorrections: false,
    transactionReversals: false,
  },
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

const project = {
  id: '018f9ca2-355a-4d66-b1d5-4d4be6e2f321',
  name: 'Lobby Marvell',
  wallet: 'CV HB(101)',
  company: 'HOLLA',
  client_name: 'PT Marvell',
  client_company: '',
  client_address: '',
  client_contact: '',
  issuer_key: 'cv-holla-berkreasi',
  status: 'active' as const,
  started_on: '2026-11-03',
  completed_on: null,
  contract_notes: '',
  lock_version: 1,
  archived_at: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

const backendProject = {
  ...project,
  start_date: project.started_on,
  completion_date: project.completed_on,
  wallet: 'CV HB(101)',
  company: 'HOLLA',
}

const document = {
  id: '22222222-2222-4222-8222-222222222222',
  project_id: project.id,
  issuer_key: project.issuer_key,
  document_type: 'invoice',
  invoice_kind: 'DP',
  status: 'draft',
  official_number: null,
  issue_date: '2026-11-03',
  due_date: '2026-11-10',
  valid_until: null,
  document_discount_amount: 0,
  document_discount_percent: '0',
  tax_percent: '0',
  notes: '',
  payment_terms: '',
  revision_of_id: null,
  superseded_by_id: null,
  void_reason: null,
  lock_version: 4,
  issued_at: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
  lines: [],
  allocations: [],
}

const meta = { capabilities: { reads_enabled: true, project_document_writes_enabled: true, transaction_correction_reversal: false } }

describe('project/document API', () => {
  it('reads same-origin projects with credentials and validates dashboard.v1', async () => {
    const request = vi.fn(async () => json({ api_version: 'dashboard.v1', data: { items: [backendProject] }, meta }))
    const api = createProjectDocumentApi({ request })
    const result = await api.listProjects()
    expect(result.projects[0]).toMatchObject(project)
    expect(request).toHaveBeenCalledWith('/admin/api/projects.php?action=list', expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }))
  })

  it('sends CSRF, If-Match, and a stable idempotency key for retry', async () => {
    const request = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => json({ api_version: 'dashboard.v1', data: { ...backendProject, lock_version: 2 }, meta }))
    const api = createProjectDocumentApi({ request, keyFactory: () => 'idem-key-1234567890' })
    const command = api.updateProject(project.id, { name: 'Lobby Revisi' }, 1)
    await command.submit(session)
    await command.submit(session)
    const first = request.mock.calls[0][1] as RequestInit
    const second = request.mock.calls[1][1] as RequestInit
    expect(first.headers).toMatchObject({
      'X-CSRF-Token': session.csrfToken,
      'Idempotency-Key': 'idem-key-1234567890',
      'If-Match': '"1"',
    })
    expect((second.headers as Record<string, string>)['Idempotency-Key']).toBe('idem-key-1234567890')
  })

  it('classifies stale conflicts and preserves authoritative readback data', async () => {
    const request = vi.fn(async () => json({
      error: { code: 'optimistic_lock_conflict', message: 'Proyek telah diperbarui.' },
    }, 409))
    const api = createProjectDocumentApi({ request, keyFactory: () => 'idem-key-1234567890' })
    const command = api.updateProject(project.id, { name: 'Nama lokal' }, 1)
    await expect(command.submit(session)).rejects.toMatchObject({
      code: 'optimistic_lock_conflict',
      stale: true,
    })
  })

  it('blocks commands when the advertised capability is off', async () => {
    const request = vi.fn()
    const api = createProjectDocumentApi({ request, keyFactory: () => 'idem-key-1234567890' })
    const command = api.issueDocument(document.id, 2)
    await expect(command.submit({ ...session, capabilities: { ...session.capabilities, documentWrites: false } })).rejects.toBeInstanceOf(ProjectDocumentApiError)
    expect(request).not.toHaveBeenCalled()
  })

  it('downloads PDFs only after validating content type', async () => {
    const request = vi.fn(async () => new Response(new Uint8Array([37, 80, 68, 70]), { headers: { 'content-type': 'application/pdf' } }))
    const api = createProjectDocumentApi({ request })
    expect((await api.downloadDocument(document.id)).type).toBe('application/pdf')
    expect(request).toHaveBeenCalledWith(`/admin/api/documents.php?action=download&document_id=${document.id}`, expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('uses exact PHP proxy read actions and normalizes backend records and capabilities', async () => {
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/admin/api/projects.php?action=list') return json({ api_version: 'dashboard.v1', data: { items: [backendProject] }, meta })
      if (url === `/admin/api/projects.php?action=get&project_id=${project.id}`) return json({ api_version: 'dashboard.v1', data: backendProject, meta })
      if (url === `/admin/api/documents.php?action=list&project_id=${project.id}`) return json({ api_version: 'dashboard.v1', data: { items: [document] }, meta })
      if (url === `/admin/api/documents.php?action=get&document_id=${document.id}`) return json({ api_version: 'dashboard.v1', data: document, meta })
      throw new Error(`Unexpected request ${url}`)
    })
    const api = createProjectDocumentApi({ request })

    const listed = await api.listProjects()
    expect(listed.projects[0]).toMatchObject({ id: project.id, started_on: project.started_on, completed_on: null, wallet: 'CV HB(101)', company: 'HOLLA' })
    expect(listed.capabilities).toEqual({ projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false })
    expect(await api.getProject(project.id)).toMatchObject({ id: project.id, started_on: project.started_on })
    expect((await api.listDocuments(project.id)).documents[0]).toMatchObject({ id: document.id, type: 'invoice', number: null, lock_version: 4 })
    expect(await api.getDocument(document.id)).toMatchObject({ id: document.id, type: 'invoice' })
  })

  it('normalizes authoritative payment reads and rejects non-integer money', async () => {
    const payment = {
      project_id: project.id,
      contract_total: 1_000_000,
      invoiced_total: 400_000,
      unbilled_total: 600_000,
      paid_total: 200_000,
      contract_outstanding: 800_000,
      overpaid_total: 0,
      unapplied_total: 0,
      payment_status: 'PARTIALLY_PAID',
      invoices: [{
        invoice_id: document.id,
        invoice_kind: 'DP',
        official_number: 'INV/HW/2026/000001',
        due_date: '2026-11-10',
        invoice_total: 400_000,
        paid_total: 200_000,
        outstanding: 200_000,
        payment_status: 'PARTIALLY_PAID',
      }],
    }
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('payment_summary')) return json({ api_version: 'dashboard.v1', data: payment, meta })
      if (url.includes('receipt_options')) return json({ api_version: 'dashboard.v1', data: {
        invoices: payment.invoices,
        transactions: [{ source_key: 'ledger:1', amount: 200_000, available_amount: 200_000, description: 'Transfer DP', transaction_date: '2026-11-03' }],
      }, meta })
      throw new Error(`Unexpected request ${url}`)
    })
    const api = createProjectDocumentApi({ request })
    expect(await api.getPaymentSummary(project.id)).toMatchObject({ paid_total: 200_000, contract_outstanding: 800_000 })
    expect((await api.getReceiptOptions(project.id)).transactions[0]).toMatchObject({ source_key: 'ledger:1', amount: 200_000 })

    const invalid = createProjectDocumentApi({ request: vi.fn(async () => json({
      api_version: 'dashboard.v1', data: { ...payment, paid_total: '200000' }, meta,
    })) })
    await expect(invalid.getPaymentSummary(project.id)).rejects.toMatchObject({ code: 'invalid_payment_summary' })
  })

  it('preserves null pre-contract totals instead of inventing zero', async () => {
    const request = vi.fn(async () => json({ api_version: 'dashboard.v1', data: {
      project_id: project.id,
      contract_total: null,
      invoiced_total: 0,
      unbilled_total: null,
      paid_total: 0,
      contract_outstanding: null,
      overpaid_total: 0,
      unapplied_total: 0,
      payment_status: 'NOT_CONTRACTED',
      invoices: [],
    }, meta }))
    const result = await createProjectDocumentApi({ request }).getPaymentSummary(project.id)
    expect(result).toMatchObject({ contract_total: null, contract_outstanding: null, payment_status: 'NOT_CONTRACTED' })
  })

  it('sends project commands with proxy-allowlisted fields', async () => {
    const request = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      const result = body.action === 'create'
        ? { project: backendProject, sales_order: { ...document, document_type: 'sales_order' } }
        : backendProject
      return json({ api_version: 'dashboard.v1', data: result, meta })
    })
    const api = createProjectDocumentApi({ request, keyFactory: () => 'idem-key-1234567890' })
    await api.createProject({
      id: null, name: 'Lobby Marvell', wallet: 'CV HB(101)', company: 'HOLLA', client_name: 'PT Marvell', client_company: '', client_address: '', client_contact: '', issuer_key: 'cv-holla-berkreasi', status: 'active', started_on: '2026-11-03', completed_on: null, contract_notes: '',
    }).submit(session)
    expect(request.mock.calls[0][0]).toBe('/admin/api/projects.php')
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({
      action: 'create', idempotency_key: 'idem-key-1234567890', values: expect.objectContaining({ name: 'Lobby Marvell', wallet: 'CV HB(101)', company: 'HOLLA', status: 'active', start_date: '2026-11-03' }),
    })
    expect(request.mock.calls[0][1]?.headers).toMatchObject({ 'If-Match': '*', 'Idempotency-Key': 'idem-key-1234567890' })

    await api.updateProject(project.id, { name: 'Lobby Revisi' }, 2).submit(session)
    expect(JSON.parse(String(request.mock.calls[1][1]?.body))).toEqual({ action: 'update', project_id: project.id, idempotency_key: 'idem-key-1234567890', expected_version: 2, changes: { name: 'Lobby Revisi' } })
    await api.updateProject(project.id, project, 2).submit(session)
    const fullUpdate = JSON.parse(String(request.mock.calls[2][1]?.body)) as { changes: Record<string, unknown> }
    expect(fullUpdate.changes).toMatchObject({ wallet: 'CV HB(101)', company: 'HOLLA' })
    expect(fullUpdate.changes).not.toHaveProperty('issuer_key')
    expect(fullUpdate.changes).not.toHaveProperty('lock_version')
    expect(fullUpdate.changes).not.toHaveProperty('id')
    await api.setProjectStatus(project.id, 'cancelled', 2).submit(session)
    expect(JSON.parse(String(request.mock.calls[3][1]?.body))).toEqual({ action: 'status', project_id: project.id, idempotency_key: 'idem-key-1234567890', expected_version: 2, status: 'cancelled' })
    await api.archiveProject(project.id, 2).submit(session)
    expect(JSON.parse(String(request.mock.calls[4][1]?.body))).toEqual({ action: 'archive', project_id: project.id, idempotency_key: 'idem-key-1234567890', expected_version: 2 })
  })

  it('sends document commands with proxy-allowlisted fields', async () => {
    const request = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => json({ api_version: 'dashboard.v1', data: document, meta }))
    const api = createProjectDocumentApi({ request, keyFactory: () => 'idem-key-1234567890' })
    const draft = {
      id: null, project_id: project.id, type: 'invoice' as const, invoice_kind: 'DP' as const, applies_to_invoice_id: null, issue_date: '2026-11-03', due_date: '2026-11-10', valid_until: null, notes: '', payment_terms: '', prepared_by: '', client_signatory: '', project_image_url: null,
      lines: [{ id: 'line-local', description: 'Panel', quantity: '1', unit: 'unit', unit_price: 1000, discount_percent: '0' }], discount_mode: 'none' as const, discount_value: '0', tax_percent: '0', allocations: [],
    }
    await api.createDocument(draft).submit(session)
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({
      action: 'create_invoice', project_id: project.id, idempotency_key: 'idem-key-1234567890', kind: 'DP', values: expect.objectContaining({ lines: [{ description: 'Panel', quantity: '1', unit: 'unit', unit_price: 1000, line_discount_percent: '0' }] }),
    })
    await api.updateDocument(document.id, draft, 4).submit(session)
    expect(JSON.parse(String(request.mock.calls[1][1]?.body))).toEqual({ action: 'update', document_id: document.id, idempotency_key: 'idem-key-1234567890', expected_version: 4, changes: expect.objectContaining({ issue_date: '2026-11-03' }) })
    await api.issueDocument(document.id, 4).submit(session)
    await api.voidDocument(document.id, 'Nilai tagihan keliru', 4).submit(session)
    await api.reviseDocument(document.id, 4).submit(session)
    expect(JSON.parse(String(request.mock.calls[2][1]?.body))).toEqual({ action: 'issue', document_id: document.id, idempotency_key: 'idem-key-1234567890', expected_version: 4 })
    expect(JSON.parse(String(request.mock.calls[3][1]?.body))).toEqual({ action: 'void', document_id: document.id, idempotency_key: 'idem-key-1234567890', expected_version: 4, reason: 'Nilai tagihan keliru' })
    expect(JSON.parse(String(request.mock.calls[4][1]?.body))).toEqual({ action: 'revise', document_id: document.id, idempotency_key: 'idem-key-1234567890', expected_version: 4 })
  })

  it('omits repository-derived fields from receipt and FINAL metadata updates', async () => {
    const request = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => json({ api_version: 'dashboard.v1', data: document, meta }))
    const api = createProjectDocumentApi({ request, keyFactory: () => 'idem-key-1234567890' })
    const base = {
      id: null, project_id: project.id, applies_to_invoice_id: null, issue_date: '2026-11-03', due_date: '2026-11-10', valid_until: null,
      notes: 'Metadata only', payment_terms: 'Net 7', prepared_by: 'Naufal', client_signatory: 'PT Client', project_image_url: null,
      lines: [{ id: 'line-local', description: 'Derived', quantity: '1', unit: 'unit', unit_price: 1000, discount_percent: '0' }],
      discount_mode: 'fixed' as const, discount_value: '500', tax_percent: '11', allocations: [],
    }
    await api.updateDocument(document.id, { ...base, type: 'receipt', invoice_kind: null }, 4).submit(session)
    await api.updateDocument(document.id, { ...base, type: 'invoice', invoice_kind: 'FINAL' }, 4).submit(session)

    for (const call of request.mock.calls) {
      const body = JSON.parse(String(call[1]?.body)) as { changes: Record<string, unknown> }
      expect(body.changes).toMatchObject({ notes: 'Metadata only', prepared_by: 'Naufal', client_signatory: 'PT Client' })
      expect(body.changes).not.toHaveProperty('lines')
      expect(body.changes).not.toHaveProperty('document_discount_amount')
      expect(body.changes).not.toHaveProperty('document_discount_percent')
      expect(body.changes).not.toHaveProperty('tax_percent')
    }
  })

  it('does not misclassify non-version domain conflicts as stale', async () => {
    const request = vi.fn(async () => json({
      error: { code: 'project_document_conflict', message: 'Nilai dokumen melanggar invariant.' },
    }, 409))
    const api = createProjectDocumentApi({ request, keyFactory: () => 'idem-key-1234567890' })
    await expect(api.updateProject(project.id, { name: 'Nama lokal' }, 1).submit(session)).rejects.toMatchObject({ stale: false })
  })

  it('rejects non-PostgreSQL identifiers before proxy routing', async () => {
    const request = vi.fn()
    const api = createProjectDocumentApi({ request })
    await expect(api.getProject('p26-generated-name')).rejects.toMatchObject({ code: 'invalid_identifier' })
    await expect(api.listDocuments('live-project-1')).rejects.toMatchObject({ code: 'invalid_identifier' })
    expect(request).not.toHaveBeenCalled()
  })
})
