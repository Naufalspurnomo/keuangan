import type { TransactionWriteSession } from './transactionApi'

const ENDPOINT = '/admin/api/debts.php'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

type RequestFn = typeof fetch
interface ApiOptions { endpoint?: string; request?: RequestFn }
export interface CreateDebtInput {
  lenderWalletId: string
  borrowerWalletId: string
  lenderBusinessUnitId: string
  borrowerBusinessUnitId: string
  projectId: string | null
  principal: number
  occurredAt: string
  dueAt: string | null
  description: string
}
export interface DebtRepaymentInput {
  debtId: string
  expectedVersion: number
  amount: number
  occurredAt: string
  description: string
}
export interface DebtEventMutationInput {
  debtId: string
  eventId: string
  expectedVersion: number
  occurredAt: string
  reason: string
  amount?: number
}
export interface DebtMutationResult { debt: { id: string; version: number; status: 'open' | 'paid' | 'reversed' }; duplicate: boolean }

export class DebtWriteError extends Error {
  readonly code: string
  readonly status?: number
  readonly uncertain: boolean
  constructor(message: string, options: { code: string; status?: number; uncertain?: boolean }) {
    super(message)
    this.name = 'DebtWriteError'
    this.code = options.code
    this.status = options.status
    this.uncertain = options.uncertain === true
  }
}

function key() {
  return `debt-${crypto.randomUUID()}`
}
function path(value: string) {
  const url = new URL(value, window.location.origin)
  if (url.origin !== window.location.origin || !url.pathname.startsWith('/admin/api/')) throw new DebtWriteError('Endpoint hutang tidak aman.', { code: 'invalid_endpoint' })
  return `${url.pathname}${url.search}`
}
function cleanText(value: string, label: string) {
  const clean = value.trim().replace(/\s+/g, ' ')
  if (!clean) throw new DebtWriteError(`${label} wajib diisi.`, { code: 'invalid_input' })
  return clean
}
function validMoney(value: number) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new DebtWriteError('Jumlah harus berupa rupiah bulat lebih dari nol.', { code: 'invalid_amount' })
}
function validateUuid(value: string, label: string) {
  if (!UUID.test(value)) throw new DebtWriteError(`${label} tidak valid.`, { code: 'invalid_identifier' })
}

async function submit(endpoint: string, body: string, idempotencyKey: string, session: TransactionWriteSession, request: RequestFn): Promise<DebtMutationResult> {
  if (!session.debtWritesEnabled || !session.csrfToken) throw new DebtWriteError('Pencatatan hutang belum tersedia.', { code: 'writes_disabled' })
  let response: Response
  try {
    response = await request(endpoint, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken, 'Idempotency-Key': idempotencyKey },
      body,
    })
  } catch {
    throw new DebtWriteError('Status pencatatan belum pasti. Coba lagi permintaan yang sama.', { code: 'network_error', uncertain: true })
  }
  let payload: unknown
  try { payload = await response.json() } catch { throw new DebtWriteError('Respons layanan hutang tidak valid.', { code: 'invalid_response', status: response.status }) }
  const value = payload as { data?: DebtMutationResult; error?: { code?: string; message?: string } }
  if (!response.ok) throw new DebtWriteError(value.error?.message || 'Pencatatan hutang gagal.', { code: value.error?.code || 'request_failed', status: response.status })
  const result = value.data
  if (!result || !UUID.test(result.debt?.id) || !Number.isSafeInteger(result.debt.version) || !['open', 'paid', 'reversed'].includes(result.debt.status) || typeof result.duplicate !== 'boolean') {
    throw new DebtWriteError('Kontrak respons hutang tidak cocok.', { code: 'invalid_response', status: response.status })
  }
  return result
}

export function createDebtAttempt(input: CreateDebtInput, options: ApiOptions = {}) {
  validateUuid(input.lenderWalletId, 'Dompet pemberi dana')
  validateUuid(input.borrowerWalletId, 'Dompet peminjam')
  validateUuid(input.lenderBusinessUnitId, 'Unit pemberi dana')
  validateUuid(input.borrowerBusinessUnitId, 'Unit peminjam')
  if (input.projectId) validateUuid(input.projectId, 'Proyek')
  if (input.lenderWalletId === input.borrowerWalletId) throw new DebtWriteError('Dompet peminjam dan pemberi dana harus berbeda.', { code: 'invalid_wallets' })
  validMoney(input.principal)
  const idempotencyKey = key()
  const body = JSON.stringify({
    idempotency_key: idempotencyKey,
    lender_wallet_id: input.lenderWalletId,
    borrower_wallet_id: input.borrowerWalletId,
    lender_business_unit_id: input.lenderBusinessUnitId,
    borrower_business_unit_id: input.borrowerBusinessUnitId,
    project_id: input.projectId,
    principal: input.principal,
    currency: 'IDR',
    occurred_at: input.occurredAt,
    due_at: input.dueAt,
    description: cleanText(input.description, 'Keterangan'),
  })
  const endpoint = path(`${options.endpoint ?? ENDPOINT}?action=create`)
  return { idempotencyKey, submit: (session: TransactionWriteSession) => submit(endpoint, body, idempotencyKey, session, options.request ?? fetch) }
}

export function createDebtRepaymentAttempt(input: DebtRepaymentInput, options: ApiOptions = {}) {
  validateUuid(input.debtId, 'Hutang')
  if (!Number.isSafeInteger(input.expectedVersion) || input.expectedVersion < 1) throw new DebtWriteError('Versi hutang tidak valid.', { code: 'invalid_version' })
  validMoney(input.amount)
  const idempotencyKey = key()
  const body = JSON.stringify({
    idempotency_key: idempotencyKey,
    expected_version: input.expectedVersion,
    amount: input.amount,
    occurred_at: input.occurredAt,
    description: cleanText(input.description, 'Keterangan'),
  })
  const endpoint = path(`${options.endpoint ?? ENDPOINT}?action=repay&debt_id=${encodeURIComponent(input.debtId)}`)
  return { idempotencyKey, submit: (session: TransactionWriteSession) => submit(endpoint, body, idempotencyKey, session, options.request ?? fetch) }
}

function createDebtEventAttempt(action: 'correct' | 'reverse', input: DebtEventMutationInput, options: ApiOptions = {}) {
  validateUuid(input.debtId, 'Hutang')
  validateUuid(input.eventId, 'Kejadian hutang')
  if (!Number.isSafeInteger(input.expectedVersion) || input.expectedVersion < 1) throw new DebtWriteError('Versi hutang tidak valid.', { code: 'invalid_version' })
  if (action === 'correct') validMoney(Number(input.amount))
  const idempotencyKey = key()
  const body = JSON.stringify({
    idempotency_key: idempotencyKey,
    expected_version: input.expectedVersion,
    ...(action === 'correct' ? { amount: input.amount } : {}),
    occurred_at: input.occurredAt,
    reason: cleanText(input.reason, 'Alasan'),
  })
  const endpoint = path(`${options.endpoint ?? ENDPOINT}?action=${action}&debt_id=${encodeURIComponent(input.debtId)}&event_id=${encodeURIComponent(input.eventId)}`)
  return { idempotencyKey, submit: (session: TransactionWriteSession) => submit(endpoint, body, idempotencyKey, session, options.request ?? fetch) }
}

export const createDebtCorrectionAttempt = (input: DebtEventMutationInput, options: ApiOptions = {}) => createDebtEventAttempt('correct', input, options)
export const createDebtReversalAttempt = (input: DebtEventMutationInput, options: ApiOptions = {}) => createDebtEventAttempt('reverse', input, options)
