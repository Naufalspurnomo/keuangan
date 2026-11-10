import type { ProjectDocumentSession } from './projectDocumentApi'

export const EVIDENCE_ENDPOINT = '/admin/api/evidence.php'

export interface ProjectTransactionEvidence {
  id: string
  project_id: string
  ledger_source_key: string
  mime_type: 'image/jpeg' | 'image/png' | 'image/webp'
  byte_size: number
  sha256: string
  original_name: string
  review_status: 'pending' | 'approved' | 'rejected'
  review_note: string | null
  reviewed_at: string | null
  created_at: string
  lock_version: number
}

interface EvidenceApiOptions {
  endpoint?: string
  request?: typeof fetch
  keyFactory?: () => string
}

function uuid(value: string) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) throw new Error('ID bukti tidak valid.')
  return value.toLowerCase()
}

function key() {
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID()
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Respons bukti tidak valid.')
  return value as Record<string, unknown>
}

function normalize(value: unknown): ProjectTransactionEvidence {
  const row = object(value)
  const status = row.review_status
  const mime = row.mime_type
  if (!['pending', 'approved', 'rejected'].includes(String(status)) || !['image/jpeg', 'image/png', 'image/webp'].includes(String(mime))) throw new Error('Status bukti tidak valid.')
  const size = row.byte_size
  const version = row.lock_version
  if (!Number.isSafeInteger(size) || Number(size) <= 0 || !Number.isSafeInteger(version) || Number(version) < 0) throw new Error('Metadata bukti tidak valid.')
  return {
    id: uuid(String(row.id)), project_id: uuid(String(row.project_id)), ledger_source_key: String(row.ledger_source_key),
    mime_type: mime as ProjectTransactionEvidence['mime_type'], byte_size: Number(size), sha256: String(row.sha256),
    original_name: String(row.original_name), review_status: status as ProjectTransactionEvidence['review_status'],
    review_note: typeof row.review_note === 'string' ? row.review_note : null,
    reviewed_at: typeof row.reviewed_at === 'string' ? row.reviewed_at : null,
    created_at: String(row.created_at), lock_version: Number(version),
  }
}

async function jsonResponse(response: Response) {
  const body = object(await response.json())
  if (!response.ok) {
    const error = object(body.error)
    throw new Error(typeof error.message === 'string' ? error.message : 'Operasi bukti gagal.')
  }
  const data = object(body.data)
  return data
}

export function createProjectEvidenceApi(options: EvidenceApiOptions = {}) {
  const endpoint = options.endpoint ?? EVIDENCE_ENDPOINT
  const request = options.request ?? fetch
  const keyFactory = options.keyFactory ?? key
  const sessionHeaders = (session: ProjectDocumentSession) => {
    if (!session.capabilities.documentWrites || session.csrfToken.length < 16) throw new Error('Sesi perubahan bukti tidak aktif.')
    const idempotencyKey = keyFactory()
    if (!/^\S{16,128}$/.test(idempotencyKey)) throw new Error('Idempotency key tidak valid.')
    return { idempotencyKey, csrf: session.csrfToken }
  }
  return {
    async list(projectId: string) {
      const response = await request(`${endpoint}?action=list&project_id=${encodeURIComponent(uuid(projectId))}`, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' } })
      const data = await jsonResponse(response)
      if (!Array.isArray(data.items)) throw new Error('Daftar bukti tidak lengkap.')
      return data.items.map(normalize)
    },
    async upload(projectId: string, ledgerSourceKey: string, file: File, session: ProjectDocumentSession) {
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size < 1 || file.size > 5 * 1024 * 1024) throw new Error('Bukti wajib JPEG, PNG, atau WebP maksimal 5 MiB.')
      const { idempotencyKey, csrf } = sessionHeaders(session)
      const body = new FormData()
      body.set('ledger_source_key', ledgerSourceKey)
      body.set('evidence', file)
      const response = await request(`${endpoint}?action=upload&project_id=${encodeURIComponent(uuid(projectId))}`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': idempotencyKey }, body,
      })
      return normalize(await jsonResponse(response))
    },
    async review(evidence: ProjectTransactionEvidence, status: 'approved' | 'rejected', note: string, session: ProjectDocumentSession) {
      const { idempotencyKey, csrf } = sessionHeaders(session)
      const response = await request(`${endpoint}?action=review&evidence_id=${encodeURIComponent(uuid(evidence.id))}`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ expected_version: evidence.lock_version, status, note }),
      })
      return normalize(await jsonResponse(response))
    },
    async download(evidenceId: string) {
      const response = await request(`${endpoint}?action=download&evidence_id=${encodeURIComponent(uuid(evidenceId))}`, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'image/jpeg, image/png, image/webp' } })
      if (!response.ok || !response.headers.get('content-type')?.startsWith('image/')) throw new Error('Bukti belum dapat dibuka.')
      return response.blob()
    },
  }
}

export type ProjectEvidenceApi = ReturnType<typeof createProjectEvidenceApi>
