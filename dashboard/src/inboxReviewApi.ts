export const INBOX_REVIEWS_ENDPOINT = '/admin/api/inbox-reviews.php'

export type InboxReviewAction = 'ignore' | 'confirm_processed'

export interface InboxReviewItem {
  eventKey: string
  provider: string
  messageId: string
  eventType: string
  isGroup: boolean
  financeSignal: boolean
  payloadScore: number
  status: string
  resultStatus: string
  attempts: number
  receivedAt: string
  updatedAt: string
}

export interface InboxReviewDetail extends InboxReviewItem {
  bodyText: string
  quotedMessageId: string | null
  mediaAvailable: boolean
}

export interface InboxReviewList {
  items: InboxReviewItem[]
  writesEnabled: boolean
  allowedActions: InboxReviewAction[]
  total: number
  offset: number
  limit: number
  hasMore: boolean
}

export interface InboxReviewResult {
  eventKey: string
  messageId: string
  action: InboxReviewAction
  status: string
}

export interface InboxReviewCommand {
  readonly idempotencyKey: string
  readonly payload: Readonly<{ action: InboxReviewAction; reason: string; expected_status: string }>
  submit: (session: { csrfToken: string }) => Promise<InboxReviewResult>
}

export interface InboxReviewApi {
  list: (page?: { offset: number; limit: number }) => Promise<InboxReviewList>
  detail: (eventKey: string) => Promise<InboxReviewDetail>
  command: (input: {
    eventKey: string
    action: InboxReviewAction
    reason: string
    expectedStatus: string
  }) => InboxReviewCommand
}

interface ApiOptions {
  endpoint?: string
  request?: typeof fetch
  keyFactory?: () => string
}

interface ErrorOptions {
  code: string
  status?: number
  uncertain?: boolean
}

export class InboxReviewApiError extends Error {
  readonly code: string
  readonly status?: number
  readonly uncertain: boolean

  constructor(message: string, options: ErrorOptions) {
    super(message)
    this.name = 'InboxReviewApiError'
    this.code = options.code
    this.status = options.status
    this.uncertain = options.uncertain ?? false
  }
}

const EVENT_KEY = /^[0-9a-f]{64}$/
const REVIEW_STATUS = /^needs_review(?:_[a-z0-9_]+)?$/
const ACTIONS = new Set<InboxReviewAction>(['ignore', 'confirm_processed'])

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function sameOriginPath(endpoint: string) {
  const target = new URL(endpoint, window.location.origin)
  if (target.origin !== window.location.origin) {
    throw new InboxReviewApiError('Endpoint peninjauan harus same-origin.', { code: 'cross_origin_endpoint' })
  }
  return target.pathname + target.search
}

function eventKey(value: string) {
  if (!EVENT_KEY.test(value)) {
    throw new InboxReviewApiError('Identitas pesan tidak valid.', { code: 'invalid_event_key' })
  }
  return value
}

function keyFactory() {
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID()
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')
}

async function responseObject(response: Response, write = false) {
  if (!response.headers.get('content-type')?.toLocaleLowerCase('en-US').includes('application/json')) {
    throw new InboxReviewApiError('Respons peninjauan bukan JSON.', {
      code: 'invalid_response', status: response.status, uncertain: write && response.ok,
    })
  }
  try {
    const body = record(await response.json())
    if (!body) throw new Error('not object')
    return body
  } catch (error) {
    if (error instanceof InboxReviewApiError) throw error
    throw new InboxReviewApiError('Respons peninjauan tidak valid.', {
      code: 'invalid_response', status: response.status, uncertain: write && response.ok,
    })
  }
}

function apiError(body: Record<string, unknown>, response: Response, write: boolean) {
  const error = record(body.error)
  const code = typeof error?.code === 'string' ? error.code : 'review_request_failed'
  const uncertain = write && (response.status >= 500 || code === 'review_outcome_unknown')
  const message = typeof error?.message === 'string' && error.message
    ? error.message
    : uncertain
      ? 'Hasil keputusan belum dapat dipastikan.'
      : 'Permintaan peninjauan ditolak.'
  return new InboxReviewApiError(message, { code, status: response.status, uncertain })
}

async function requestObject(request: typeof fetch, url: string, init: RequestInit, write = false) {
  let response: Response
  try {
    response = await request(url, init)
  } catch {
    throw new InboxReviewApiError(
      write
        ? 'Koneksi terputus setelah keputusan dikirim. Hasil keputusan belum dapat dipastikan.'
        : 'Data peninjauan belum dapat dimuat.',
      { code: write ? 'review_outcome_unknown' : 'review_service_unavailable', uncertain: write },
    )
  }
  const body = await responseObject(response, write)
  if (!response.ok) throw apiError(body, response, write)
  if (body.api_version !== 'dashboard.v1' || !record(body.data)) {
    throw new InboxReviewApiError('Kontrak respons peninjauan tidak cocok.', {
      code: 'invalid_response', status: response.status, uncertain: write,
    })
  }
  return record(body.data)!
}

function requiredText(source: Record<string, unknown>, field: string) {
  if (typeof source[field] !== 'string') throw new InboxReviewApiError('Data peninjauan tidak lengkap.', { code: 'invalid_response' })
  return source[field] as string
}

function reviewItem(value: unknown): InboxReviewItem {
  const source = record(value)
  if (!source
      || typeof source.event_key !== 'string' || !EVENT_KEY.test(source.event_key)
      || typeof source.is_group !== 'boolean'
      || typeof source.finance_signal !== 'boolean'
      || !Number.isSafeInteger(source.payload_score)
      || !Number.isSafeInteger(source.attempts)) {
    throw new InboxReviewApiError('Data peninjauan tidak lengkap.', { code: 'invalid_response' })
  }
  return {
    eventKey: source.event_key,
    provider: requiredText(source, 'provider'),
    messageId: requiredText(source, 'message_id'),
    eventType: requiredText(source, 'event_type'),
    isGroup: source.is_group,
    financeSignal: source.finance_signal,
    payloadScore: source.payload_score as number,
    status: requiredText(source, 'status'),
    resultStatus: requiredText(source, 'result_status'),
    attempts: source.attempts as number,
    receivedAt: requiredText(source, 'received_at'),
    updatedAt: requiredText(source, 'updated_at'),
  }
}

function result(value: Record<string, unknown>): InboxReviewResult {
  if (typeof value.event_key !== 'string' || !EVENT_KEY.test(value.event_key)
      || typeof value.message_id !== 'string'
      || typeof value.action !== 'string' || !ACTIONS.has(value.action as InboxReviewAction)
      || typeof value.status !== 'string') {
    throw new InboxReviewApiError('Bukti keputusan dari server tidak lengkap.', {
      code: 'invalid_response', uncertain: true,
    })
  }
  return {
    eventKey: value.event_key,
    messageId: value.message_id,
    action: value.action as InboxReviewAction,
    status: value.status,
  }
}

export function createInboxReviewApi(options: ApiOptions = {}): InboxReviewApi {
  const endpoint = sameOriginPath(options.endpoint ?? INBOX_REVIEWS_ENDPOINT)
  const request = options.request ?? fetch
  const makeKey = options.keyFactory ?? keyFactory
  const read = (url: string) => requestObject(request, url, {
    credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' },
  })

  return {
    async list(page = { offset: 0, limit: 25 }) {
      if (!Number.isSafeInteger(page.offset) || page.offset < 0
          || !Number.isSafeInteger(page.limit) || page.limit < 1 || page.limit > 50) {
        throw new InboxReviewApiError('Halaman peninjauan tidak valid.', { code: 'invalid_pagination' })
      }
      const data = await read(`${endpoint}?action=list&offset=${page.offset}&limit=${page.limit}`)
      if (!Array.isArray(data.items) || typeof data.writes_enabled !== 'boolean' || !Array.isArray(data.allowed_actions)
          || !Number.isSafeInteger(data.total) || !Number.isSafeInteger(data.offset)
          || !Number.isSafeInteger(data.limit) || typeof data.has_more !== 'boolean') {
        throw new InboxReviewApiError('Daftar peninjauan tidak lengkap.', { code: 'invalid_response' })
      }
      const allowedActions = data.allowed_actions.map((action) => {
        if (typeof action !== 'string' || !ACTIONS.has(action as InboxReviewAction)) {
          throw new InboxReviewApiError('Daftar tindakan tidak valid.', { code: 'invalid_response' })
        }
        return action as InboxReviewAction
      })
      return {
        items: data.items.map(reviewItem),
        writesEnabled: data.writes_enabled,
        allowedActions,
        total: data.total as number,
        offset: data.offset as number,
        limit: data.limit as number,
        hasMore: data.has_more,
      }
    },
    async detail(key: string) {
      const data = await read(`${endpoint}?action=detail&event_key=${eventKey(key)}`)
      const item = reviewItem(data)
      if (typeof data.body_text !== 'string'
          || !(typeof data.quoted_message_id === 'string' || data.quoted_message_id === null)
          || typeof data.media_available !== 'boolean') {
        throw new InboxReviewApiError('Detail peninjauan tidak lengkap.', { code: 'invalid_response' })
      }
      return {
        ...item,
        bodyText: data.body_text,
        quotedMessageId: data.quoted_message_id as string | null,
        mediaAvailable: data.media_available,
      }
    },
    command(input) {
      const key = eventKey(input.eventKey)
      const reason = input.reason.trim()
      if (!ACTIONS.has(input.action)) throw new InboxReviewApiError('Tindakan tidak didukung.', { code: 'invalid_review_action' })
      if (!reason || reason.length > 1000) throw new InboxReviewApiError('Alasan harus berisi 1 sampai 1000 karakter.', { code: 'invalid_review_reason' })
      if (!REVIEW_STATUS.test(input.expectedStatus)) throw new InboxReviewApiError('Status pesan tidak valid.', { code: 'invalid_expected_status' })
      const idempotencyKey = makeKey()
      if (!/^\S{16,128}$/.test(idempotencyKey)) throw new InboxReviewApiError('Identitas perintah tidak valid.', { code: 'invalid_idempotency_key' })
      const payload = Object.freeze({ action: input.action, reason, expected_status: input.expectedStatus })
      const serialized = JSON.stringify(payload)
      return Object.freeze({
        idempotencyKey,
        payload,
        async submit(session: { csrfToken: string }) {
          if (typeof session.csrfToken !== 'string' || session.csrfToken.length < 16) {
            throw new InboxReviewApiError('Sesi keputusan tidak valid.', { code: 'invalid_write_session' })
          }
          const data = await requestObject(request, `${endpoint}?event_key=${key}`, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
            headers: {
              Accept: 'application/json',
              'Content-Type': 'application/json',
              'X-CSRF-Token': session.csrfToken,
              'Idempotency-Key': idempotencyKey,
            },
            body: serialized,
          }, true)
          return result(data)
        },
      })
    },
  }
}

export function reviewErrorMessage(error: unknown) {
  if (!(error instanceof InboxReviewApiError) && !(error && typeof error === 'object' && 'code' in error)) {
    return 'Keputusan belum dapat diproses.'
  }
  const value = error as { code: string; uncertain?: boolean }
  if (value.uncertain || value.code === 'review_outcome_unknown') {
    return 'Hasil keputusan belum dapat dipastikan. Jangan kirim keputusan baru; periksa daftar kembali.'
  }
  if (value.code === 'review_conflict' || value.code === 'ledger_transaction_exists' || value.code === 'ledger_transaction_not_found') {
    return value.code === 'review_conflict'
      ? 'Pesan sudah berubah atau ditinjau di tempat lain. Muat daftar kembali sebelum memutuskan.'
      : 'Keputusan tidak cocok dengan bukti buku besar terbaru.'
  }
  if (value.code === 'ledger_proof_incomplete') return 'Pemeriksaan buku besar belum lengkap. Tidak ada perubahan yang dilakukan.'
  if (value.code === 'ledger_unavailable') return 'Buku besar sedang tidak tersedia. Tidak ada perubahan yang dilakukan.'
  if (value.code === 'invalid_review_reason' || value.code === 'invalid_review_action' || value.code === 'invalid_expected_status') {
    return 'Alasan atau keputusan tidak valid. Periksa isian lalu buat keputusan baru.'
  }
  if (value.code === 'review_writes_disabled') return 'Perubahan peninjauan sedang dinonaktifkan.'
  return error instanceof Error && error.message ? error.message : 'Keputusan belum dapat diproses.'
}
