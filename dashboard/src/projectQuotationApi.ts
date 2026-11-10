import type { ProjectDocumentSession } from './projectDocumentApi'
import type { ProjectQuotation } from './projectDocuments'

const endpoint = '/admin/api/documents.php'
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const key = () => crypto.randomUUID().replaceAll('-', '')

function params(values: Record<string, string>) {
  const query = new URLSearchParams(values)
  return `${endpoint}?${query.toString()}`
}

async function body(response: Response): Promise<Record<string, unknown>> {
  const payload = await response.json().catch(() => null) as { data?: Record<string, unknown>; error?: { message?: string } } | null
  if (!response.ok) throw new Error(payload?.error?.message || `Quotation request failed (${response.status})`)
  if (!payload?.data) throw new Error('Quotation response is incomplete.')
  return payload.data
}

function quotation(value: unknown): ProjectQuotation {
  const item = value as ProjectQuotation
  if (!item || !uuid.test(item.id) || !uuid.test(item.project_id) || !Number.isSafeInteger(item.amount) || item.amount <= 0) {
    throw new Error('Quotation response is invalid.')
  }
  return item
}

async function write(action: string, payload: Record<string, unknown>, session: ProjectDocumentSession, version: number | '*') {
  if (!session.capabilities.documentWrites || session.csrfToken.length < 16) throw new Error('Sesi perubahan dokumen tidak valid.')
  const idempotencyKey = key()
  const response = await fetch(endpoint, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    headers: {
      Accept: 'application/json', 'Content-Type': 'application/json',
      'X-CSRF-Token': session.csrfToken, 'Idempotency-Key': idempotencyKey,
      'If-Match': version === '*' ? '*' : `"${version}"`,
    },
    body: JSON.stringify({ action, idempotency_key: idempotencyKey, ...payload }),
  })
  return body(response)
}

export function createProjectQuotationApi() {
  return {
    async list(projectId: string) {
      if (!uuid.test(projectId)) throw new Error('Project ID tidak valid.')
      const response = await fetch(params({ action: 'quotations', project_id: projectId }), { credentials: 'same-origin', cache: 'no-store' })
      const data = await body(response)
      if (!Array.isArray(data.items)) throw new Error('Daftar quotation tidak lengkap.')
      return data.items.map(quotation)
    },
    async create(projectId: string, values: { canva_url: string; amount: number; channel: ProjectQuotation['channel']; negotiation_notes: string }, session: ProjectDocumentSession) {
      const data = await write('create_quotation', { project_id: projectId, values }, session, '*')
      return quotation(data)
    },
    async transition(item: ProjectQuotation, status: 'sent' | 'accepted' | 'rejected' | 'revised', note: string, session: ProjectDocumentSession) {
      const data = await write('transition_quotation', { quotation_id: item.id, expected_version: item.lock_version, status, note }, session, item.lock_version)
      return quotation(data)
    },
    async apply(item: ProjectQuotation, salesOrderVersion: number, session: ProjectDocumentSession) {
      const data = await write('apply_quotation', { quotation_id: item.id, sales_order_version: salesOrderVersion }, session, '*')
      const id = String(data.id || '')
      if (!uuid.test(id)) throw new Error('Sales Order readback ID tidak valid.')
      return id
    },
  }
}

export type ProjectQuotationApi = ReturnType<typeof createProjectQuotationApi>
