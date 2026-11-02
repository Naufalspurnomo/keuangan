import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import App from './App'
import { validLiveSnapshot } from './liveSnapshot.test'

const liveSnapshot = (): import('./snapshot').DashboardSnapshot => ({
  ...validLiveSnapshot(),
  meta: {
    ...validLiveSnapshot().meta,
    as_of: '2026-11-02T09:30:00Z',
    data_through: '2026-11-01',
  },
  wallets: [
    { source_key: 'wallet-live-1', name: 'Dompet Produksi Utama', balance: 12_500_000 },
    { source_key: 'wallet-live-2', name: 'Dompet Produksi Bali', balance: 2_500_000 },
    { source_key: 'wallet-live-3', name: 'Dompet Tak Terpetakan', balance: 750_000 },
  ],
  project_summaries: [
    { name: 'Proyek Produksi Alfa', portfolio: 'Hollawall' as const, net_cashflow: 9_000_000, transaction_count: 1, lifecycle_status: 'active' as const, started_on: '2026-10-01' },
    { name: 'Proyek Produksi Beta', portfolio: 'Texturin' as const, net_cashflow: -1_500_000, transaction_count: 1, lifecycle_status: 'completed' as const, started_on: '2026-09-01', completed_on: '2026-10-31' },
  ],
  transactions: [
    {
      id: 981,
      source_key: 'tx-live-981',
      transaction_date: '2026-11-01',
      transaction_type: 'Pemasukan',
      amount: 9_000_000,
      wallet: 'Dompet Produksi Utama',
      company: 'Holla',
      project: 'Proyek Produksi Alfa',
      notes: 'Pembayaran produksi aktual',
    },
    {
      id: 982,
      source_key: 'tx-live-982',
      transaction_date: '2026-10-31',
      transaction_type: 'Pengeluaran',
      amount: 1_500_000,
      wallet: 'Dompet Produksi Bali',
      company: 'Texturin Regional Baru',
      project: 'Proyek Produksi Beta',
      notes: 'Material produksi aktual',
    },
    {
      id: 983,
      source_key: 'tx-live-983',
      transaction_date: '2026-10-30',
      transaction_type: 'Pengeluaran',
      amount: 250_000,
      wallet: 'Dompet Tak Terpetakan',
      company: 'Unit Operasional Baru',
      project: 'Operasional',
      office_category: 'Kategori Produksi Khusus',
      notes: 'Biaya kategori aktual',
    },
  ],
  debts: [{
    source_key: 'debt-live-1', date: '2026-10-20', amount: 500_000, notes: 'Pinjaman aktual',
    borrower: 'Dompet Tak Terpetakan', lender: 'Dompet Produksi Utama', status: 'OPEN',
  }],
  cash_trend: [
    { month: '2026-10', balance: 6_750_000, net_movement: -1_750_000 },
    { month: '2026-11', balance: 15_750_000, net_movement: 9_000_000 },
  ],
})

function liveResponse(snapshot = liveSnapshot()) {
  return new Response(JSON.stringify(snapshot), { status: 200, headers: { 'content-type': 'application/json' } })
}

function navigation() {
  return within(document.querySelector('aside.sidebar') as HTMLElement)
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState(null, '', '/admin/')
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState(null, '', '/')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('production live source mode', () => {
  it('keeps the complete dashboard shell, analytics, routes, reports, and source-grounded unknown values', async () => {
    const request = vi.fn(async (_input?: RequestInfo | URL) => liveResponse())
    vi.stubGlobal('fetch', request)

    render(<App />)

    expect(await screen.findByText('Mode live · hanya baca')).toBeTruthy()
    expect(document.querySelector('.app-shell.finance-workspace-shell')).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Ringkasan' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Arus Kas' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Dompet' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Proyek' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Operasional Kantor' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Hutang Internal' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Laporan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Tren kas 12 bulan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Sebaran saldo dompet' })).toBeTruthy()
    expect(screen.getByText('Dompet Tak Terpetakan')).toBeTruthy()

    expect(screen.queryByText('Workspace demo')).toBeNull()
    expect(screen.getByText('Workspace live')).toBeTruthy()

    fireEvent.click(navigation().getByRole('button', { name: 'Operasional Kantor' }))
    expect(window.location.hash).toBe('#office')
    expect(screen.getByText('Kategori Produksi Khusus')).toBeTruthy()
    expect(screen.getByText('Biaya kategori aktual')).toBeTruthy()
    expect(screen.getByText('DATA LIVE')).toBeTruthy()
    expect(screen.queryByText('DATA DEMO')).toBeNull()

    fireEvent.click(navigation().getByRole('button', { name: 'Laporan' }))
    expect(window.location.hash).toBe('#reports')
    expect(screen.getByRole('heading', { name: 'Pratinjau dan ekspor PDF' })).toBeTruthy()
    expect(screen.getByText('Texturin Regional Baru')).toBeTruthy()
    expect(screen.getByText('Unit Operasional Baru')).toBeTruthy()
    expect(request).toHaveBeenCalledWith('/admin/api/snapshot.php', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('is read-only, never seeds the demo workspace, and keeps theme behavior', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => liveResponse()))

    render(<App />)

    await screen.findByText('Mode live · hanya baca')
    expect(screen.queryByText(/Data keuangan demo tersimpan/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Reset/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Tambah transaksi/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Tambah proyek/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Tambah hutang/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Ubah transaksi/i })).toBeNull()
    expect(screen.queryByText('Audit data demo')).toBeNull()
    expect(localStorage.getItem('hollawall-finance-demo-v3')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Gunakan tema gelap' }))
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
    expect(localStorage.getItem('hollawall-theme')).toBe('dark')
    expect(localStorage.getItem('hollawall-finance-demo-v3')).toBeNull()
  })

  it('keeps snapshot failure closed instead of mounting or seeding demo data', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    })))

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Data live belum tersedia')
    expect(screen.getByText(/Data demo tidak ditampilkan sebagai pengganti/)).toBeTruthy()
    expect(document.querySelector('.app-shell')).toBeNull()
    expect(localStorage.getItem('hollawall-finance-demo-v3')).toBeNull()
  })

  it('marks presensi unavailable and never queries a generated route key as a canonical project ID', async () => {
    const request = vi.fn(async (_input?: RequestInfo | URL) => liveResponse())
    vi.stubGlobal('fetch', request)

    render(<App />)
    await screen.findByText('Mode live · hanya baca')
    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Buka proyek Proyek Produksi Alfa' }))

    expect(window.location.hash).toMatch(/^#projects\?project=/)
    fireEvent.click(screen.getByRole('tab', { name: 'Presensi' }))
    expect(screen.getByRole('status')).toHaveTextContent('Presensi belum tersedia')
    expect(screen.getByText(/ID proyek presensi kanonis tidak tersedia/)).toBeTruthy()
    expect(request.mock.calls.some(([input]) => String(input).includes('/admin/api/presensi.php'))).toBe(false)
  })

  it('queries presensi only with an explicit canonical project mapping', async () => {
    const snapshot = liveSnapshot()
    snapshot.project_summaries[0] = { ...snapshot.project_summaries[0], project_id: 'p26-produksi-alfa' }
    const request = vi.fn(async (input: RequestInfo | URL) => String(input).startsWith('/admin/api/presensi.php')
      ? new Response(JSON.stringify({ version: 'presensi.admin.v1', records: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
      : liveResponse(snapshot))
    vi.stubGlobal('fetch', request)

    render(<App />)
    await screen.findByText('Mode live · hanya baca')
    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Buka proyek Proyek Produksi Alfa' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Presensi' }))

    await screen.findByText('Belum ada presensi untuk Proyek Produksi Alfa')
    expect(request).toHaveBeenCalledWith(
      '/admin/api/presensi.php?project_id=p26-produksi-alfa',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
    expect(request.mock.calls.some(([input]) => String(input).includes('project_id=proyek-produksi-alfa'))).toBe(false)
  })
})
