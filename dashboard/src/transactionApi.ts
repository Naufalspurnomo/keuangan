export const WRITE_SESSION_ENDPOINT = '/admin/api/write-session.php'
export const TRANSACTIONS_ENDPOINT = '/admin/api/transactions.php'

export type TransactionWriteScope = 'project' | 'office'
export type TransactionWriteDirection = 'Pemasukan' | 'Pengeluaran'

export interface TransactionWritePayload {
  date: string
  scope: TransactionWriteScope
  direction: TransactionWriteDirection
  amount: number
  description: string
  wallet: string
  company: string
  category: string
  project?: string
}

export interface TransactionWriteSession {
  csrfToken: string
  writesEnabled: boolean
  canonicalWritesEnabled?: boolean
}

export interface CanonicalTransactionMutationInput {
  action: 'correction' | 'reversal'
  transactionId: string
  expectedVersion: number
  reason: string
  amount?: number
  description?: string
  category?: string
}

export interface CanonicalTransactionMutationResult {
  transactionId: string
  version: number
  status: 'correction' | 'reversal'
  duplicate: boolean
}

export type RecordedTransaction = {
  recorded: true
  authority: 'google_sheets'
  transactionId: string
  sheetName: string
  sheetRow: number
  sourceBlock: string
  sheetMessageId: string
  projectionStatus: string
  transactionVersion?: never
  duplicate: boolean
} | {
  recorded: true
  authority: 'postgresql'
  transactionId: string
  transactionVersion: number
  sheetName?: never
  sheetRow?: never
  sourceBlock?: never
  sheetMessageId?: never
  projectionStatus?: never
  duplicate: boolean
}

export interface TransactionWriteAttempt {
  readonly idempotencyKey: string
  readonly payload: Readonly<TransactionWritePayload>
  submit: (session: TransactionWriteSession) => Promise<RecordedTransaction>
}

export class TransactionWriteError extends Error {
  readonly code: string
  readonly uncertain: boolean
  readonly retryable: boolean
  readonly status?: number

  constructor(message: string, options: { code: string; uncertain?: boolean; retryable?: boolean; status?: number }) {
    super(message)
    this.name = 'TransactionWriteError'
    this.code = options.code
    this.uncertain = options.uncertain ?? false
    this.retryable = options.retryable ?? false
    this.status = options.status
  }
}

interface ApiOptions {
  endpoint?: string
  request?: typeof fetch
}

interface WriteAttemptOptions extends ApiOptions {
  keyFactory?: () => string
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function sameOriginPath(endpoint: string) {
  const target = new URL(endpoint, window.location.origin)
  if (target.origin !== window.location.origin) {
    throw new TransactionWriteError('Endpoint pencatatan harus same-origin.', { code: 'cross_origin_endpoint' })
  }
  return target.pathname + target.search
}

async function jsonResponse(response: Response, contract: string): Promise<Record<string, unknown>> {
  if (!response.headers.get('content-type')?.toLocaleLowerCase('en-US').includes('application/json')) {
    throw new TransactionWriteError(`Respons ${contract} bukan JSON.`, {
      code: 'invalid_response',
      uncertain: contract === 'pencatatan' && response.ok,
      retryable: contract === 'pencatatan' && response.ok,
      status: response.status,
    })
  }
  try {
    const body = record(await response.json())
    if (!body) throw new Error('not an object')
    return body
  } catch {
    throw new TransactionWriteError(`Respons ${contract} tidak valid.`, {
      code: 'invalid_response',
      uncertain: contract === 'pencatatan' && response.ok,
      retryable: contract === 'pencatatan' && response.ok,
      status: response.status,
    })
  }
}

function apiError(body: Record<string, unknown>, status: number) {
  const error = record(body.error)
  const code = typeof error?.code === 'string' ? error.code : 'transaction_failed'
  const serverMessage = typeof error?.message === 'string' ? error.message : ''
  const uncertain = status >= 500
  const fallback = uncertain
    ? 'Hasil pencatatan belum dapat dipastikan. Coba lagi dengan permintaan yang sama.'
    : 'Transaksi ditolak dan belum dicatat.'
  return new TransactionWriteError(serverMessage || fallback, {
    code,
    uncertain,
    retryable: uncertain,
    status,
  })
}

export async function loadTransactionWriteSession(options: ApiOptions = {}): Promise<TransactionWriteSession> {
  const endpoint = sameOriginPath(options.endpoint ?? WRITE_SESSION_ENDPOINT)
  const request = options.request ?? fetch
  let response: Response
  try {
    response = await request(endpoint, {
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new TransactionWriteError('Status pencatatan tidak dapat dimuat.', {
      code: 'write_session_unavailable',
      retryable: true,
    })
  }
  const body = await jsonResponse(response, 'sesi pencatatan')
  if (!response.ok) throw apiError(body, response.status)
  const data = record(body.data)
  const capabilities = record(data?.capabilities)
  if (body.api_version !== 'dashboard.v1'
      || typeof data?.csrf_token !== 'string'
      || data.csrf_token.length < 16
      || typeof capabilities?.writes_enabled !== 'boolean'
      || (capabilities?.canonical_finance_writes_enabled !== undefined
        && typeof capabilities.canonical_finance_writes_enabled !== 'boolean')) {
    throw new TransactionWriteError('Kontrak sesi pencatatan tidak cocok.', { code: 'invalid_write_session' })
  }
  return {
    csrfToken: data.csrf_token,
    writesEnabled: capabilities.writes_enabled,
    canonicalWritesEnabled: capabilities.canonical_finance_writes_enabled === true,
  }
}

function generateIdempotencyKey() {
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID()
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')
}

function recordedTransaction(body: Record<string, unknown>, response: Response): RecordedTransaction {
  const data = record(body.data)
  const envelopeValid = (response.status === 200 || response.status === 201)
    && body.api_version === 'dashboard.v1'
    && data?.recorded === true
    && typeof data.transaction_id === 'string'
    && data.transaction_id.length > 0
    && typeof data.duplicate === 'boolean'
  const sheetValid = envelopeValid
    && (data?.authority === undefined || data.authority === 'google_sheets')
    && typeof data?.sheet_name === 'string'
    && data.sheet_name.length > 0
    && Number.isSafeInteger(data.sheet_row)
    && Number(data.sheet_row) > 0
    && typeof data.source_block === 'string'
    && data.source_block.length > 0
    && typeof data.sheet_message_id === 'string'
    && data.sheet_message_id.length > 0
    && typeof data.projection_status === 'string'
    && data.projection_status.length > 0
    && data.transaction_version === undefined
  const postgresValid = envelopeValid
    && data?.authority === 'postgresql'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(data.transaction_id))
    && Number.isSafeInteger(data.transaction_version)
    && Number(data.transaction_version) > 0
    && data.sheet_name === undefined
    && data.sheet_row === undefined
    && data.source_block === undefined
    && data.sheet_message_id === undefined
    && data.projection_status === undefined
  if (!data || (!sheetValid && !postgresValid)) {
    throw new TransactionWriteError('Server belum memberikan bukti pencatatan yang lengkap.', {
      code: 'unverified_recording',
      uncertain: true,
      retryable: true,
      status: response.status,
    })
  }
  if (postgresValid) {
    return {
      recorded: true,
      authority: 'postgresql',
      transactionId: data.transaction_id as string,
      transactionVersion: data.transaction_version as number,
      duplicate: data.duplicate as boolean,
    }
  }
  return {
    recorded: true,
    authority: 'google_sheets',
    transactionId: data.transaction_id as string,
    sheetName: data.sheet_name as string,
    sheetRow: data.sheet_row as number,
    sourceBlock: data.source_block as string,
    sheetMessageId: data.sheet_message_id as string,
    projectionStatus: data.projection_status as string,
    duplicate: data.duplicate as boolean,
  }
}

export function createTransactionWriteAttempt(
  payload: TransactionWritePayload,
  options: WriteAttemptOptions = {},
): TransactionWriteAttempt {
  const endpoint = sameOriginPath(options.endpoint ?? TRANSACTIONS_ENDPOINT)
  const request = options.request ?? fetch
  const idempotencyKey = (options.keyFactory ?? generateIdempotencyKey)()
  if (!/^\S{16,128}$/.test(idempotencyKey)) {
    throw new TransactionWriteError('Idempotency key tidak valid.', { code: 'invalid_idempotency_key' })
  }
  const immutablePayload = Object.freeze({ ...payload })
  const body = JSON.stringify({ idempotency_key: idempotencyKey, ...immutablePayload })

  return Object.freeze({
    idempotencyKey,
    payload: immutablePayload,
    async submit(session: TransactionWriteSession) {
      if (!session.writesEnabled) {
        throw new TransactionWriteError('Pencatatan transaksi belum diaktifkan.', {
          code: 'transaction_writes_disabled',
        })
      }
      if (typeof session.csrfToken !== 'string' || session.csrfToken.length < 16) {
        throw new TransactionWriteError('Sesi pencatatan tidak valid.', { code: 'invalid_write_session' })
      }
      let response: Response
      try {
        response = await request(endpoint, {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
          redirect: 'error',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'X-CSRF-Token': session.csrfToken,
            'Idempotency-Key': idempotencyKey,
          },
          body,
        })
      } catch {
        throw new TransactionWriteError('Koneksi terputus setelah permintaan dikirim. Status pencatatan belum pasti.', {
          code: 'transaction_outcome_unknown',
          uncertain: true,
          retryable: true,
        })
      }
      const responseBody = await jsonResponse(response, 'pencatatan')
      if (!response.ok) throw apiError(responseBody, response.status)
      return recordedTransaction(responseBody, response)
    },
  })
}

export function createCanonicalTransactionMutation(
  input: CanonicalTransactionMutationInput,
  options: WriteAttemptOptions = {},
) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.transactionId)) {
    throw new TransactionWriteError('ID transaksi kanonis tidak valid.', { code: 'invalid_transaction_id' })
  }
  if (!Number.isSafeInteger(input.expectedVersion) || input.expectedVersion < 1) {
    throw new TransactionWriteError('Versi transaksi tidak valid.', { code: 'invalid_transaction_version' })
  }
  const reason = input.reason.trim()
  if (!reason) throw new TransactionWriteError('Alasan wajib diisi.', { code: 'reason_required' })
  if (input.action === 'correction'
      && input.amount === undefined
      && input.description === undefined
      && input.category === undefined) {
    throw new TransactionWriteError('Koreksi harus mengubah nominal, deskripsi, atau kategori.', { code: 'empty_correction' })
  }
  const params = new URLSearchParams({ action: input.action, transaction_id: input.transactionId })
  const endpoint = sameOriginPath(`${options.endpoint ?? TRANSACTIONS_ENDPOINT}?${params.toString()}`)
  const request = options.request ?? fetch
  const idempotencyKey = (options.keyFactory ?? generateIdempotencyKey)()
  if (!/^\S{16,128}$/.test(idempotencyKey)) {
    throw new TransactionWriteError('Idempotency key tidak valid.', { code: 'invalid_idempotency_key' })
  }
  const body = JSON.stringify({
    idempotency_key: idempotencyKey,
    expected_version: input.expectedVersion,
    reason,
    ...(input.amount === undefined ? {} : { amount: input.amount }),
    ...(input.description === undefined ? {} : { description: input.description }),
    ...(input.category === undefined ? {} : { category: input.category }),
  })

  return Object.freeze({
    idempotencyKey,
    async submit(session: TransactionWriteSession): Promise<CanonicalTransactionMutationResult> {
      if (!session.canonicalWritesEnabled) {
        throw new TransactionWriteError('Koreksi dan pembalikan belum diaktifkan.', {
          code: 'canonical_finance_writes_disabled',
        })
      }
      if (typeof session.csrfToken !== 'string' || session.csrfToken.length < 16) {
        throw new TransactionWriteError('Sesi pencatatan tidak valid.', { code: 'invalid_write_session' })
      }
      let response: Response
      try {
        response = await request(endpoint, {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
          redirect: 'error',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'X-CSRF-Token': session.csrfToken,
            'Idempotency-Key': idempotencyKey,
          },
          body,
        })
      } catch {
        throw new TransactionWriteError('Koneksi terputus. Status perubahan belum pasti.', {
          code: 'transaction_outcome_unknown',
          uncertain: true,
          retryable: true,
        })
      }
      const responseBody = await jsonResponse(response, 'perubahan transaksi')
      if (!response.ok) throw apiError(responseBody, response.status)
      const data = record(responseBody.data)
      const transaction = record(data?.transaction)
      const status = transaction?.status
      if (responseBody.api_version !== 'finance.v1'
          || typeof transaction?.id !== 'string'
          || !Number.isSafeInteger(transaction.version)
          || (status !== 'correction' && status !== 'reversal')
          || typeof data?.duplicate !== 'boolean') {
        throw new TransactionWriteError('Server belum memberikan bukti perubahan yang lengkap.', {
          code: 'unverified_mutation', uncertain: true, retryable: true, status: response.status,
        })
      }
      return {
        transactionId: transaction.id,
        version: transaction.version as number,
        status,
        duplicate: data.duplicate,
      }
    },
  })
}

export function jakartaToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Jakarta',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${value.year}-${value.month}-${value.day}`
}
