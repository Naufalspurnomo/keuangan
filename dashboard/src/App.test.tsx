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
    drilldowns: {
      cash_balance: 'wallets', operating_inflow: 'transactions:external-income', operating_outflow: 'transactions:external-expense',
      net_operating_cashflow: 'transactions:external', open_internal_debt: 'debts:open', project_cashflow: 'transactions:projects',
    },
  },
  meta: { as_of: '2026-10-21T12:00:00Z', data_through: '2026-10-21', source: 'test', freshness: 'fresh', data_completeness: { valid_rows: 3, invalid_rows: 1, completeness_pct: 75 } },
  wallets: [{ source_key: 'CV HB(101):wallet:summary', name: 'CV HB(101)', balance: 868900000 }],
  transactions: [
    { id: 1, source_key: 'CV HB(101):pemasukan:9', transaction_date: '2026-10-21', transaction_type: 'Pemasukan', amount: 497500000, wallet: 'CV HB(101)', company: 'HOLLA', project: 'Villa A', notes: 'Termin eksternal', internal_movement: false },
    { id: 2, source_key: 'CV HB(101):pemasukan:10', transaction_date: '2026-10-21', transaction_type: 'Pemasukan', amount: 28500000, wallet: 'CV HB(101)', company: 'HOLLA', project: 'Saldo Umum', notes: 'Terima pelunasan hutang', internal_movement: true },
    { id: 3, source_key: 'CV HB(101):pengeluaran:11', transaction_date: '2026-10-20', transaction_type: 'Pengeluaran', amount: 192150000, wallet: 'CV HB(101)', company: 'HOLLA', project: 'Villa A', notes: 'Vendor eksternal', internal_movement: false },
  ],
  debts: [{ source_key: 'HUTANG:2', date: '2026-10-20', amount: 28500000, notes: 'Bridge', borrower: 'CV HB(101)', lender: 'TX SBY(216)', status: 'OPEN' }],
  quality_rows: [{ source_key: 'TX SBY(216):pengeluaran:12', invalid_reason: 'invalid_date_or_amount' }],
  cash_trend: [], project_summaries: [{ name: 'Villa A', net_cashflow: 305350000 }],
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

  it('drills an operating KPI into exact external transactions', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })
    fireEvent.click(screen.getByRole('button', { name: /Pemasukan operasional/ }))
    expect(await screen.findByRole('heading', { name: 'Semua Transaksi' })).toBeTruthy()
    expect(screen.getByText('Termin eksternal')).toBeTruthy()
    expect(screen.getByText('CV HB(101):pemasukan:9')).toBeTruthy()
    expect(screen.queryByText('Terima pelunasan hutang')).toBeNull()
    expect(screen.getByText('1 transaksi')).toBeTruthy()
  })

  it('drills the cash headline into wallet source keys', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })
    fireEvent.click(screen.getByRole('button', { name: 'Saldo kas' }))
    expect(await screen.findByRole('heading', { name: 'Dompet & Rekening' })).toBeTruthy()
    expect(screen.getByText(/CV HB\(101\):wallet:summary/)).toBeTruthy()
  })

  it('drills open debt into its source key', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })
    fireEvent.click(screen.getByRole('button', { name: /Hutang antar-dompet terbuka/ }))
    expect(await screen.findByRole('heading', { name: 'Hutang Antar-Dompet' })).toBeTruthy()
    expect(screen.getByText(/HUTANG:2/)).toBeTruthy()
  })

  it('drills completeness into invalid source keys', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })
    fireEvent.click(screen.getByRole('button', { name: /Kelengkapan data/ }))
    expect(await screen.findByRole('heading', { name: 'Laporan' })).toBeTruthy()
    expect(screen.getByText(/TX SBY\(216\):pengeluaran:12/)).toBeTruthy()
    expect(screen.getByText(/invalid_date_or_amount/)).toBeTruthy()
  })

  it('fails closed without showing demo values when live data is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'unavailable' } }), { status: 503 })))
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Data keuangan tidak tersedia' })).toBeTruthy()
    expect(screen.queryByText('PRATINJAU · DATA DEMO')).toBeNull()
    expect(screen.queryByText('Rp 868.900.000')).toBeNull()
  })
})
