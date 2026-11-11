import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { loadLiveSnapshot, type LiveSnapshotLoadOptions } from './liveSnapshot'
import type { DashboardSnapshot, ProjectSummary, WalletSnapshot } from './snapshot'

type LiveSnapshotLoader = (options?: LiveSnapshotLoadOptions) => Promise<DashboardSnapshot>

export interface LiveSnapshotViewModel {
  source: string
  freshness: DashboardSnapshot['meta']['freshness']
  freshnessLabel: string
  dataThrough: string | null
  asOf: string
  cashBalance: number
  operatingInflow: number
  operatingOutflow: number
  netOperatingCashflow: number
  openInternalDebt: number
  projectCashflow: number
  validRows: number
  invalidRows: number
  completenessPct: number
  wallets: WalletSnapshot[]
  projects: ProjectSummary[]
}

export type LiveSnapshotState =
  | { status: 'loading'; data: null; error: null; refreshing: false }
  | { status: 'ready'; data: DashboardSnapshot; error: Error | null; refreshing: boolean }
  | { status: 'error'; data: null; error: Error; refreshing: false }

interface UseLiveSnapshotOptions {
  endpoint?: string
  loader?: LiveSnapshotLoader
  pollIntervalMs?: number
}

const rupiah = new Intl.NumberFormat('id-ID', {
  style: 'currency',
  currency: 'IDR',
  maximumFractionDigits: 0,
})

const dateFormatter = new Intl.DateTimeFormat('id-ID', {
  dateStyle: 'long',
  timeZone: 'UTC',
})

const freshnessLabels: Record<DashboardSnapshot['meta']['freshness'], string> = {
  fresh: 'Segar',
  aging: 'Perlu diperbarui',
  stale: 'Kedaluwarsa',
}

function readableError(error: unknown): Error {
  return error instanceof Error ? error : new Error('Permintaan data live gagal.')
}

function formatSnapshotDate(value: string | null): string {
  if (!value) return 'belum tersedia'
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? value : dateFormatter.format(parsed)
}

export function adaptLiveSnapshot(snapshot: DashboardSnapshot): LiveSnapshotViewModel {
  const { metrics } = snapshot.overview
  return {
    source: snapshot.meta.source ?? 'Sumber keuangan terautentikasi',
    freshness: snapshot.meta.freshness,
    freshnessLabel: freshnessLabels[snapshot.meta.freshness],
    dataThrough: snapshot.meta.data_through ?? null,
    asOf: snapshot.meta.as_of,
    cashBalance: metrics.cash_balance,
    operatingInflow: metrics.operating_inflow,
    operatingOutflow: metrics.operating_outflow,
    netOperatingCashflow: metrics.net_operating_cashflow,
    openInternalDebt: metrics.open_internal_debt,
    projectCashflow: metrics.project_cashflow,
    validRows: snapshot.overview.counts.valid_rows,
    invalidRows: snapshot.overview.counts.invalid_rows,
    completenessPct: snapshot.meta.data_completeness.completeness_pct,
    wallets: [...snapshot.wallets].sort((left, right) => right.balance - left.balance || left.name.localeCompare(right.name)),
    projects: [...(snapshot.project_summaries ?? [])].sort(
      (left, right) => Math.abs(right.net_cashflow) - Math.abs(left.net_cashflow) || left.name.localeCompare(right.name),
    ),
  }
}

export function useLiveSnapshot({ endpoint, loader = loadLiveSnapshot, pollIntervalMs = 5_000 }: UseLiveSnapshotOptions = {}) {
  const [state, setState] = useState<LiveSnapshotState>({ status: 'loading', data: null, error: null, refreshing: false })
  const activeController = useRef<AbortController | null>(null)
  const requestSequence = useRef(0)

  const reload = useCallback(() => {
    activeController.current?.abort()
    const controller = new AbortController()
    const sequence = ++requestSequence.current
    activeController.current = controller
    setState((current) => current.data
      ? { status: 'ready', data: current.data, error: null, refreshing: true }
      : { status: 'loading', data: null, error: null, refreshing: false })
    return loader({ endpoint, signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted && sequence === requestSequence.current) {
          setState({ status: 'ready', data, error: null, refreshing: false })
        }
        return data
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && sequence === requestSequence.current) {
          const readable = readableError(error)
          setState((current) => current.data
            ? { status: 'ready', data: current.data, error: readable, refreshing: false }
            : { status: 'error', data: null, error: readable, refreshing: false })
        }
        throw error
      })
  }, [endpoint, loader])

  useEffect(() => {
    void reload().catch(() => undefined)
    const poll = () => { if (document.visibilityState === 'visible') void reload().catch(() => undefined) }
    const interval = window.setInterval(poll, pollIntervalMs)
    const onFocus = () => { if (document.visibilityState === 'visible') void reload().catch(() => undefined) }
    const onVisibilityChange = () => { if (document.visibilityState === 'visible') void reload().catch(() => undefined) }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      activeController.current?.abort()
    }
  }, [pollIntervalMs, reload])

  return { ...state, reload }
}

interface LiveSnapshotBannerProps {
  endpoint?: string
  loader?: LiveSnapshotLoader
}

export function LiveSnapshotBanner({ endpoint, loader = loadLiveSnapshot }: LiveSnapshotBannerProps) {
  const resolvedEndpoint = endpoint ?? (window.location.pathname.startsWith('/admin')
    ? '/admin/api/snapshot.php'
    : '/live-api/snapshot')
  const state = useLiveSnapshot({ endpoint: resolvedEndpoint, loader })
  const view = useMemo(
    () => (state.status === 'ready' ? adaptLiveSnapshot(state.data) : null),
    [state],
  )

  if (state.status === 'loading') {
    return (
      <section className="live-snapshot live-snapshot--loading" role="status" aria-live="polite">
        <span className="live-snapshot__pulse" aria-hidden="true" />
        <div>
          <strong>Memuat data keuangan</strong>
          <p>Menyiapkan ringkasan terbaru.</p>
        </div>
      </section>
    )
  }

  if (state.status === 'error') {
    return (
      <section className="live-snapshot live-snapshot--error" role="alert">
        <div>
          <strong>Data belum tersedia</strong>
          <p>{state.error.message} Data demo tidak ditampilkan sebagai pengganti.</p>
        </div>
        <button type="button" onClick={() => void state.reload()} aria-label="Coba lagi data">
          Coba lagi
        </button>
      </section>
    )
  }

  if (!view) return null

  return (
    <section className={`live-snapshot live-snapshot--${view.freshness}`} aria-label="Status data">
      <div className="live-snapshot__heading">
        <div>
          <span className="live-snapshot__eyebrow">Ringkasan keuangan</span>
          <h2>{view.source}</h2>
          <p>
            {view.freshnessLabel} · Data sampai {formatSnapshotDate(view.dataThrough)} · {view.validRows} baris valid ·{' '}
            {view.invalidRows} perlu ditinjau
          </p>
        </div>
        <button type="button" onClick={() => void state.reload()} aria-label="Muat ulang data" disabled={state.refreshing}>
          {state.refreshing ? 'Memperbarui…' : 'Muat ulang'}
        </button>
      </div>
      <div className="live-snapshot__metrics">
        <article>
          <span>Saldo kas</span>
          <strong>{rupiah.format(view.cashBalance)}</strong>
        </article>
        <article>
          <span>Arus kas bersih</span>
          <strong>{rupiah.format(view.netOperatingCashflow)}</strong>
        </article>
        <article>
          <span>Hutang internal terbuka</span>
          <strong>{rupiah.format(view.openInternalDebt)}</strong>
        </article>
        <article>
          <span>Kelengkapan</span>
          <strong>{view.completenessPct.toLocaleString('id-ID')}%</strong>
        </article>
      </div>
      <p className="live-snapshot__scope">
        {view.wallets.length} dompet · {view.projects.length} proyek terproyeksi
      </p>
    </section>
  )
}
