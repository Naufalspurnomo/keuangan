import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
vi.mock('./FinancialChart', () => ({
  default: ({ kind }: { kind: string }) => <div data-testid={`chart-${kind}`} />,
}))

import App from './App'

const overview = {
  version: 'dashboard.v1',
  data: {
    metrics: { cash_balance: 868900000, operating_inflow: 497500000, operating_outflow: 192150000, net_operating_cashflow: 305350000, open_internal_debt: 28500000, project_cashflow: 305350000 },
    counts: { valid_rows: 148, invalid_rows: 2 },
    labels: { cash_balance: 'Saldo kas', operating_inflow: 'Pemasukan operasional', operating_outflow: 'Pengeluaran operasional', net_operating_cashflow: 'Arus kas operasional bersih', open_internal_debt: 'Hutang antar-dompet terbuka', project_cashflow: 'Arus kas proyek bersih' },
    drilldowns: {},
  },
  meta: { as_of: '2026-10-21T12:00:00Z', freshness: 'fresh', data_completeness: { valid_rows: 148, invalid_rows: 2, completeness_pct: 98.7 } },
  error: null,
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/auth/me')) return new Response(JSON.stringify({ version: 'dashboard.v1', data: { identity: { email: 'naufalspurnomo@gmail.com', role: 'owner' } }, meta: overview.meta, error: null }), { status: 200 })
    if (url.includes('/overview')) return new Response(JSON.stringify(overview), { status: 200 })
    return new Response(JSON.stringify({ ...overview, data: { items: [], next_cursor: null } }), { status: 200 })
  }))
})

afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear() })

function renderApp() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider>)
}

describe('Hollawall command center', () => {
  it('renders owner financial overview and seven navigation views', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })).toBeTruthy()
    expect(screen.getByText('TOTAL POSISI KAS')).toBeTruthy()
    for (const label of ['Ringkasan', 'Arus Kas', 'Dompet', 'Transaksi', 'Proyek', 'Hutang Internal', 'Laporan']) expect(screen.getAllByRole('button', { name: new RegExp(label) }).length).toBeGreaterThan(0)
  })

  it('persists explicit dark mode choice', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })
    fireEvent.click(screen.getByRole('button', { name: 'Ubah tema' }))
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
    expect(localStorage.getItem('hollawall-theme')).toBe('dark')
  })

  it('navigates to transaction detail without a page reload', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })
    fireEvent.click(screen.getByRole('button', { name: /Transaksi/ }))
    expect(await screen.findByRole('heading', { name: 'Semua Transaksi' })).toBeTruthy()
    expect(screen.getByPlaceholderText(/Cari transaksi/)).toBeTruthy()
  })

  it('uses API-shaped demo fallback when dashboard resources are unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/me')) return new Response(JSON.stringify({ version: 'dashboard.v1', data: { identity: { email: 'naufalspurnomo@gmail.com', role: 'owner' } }, meta: overview.meta, error: null }), { status: 200 })
      return new Response(JSON.stringify({ error: { code: 'unavailable', message: 'unavailable' } }), { status: 503 })
    }))
    renderApp()
    expect(await screen.findByText('PRATINJAU · DATA DEMO')).toBeTruthy()
    expect(screen.getByText('Rp 868.900.000')).toBeTruthy()
  })
})
