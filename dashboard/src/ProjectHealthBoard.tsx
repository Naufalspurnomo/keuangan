import { useMemo, useState, type CSSProperties } from 'react'
import { Search } from 'lucide-react'

import type { ProjectHealth, ProjectSummary } from './snapshot'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })

type Filter = 'all' | 'active' | 'attention' | 'completed' | 'unmarked'
type Portfolio = 'all' | NonNullable<ProjectSummary['portfolio']>

const healthMeta: Record<ProjectHealth, { label: string; copy: string }> = {
  healthy: { label: 'Baru · Sehat', copy: 'Berjalan 0–14 hari' },
  watch: { label: 'Pantau', copy: 'Berjalan 15–30 hari' },
  overdue: { label: 'Lewat 30 hari', copy: 'Masih aktif dan perlu perhatian' },
  completed: { label: 'Selesai', copy: 'Lifecycle sudah ditutup' },
  unmarked: { label: 'Belum ditandai', copy: 'Tidak ada marker Start/Selesai' },
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

function timelineWindow() {
  const end = new Date()
  const start = new Date(end.getFullYear(), end.getMonth() - 2, 1)
  const windowEnd = new Date(end.getFullYear(), end.getMonth() + 1, 0)
  const months = Array.from({ length: 3 }, (_, index) => {
    const value = new Date(start.getFullYear(), start.getMonth() + index, 1)
    return value.toLocaleDateString('id-ID', { month: 'long' })
  })
  return { start, end: windowEnd, months }
}

function timelineStyle(project: ProjectSummary, start: Date, end: Date): CSSProperties | null {
  const rawStart = parseDate(project.started_on ?? project.first_activity_on)
  const rawEnd = project.lifecycle_status === 'active' ? new Date() : parseDate(project.completed_on ?? project.last_activity_on)
  if (!rawStart || !rawEnd || rawEnd < start || rawStart > end) return null
  const duration = Math.max(1, end.getTime() - start.getTime())
  const visibleStart = Math.max(start.getTime(), rawStart.getTime())
  const visibleEnd = Math.min(end.getTime(), rawEnd.getTime())
  const left = ((visibleStart - start.getTime()) / duration) * 100
  const width = Math.max(3, ((visibleEnd - visibleStart) / duration) * 100)
  return { '--timeline-left': `${left}%`, '--timeline-width': `${Math.min(width, 100 - left)}%` } as CSSProperties
}

export default function ProjectHealthBoard({ projects, onOpen }: { projects: ProjectSummary[]; onOpen: (name: string) => void }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [portfolio, setPortfolio] = useState<Portfolio>('all')
  const [query, setQuery] = useState('')
  const normalizedQuery = query.trim().toLocaleLowerCase('id-ID')
  const filtered = useMemo(
    () => projects.filter((project) => matchesFilter(project, filter)
      && (portfolio === 'all' || project.portfolio === portfolio)
      && (!normalizedQuery || project.name.toLocaleLowerCase('id-ID').includes(normalizedQuery))),
    [filter, normalizedQuery, portfolio, projects],
  )
  const portfolioOptions = Array.from(new Set(projects.map((project) => project.portfolio).filter(Boolean))) as Portfolio[]
  const counts = Object.fromEntries(
    (['healthy', 'watch', 'overdue', 'completed', 'unmarked'] as ProjectHealth[])
      .map((health) => [health, projects.filter((project) => projectHealth(project) === health).length]),
  ) as Record<ProjectHealth, number>
  const timeline = timelineWindow()
  const timelineProjects = filtered.map((project) => ({ project, style: timelineStyle(project, timeline.start, timeline.end) })).filter((item) => item.style)

  return <section className="project-health-board">
    <div className="project-health-summary">
      <div><p className="eyebrow">PROJECT HEALTH BOARD</p><h2>Umur dan kesehatan proyek</h2><p>Status mengikuti marker Start/Selesai. Warna tidak dipakai sendirian—setiap kartu membawa label.</p></div>
      <div className="project-summary-stats" aria-label="Ringkasan kesehatan proyek">
        <span className="healthy"><strong>{counts.healthy}</strong> baru/sehat</span>
        <span className="watch"><strong>{counts.watch}</strong> pantau</span>
        <span className="overdue"><strong>{counts.overdue}</strong> terlambat &gt;30 hari</span>
        <span><strong>{counts.completed}</strong> selesai</span>
        <span><strong>{counts.unmarked}</strong> belum ditandai</span>
      </div>
    </div>
    <div className="project-controls">
      <label className="project-search"><Search size={18} /><span className="sr-only">Cari proyek</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari nama proyek…" /></label>
      <label className="portfolio-select"><span>Portfolio</span><select aria-label="Filter portfolio" value={portfolio} onChange={(event) => setPortfolio(event.target.value as Portfolio)}><option value="all">Semua portfolio</option>{portfolioOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <div className="project-filters" role="group" aria-label="Filter kesehatan proyek">
        {([
          ['all', 'Semua'], ['active', 'Aktif'], ['attention', 'Perlu perhatian'], ['completed', 'Selesai'], ['unmarked', 'Belum ditandai'],
        ] as const).map(([value, label]) => <button key={value} type="button" className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>)}
      </div>
      <span className="result-count">{filtered.length.toLocaleString('id-ID')} proyek</span>
    </div>
    <section className="project-timeline" aria-label="Timeline proyek tiga bulan">
      <div className="timeline-heading"><div><p className="eyebrow">PORTFOLIO TIMELINE</p><h2>Timeline 3 bulan</h2></div><span>Marker lifecycle + aktivitas sumber</span></div>
      <div className="timeline-months" aria-hidden="true">{timeline.months.map((month) => <span key={month}>{month}</span>)}</div>
      {timelineProjects.length ? <div className="timeline-rows">{timelineProjects.map(({ project, style }) => <button key={project.name} type="button" className="timeline-row" onClick={() => onOpen(project.name)} aria-label={`Buka transaksi proyek ${project.name} dari timeline`}><span className="timeline-label"><strong>{project.name}</strong><small>{project.portfolio ?? 'Belum dipetakan'}</small></span><span className={`timeline-track ${projectHealth(project)}`}><i style={style ?? undefined}></i></span></button>)}</div> : <p className="timeline-empty">Tidak ada proyek pada jendela tiga bulan ini.</p>}
    </section>
    {filtered.length ? <div className="project-health-grid">
      {filtered.map((project) => {
        const health = projectHealth(project)
        const meta = healthMeta[health]
        const age = project.age_days
        const progress = age === null || age === undefined ? 0 : Math.min(100, (age / 45) * 100)
        return <button type="button" className={`project-health-card ${health}`} key={project.name} onClick={() => onOpen(project.name)} aria-label={`Buka transaksi proyek ${project.name}, ${meta.label}`}>
          <div className="project-card-head"><span className={`health-badge ${health}`}>{meta.label}</span><span>{project.portfolio ?? 'Belum dipetakan'} · {project.transaction_count ?? 0} transaksi</span></div>
          <h3>{project.name}</h3>
          <p className="project-health-copy">{meta.copy}</p>
          <div className="project-age-track" aria-label={age === null || age === undefined ? 'Umur proyek belum tersedia' : `${age} hari`}><span style={{ width: `${progress}%` }}></span><i className="threshold fourteen"></i><i className="threshold thirty"></i></div>
          <div className="project-age-label"><strong>{age === null || age === undefined ? 'Umur belum tersedia' : `${age} hari`}</strong><span>{project.lifecycle_status === 'completed' ? `Selesai ${dateLabel(project.completed_on)}` : project.started_on ? `Mulai ${dateLabel(project.started_on)}` : 'Marker Start belum ada'}</span></div>
          <dl>
            <div><dt>Aktivitas terakhir</dt><dd>{dateLabel(project.last_activity_on)}</dd></div>
            <div><dt>Arus kas bersih</dt><dd className={project.net_cashflow >= 0 ? 'positive' : 'negative'}>{IDR.format(project.net_cashflow)}</dd></div>
          </dl>
          <small>{project.source_key_latest ?? 'source key belum tersedia'}</small>
        </button>
      })}
    </div> : <div className="project-empty"><strong>Proyek tidak ditemukan</strong><p>Ubah pencarian atau filter status.</p></div>}
  </section>
}
