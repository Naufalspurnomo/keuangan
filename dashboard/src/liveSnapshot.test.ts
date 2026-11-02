import { describe, expect, it, vi } from 'vitest'

import { loadLiveSnapshot } from './liveSnapshot'
import type { DashboardSnapshot } from './snapshot'

export const validLiveSnapshot = (): DashboardSnapshot => ({
  version: 'dashboard.snapshot.v1',
  meta: {
    as_of: '2026-11-02T09:30:00Z',
    data_through: '2026-11-01',
    source: 'finance-ledger',
    source_status: 'live',
    freshness: 'fresh',
    data_completeness: { valid_rows: 12, invalid_rows: 1, completeness_pct: 92.3 },
  },
  overview: {
    metrics: {
      cash_balance: 15_000_000,
      operating_inflow: 20_000_000,
      operating_outflow: 5_000_000,
      net_operating_cashflow: 15_000_000,
      open_internal_debt: 2_000_000,
      project_cashflow: 14_000_000,
    },
    counts: { valid_rows: 12, invalid_rows: 1 },
    labels: {},
    drilldowns: {},
  },
  wallets: [{ source_key: 'wallet-1', name: 'CV HB', balance: 15_000_000 }],
  transactions: [],
  debts: [],
  cash_trend: [],
  project_summaries: [{ name: 'Proyek Live', net_cashflow: 14_000_000 }],
})

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json; charset=utf-8' },
    ...init,
  })
}

describe('loadLiveSnapshot', () => {
  it('requests only the same-origin path without forwarding an absolute URL', async () => {
    const request = vi.fn(async () => jsonResponse(validLiveSnapshot()))

    await expect(loadLiveSnapshot('/admin/api/snapshot.php?scope=finance', request)).resolves.toEqual(validLiveSnapshot())
    expect(request).toHaveBeenCalledWith('/admin/api/snapshot.php?scope=finance', {
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: { Accept: 'application/json' },
    })
  })

  it('rejects cross-origin URLs before making a request', async () => {
    const request = vi.fn()

    await expect(loadLiveSnapshot('https://attacker.example/snapshot', request)).rejects.toThrow('Snapshot harus same-origin.')
    expect(request).not.toHaveBeenCalled()
  })

  it('reports HTTP failures without parsing the response body', async () => {
    const response = new Response('<html>login</html>', { status: 401, headers: { 'content-type': 'text/html' } })
    const json = vi.spyOn(response, 'json')

    await expect(loadLiveSnapshot(undefined, vi.fn(async () => response))).rejects.toThrow('Snapshot unavailable (401)')
    expect(json).not.toHaveBeenCalled()
  })

  it('rejects successful non-JSON responses', async () => {
    const response = new Response('<html>login</html>', { status: 200, headers: { 'content-type': 'text/html' } })

    await expect(loadLiveSnapshot(undefined, vi.fn(async () => response))).rejects.toThrow('Respons snapshot bukan JSON.')
  })

  it.each([
    ['null payload', null, 'Snapshot tidak valid.'],
    ['wrong contract version', { ...validLiveSnapshot(), version: 'dashboard.snapshot.v2' }, 'Kontrak snapshot tidak cocok.'],
    ['missing metadata', { ...validLiveSnapshot(), meta: null }, 'Kontrak snapshot tidak cocok.'],
    ['non-array transactions', { ...validLiveSnapshot(), transactions: {} }, 'Kontrak snapshot tidak cocok.'],
  ])('rejects %s', async (_label, payload, message) => {
    await expect(loadLiveSnapshot(undefined, vi.fn(async () => jsonResponse(payload)))).rejects.toThrow(message)
  })
})
