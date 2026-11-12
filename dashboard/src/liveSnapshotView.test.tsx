import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { adaptLiveSnapshot, LiveSnapshotBanner } from './liveSnapshotView'
import type { DashboardSnapshot } from './snapshot'

const snapshot = (): DashboardSnapshot => ({
  version: 'dashboard.snapshot.v1',
  meta: {
    as_of: '2026-11-02T09:30:00Z',
    data_through: '2026-11-01',
    source: 'Hollawall ledger',
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
  wallets: [
    { source_key: 'wallet-2', name: 'TX SBY', balance: 5_000_000 },
    { source_key: 'wallet-1', name: 'CV HB', balance: 10_000_000 },
  ],
  transactions: [],
  debts: [],
  cash_trend: [],
  project_summaries: [
    { name: 'Proyek B', net_cashflow: 4_000_000 },
    { name: 'Proyek A', net_cashflow: 10_000_000 },
  ],
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('adaptLiveSnapshot', () => {
  it('creates a stable read-only view model without mutating server order', () => {
    const input = snapshot()
    const adapted = adaptLiveSnapshot(input)

    expect(adapted).toMatchObject({
      source: 'Hollawall ledger',
      freshness: 'fresh',
      cashBalance: 15_000_000,
      validRows: 12,
      invalidRows: 1,
      completenessPct: 92.3,
    })
    expect(adapted.wallets.map((wallet) => wallet.name)).toEqual(['CV HB', 'TX SBY'])
    expect(adapted.projects.map((project) => project.name)).toEqual(['Proyek A', 'Proyek B'])
    expect(input.wallets.map((wallet) => wallet.name)).toEqual(['TX SBY', 'CV HB'])
  })
})

describe('LiveSnapshotBanner', () => {
  it('loads authenticated live finance through the injected loader and exposes freshness', async () => {
    const loader = vi.fn(async () => snapshot())
    render(<LiveSnapshotBanner loader={loader} />)

    expect(screen.getByRole('status').textContent).toContain('Memuat data keuangan')
    await waitFor(() => expect(screen.getByRole('region', { name: 'Status data' })).toBeTruthy())
    expect(screen.getByText('Ringkasan keuangan')).toBeTruthy()
    expect(screen.getAllByText((text) => text.replace(/\s/g, '') === 'Rp15.000.000')).toHaveLength(2)
    expect(screen.getByText(/12 baris valid · 1 perlu ditinjau/)).toBeTruthy()
    expect(screen.getByText(/Segar · Data sampai 1 November 2026/)).toBeTruthy()
    expect(loader).toHaveBeenCalledTimes(1)
    expect(loader).toHaveBeenCalledWith(expect.objectContaining({
      endpoint: '/live-api/snapshot',
      signal: expect.any(AbortSignal),
    }))
  })

  it('fails closed and retries without displaying demo data as live', async () => {
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error('Snapshot unavailable (503)'))
      .mockResolvedValueOnce(snapshot())
    render(<LiveSnapshotBanner loader={loader} />)

    const error = await screen.findByRole('alert')
    expect(error.textContent).toContain('Data belum tersedia')
    expect(error.textContent).toContain('Snapshot unavailable (503)')
    expect(screen.queryByText('Rp15.000.000')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Coba lagi data' }))

    await waitFor(() => expect(screen.getByText('Ringkasan keuangan')).toBeTruthy())
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('keeps the last good snapshot mounted while a refresh is pending', async () => {
    let resolveRefresh!: (value: DashboardSnapshot) => void
    const refreshed = snapshot()
    refreshed.overview.metrics.cash_balance = 22_000_000
    const loader = vi.fn()
      .mockResolvedValueOnce(snapshot())
      .mockImplementationOnce(() => new Promise<DashboardSnapshot>((resolve) => { resolveRefresh = resolve }))
    render(<LiveSnapshotBanner loader={loader} />)

    await screen.findAllByText((text) => text.replace(/\s/g, '') === 'Rp15.000.000')
    fireEvent.click(screen.getByRole('button', { name: 'Muat ulang data' }))
    await waitFor(() => expect(loader).toHaveBeenCalledTimes(2))

    expect(screen.getAllByText((text) => text.replace(/\s/g, '') === 'Rp15.000.000')).toHaveLength(2)
    expect(screen.queryByText('Menghubungkan data keuangan')).toBeNull()

    resolveRefresh(refreshed)
    await screen.findByText((text) => text.replace(/\s/g, '') === 'Rp22.000.000')
  })

  it('does not abort and restart a slow snapshot on each poll tick', async () => {
    vi.useFakeTimers()
    let resolveSnapshot!: (value: DashboardSnapshot) => void
    let observedSignal: AbortSignal | undefined
    const loader = vi.fn((options) => {
      observedSignal = options?.signal
      return new Promise<DashboardSnapshot>((resolve) => { resolveSnapshot = resolve })
    })
    render(<LiveSnapshotBanner loader={loader} />)
    await act(async () => { await Promise.resolve() })

    await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })

    expect(loader).toHaveBeenCalledTimes(1)
    expect(observedSignal?.aborted).toBe(false)

    await act(async () => {
      resolveSnapshot(snapshot())
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(screen.getByText('Ringkasan keuangan')).toBeTruthy()
  })

  it('polls every five seconds only while visible and refreshes on focus or restored visibility', async () => {
    vi.useFakeTimers()
    let visibility: DocumentVisibilityState = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
    const loader = vi.fn(async () => snapshot())
    render(<LiveSnapshotBanner loader={loader} />)
    await act(async () => { await Promise.resolve() })
    expect(loader).toHaveBeenCalledTimes(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(4_999) })
    expect(loader).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(loader).toHaveBeenCalledTimes(2)

    visibility = 'hidden'
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(loader).toHaveBeenCalledTimes(2)

    visibility = 'visible'
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await act(async () => { await Promise.resolve() })
    expect(loader).toHaveBeenCalledTimes(3)

    act(() => window.dispatchEvent(new Event('focus')))
    await act(async () => { await Promise.resolve() })
    expect(loader).toHaveBeenCalledTimes(4)
  })
})
