import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
vi.mock('./FinancialChart', () => ({
  default: ({ kind }: { kind: string }) => <div data-testid={`chart-${kind}`} />,
}))

import App from './App'

const snapshot = {
  version: 'dashboard.snapshot.v1',
  overview: {
    metrics: { cash_balance: 868900000, operating_inflow: 497500000, operating_outflow: 192150000, net_operating_cashflow: 305350000, open_internal_debt: 28500000, project_cashflow: 305350000 },
    counts: { valid_rows: 148, invalid_rows: 2 },
    labels: { cash_balance: 'Saldo kas', operating_inflow: 'Pemasukan operasional', operating_outflow: 'Pengeluaran operasional', net_operating_cashflow: 'Arus kas operasional bersih', open_internal_debt: 'Hutang antar-dompet terbuka', project_cashflow: 'Arus kas proyek bersih' },
    drilldowns: {},
  },
  meta: { as_of: '2026-10-21T12:00:00Z', data_through: '2026-10-21', source: 'test', freshness: 'fresh', data_completeness: { valid_rows: 148, invalid_rows: 2, completeness_pct: 98.7 } },
  wallets: [], transactions: [], debts: [], cash_trend: [], project_summaries: [],
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 })))
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

  it('fails closed without showing demo values when live data is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'unavailable' } }), { status: 503 })))
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Data keuangan tidak tersedia' })).toBeTruthy()
    expect(screen.queryByText('PRATINJAU · DATA DEMO')).toBeNull()
    expect(screen.queryByText('Rp 868.900.000')).toBeNull()
  })
})
