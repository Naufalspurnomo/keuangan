import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Search } from 'lucide-react'

import ActiveProjectAgeChart from './ActiveProjectAgeChart'
import type { ProjectHealth, ProjectSummary } from './snapshot'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const PAGE_SIZE = 12

type Filter = 'all' | 'active' | 'attention' | 'completed'
type Portfolio = 'all' | NonNullable<ProjectSummary['portfolio']>

const healthMeta: Record<ProjectHealth, { label: string; copy: string }> = {
  healthy: { label: 'Baru · Sehat', copy: 'Berjalan 0–14 hari' },
  watch: { label: 'Pantau', copy: 'Berjalan 15–30 hari' },
  overdue: { label: 'Lewat 30 hari', copy: 'Aktif dan perlu perhatian' },
  completed: { label: 'Selesai', copy: 'Lifecycle sudah ditutup' },
  unmarked: { label: 'Belum ditandai', copy: 'Marker Start/Selesai belum ada' },
}

const portfolioIdentity: Record<string, { mark: string; copy: string }> = {
  Hollawall: { mark: 'H', copy: 'Produksi & aktivasi' },
  Texturin: { mark: 'T', copy: 'Tekstur & finishing' },
  Operasional: { mark: 'O', copy: 'Operasional bersama' },
  'Lintas portfolio': { mark: 'L', copy: 'Lintas unit' },
}

function parseDate(value?: string | null) {
  return value ? new Date(`${value}T00:00:00`) : null
}

function dateLabel(value?: string | null) {
  const date = parseDate(value)
  return date ? date.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

function projectHealth(project: ProjectSummary): ProjectHealth {
  return project.health ?? 'unmarked'
}

function matchesFilter(project: ProjectSummary, filter: Filter) {
  const health = projectHealth(project)
  if (filter === 'all') return true
  if (filter === 'active') return ['healthy', 'watch', 'overdue'].includes(health)
  if (filter === 'attention') return ['watch', 'overdue'].includes(health)
  return health === filter
}

function portfolioClass(value?: string | null) {
  return `portfolio-${(value ?? 'unmapped').toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
}

function isoDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function buildCandleDemo(projects: ProjectSummary[], asOfValue?: string | null) {
  const asOf = parseDate(asOfValue) ?? new Date()
  const demoCounts = new Map<string, number>()
  const demoIndexes = new Map<string, number>()
  projects.forEach((project) => {
    if (project.lifecycle_status === 'active' && (project.portfolio === 'Hollawall' || project.portfolio === 'Texturin')) {
      demoCounts.set(project.portfolio, (demoCounts.get(project.portfolio) ?? 0) + 1)
    }
  })
  return projects.map((project) => {
    if (project.lifecycle_status !== 'active' || (project.portfolio !== 'Hollawall' && project.portfolio !== 'Texturin')) return project
    const demoIndex = demoIndexes.get(project.portfolio) ?? 0
    const demoCount = demoCounts.get(project.portfolio) ?? 1
    const age = demoCount <= 1 ? 21 : Math.round(3 + (demoIndex / (demoCount - 1)) * 87)
    demoIndexes.set(project.portfolio, demoIndex + 1)
    const started = new Date(asOf.getTime() - age * 86_400_000)
    const firstActivity = new Date(started.getTime() + Math.max(1, Math.round(age * .16)) * 86_400_000)
    const lastActivity = new Date(asOf.getTime() - Math.max(1, Math.round(age * .08)) * 86_400_000)
    return {
      ...project,
      age_days: age,
      started_on: isoDate(started),
      first_activity_on: isoDate(firstActivity),
      last_activity_on: isoDate(lastActivity),
      health: age <= 14 ? 'healthy' : age <= 30 ? 'watch' : 'overdue',
    } as ProjectSummary
  })
}

export default function ProjectHealthBoard({ projects, asOf, onOpen }: { projects: ProjectSummary[]; asOf?: string | null; onOpen: (name: string) => void }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [portfolio, setPortfolio] = useState<Portfolio>('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [candleMode, setCandleMode] = useState<'demo' | 'actual'>('demo')
  const normalizedQuery = query.trim().toLocaleLowerCase('id-ID')
  const portfolioOptions = useMemo(() => Array.from(new Set(projects.map((project) => project.portfolio).filter(Boolean))) as Portfolio[], [projects])
  const filtered = useMemo(
    () => projects.filter((project) => matchesFilter(project, filter)
      && (portfolio === 'all' || project.portfolio === portfolio)
      && (!normalizedQuery || project.name.toLocaleLowerCase('id-ID').includes(normalizedQuery)))
      .sort((left, right) => (parseDate(right.last_activity_on)?.getTime() ?? 0) - (parseDate(left.last_activity_on)?.getTime() ?? 0)),
    [projects, filter, normalizedQuery, portfolio],
  )
  const ordered = useMemo(() => {
    if (portfolio !== 'all') return filtered
    const buckets = portfolioOptions.map((name) => filtered.filter((project) => project.portfolio === name))
    const unmapped = filtered.filter((project) => !project.portfolio)
    const result: ProjectSummary[] = []
    const length = Math.max(0, ...buckets.map((bucket) => bucket.length), unmapped.length)
    for (let index = 0; index < length; index += 1) {
      buckets.forEach((bucket) => { if (bucket[index]) result.push(bucket[index]) })
      if (unmapped[index]) result.push(unmapped[index])
    }
    return result
  }, [filtered, portfolio, portfolioOptions])
  const counts = Object.fromEntries(
    (['healthy', 'watch', 'overdue', 'completed', 'unmarked'] as ProjectHealth[])
      .map((health) => [health, projects.filter((project) => projectHealth(project) === health).length]),
  ) as Record<ProjectHealth, number>
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const visible = ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const groupedVisible = portfolioOptions.map((name) => ({ name, projects: visible.filter((project) => project.portfolio === name) })).filter((group) => group.projects.length)
  const unmappedVisible = visible.filter((project) => !project.portfolio)
  const chartPortfolios = (portfolio === 'all' ? portfolioOptions : [portfolio]).filter((value) => value === 'Hollawall' || value === 'Texturin') as NonNullable<ProjectSummary['portfolio']>[]
  const candleProjects = useMemo(() => candleMode === 'demo' ? buildCandleDemo(projects, asOf) : projects, [asOf, candleMode, projects])

  useEffect(() => setPage(0), [filter, normalizedQuery, portfolio])
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1) }, [page, pageCount])

  return <section className="project-health-board project-portfolio-ledger">
    <header className="project-register-head">
      <div><p className="eyebrow">UNIT USAHA</p><h2>Hollawall &amp; Texturin</h2><p>Pilih unit usaha untuk melihat proyek, status, umur, dan arus kas dari sumber yang sama.</p></div>
      <div className="project-summary-stats" aria-label="Ringkasan kesehatan proyek">
        {[
          { key: 'healthy', count: counts.healthy, label: 'Baru · Sehat' },
          { key: 'watch', count: counts.watch, label: 'Pantau' },
          { key: 'overdue', count: counts.overdue, label: 'Lewat 30 hari' },
          { key: 'completed', count: counts.completed, label: 'Selesai' },
        ].filter((item) => item.count > 0).map((item) => <span className={item.key} key={item.key}><strong>{item.count}</strong>{item.label}</span>)}
      </div>
    </header>

    <div className="project-explorer">
      <div className="project-query-row">
        <label className="project-search"><Search size={18} /><span className="sr-only">Cari proyek</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari nama proyek…" /></label>
        <span className="result-count"><strong>{filtered.length.toLocaleString('id-ID')}</strong> proyek</span>
      </div>

      <div className="portfolio-switcher" role="group" aria-label="Filter portfolio">
        <button type="button" className={portfolio === 'all' ? 'active portfolio-all' : 'portfolio-all'} onClick={() => setPortfolio('all')} aria-pressed={portfolio === 'all'} aria-label="Filter portfolio Semua portfolio">
          <i>∑</i><span><strong>Semua unit</strong><small>{projects.length.toLocaleString('id-ID')} proyek</small></span>
        </button>
        {portfolioOptions.map((value) => {
          const identity = portfolioIdentity[value] ?? { mark: value.charAt(0), copy: 'Portfolio' }
          const count = projects.filter((project) => project.portfolio === value).length
          return <button type="button" key={value} className={`${portfolio === value ? 'active ' : ''}${portfolioClass(value)}`} onClick={() => setPortfolio(value)} aria-pressed={portfolio === value} aria-label={`Filter portfolio ${value}`}>
            <i>{identity.mark}</i><span><strong>{value}</strong><small>{count.toLocaleString('id-ID')} proyek · {identity.copy}</small></span>
          </button>
        })}
      </div>

    </div>

    {filter !== 'completed' && <>
      <section className="candle-demo-control" aria-label="Sumber umur project candle">
        <div><p>{candleMode === 'demo' ? 'SIMULASI UMUR' : 'DATA AKTUAL'}</p><strong>{candleMode === 'demo' ? 'Variasi warna untuk uji visual' : 'Umur proyek dari snapshot'}</strong><span>{candleMode === 'demo' ? 'Nama proyek dan tujuan klik tetap asli. Hanya umur, tanggal, serta rentang garis pada candle yang dibuat bervariasi.' : 'Candle memakai umur dan tanggal aktual. Proyek lama dapat terlihat dominan merah.'}</span></div>
        <div role="group" aria-label="Pilih sumber umur candle"><button type="button" className={candleMode === 'demo' ? 'active' : ''} aria-pressed={candleMode === 'demo'} onClick={() => setCandleMode('demo')}>Demo variasi</button><button type="button" className={candleMode === 'actual' ? 'active' : ''} aria-pressed={candleMode === 'actual'} onClick={() => setCandleMode('actual')}>Data aktual</button></div>
      </section>
      <ActiveProjectAgeChart projects={candleProjects} portfolios={chartPortfolios} query={query} asOf={asOf} onOpen={onOpen} />
    </>}

    <div className="project-ledger-filter-block">
      <p>FILTER DAFTAR PROYEK</p>
      <div className="project-filter-rail" role="group" aria-label="Filter daftar proyek">
        {([
          ['all', 'Semua'], ['active', 'Aktif'], ['attention', 'Perlu perhatian'], ['completed', 'Selesai'],
        ] as const).map(([value, label]) => <button key={value} type="button" className={filter === value ? 'active' : ''} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
      </div>
    </div>

    {filtered.length ? <section className="project-ledger-results" aria-label="Daftar proyek per perusahaan">
      <header><div><p className="eyebrow">DAFTAR PROYEK · DATA AKTUAL</p><h2>Proyek per unit usaha</h2><p>Klik satu baris untuk membuka transaksi proyek. Umur dihitung sejak marker Mulai; arus kas bersih adalah pemasukan dikurangi pengeluaran proyek.</p></div><span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} dari {filtered.length.toLocaleString('id-ID')}</span></header>
      <div className="portfolio-project-groups">
        {[...groupedVisible, ...(unmappedVisible.length ? [{ name: 'Belum dipetakan' as Portfolio, projects: unmappedVisible }] : [])].map((group) => {
          const identity = portfolioIdentity[group.name] ?? { mark: group.name.charAt(0), copy: 'Portfolio' }
          return <section className={`portfolio-project-group ${portfolioClass(group.name)}`} key={group.name}>
            <header><i>{identity.mark}</i><div><h3>{group.name}</h3><p>{identity.copy}</p></div><span>{group.projects.length} tampil</span></header>
            <div className="project-ledger-column-head" aria-hidden="true"><span>Proyek &amp; aktivitas terakhir</span><span>Status umur</span><span>Umur berjalan</span><span>Arus kas bersih</span></div>
            <div className="project-ledger-rows">{group.projects.map((project) => {
              const health = projectHealth(project)
              const meta = healthMeta[health]
              return <button type="button" className={`project-ledger-row ${health}`} key={project.name} onClick={() => onOpen(project.name)} aria-label={`Buka transaksi proyek ${project.name}, ${meta.label}`}>
                <span className="project-ledger-main"><strong>{project.name}</strong><small>{project.portfolio ?? 'Belum dipetakan'} · {project.transaction_count ?? 0} transaksi · aktivitas terakhir {dateLabel(project.last_activity_on)}</small></span>
                <span className={`health-label ${health}`}>{meta.label}</span>
                <span className="project-ledger-age"><small>Umur</small><strong>{project.age_days === null || project.age_days === undefined ? '—' : `${project.age_days} hari`}</strong></span>
                <span className={`project-ledger-money ${project.net_cashflow >= 0 ? 'positive' : 'negative'}`}><small>Arus kas</small><strong>{IDR.format(project.net_cashflow)}</strong></span>
              </button>
            })}</div>
          </section>
        })}
      </div>
      {pageCount > 1 && <nav className="project-ledger-pagination" aria-label="Pagination proyek"><button type="button" onClick={() => setPage((value) => Math.max(0, value - 1))} disabled={page === 0}><ArrowLeft size={16} /> Sebelumnya</button><span>Halaman {page + 1} / {pageCount}</span><button type="button" onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))} disabled={page === pageCount - 1}>Berikutnya <ArrowRight size={16} /></button></nav>}
    </section> : <div className="project-empty"><strong>Proyek tidak ditemukan</strong><p>Ubah pencarian, perusahaan, atau status.</p></div>}
  </section>
}
