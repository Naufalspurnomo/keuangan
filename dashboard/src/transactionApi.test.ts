import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createTransactionWriteAttempt,
  jakartaToday,
  loadTransactionWriteSession,
  type TransactionWritePayload,
} from './transactionApi'

const sessionEnvelope = (writesEnabled = true) => new Response(JSON.stringify({
  api_version: 'dashboard.v1',
  data: {
    csrf_token: 'csrf-owner-session-token-0001',
    capabilities: { writes_enabled: writesEnabled },
  },
}), { status: 200, headers: { 'content-type': 'application/json' } })

const recordedEnvelope = () => new Response(JSON.stringify({
  api_version: 'dashboard.v1',
  data: {
    recorded: true,
    transaction_id: 'sheet:CV HB(101):pemasukan:77',
    sheet_name: 'CV HB(101)',
    sheet_row: 77,
    source_block: 'pemasukan',
    sheet_message_id: 'dashboard:request:hash',
    projection_status: 'updated',
    duplicate: false,
  },
}), { status: 201, headers: { 'content-type': 'application/json' } })

const payload: TransactionWritePayload = {
  date: '2026-11-02',
  scope: 'project',
  direction: 'Pemasukan',
  amount: 1_250_000,
  description: 'Pembayaran proyek Alfa',
  wallet: 'CV HB(101)',
  company: 'HOLLA',
  category: 'Bahan Alat',
  project: 'Proyek Produksi Alfa',
}

afterEach(() => vi.restoreAllMocks())

describe('authenticated transaction API', () => {
  it('loads the owner CSRF token and write capability same-origin without caching', async () => {
    const request = vi.fn(async () => sessionEnvelope())

    await expect(loadTransactionWriteSession({ request })).resolves.toEqual({
      csrfToken: 'csrf-owner-session-token-0001',
      writesEnabled: true,
    })
    expect(request).toHaveBeenCalledWith('/admin/api/write-session.php', {
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: { Accept: 'application/json' },
    })
  })

  it('posts the exact contract with matching CSRF and idempotency keys', async () => {
    const request = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => recordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'dashboard-test-key-00000001',
    })

    await expect(attempt.submit({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true }))
      .resolves.toMatchObject({ recorded: true, sheetRow: 77, duplicate: false, projectionStatus: 'updated' })

    const [, options] = request.mock.calls[0]
    expect(request).toHaveBeenCalledWith('/admin/api/transactions.php', expect.objectContaining({
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-CSRF-Token': 'csrf-owner-session-token-0001',
        'Idempotency-Key': 'dashboard-test-key-00000001',
      },
    }))
    expect(JSON.parse(String(options?.body))).toEqual({
      idempotency_key: 'dashboard-test-key-00000001',
      ...payload,
    })
  })

  it('preserves one key and body when an uncertain request is retried', async () => {
    const request = vi.fn()
      .mockRejectedValueOnce(new TypeError('network interrupted'))
      .mockResolvedValueOnce(recordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'dashboard-retry-key-000001',
    })
    const session = { csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true }

    await expect(attempt.submit(session)).rejects.toMatchObject({ uncertain: true })
    await expect(attempt.submit(session)).resolves.toMatchObject({ recorded: true })

    const first = request.mock.calls[0][1]
    const second = request.mock.calls[1][1]
    expect(first?.headers).toEqual(second?.headers)
    expect(first?.body).toBe(second?.body)
  })

  it('never accepts a success-looking response without verified Sheet evidence', async () => {
    const request = vi.fn(async () => new Response(JSON.stringify({
      api_version: 'dashboard.v1',
      data: { recorded: false, transaction_id: 'pending' },
    }), { status: 201, headers: { 'content-type': 'application/json' } }))
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'dashboard-invalid-key-0001',
    })

    await expect(attempt.submit({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true }))
      .rejects.toMatchObject({ uncertain: true })
  })

  it('fails closed when writes are disabled or the session contract is malformed', async () => {
    await expect(loadTransactionWriteSession({ request: vi.fn(async () => sessionEnvelope(false)) }))
      .resolves.toEqual({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: false })
    await expect(loadTransactionWriteSession({ request: vi.fn(async () => new Response(JSON.stringify({ data: {} }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })) })).rejects.toThrow('Kontrak sesi pencatatan tidak cocok')
  })
})

describe('Jakarta date', () => {
  it('uses Asia/Jakarta rather than UTC or browser-local date', () => {
    expect(jakartaToday(new Date('2026-11-01T17:30:00.000Z'))).toBe('2026-11-02')
  })
})
