import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createCanonicalTransactionMutation,
  createTransactionWriteAttempt,
  sameTransactionPayload,
  jakartaToday,
  loadTransactionWriteSession,
  type TransactionWritePayload,
} from './transactionApi'

const sessionEnvelope = (writesEnabled = true, canonicalWritesEnabled = false) => new Response(JSON.stringify({
  api_version: 'dashboard.v1',
  data: {
    csrf_token: 'csrf-owner-session-token-0001',
    capabilities: {
      writes_enabled: writesEnabled,
      canonical_finance_writes_enabled: canonicalWritesEnabled,
    },
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

const canonicalRecordedEnvelope = (extra: Record<string, unknown> = {}) => new Response(JSON.stringify({
  api_version: 'dashboard.v1',
  data: {
    recorded: true,
    authority: 'postgresql',
    transaction_id: '00000000-0000-4000-8000-000000000601',
    transaction_version: 1,
    duplicate: false,
    ...extra,
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
  it('compares unresolved attempts against the exact canonical payload', () => {
    expect(sameTransactionPayload(payload, { ...payload })).toBe(true)
    expect(sameTransactionPayload(payload, { ...payload, amount: payload.amount + 1 })).toBe(false)
    expect(sameTransactionPayload(payload, { ...payload, project: undefined })).toBe(false)
  })

  it('loads the owner CSRF token and write capability same-origin without caching', async () => {
    const request = vi.fn(async () => sessionEnvelope())

    await expect(loadTransactionWriteSession({ request })).resolves.toEqual({
      csrfToken: 'csrf-owner-session-token-0001',
      writesEnabled: true,
      canonicalWritesEnabled: false,
      debtWritesEnabled: false,
    })
    expect(request).toHaveBeenCalledWith('/admin/api/write-session.php', {
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: { Accept: 'application/json' },
    })
  })

  it('posts the exact contract with matching CSRF and idempotency keys', async () => {
    const request = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => canonicalRecordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'dashboard-test-key-00000001',
    })

    await expect(attempt.submit({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true, canonicalWritesEnabled: true }))
      .resolves.toMatchObject({ recorded: true, authority: 'postgresql', duplicate: false })

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

  it('requires canonical writes for creation even when legacy writes are enabled', async () => {
    const request = vi.fn(async () => canonicalRecordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'canonical-create-gate-0001',
    })

    await expect(attempt.submit({
      csrfToken: 'csrf-owner-session-token-0001',
      writesEnabled: true,
      canonicalWritesEnabled: false,
    })).rejects.toMatchObject({ code: 'canonical_finance_writes_disabled' })
    expect(request).not.toHaveBeenCalled()
  })

  it('creates with canonical writes without consulting the legacy write flag', async () => {
    const request = vi.fn(async () => canonicalRecordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'canonical-create-only-0001',
    })

    await expect(attempt.submit({
      csrfToken: 'csrf-owner-session-token-0001',
      writesEnabled: false,
      canonicalWritesEnabled: true,
    })).resolves.toMatchObject({ authority: 'postgresql' })
    expect(request).toHaveBeenCalledOnce()
  })

  it('rejects Sheet-shaped success in canonical production creation', async () => {
    const request = vi.fn(async () => recordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'canonical-no-sheet-00001',
    })

    await expect(attempt.submit({
      csrfToken: 'csrf-owner-session-token-0001',
      writesEnabled: true,
      canonicalWritesEnabled: true,
    })).rejects.toMatchObject({ code: 'unverified_recording', uncertain: true })
  })

  it('accepts exact PostgreSQL authority evidence without Sheet locators', async () => {
    const request = vi.fn(async () => canonicalRecordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'dashboard-postgres-key-0001',
    })

    await expect(attempt.submit({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true, canonicalWritesEnabled: true }))
      .resolves.toEqual({
        recorded: true,
        authority: 'postgresql',
        transactionId: '00000000-0000-4000-8000-000000000601',
        transactionVersion: 1,
        duplicate: false,
      })
  })

  it('rejects mixed PostgreSQL and Sheet authority evidence', async () => {
    const request = vi.fn(async () => canonicalRecordedEnvelope({
      sheet_name: 'legacy-primary',
      sheet_row: 9,
    }))
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'dashboard-mixed-key-000001',
    })

    await expect(attempt.submit({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true, canonicalWritesEnabled: true }))
      .rejects.toMatchObject({ code: 'unverified_recording', uncertain: true })
  })

  it('preserves one key and body when an uncertain request is retried', async () => {
    const request = vi.fn()
      .mockRejectedValueOnce(new TypeError('network interrupted'))
      .mockResolvedValueOnce(canonicalRecordedEnvelope())
    const attempt = createTransactionWriteAttempt(payload, {
      request,
      keyFactory: () => 'dashboard-retry-key-000001',
    })
    const session = { csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true, canonicalWritesEnabled: true }

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

    await expect(attempt.submit({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: true, canonicalWritesEnabled: true }))
      .rejects.toMatchObject({ uncertain: true })
  })

  it('fails closed when writes are disabled or the session contract is malformed', async () => {
    await expect(loadTransactionWriteSession({ request: vi.fn(async () => sessionEnvelope(false)) }))
      .resolves.toEqual({ csrfToken: 'csrf-owner-session-token-0001', writesEnabled: false, canonicalWritesEnabled: false, debtWritesEnabled: false })
    await expect(loadTransactionWriteSession({ request: vi.fn(async () => new Response(JSON.stringify({ data: {} }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })) })).rejects.toThrow('Kontrak sesi pencatatan tidak cocok')
  })

  it.each(['correction', 'reversal'] as const)('submits canonical %s with immutable retry identity', async (action) => {
    const request = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({
      api_version: 'finance.v1',
      data: {
        transaction: {
          id: '00000000-0000-4000-8000-000000000011',
          version: 2,
          status: action,
        },
        duplicate: false,
      },
    }), { status: 201, headers: { 'content-type': 'application/json' } }))
    const mutation = createCanonicalTransactionMutation({
      action,
      transactionId: '00000000-0000-4000-8000-000000000010',
      expectedVersion: 1,
      reason: 'Bukti transaksi dikonfirmasi ulang',
      ...(action === 'correction' ? { amount: 150_000 } : {}),
    }, { request, keyFactory: () => 'canonical-mutation-key-0001' })
    const session = {
      csrfToken: 'csrf-owner-session-token-0001',
      writesEnabled: true,
      canonicalWritesEnabled: true,
    }

    await expect(mutation.submit(session)).resolves.toEqual({
      transactionId: '00000000-0000-4000-8000-000000000011',
      version: 2,
      status: action,
      duplicate: false,
    })

    const [endpoint, options] = request.mock.calls[0]
    expect(endpoint).toBe(`/admin/api/transactions.php?action=${action}&transaction_id=00000000-0000-4000-8000-000000000010`)
    expect(options?.headers).toEqual(expect.objectContaining({
      'X-CSRF-Token': session.csrfToken,
      'Idempotency-Key': 'canonical-mutation-key-0001',
    }))
    expect(JSON.parse(String(options?.body))).toEqual({
      idempotency_key: 'canonical-mutation-key-0001',
      expected_version: 1,
      reason: 'Bukti transaksi dikonfirmasi ulang',
      ...(action === 'correction' ? { amount: 150_000 } : {}),
    })
  })

  it('blocks canonical lifecycle mutations when the server capability is false', async () => {
    const mutation = createCanonicalTransactionMutation({
      action: 'reversal',
      transactionId: '00000000-0000-4000-8000-000000000010',
      expectedVersion: 1,
      reason: 'Transaksi duplikat',
    })

    await expect(mutation.submit({
      csrfToken: 'csrf-owner-session-token-0001',
      writesEnabled: true,
      canonicalWritesEnabled: false,
    })).rejects.toMatchObject({ code: 'canonical_finance_writes_disabled' })
  })
})

describe('Jakarta date', () => {
  it('uses Asia/Jakarta rather than UTC or browser-local date', () => {
    expect(jakartaToday(new Date('2026-11-01T17:30:00.000Z'))).toBe('2026-11-02')
  })
})
