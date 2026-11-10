import { describe, expect, it, vi } from 'vitest'

import { createProjectEvidenceApi } from './projectEvidenceApi'

const projectId = '11111111-1111-4111-8111-111111111111'
const evidenceId = '44444444-4444-4444-8444-444444444444'
const item = {
  id: evidenceId, project_id: projectId, ledger_source_key: 'ledger:1', mime_type: 'image/png',
  byte_size: 12, sha256: 'a'.repeat(64), original_name: 'bukti.png', review_status: 'pending',
  review_note: null, reviewed_at: null, created_at: '2026-11-10T00:00:00Z', lock_version: 0,
}
const session = {
  csrfToken: 'csrf-token-that-is-long-enough',
  capabilities: { projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false },
}
const response = (data: unknown, status = 200, headers: Record<string, string> = { 'content-type': 'application/json' }) => new Response(JSON.stringify({ api_version: 'dashboard.v1', data, meta: { capabilities: {} } }), { status, headers })

describe('projectEvidenceApi', () => {
  it('uploads multipart evidence without forcing a content-type and reads authoritative status', async () => {
    const request = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(init?.body).toBeInstanceOf(FormData)
      expect(new Headers(init?.headers).has('Content-Type')).toBe(false)
      expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('evidence-command-key-0001')
      return response(item, 201)
    })
    const api = createProjectEvidenceApi({ request: request as typeof fetch, keyFactory: () => 'evidence-command-key-0001' })
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'bukti.png', { type: 'image/png' })

    const result = await api.upload(projectId, 'ledger:1', file, session)

    expect(result.review_status).toBe('pending')
    expect(request.mock.calls[0][0]).toContain(`project_id=${projectId}`)
  })

  it('reviews with explicit lock version and does not retry', async () => {
    const request = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({ expected_version: 0, status: 'approved', note: '' })
      return response({ ...item, review_status: 'approved', lock_version: 1 })
    })
    const api = createProjectEvidenceApi({ request: request as typeof fetch, keyFactory: () => 'evidence-command-key-0002' })

    const result = await api.review(item as never, 'approved', '', session)

    expect(result.review_status).toBe('approved')
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('rejects unsupported or oversized files before network', async () => {
    const request = vi.fn()
    const api = createProjectEvidenceApi({ request: request as typeof fetch })
    const file = new File(['not-image'], 'fake.txt', { type: 'text/plain' })

    await expect(api.upload(projectId, 'ledger:1', file, session)).rejects.toThrow(/JPEG, PNG, atau WebP/)
    expect(request).not.toHaveBeenCalled()
  })

  it('lists and downloads private evidence', async () => {
    const image = new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' })
    const request = vi.fn(async (url: string) => url.includes('action=list')
      ? response({ items: [item] })
      : new Response(image, { status: 200, headers: { 'content-type': 'image/png' } }))
    const api = createProjectEvidenceApi({ request: request as typeof fetch })

    expect((await api.list(projectId))[0].id).toBe(evidenceId)
    expect((await api.download(evidenceId)).type).toBe('image/png')
  })
})
