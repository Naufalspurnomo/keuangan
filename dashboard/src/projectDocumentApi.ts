import {
  calculateDocumentTotals,
  createEmptyDocumentDraft,
  type DocumentLineInput,
  type ProjectDocumentCapabilities,
  type ProjectDocumentDraft,
  type ProjectDocumentRecord,
  type ProjectDraft,
  type ProjectRecord,
  type ProductionProjectStatus,
  type ReceiptAllocation,
} from './projectDocuments'

export const PROJECTS_ENDPOINT = '/admin/api/projects.php'
export const DOCUMENTS_ENDPOINT = '/admin/api/documents.php'

export interface ProjectDocumentSession {
  csrfToken: string
  capabilities: ProjectDocumentCapabilities
}

export interface ProjectListResult {
  projects: ProjectRecord[]
  capabilities: ProjectDocumentCapabilities
}

export interface DocumentListResult {
  documents: ProjectDocumentRecord[]
  capabilities: ProjectDocumentCapabilities
}

export interface ProjectDocumentCommand<T> {
  readonly idempotencyKey: string
  readonly payload: Readonly<Record<string, unknown>>
  submit: (session: ProjectDocumentSession) => Promise<T>
}

interface ApiOptions {
  projectsEndpoint?: string
  documentsEndpoint?: string
  request?: typeof fetch
  keyFactory?: () => string
}

interface ErrorOptions {
  code: string
  status?: number
  stale?: boolean
  uncertain?: boolean
  retryable?: boolean
  current?: unknown
}

interface Envelope {
  data: Record<string, unknown>
  capabilities: ProjectDocumentCapabilities
}

export class ProjectDocumentApiError extends Error {
  readonly code: string
  readonly status?: number
  readonly stale: boolean
  readonly uncertain: boolean
  readonly retryable: boolean
  readonly current?: unknown

  constructor(message: string, options: ErrorOptions) {
    super(message)
    this.name = 'ProjectDocumentApiError'
    this.code = options.code
    this.status = options.status
    this.stale = options.stale ?? false
    this.uncertain = options.uncertain ?? false
    this.retryable = options.retryable ?? false
    this.current = options.current
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function nullableText(value: unknown) {
  return typeof value === 'string' && value ? value : null
}

function sameOriginPath(endpoint: string) {
  const target = new URL(endpoint, window.location.origin)
  if (target.origin !== window.location.origin) {
    throw new ProjectDocumentApiError('Endpoint harus same-origin.', { code: 'cross_origin_endpoint' })
  }
  return target.pathname + target.search
}

function generateIdempotencyKey() {
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID()
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function uuid(value: string) {
  if (!UUID.test(value)) throw new ProjectDocumentApiError('ID PostgreSQL tidak valid.', { code: 'invalid_identifier' })
  return value.toLocaleLowerCase('en-US')
}

function capabilitySet(value: unknown): ProjectDocumentCapabilities {
  const source = record(value) ?? {}
  const writes = source.project_document_writes_enabled === true
  const transactionLifecycle = source.transaction_correction_reversal === true
  return {
    projectWrites: writes,
    documentWrites: writes,
    transactionCorrections: transactionLifecycle,
    transactionReversals: transactionLifecycle,
  }
}

async function responseObject(response: Response, write = false) {
  const contentType = response.headers.get('content-type')?.toLocaleLowerCase('en-US') ?? ''
  if (!contentType.includes('application/json')) {
    throw new ProjectDocumentApiError('Respons server bukan JSON.', {
      code: 'invalid_response', status: response.status, uncertain: write && response.ok, retryable: write && response.ok,
    })
  }
  try {
    const body = record(await response.json())
    if (!body) throw new Error('not object')
    return body
  } catch (error) {
    if (error instanceof ProjectDocumentApiError) throw error
    throw new ProjectDocumentApiError('Kontrak respons server tidak cocok.', {
      code: 'invalid_response', status: response.status, uncertain: write && response.ok, retryable: write && response.ok,
    })
  }
}

function apiError(body: Record<string, unknown>, response: Response, write = false) {
  const error = record(body.error)
  const data = record(body.data)
  const code = typeof error?.code === 'string' ? error.code : 'request_failed'
  const stale = response.status === 412 || code === 'optimistic_lock_conflict'
  const uncertain = write && response.status >= 500 && code !== 'project_document_writes_disabled'
  return new ProjectDocumentApiError(
    typeof error?.message === 'string' && error.message
      ? error.message
      : uncertain
        ? 'Hasil perubahan belum dapat dipastikan. Ulangi permintaan yang sama.'
        : 'Permintaan ditolak server.',
    { code, status: response.status, stale, uncertain, retryable: uncertain, current: data?.current },
  )
}

function envelope(body: Record<string, unknown>, response: Response): Envelope {
  if (body.api_version !== 'dashboard.v1' || !record(body.data)) {
    throw new ProjectDocumentApiError('Kontrak respons server tidak cocok.', { code: 'invalid_response', status: response.status })
  }
  const meta = record(body.meta)
  return { data: record(body.data)!, capabilities: capabilitySet(meta?.capabilities) }
}

function normalizeProject(value: unknown): ProjectRecord {
  const item = record(value)
  if (!item || typeof item.id !== 'string' || !UUID.test(item.id) || typeof item.name !== 'string'
      || typeof item.client_name !== 'string' || typeof item.issuer_key !== 'string'
      || !['planned', 'active', 'completed', 'cancelled'].includes(String(item.status))
      || typeof item.lock_version !== 'number') {
    throw new ProjectDocumentApiError('Data proyek dari server tidak lengkap.', { code: 'invalid_project' })
  }
  return {
    id: item.id,
    name: item.name,
    client_name: item.client_name,
    client_company: text(item.client_company),
    client_address: text(item.client_address),
    client_contact: text(item.client_contact),
    issuer_key: item.issuer_key,
    status: item.status as ProductionProjectStatus,
    started_on: text(item.start_date || item.started_on),
    completed_on: nullableText(item.completion_date ?? item.completed_on),
    contract_notes: text(item.contract_notes),
    wallet: text(item.wallet),
    company: text(item.company),
    lock_version: item.lock_version,
    archived_at: nullableText(item.archived_at),
    created_at: text(item.created_at),
    updated_at: text(item.updated_at),
  }
}

function normalizeLine(value: unknown, index: number): DocumentLineInput {
  const item = record(value) ?? {}
  return {
    id: text(item.id) || `line-${index + 1}`,
    description: text(item.description),
    quantity: text(item.quantity) || '1',
    unit: text(item.unit) || 'unit',
    unit_price: Number(item.unit_price) || 0,
    discount_percent: text(item.line_discount_percent ?? item.discount_percent) || '0',
  }
}

function normalizeAllocation(value: unknown): ReceiptAllocation {
  const item = record(value) ?? {}
  const sourceKey = text(item.ledger_source_key ?? item.source_key)
  return {
    transaction_id: sourceKey,
    source_key: sourceKey,
    amount: Number(item.amount) || 0,
    available_amount: typeof item.available_amount === 'number' ? item.available_amount : undefined,
    description: text(item.description),
    transaction_date: text(item.transaction_date),
  }
}

function normalizeDocument(value: unknown): ProjectDocumentRecord {
  const item = record(value)
  const documentType = item?.document_type ?? item?.type
  if (!item || typeof item.id !== 'string' || !UUID.test(item.id) || typeof item.project_id !== 'string' || !UUID.test(item.project_id)
      || !['sales_order', 'invoice', 'receipt'].includes(String(documentType))
      || !['draft', 'issued', 'void', 'superseded'].includes(String(item.status))
      || typeof item.lock_version !== 'number') {
    throw new ProjectDocumentApiError('Data dokumen dari server tidak lengkap.', { code: 'invalid_document' })
  }
  const type = documentType as ProjectDocumentRecord['type']
  const lines = Array.isArray(item.lines) ? item.lines.map(normalizeLine) : []
  const allocations = Array.isArray(item.allocations) ? item.allocations.map(normalizeAllocation) : []
  const fixedDiscount = Number(item.document_discount_amount) || 0
  const percentDiscount = text(item.document_discount_percent) || '0'
  const base = createEmptyDocumentDraft(item.project_id, type, text(item.issue_date) || new Date().toISOString().slice(0, 10))
  const draft: ProjectDocumentDraft = {
    ...base,
    id: item.id,
    invoice_kind: item.invoice_kind === 'DP' || item.invoice_kind === 'PROGRESS' || item.invoice_kind === 'FINAL' ? item.invoice_kind : null,
    due_date: nullableText(item.due_date),
    valid_until: nullableText(item.valid_until),
    notes: text(item.notes),
    payment_terms: text(item.payment_terms),
    prepared_by: text(item.prepared_by),
    client_signatory: text(item.client_signatory),
    project_image_url: nullableText(item.project_image_url),
    lines,
    allocations,
    discount_mode: fixedDiscount ? 'fixed' : Number(percentDiscount) ? 'percent' : 'none',
    discount_value: fixedDiscount ? String(fixedDiscount) : percentDiscount,
    tax_percent: text(item.tax_percent) || '0',
  }
  const immutable = record(item.immutable_snapshot)
  const immutableTotals = record(immutable?.totals)
  const totals = immutableTotals && typeof immutableTotals.total === 'number'
    ? {
        lines: calculateDocumentTotals(draft).lines,
        subtotal: Number(immutableTotals.subtotal) || 0,
        document_discount: Number(immutableTotals.document_discount) || 0,
        taxable_base: Number(immutableTotals.taxable_base) || 0,
        tax: Number(immutableTotals.tax) || 0,
        total: immutableTotals.total,
      }
    : calculateDocumentTotals(draft)
  return {
    ...draft,
    id: item.id,
    status: item.status as ProjectDocumentRecord['status'],
    number: nullableText(item.official_number ?? item.number),
    currency: 'IDR',
    totals,
    lock_version: item.lock_version,
    revised_from_id: nullableText(item.revision_of_id ?? item.revised_from_id),
    superseded_by_id: nullableText(item.superseded_by_id),
    void_reason: nullableText(item.void_reason),
    issued_at: nullableText(item.issued_at),
    created_at: text(item.created_at),
    updated_at: text(item.updated_at),
  }
}

function query(endpoint: string, params: Record<string, string>) {
  const target = new URL(endpoint, window.location.origin)
  Object.entries(params).forEach(([key, value]) => target.searchParams.set(key, value))
  return sameOriginPath(target.toString())
}

function projectValues(project: ProjectDraft) {
  return {
    name: project.name,
    client_name: project.client_name,
    client_company: project.client_company,
    client_address: project.client_address,
    client_contact: project.client_contact,
    issuer_key: project.issuer_key,
    wallet: project.wallet,
    company: project.company,
    status: project.status,
    start_date: project.started_on,
    completion_date: project.completed_on,
    contract_notes: project.contract_notes,
  }
}

function documentValues(document: ProjectDocumentDraft) {
  const metadata = {
    issue_date: document.issue_date,
    due_date: document.due_date,
    valid_until: document.valid_until,
    notes: document.notes,
    payment_terms: document.payment_terms,
    prepared_by: document.prepared_by,
    client_signatory: document.client_signatory,
    project_image_url: document.project_image_url,
  }
  if (document.type === 'receipt' || (document.type === 'invoice' && document.invoice_kind === 'FINAL')) {
    return metadata
  }
  const fixed = document.discount_mode === 'fixed' ? Number(document.discount_value) : 0
  const percentage = document.discount_mode === 'percent' ? document.discount_value : '0'
  return {
    ...metadata,
    document_discount_amount: fixed,
    document_discount_percent: percentage,
    tax_percent: document.tax_percent,
    lines: document.lines.map((line) => ({
      description: line.description,
      quantity: line.quantity,
      unit: line.unit,
      unit_price: line.unit_price,
      line_discount_percent: line.discount_percent,
    })),
  }
}

export function createProjectDocumentApi(options: ApiOptions = {}) {
  const projectsEndpoint = sameOriginPath(options.projectsEndpoint ?? PROJECTS_ENDPOINT)
  const documentsEndpoint = sameOriginPath(options.documentsEndpoint ?? DOCUMENTS_ENDPOINT)
  const request = options.request ?? fetch
  const keyFactory = options.keyFactory ?? generateIdempotencyKey

  async function read(endpoint: string) {
    let response: Response
    try {
      response = await request(endpoint, {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' },
      })
    } catch (error) {
      if (error instanceof ProjectDocumentApiError) throw error
      throw new ProjectDocumentApiError('Data belum dapat dimuat.', { code: 'read_unavailable', retryable: true })
    }
    const body = await responseObject(response)
    if (!response.ok) throw apiError(body, response)
    return envelope(body, response)
  }

  function command<T>(endpoint: string, payload: Record<string, unknown>, expectedVersion: number | undefined, capability: keyof ProjectDocumentCapabilities, parse: (data: Record<string, unknown>) => T): ProjectDocumentCommand<T> {
    const idempotencyKey = keyFactory()
    if (!/^\S{16,128}$/.test(idempotencyKey)) throw new ProjectDocumentApiError('Idempotency key tidak valid.', { code: 'invalid_idempotency_key' })
    const bodyPayload = Object.freeze({
      ...payload,
      idempotency_key: idempotencyKey,
      ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
    })
    const serialized = JSON.stringify(bodyPayload)
    return Object.freeze({
      idempotencyKey,
      payload: bodyPayload,
      async submit(session: ProjectDocumentSession) {
        if (!session.capabilities[capability]) {
          throw new ProjectDocumentApiError(capability === 'projectWrites' ? 'Perubahan proyek belum diaktifkan.' : 'Perubahan dokumen belum diaktifkan.', { code: 'writes_disabled' })
        }
        if (typeof session.csrfToken !== 'string' || session.csrfToken.length < 16) {
          throw new ProjectDocumentApiError('Sesi perubahan tidak valid.', { code: 'invalid_write_session' })
        }
        let response: Response
        try {
          response = await request(endpoint, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
            headers: {
              Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken,
              'Idempotency-Key': idempotencyKey, 'If-Match': expectedVersion === undefined ? '*' : `"${expectedVersion}"`,
            },
            body: serialized,
          })
        } catch {
          throw new ProjectDocumentApiError('Koneksi terputus setelah permintaan dikirim. Status perubahan belum pasti.', {
            code: 'outcome_unknown', uncertain: true, retryable: true,
          })
        }
        const body = await responseObject(response, true)
        if (!response.ok) throw apiError(body, response, true)
        return parse(envelope(body, response).data)
      },
    })
  }

  return {
    async listProjects(): Promise<ProjectListResult> {
      const result = await read(query(projectsEndpoint, { action: 'list' }))
      if (!Array.isArray(result.data.items)) throw new ProjectDocumentApiError('Daftar proyek dari server tidak lengkap.', { code: 'invalid_projects' })
      return { projects: result.data.items.map(normalizeProject), capabilities: result.capabilities }
    },
    async getProject(projectId: string): Promise<ProjectRecord> {
      const result = await read(query(projectsEndpoint, { action: 'get', project_id: uuid(projectId) }))
      return normalizeProject(result.data)
    },
    createProject(project: ProjectDraft) {
      return command(projectsEndpoint, { action: 'create', values: projectValues(project) }, undefined, 'projectWrites', (data) => normalizeProject(data.project))
    },
    updateProject(projectId: string, changes: Partial<ProjectDraft>, expectedVersion: number) {
      uuid(projectId)
      const mapped: Record<string, unknown> = {}
      const fields = [
        'name', 'client_name', 'client_company', 'client_address', 'client_contact',
        'wallet', 'company', 'status', 'contract_notes',
      ] as const
      fields.forEach((field) => {
        if (field in changes) mapped[field] = changes[field]
      })
      if ('started_on' in changes) mapped.start_date = changes.started_on
      if ('completed_on' in changes) mapped.completion_date = changes.completed_on
      return command(projectsEndpoint, { action: 'update', project_id: projectId, changes: mapped }, expectedVersion, 'projectWrites', normalizeProject)
    },
    setProjectStatus(projectId: string, status: ProductionProjectStatus, expectedVersion: number) {
      uuid(projectId)
      return command(projectsEndpoint, { action: 'status', project_id: projectId, status }, expectedVersion, 'projectWrites', normalizeProject)
    },
    archiveProject(projectId: string, expectedVersion: number) {
      uuid(projectId)
      return command(projectsEndpoint, { action: 'archive', project_id: projectId }, expectedVersion, 'projectWrites', normalizeProject)
    },
    async listDocuments(projectId: string): Promise<DocumentListResult> {
      const result = await read(query(documentsEndpoint, { action: 'list', project_id: uuid(projectId) }))
      if (!Array.isArray(result.data.items)) throw new ProjectDocumentApiError('Daftar dokumen dari server tidak lengkap.', { code: 'invalid_documents' })
      return { documents: result.data.items.map(normalizeDocument), capabilities: result.capabilities }
    },
    async getDocument(documentId: string): Promise<ProjectDocumentRecord> {
      const result = await read(query(documentsEndpoint, { action: 'get', document_id: uuid(documentId) }))
      return normalizeDocument(result.data)
    },
    createDocument(document: ProjectDocumentDraft) {
      uuid(document.project_id)
      if (document.type === 'sales_order') throw new ProjectDocumentApiError('Sales Order dibuat otomatis bersama proyek.', { code: 'unsupported_document_create' })
      if (document.type === 'receipt') {
        return command(documentsEndpoint, {
          action: 'create_receipt', project_id: document.project_id,
          allocations: document.allocations.map((allocation) => ({ ledger_source_key: allocation.source_key, amount: allocation.amount })),
          values: documentValues(document),
        }, undefined, 'documentWrites', normalizeDocument)
      }
      return command(documentsEndpoint, {
        action: 'create_invoice', project_id: document.project_id, kind: document.invoice_kind, values: documentValues(document),
      }, undefined, 'documentWrites', normalizeDocument)
    },
    updateDocument(documentId: string, document: ProjectDocumentDraft, expectedVersion: number) {
      uuid(documentId)
      return command(documentsEndpoint, { action: 'update', document_id: documentId, changes: documentValues(document) }, expectedVersion, 'documentWrites', normalizeDocument)
    },
    issueDocument(documentId: string, expectedVersion: number) {
      uuid(documentId)
      return command(documentsEndpoint, { action: 'issue', document_id: documentId }, expectedVersion, 'documentWrites', normalizeDocument)
    },
    voidDocument(documentId: string, reason: string, expectedVersion: number) {
      uuid(documentId)
      return command(documentsEndpoint, { action: 'void', document_id: documentId, reason }, expectedVersion, 'documentWrites', normalizeDocument)
    },
    reviseDocument(documentId: string, expectedVersion: number) {
      uuid(documentId)
      return command(documentsEndpoint, { action: 'revise', document_id: documentId }, expectedVersion, 'documentWrites', normalizeDocument)
    },
    async downloadDocument(documentId: string): Promise<Blob> {
      let response: Response
      try {
        response = await request(query(documentsEndpoint, { action: 'download', document_id: uuid(documentId) }), {
          credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/pdf' },
        })
      } catch (error) {
        if (error instanceof ProjectDocumentApiError) throw error
        throw new ProjectDocumentApiError('PDF belum dapat diunduh.', { code: 'download_unavailable', retryable: true })
      }
      if (!response.ok) {
        if (response.headers.get('content-type')?.includes('application/json')) throw apiError(await responseObject(response), response)
        throw new ProjectDocumentApiError('PDF belum dapat diunduh.', { code: 'download_failed', status: response.status })
      }
      if (!response.headers.get('content-type')?.toLocaleLowerCase('en-US').includes('application/pdf')) {
        throw new ProjectDocumentApiError('Respons unduhan bukan PDF.', { code: 'invalid_pdf' })
      }
      return response.blob()
    },
  }
}

export type ProjectDocumentApi = ReturnType<typeof createProjectDocumentApi>
