import { DOCUMENTS_ENDPOINT, ProjectDocumentApiError, type ProjectDocumentSession } from './projectDocumentApi'
import type {
  ProjectQuotation,
  ProjectQuotationDealResult,
  ProjectQuotationValues,
  QuotationInstallment,
} from './projectDocuments'
import { COMMERCIAL_META_FIELDS } from './commercialDocumentPolicy'

const DEFAULT_PROXY_ENDPOINT = DOCUMENTS_ENDPOINT
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

interface ProjectQuotationApiOptions {
  endpoint?: string
  request?: typeof fetch
  keyFactory?: () => string
}

interface DashboardEnvelope {
  api_version?: unknown
  data?: unknown
  meta?: unknown
  error?: unknown
}

function generatedKey() {
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID().replaceAll('-', '')
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function sameOriginEndpoint(value: string) {
  const target = new URL(value, window.location.origin)
  if (target.origin !== window.location.origin) throw new Error('Endpoint quotation harus same-origin.')
  if (target.search || target.hash) throw new Error('Endpoint quotation tidak boleh memiliki query.')
  return target.pathname
}

function apiError(response: Response, payload: DashboardEnvelope | null, write: boolean) {
  const error = record(payload?.error)
  const code = typeof error?.code === 'string' ? error.code : 'quotation_request_failed'
  const stale = response.status === 412 || code === 'optimistic_lock_conflict' || code === 'if_match_failed'
  const uncertain = write && response.status >= 500 && code !== 'project_document_writes_disabled'
  return new ProjectDocumentApiError(
    typeof error?.message === 'string' && error.message
      ? error.message
      : uncertain
        ? 'Hasil perubahan quotation belum dapat dipastikan.'
        : `Permintaan quotation gagal (${response.status}).`,
    { code, status: response.status, stale, uncertain, retryable: uncertain },
  )
}

async function jsonData(response: Response, write = false): Promise<Record<string, unknown>> {
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? ''
  let payload: DashboardEnvelope | null = null
  if (contentType.includes('application/json')) {
    payload = await response.json().catch(() => null) as DashboardEnvelope | null
  }
  if (!response.ok) throw apiError(response, payload, write)
  const data = record(payload?.data)
  const meta = record(payload?.meta)
  if (payload?.api_version !== 'dashboard.v1' || !data || !record(meta?.capabilities)) {
    throw new ProjectDocumentApiError('Kontrak respons quotation tidak cocok.', {
      code: 'invalid_response', status: response.status, uncertain: write, retryable: write,
    })
  }
  return data
}

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function nullableText(value: unknown) {
  return typeof value === 'string' && value ? value : null
}

function decimalText(value: unknown, fallback = '0') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback
}

function normalizedCommercialMeta(item: Record<string, unknown>) {
  const nested = record(item.commercial_meta) ?? {}
  return Object.fromEntries(COMMERCIAL_META_FIELDS.flatMap((field) => {
    const selected = nested[field] ?? item[field]
    return selected === undefined ? [] : [[field, selected]]
  }))
}

function normalizeLine(value: unknown, index: number) {
  const item = record(value) ?? {}
  return {
    id: text(item.id) || `line-${index + 1}`,
    description: text(item.description),
    quantity: decimalText(item.quantity, '1'),
    unit: text(item.unit) || 'unit',
    unit_price: Number(item.unit_price) || 0,
    discount_percent: decimalText(item.discount_percent ?? item.line_discount_percent),
    ...normalizedCommercialMeta(item),
  }
}

function normalizeInstallment(value: unknown, index: number): QuotationInstallment {
  const item = record(value)
  const amount = item?.amount
  if (!item || typeof amount !== 'number' || !Number.isSafeInteger(amount) || amount < 0) {
    throw new ProjectDocumentApiError('Jadwal cicilan tidak valid.', { code: 'invalid_quotation' })
  }
  const kind = String(item.kind || '').toUpperCase()
  return {
    sequence: Number.isInteger(item.sequence) ? Number(item.sequence) : index + 1,
    kind: kind === 'DP' ? 'DP' : 'INSTALLMENT',
    label: text(item.label) || (index === 0 ? 'DP' : `Pelunasan ${index}`),
    amount,
    ...(typeof item.percent === 'number' ? { percent: item.percent } : {}),
  }
}

function quotation(value: unknown): ProjectQuotation {
  const item = record(value)
  const amount = item?.amount
  if (!item || typeof item.id !== 'string' || !UUID.test(item.id)
      || typeof item.project_id !== 'string' || !UUID.test(item.project_id)
      || typeof amount !== 'number' || !Number.isSafeInteger(amount) || amount <= 0
      || typeof item.version !== 'number' || !Number.isInteger(item.version)
      || typeof item.lock_version !== 'number' || !Number.isInteger(item.lock_version)
      || !['draft', 'sent', 'revised', 'accepted', 'rejected'].includes(String(item.status))) {
    throw new ProjectDocumentApiError('Respons quotation tidak valid.', { code: 'invalid_quotation' })
  }
  const discountMode = item.discount_mode === 'fixed' || item.discount_mode === 'percent' ? item.discount_mode : 'none'
  return {
    id: item.id,
    project_id: item.project_id,
    version: item.version,
    canva_url: text(item.canva_url),
    amount,
    status: item.status as ProjectQuotation['status'],
    channel: ['whatsapp', 'phone', 'email', 'meeting', 'other'].includes(String(item.channel))
      ? item.channel as ProjectQuotation['channel']
      : 'other',
    negotiation_notes: nullableText(item.negotiation_notes),
    template_key: text(item.template_key) || undefined,
    template_version: text(item.template_version) || undefined,
    payment_profile_key: text(item.payment_profile_key) || undefined,
    official_number: nullableText(item.official_number),
    issued_at: nullableText(item.issued_at),
    recipient_name: text(item.recipient_name),
    recipient_company: text(item.recipient_company),
    recipient_address: text(item.recipient_address),
    recipient_contact: text(item.recipient_contact),
    project_name: text(item.project_name),
    subject: text(item.subject),
    valid_until: nullableText(item.valid_until),
    project_image_url: nullableText(item.project_image_url),
    lines: Array.isArray(item.lines) ? item.lines.map(normalizeLine) : [],
    discount_mode: discountMode,
    discount_value: decimalText(item.discount_value),
    tax_percent: decimalText(item.tax_percent),
    payment_terms: text(item.payment_terms),
    content_notes: text(item.content_notes),
    accepted_snapshot: record(item.accepted_snapshot) as ProjectQuotation['accepted_snapshot'],
    installment_schedule: Array.isArray(item.installment_schedule)
      ? item.installment_schedule.map(normalizeInstallment)
      : [],
    sent_at: nullableText(item.sent_at),
    decided_at: nullableText(item.decided_at),
    sales_order_id: nullableText(item.sales_order_id),
    dp_invoice_id: nullableText(item.dp_invoice_id),
    created_at: text(item.created_at),
    updated_at: text(item.updated_at),
    lock_version: item.lock_version,
  }
}

function dealResult(value: Record<string, unknown>): ProjectQuotationDealResult {
  const salesOrder = record(value.sales_order)
  const dpInvoice = record(value.dp_invoice)
  const salesOrderId = text(salesOrder?.id)
  const dpInvoiceId = text(dpInvoice?.id)
  if (!UUID.test(salesOrderId) || !UUID.test(dpInvoiceId) || !Array.isArray(value.installment_schedule)) {
    throw new ProjectDocumentApiError('Respons Deal quotation tidak lengkap.', { code: 'invalid_quotation_deal' })
  }
  return {
    quotation: quotation(value.quotation),
    sales_order_id: salesOrderId,
    dp_invoice_id: dpInvoiceId,
    installment_schedule: value.installment_schedule.map(normalizeInstallment),
  }
}

export function createProjectQuotationApi(options: ProjectQuotationApiOptions = {}) {
  const request = options.request ?? fetch
  const endpoint = sameOriginEndpoint(options.endpoint ?? DEFAULT_PROXY_ENDPOINT)
  const keyFactory = options.keyFactory ?? generatedKey

  const getJson = async (action: string, params: Record<string, string>) => {
    const query = new URLSearchParams({ action, ...params })
    const response = await request(`${endpoint}?${query}`, {
      credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' },
    })
    return jsonData(response)
  }

  const write = async (
    action: string,
    payload: Record<string, unknown>,
    session: ProjectDocumentSession,
    version: number | '*',
  ) => {
    if (!session.capabilities.documentWrites || session.csrfToken.length < 16) {
      throw new Error('Sesi perubahan dokumen tidak valid.')
    }
    const idempotencyKey = keyFactory()
    try {
      const response = await request(endpoint, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: {
          Accept: 'application/json', 'Content-Type': 'application/json',
          'X-CSRF-Token': session.csrfToken, 'Idempotency-Key': idempotencyKey,
          'If-Match': version === '*' ? '*' : `"${version}"`,
        },
        body: JSON.stringify({ action, idempotency_key: idempotencyKey, ...payload }),
      })
      return await jsonData(response, true)
    } catch (reason) {
      if (reason instanceof ProjectDocumentApiError) throw reason
      throw new ProjectDocumentApiError('Hasil perubahan quotation belum dapat dipastikan.', {
        code: 'network_error', uncertain: true, retryable: true,
      })
    }
  }

  return {
    async list(projectId: string) {
      if (!UUID.test(projectId)) throw new Error('Project ID tidak valid.')
      const data = await getJson('quotations', { project_id: projectId })
      if (!Array.isArray(data.items)) throw new Error('Daftar quotation tidak lengkap.')
      return data.items.map(quotation)
    },
    async create(projectId: string, values: ProjectQuotationValues, session: ProjectDocumentSession) {
      if (!UUID.test(projectId)) throw new Error('Project ID tidak valid.')
      return quotation(await write('create_quotation', { project_id: projectId, values }, session, '*'))
    },
    async saveDraft(item: ProjectQuotation, values: ProjectQuotationValues, session: ProjectDocumentSession) {
      return quotation(await write('update_quotation', {
        quotation_id: item.id, expected_version: item.lock_version, changes: values,
      }, session, item.lock_version))
    },
    async revise(item: ProjectQuotation, values: ProjectQuotationValues, session: ProjectDocumentSession) {
      return quotation(await write('revise_quotation', {
        quotation_id: item.id, expected_version: item.lock_version, changes: values,
      }, session, item.lock_version))
    },
    async transition(item: ProjectQuotation, status: 'sent' | 'rejected', note: string, session: ProjectDocumentSession) {
      return quotation(await write('transition_quotation', {
        quotation_id: item.id, expected_version: item.lock_version, status, note,
      }, session, item.lock_version))
    },
    async deal(
      item: ProjectQuotation,
      setup: { sales_order_id: string; sales_order_version: number; dp_percent: number; remaining_installments: number },
      session: ProjectDocumentSession,
    ) {
      return dealResult(await write('deal_quotation', {
        quotation_id: item.id, expected_version: item.lock_version, ...setup,
      }, session, item.lock_version))
    },
    async download(item: ProjectQuotation) {
      const query = new URLSearchParams({ action: 'download_quotation', quotation_id: item.id })
      const response = await request(`${endpoint}?${query}`, {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/pdf' },
      })
      if (!response.ok) throw new Error(`PDF quotation gagal diunduh (${response.status}).`)
      const contentType = response.headers.get('content-type')?.toLowerCase() ?? ''
      if (!contentType.includes('application/pdf')) throw new Error('Respons unduhan bukan PDF.')
      return response.blob()
    },
  }
}

export type ProjectQuotationApi = ReturnType<typeof createProjectQuotationApi>
