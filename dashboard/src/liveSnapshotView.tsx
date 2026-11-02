import { useCallback, useEffect, useMemo, useState } from 'react'

import { loadLiveSnapshot, type LiveSnapshotLoadOptions } from './liveSnapshot'
import type { DashboardSnapshot, ProjectSummary, WalletSnapshot } from './snapshot'
import './live-snapshot.css'

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
  | { status: 'loading'; data: null; error: null }
  | { status: 'ready'; data: DashboardSnapshot; error: null }
  | { status: 'error'; data: null; error: Error }

interface UseLiveSnapshotOptions {
  endpoint?: string
  loader?: LiveSnapshotLoader
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

export function useLiveSnapshot({ endpoint, loader = loadLiveSnapshot }: UseLiveSnapshotOptions = {}) {
  const [requestId, setRequestId] = useState(0)
  const [state, setState] = useState<LiveSnapshotState>({ status: 'loading', data: null, error: null })

  const reload = useCallback(() => setRequestId((current) => current + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading', data: null, error: null })
    loader({ endpoint, signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setState({ status: 'ready', data, error: null })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState({ status: 'error', data: null, error: readableError(error) })
      })

    return () => controller.abort()
  }, [endpoint, loader, requestId])

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
          <strong>Menghubungkan data keuangan live</strong>
          <p>Memverifikasi sesi admin dan kontrak snapshot.</p>
        </div>
      </section>
    )
  }

  if (state.status === 'error') {
    return (
      <section className="live-snapshot live-snapshot--error" role="alert">
        <div>
          <strong>Data live belum tersedia</strong>
          <p>{state.error.message} Data demo tidak ditampilkan sebagai data live.</p>
        </div>
        <button type="button" onClick={state.reload} aria-label="Coba lagi data live">
          Coba lagi
        </button>
      </section>
    )
  }

  if (!view) return null

  return (
    <section className={`live-snapshot live-snapshot--${view.freshness}`} aria-label="Status data live">
      <div className="live-snapshot__heading">
        <div>
          <span className="live-snapshot__eyebrow">Data keuangan live</span>
          <h2>{view.source}</h2>
          <p>
            {view.freshnessLabel} · Data sampai {formatSnapshotDate(view.dataThrough)} · {view.validRows} baris valid ·{' '}
            {view.invalidRows} perlu ditinjau
          </p>
        </div>
        <button type="button" onClick={state.reload} aria-label="Muat ulang data live">
          Muat ulang
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
