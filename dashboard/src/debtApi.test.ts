import { describe, expect, it, vi } from 'vitest'

import { createDebtAttempt, createDebtCorrectionAttempt, createDebtRepaymentAttempt, createDebtReversalAttempt } from './debtApi'

const session = { csrfToken: 'csrf', writesEnabled: true, canonicalWritesEnabled: true, debtWritesEnabled: true }

function jsonResponse(data: unknown, status = 201) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('canonical debt API', () => {
  it('creates a debt with stable idempotency and exact owner headers', async () => {
    const request = vi.fn().mockImplementation(async () => jsonResponse({
      api_version: 'finance.v1',
      data: { debt: { id: '00000000-0000-4000-8000-000000000001', version: 1, status: 'open' }, duplicate: false },
    }))
    const attempt = createDebtAttempt({
      lenderWalletId: '34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b',
      borrowerWalletId: '07743a6c-1ad0-5c00-9d96-0beaee4b8e01',
      lenderBusinessUnitId: 'd3261754-6ee5-5d37-b0e2-79614da60abb',
      borrowerBusinessUnitId: '0e21a9d9-4bda-5cb2-965b-bc2202e981ce',
      projectId: null,
      principal: 250_000,
      occurredAt: '2026-11-12T00:00:00+07:00',
      dueAt: '2026-12-12T00:00:00+07:00',
      description: 'Pinjaman operasional',
    }, { request })

    await attempt.submit(session)
    await attempt.submit(session)

    expect(request).toHaveBeenCalledTimes(2)
    const [url, init] = request.mock.calls[0]
    expect(url).toBe('/admin/api/debts.php?action=create')
    expect(init.headers['X-CSRF-Token']).toBe('csrf')
    expect(init.headers['Idempotency-Key']).toBe(attempt.idempotencyKey)
    expect(JSON.parse(init.body).idempotency_key).toBe(attempt.idempotencyKey)
    expect(request.mock.calls[1][1].body).toBe(init.body)
  })

  it('posts repayment against the aggregate version', async () => {
    const request = vi.fn().mockResolvedValue(jsonResponse({
      api_version: 'finance.v1',
      data: { debt: { id: '00000000-0000-4000-8000-000000000001', version: 2, status: 'open' }, duplicate: false },
    }))
    const attempt = createDebtRepaymentAttempt({
      debtId: '00000000-0000-4000-8000-000000000001',
      expectedVersion: 1,
      amount: 100_000,
      occurredAt: '2026-11-12T00:00:00+07:00',
      description: 'Cicilan pertama',
    }, { request })

    await attempt.submit(session)

    expect(request.mock.calls[0][0]).toContain('action=repay')
    expect(request.mock.calls[0][0]).toContain('debt_id=00000000-0000-4000-8000-000000000001')
    expect(JSON.parse(request.mock.calls[0][1].body).expected_version).toBe(1)
  })

  it('fails closed when canonical writes are disabled', async () => {
    const request = vi.fn()
    const attempt = createDebtRepaymentAttempt({
      debtId: '00000000-0000-4000-8000-000000000001', expectedVersion: 1,
      amount: 1, occurredAt: '2026-11-12T00:00:00+07:00', description: 'x',
    }, { request })

    await expect(attempt.submit({ csrfToken: 'csrf', writesEnabled: true, canonicalWritesEnabled: true, debtWritesEnabled: false })).rejects.toThrow('belum tersedia')
    expect(request).not.toHaveBeenCalled()
  })

  it.each([
    ['correct', createDebtCorrectionAttempt, 250_000],
    ['reverse', createDebtReversalAttempt, undefined],
  ] as const)('submits immutable debt event %s with version and reason', async (action, factory, amount) => {
    const request = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({
      api_version: 'finance.v1',
      data: { debt: { id: '00000000-0000-4000-8000-000000000001', version: 3, status: 'open' }, duplicate: false },
    }))
    const attempt = factory({
      debtId: '00000000-0000-4000-8000-000000000001',
      eventId: '00000000-0000-4000-8000-000000000002',
      expectedVersion: 2,
      occurredAt: '2026-11-12T12:00:00+07:00',
      reason: 'Perbaikan bukti',
      ...(amount ? { amount } : {}),
    }, { request })

    await attempt.submit(session)

    expect(request).toHaveBeenCalledWith(expect.stringContaining(`action=${action}`), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'Idempotency-Key': attempt.idempotencyKey }),
    }))
    const body = JSON.parse(String(request.mock.calls[0][1]?.body))
    expect(body).toMatchObject({ expected_version: 2, reason: 'Perbaikan bukti' })
    if (amount) expect(body.amount).toBe(amount)
    else expect(body).not.toHaveProperty('amount')
  })
})
