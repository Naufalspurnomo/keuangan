import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  wallets: [
    { source_key: 'CV HB(101):wallet:summary', name: 'CV HB(101)', balance: 868900000 },
    { source_key: 'TX SBY(216):wallet:summary', name: 'TX SBY(216)', balance: 120000000 },
    { source_key: 'TX BALI(087):wallet:summary', name: 'TX BALI(087)', balance: 80000000 },
  ],
  transactions: [
    { id: 1, source_key: 'CV HB(101):pemasukan:9', transaction_date: '2026-10-21', transaction_type: 'Pemasukan', amount: 497500000, wallet: 'CV HB(101)', company: 'HOLLA', project: 'Villa A', notes: 'Termin Holla', internal_movement: false },
    { id: 2, source_key: 'CV HB(101):pemasukan:10', transaction_date: '2026-10-21', transaction_type: 'Pemasukan', amount: 28500000, wallet: 'CV HB(101)', company: 'HOLLA', project: 'Saldo Umum', notes: 'Terima pelunasan hutang', internal_movement: true },
    { id: 3, source_key: 'CV HB(101):pengeluaran:11', transaction_date: '2026-10-20', transaction_type: 'Pengeluaran', amount: 192150000, wallet: 'CV HB(101)', company: 'HOLLA', project: 'Villa A', notes: 'Vendor Holla', internal_movement: false },
    { id: 4, source_key: 'CV HB(101):pemasukan:12', transaction_date: '2026-10-19', transaction_type: 'Pemasukan', amount: 72000000, wallet: 'CV HB(101)', company: 'HOJJA', project: 'Woodtopics', notes: 'Termin Hojja', internal_movement: false },
    { id: 5, source_key: 'TX SBY(216):pemasukan:20', transaction_date: '2026-10-18', transaction_type: 'Pemasukan', amount: 44000000, wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya', project: 'Pizza A', notes: 'Termin Texturin SBY', internal_movement: false },
    { id: 6, source_key: 'TX BALI(087):pengeluaran:21', transaction_date: '2026-10-17', transaction_type: 'Pengeluaran', amount: 13000000, wallet: 'TX BALI(087)', company: 'TEXTURIN-Bali', project: 'Lobby Bali', notes: 'Vendor Texturin Bali', internal_movement: false },
  ],
  debts: [{ source_key: 'HUTANG:2', date: '2026-10-20', amount: 28500000, notes: 'Bridge', borrower: 'CV HB(101)', lender: 'TX SBY(216)', status: 'OPEN' }],
  quality_rows: [{ source_key: 'TX SBY(216):pengeluaran:12', invalid_reason: 'invalid_date_or_amount' }],
  cash_trend: [], project_summaries: [
    { name: 'Villa A', portfolio: 'Hollawall', net_cashflow: 305350000, transaction_count: 2, first_activity_on: '2026-09-01', last_activity_on: '2026-10-21', started_on: '2026-09-01', completed_on: null, age_days: 50, lifecycle_status: 'active', health: 'overdue', source_key_first: 'CV HB(101):pemasukan:9', source_key_latest: 'CV HB(101):pengeluaran:11' },
    { name: 'Proyek Baru', portfolio: 'Texturin', net_cashflow: 12000000, transaction_count: 1, first_activity_on: '2026-10-17', last_activity_on: '2026-10-17', started_on: '2026-10-17', completed_on: null, age_days: 4, lifecycle_status: 'active', health: 'healthy', source_key_first: 'TX SBY(216):pemasukan:20', source_key_latest: 'TX SBY(216):pemasukan:20' },
  ],
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
    expect(await screen.findByText('TOTAL POSISI KAS')).toBeTruthy()
    for (const label of ['Ringkasan', 'Arus Kas', 'Dompet', 'Transaksi', 'Proyek', 'Hutang Internal', 'Laporan']) expect(screen.getAllByRole('button', { name: new RegExp(label) }).length).toBeGreaterThan(0)
  }, 10_000)

  it('separates four real companies and three real wallets into Hollawall and Texturin sections', async () => {
    renderApp()
    const report = await screen.findByRole('region', { name: 'Laporan unit usaha' })

    expect(report.querySelector('.portfolio-section')).toBeNull()
    expect(report.querySelector('.business-chart-card')).toBeNull()
    expect(report.querySelector('.business-ledger-card')).toBeNull()
    expect(report.querySelector('.unit-navigator')).toBeTruthy()
    expect(report.querySelector('.unit-focus-canvas')).toBeTruthy()
    expect(report.querySelector('.activity-stream')).toBeTruthy()
    expect(within(report).getByRole('heading', { name: 'Hollawall Section' })).toBeTruthy()
    expect(within(report).getByRole('heading', { name: 'Texturin Section' })).toBeTruthy()
    for (const company of ['Holla', 'Hojja', 'TX Surabaya', 'TX Bali']) {
      expect(within(report).getByRole('button', { name: new RegExp(`Pilih perusahaan ${company}`) })).toBeTruthy()
    }

    fireEvent.click(within(report).getByRole('button', { name: /Pilih perusahaan Hojja/ }))
    expect(within(report).getByRole('heading', { name: 'Hojja' })).toBeTruthy()
    expect(within(report).getByText(/Termin Hojja/)).toBeTruthy()
    expect(within(report).queryByText(/Termin Holla/)).toBeNull()

    fireEvent.click(within(report).getByRole('button', { name: 'Lihat berdasarkan dompet' }))
    for (const wallet of ['CV HB (101)', 'TX SBY (216)', 'TX BALI (087)']) {
      expect(within(report).getByRole('button', { name: new RegExp(`Pilih dompet ${wallet.replace(/[()]/g, '\\$&')}`) })).toBeTruthy()
    }
    fireEvent.click(within(report).getByRole('button', { name: /Pilih dompet TX BALI \(087\)/ }))
    expect(within(report).getByRole('heading', { name: 'TX BALI (087)' })).toBeTruthy()
    expect(within(report).getByText(/Vendor Texturin Bali/)).toBeTruthy()
    expect(within(report).queryByText(/Termin Texturin SBY/)).toBeNull()
  })

  it('renders the sketched monthly report matrix and separate project timelines', async () => {
    renderApp()
    const module = await screen.findByRole('region', { name: 'Laporan omzet dan timeline proyek' })

    expect(within(module).getByText('HOLLA REPORT')).toBeTruthy()
    expect(within(module).getByText('Bulan ini')).toBeTruthy()
    expect(within(module).getByText('Bulan lalu')).toBeTruthy()
    expect(within(module).getByText('HOLLA')).toBeTruthy()
    expect(within(module).getByText('TX')).toBeTruthy()
    expect(within(module).getByText('HOJJA')).toBeTruthy()
    expect(within(module).getByRole('region', { name: 'Timeline proyek Hollawall' })).toBeTruthy()
    expect(within(module).getByRole('region', { name: 'Timeline proyek Texturin' })).toBeTruthy()
    for (const name of ['Timeline proyek Hollawall', 'Timeline proyek Texturin']) {
      const timeline = within(module).getByRole('region', { name })
      expect(within(timeline).getByText('Oktober')).toBeTruthy()
      expect(within(timeline).getByText('November')).toBeTruthy()
      expect(within(timeline).getByText('Desember')).toBeTruthy()
    }

    fireEvent.click(within(module).getByRole('button', { name: 'Buka proyek Villa A dari timeline' }))
    expect(within(module).getByRole('heading', { name: 'Villa A' })).toBeTruthy()
    expect(within(module).getByText('Mulai')).toBeTruthy()
    expect(within(module).getByText('1 Sep 2026')).toBeTruthy()

    fireEvent.click(within(module).getByRole('button', { name: 'Tambah proyek Hollawall' }))
    expect(within(module).getByRole('dialog', { name: 'Dashboard read-only' })).toBeTruthy()
    expect(within(module).getByText(/kelola proyek dari sumber data/)).toBeTruthy()
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
    await screen.findByText('TOTAL POSISI KAS', {}, { timeout: 4_000 })
    fireEvent.click(screen.getByRole('button', { name: /Pemasukan operasional/ }))
    expect(await screen.findByRole('heading', { name: 'Semua Transaksi' })).toBeTruthy()
    expect(screen.getByText('Termin Holla')).toBeTruthy()
    expect(screen.getByText('CV HB(101):pemasukan:9')).toBeTruthy()
    expect(screen.queryByText('Terima pelunasan hutang')).toBeNull()
    expect(screen.getByText('3 transaksi')).toBeTruthy()
  })

  it('drills the cash headline into wallet source keys', async () => {
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'Saldo kas' }))
    expect(await screen.findByRole('heading', { name: 'Dompet & Rekening' })).toBeTruthy()
    expect(screen.getByText(/CV HB\(101\):wallet:summary/)).toBeTruthy()
  })

  it('drills open debt into its source key', async () => {
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: /Hutang antar-dompet terbuka/ }))
    expect(await screen.findByRole('heading', { name: 'Hutang Antar-Dompet' })).toBeTruthy()
    expect(screen.getByText(/HUTANG:2/)).toBeTruthy()
  })

  it('drills completeness into invalid source keys', async () => {
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: /Kelengkapan data/ }, { timeout: 4_000 }))
    expect(await screen.findByRole('heading', { name: 'Laporan' })).toBeTruthy()
    expect(screen.getByText(/TX SBY\(216\):pengeluaran:12/)).toBeTruthy()
    expect(screen.getByText(/invalid_date_or_amount/)).toBeTruthy()
  })

  it('keeps navigation usable while the first snapshot is loading', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Ringkasan Perusahaan' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Buka navigasi' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Mengambil data keuangan' })).toBeTruthy()
    expect(screen.queryByText('Menyiapkan pusat kendali…')).toBeNull()
  })

  it('fails closed inside the dashboard shell and offers retry', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'unavailable' } }), { status: 503 })))
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Dashboard belum bisa mengambil data' }, { timeout: 4_000 })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Coba lagi' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Proyek/ })).toBeTruthy()
    expect(screen.queryByText('PRATINJAU · DATA DEMO')).toBeNull()
    expect(screen.queryByText('Rp 868.900.000')).toBeNull()
  })

  it('shows project health, age and opens the selected project transactions', async () => {
    renderApp()
    await screen.findByText('TOTAL POSISI KAS')
    fireEvent.click(screen.getByRole('button', { name: 'Proyek' }))
    expect(await screen.findByRole('heading', { name: 'Umur dan kesehatan proyek' })).toBeTruthy()
    expect(screen.getByText('Lewat 30 hari')).toBeTruthy()
    expect(screen.getByText('Baru · Sehat')).toBeTruthy()
    expect(screen.getByText('50 hari')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Timeline 3 bulan' })).toBeTruthy()
    expect(screen.getAllByText('Hollawall').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Texturin').length).toBeGreaterThan(0)
    fireEvent.change(screen.getByLabelText('Filter portfolio'), { target: { value: 'Texturin' } })
    expect(screen.queryByRole('button', { name: /Buka transaksi proyek Villa A/ })).toBeNull()
    expect(screen.getAllByRole('button', { name: /Buka transaksi proyek Proyek Baru/ }).length).toBeGreaterThan(0)
    fireEvent.change(screen.getByLabelText('Filter portfolio'), { target: { value: 'all' } })
    fireEvent.click(screen.getByRole('button', { name: /^Buka transaksi proyek Villa A,/ }))
    expect(await screen.findByRole('heading', { name: 'Semua Transaksi' })).toBeTruthy()
    expect(screen.getByDisplayValue('Villa A')).toBeTruthy()
    expect(screen.getByText('2 transaksi')).toBeTruthy()
  })
})
