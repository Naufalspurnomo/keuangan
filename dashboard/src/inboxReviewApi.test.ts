import { describe, expect, it, vi } from 'vitest'

import {
  InboxReviewApiError,
  createInboxReviewApi,
  reviewErrorMessage,
} from './inboxReviewApi'

const EVENT_KEY = 'a'.repeat(64)
const JSON_HEADERS = { 'Content-Type': 'application/json' }

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS })
}

const listEnvelope = {
  api_version: 'dashboard.v1',
  data: {
    items: [{
      event_key: EVENT_KEY,
      provider: 'wuzapi',
      message_id: 'message-1',
      event_type: 'image',
      is_group: false,
      finance_signal: true,
      payload_score: 9,
      status: 'needs_review_notified',
      result_status: 'ignored_finance_signal',
      attempts: 2,
      received_at: '2026-11-09T10:00:00Z',
      updated_at: '2026-11-09T10:05:00Z',
    }],
    writes_enabled: true,
    allowed_actions: ['confirm_processed', 'ignore'],
  },
}

const detailEnvelope = {
  api_version: 'dashboard.v1',
  data: {
    ...listEnvelope.data.items[0],
    body_text: '<img src=x onerror=alert(1)> Transfer Rp100.000',
    quoted_message_id: 'quote-1',
    media_available: true,
  },
}

describe('inbox review API', () => {
  it('uses exact same-origin list and detail reads and validates their contracts', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(json(listEnvelope))
      .mockResolvedValueOnce(json(detailEnvelope))
    const api = createInboxReviewApi({ request })

    const list = await api.list()
    const detail = await api.detail(EVENT_KEY)

    expect(request).toHaveBeenNthCalledWith(1, '/admin/api/inbox-reviews.php?action=list', expect.objectContaining({
      credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    }))
    expect(request).toHaveBeenNthCalledWith(2, `/admin/api/inbox-reviews.php?action=detail&event_key=${EVENT_KEY}`, expect.any(Object))
    expect(list.writesEnabled).toBe(true)
    expect(list.allowedActions).toEqual(['confirm_processed', 'ignore'])
    expect(list.items[0].eventKey).toBe(EVENT_KEY)
    expect(detail.bodyText).toBe('<img src=x onerror=alert(1)> Transfer Rp100.000')
    expect(detail.mediaAvailable).toBe(true)
  })

  it('rejects cross-origin endpoints, malformed event keys, and invalid response envelopes', async () => {
    expect(() => createInboxReviewApi({ endpoint: 'https://evil.example/reviews' })).toThrow(/same-origin/i)
    const api = createInboxReviewApi({ request: vi.fn().mockResolvedValue(json({ api_version: 'dashboard.v1', data: { items: 'bad' } })) })
    await expect(api.detail('../secret')).rejects.toMatchObject({ code: 'invalid_event_key' })
    await expect(api.list()).rejects.toMatchObject({ code: 'invalid_response' })
  })

  it('creates an immutable command whose retries keep one idempotency key and exact body', async () => {
    const request = vi.fn()
      .mockRejectedValueOnce(new TypeError('network'))
      .mockResolvedValueOnce(json({
        api_version: 'dashboard.v1',
        data: { event_key: EVENT_KEY, message_id: 'message-1', action: 'ignore', status: 'ignored' },
      }))
    const api = createInboxReviewApi({ request, keyFactory: () => 'review-command-0001' })
    const command = api.command({
      eventKey: EVENT_KEY,
      action: 'ignore',
      reason: 'Bukan transaksi',
      expectedStatus: 'needs_review_notified',
    })

    await expect(command.submit({ csrfToken: 'owner-csrf-token' })).rejects.toMatchObject({
      code: 'review_outcome_unknown', uncertain: true,
    })
    await expect(command.submit({ csrfToken: 'owner-csrf-token' })).resolves.toMatchObject({ status: 'ignored' })

    expect(command.idempotencyKey).toBe('review-command-0001')
    expect(request).toHaveBeenCalledTimes(2)
    for (const call of request.mock.calls) {
      expect(call[0]).toBe(`/admin/api/inbox-reviews.php?event_key=${EVENT_KEY}`)
      expect(call[1]).toMatchObject({
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRF-Token': 'owner-csrf-token',
          'Idempotency-Key': 'review-command-0001',
        },
        body: JSON.stringify({ action: 'ignore', reason: 'Bukan transaksi', expected_status: 'needs_review_notified' }),
      })
    }
  })

  it('maps stale, ledger, and validation failures to plain Indonesian without offering automatic retry', () => {
    expect(reviewErrorMessage(new InboxReviewApiError('server', { code: 'review_conflict', status: 409 }))).toMatch(/sudah berubah/i)
    expect(reviewErrorMessage(new InboxReviewApiError('server', { code: 'ledger_proof_incomplete', status: 503 }))).toMatch(/belum lengkap/i)
    expect(reviewErrorMessage(new InboxReviewApiError('server', { code: 'ledger_unavailable', status: 503 }))).toMatch(/tidak tersedia/i)
    expect(reviewErrorMessage(new InboxReviewApiError('server', { code: 'invalid_review_reason', status: 422 }))).toMatch(/alasan/i)
    expect(reviewErrorMessage(new InboxReviewApiError('server', { code: 'review_outcome_unknown', uncertain: true }))).toMatch(/belum dapat dipastikan/i)
  })
})
