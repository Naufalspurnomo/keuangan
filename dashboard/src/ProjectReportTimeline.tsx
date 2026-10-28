import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { ArrowDownRight, ArrowLeft, ArrowRight, ArrowUpRight, Plus, X } from 'lucide-react'

import type { ProjectSummary } from './snapshot'
import type { Transaction } from './types'

type Portfolio = 'Hollawall' | 'Texturin'
type MatrixUnit = 'HOLLA' | 'TX' | 'HOJJA'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 1 })
const matrixLabel: Record<MatrixUnit, string> = { HOLLA: 'Holla', TX: 'Texturin', HOJJA: 'Hojja' }
const matrixCode: Record<MatrixUnit, string> = { HOLLA: 'HOLLA', TX: 'TX', HOJJA: 'HOJJA' }
const formatMatrixValue = (value: number) => value === 0 ? 'Rp 0' : `Rp ${compact.format(value)}`
const accents = ['coral', 'teal', 'gold', 'violet', 'blue', 'rose']

function parseDate(value?: string | null) {
  if (!value) return null
  return new Date(value.includes('T') ? value : `${value}T00:00:00`)
}

function dateLabel(value?: string | null) {
  const date = parseDate(value)
  return date ? date.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

function isInternal(row: Transaction) {
  return (row.transfer_scope ?? (row.internal_movement ? 'internal' : 'external')) === 'internal'
}

function matrixUnit(row: Transaction): MatrixUnit | null {
  const company = row.company.trim().toLocaleLowerCase('id-ID')
  const project = row.project.trim().toLocaleLowerCase('id-ID')
  if (project.startsWith('hojja') || company === 'hojja') return 'HOJJA'
  if (project.startsWith('holla') || company === 'holla' || company.startsWith('cv hb')) return 'HOLLA'
  if (company.startsWith('texturin') || company.startsWith('tx sby') || company.startsWith('tx bali')) return 'TX'
  return null
}

function quarterWindow(asOf?: string | null) {
  const anchor = parseDate(asOf) ?? new Date()
  const quarterStartMonth = Math.floor(anchor.getMonth() / 3) * 3
  const start = new Date(anchor.getFullYear(), quarterStartMonth, 1)
  const end = new Date(anchor.getFullYear(), quarterStartMonth + 3, 0)
  const months = Array.from({ length: 3 }, (_, index) => {
    const date = new Date(anchor.getFullYear(), quarterStartMonth + index, 1)
    return {
      name: date.toLocaleDateString('id-ID', { month: 'long' }),
      short: date.toLocaleDateString('id-ID', { month: 'short' }),
    }
  })
  return { anchor, start, end, months }
}

function projectStyle(project: ProjectSummary, start: Date, end: Date, anchor: Date): CSSProperties | null {
  const rawStart = parseDate(project.started_on ?? project.first_activity_on)
  const rawEnd = project.lifecycle_status === 'active'
    ? anchor
    : parseDate(project.completed_on ?? project.last_activity_on)
  if (!rawStart || !rawEnd || rawEnd < start || rawStart > end) return null
  const duration = Math.max(1, end.getTime() - start.getTime())
  const visibleStart = Math.max(start.getTime(), rawStart.getTime())
  const visibleEnd = Math.min(end.getTime(), rawEnd.getTime())
  const top = Math.min(86, ((visibleStart - start.getTime()) / duration) * 100)
  const height = Math.max(14, ((visibleEnd - visibleStart) / duration) * 100)
  return {
    '--project-top': `${top}%`,
    '--project-height': `${Math.min(height, 100 - top)}%`,
  } as CSSProperties
}

function SectionTimeline({ portfolio, projects, window, selected, onSelect, onNew }: {
  portfolio: Portfolio
  projects: ProjectSummary[]
  window: ReturnType<typeof quarterWindow>
  selected?: string
  onSelect: (project: ProjectSummary) => void
  onNew: () => void
}) {
  const [mobile, setMobile] = useState(() => matchMedia('(max-width: 580px)').matches)
  const [page, setPage] = useState(0)
  const items = projects
    .filter((project) => project.portfolio === portfolio)
    .sort((left, right) => (parseDate(right.started_on ?? right.first_activity_on)?.getTime() ?? 0) - (parseDate(left.started_on ?? left.first_activity_on)?.getTime() ?? 0))
    .map((project, index) => ({ project, style: projectStyle(project, window.start, window.end, window.anchor), accent: accents[index % accents.length] }))
    .filter((item) => item.style)
  const pageSize = mobile ? 3 : 4
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const visibleItems = items.slice(safePage * pageSize, safePage * pageSize + pageSize)
  const visibleRange = {
    start: items.length ? safePage * pageSize + 1 : 0,
    end: Math.min(items.length, (safePage + 1) * pageSize),
  }
  useEffect(() => {
    const media = matchMedia('(max-width: 580px)')
    const update = () => setMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => setPage(0), [mobile, portfolio, window.start.getTime()])
  const scroll = (direction: -1 | 1) => setPage((current) => Math.min(pageCount - 1, Math.max(0, current + direction)))

  return <section className={`vertical-project-section ${portfolio.toLocaleLowerCase('id-ID')}`} aria-label={`Timeline proyek ${portfolio}`}>
    <header>
      <div><p>{portfolio.toUpperCase()} SECTION</p><h3>{mobile ? 'Proyek periode ini' : `Rentang proyek ${portfolio}`}</h3></div>
      <button type="button" className="new-project-button" aria-label={`Tambah proyek ${portfolio}`} onClick={onNew}><Plus size={15} />Proyek Baru</button>
    </header>
    {items.length > 0 && <div className="project-lane-navigation" aria-label={`Navigasi proyek ${portfolio}`}>
      <span>{visibleRange.start}–{Math.min(visibleRange.end, items.length)} dari {items.length} proyek</span>
      <div><button type="button" aria-label={`Proyek ${portfolio} sebelumnya`} onClick={() => scroll(-1)} disabled={safePage === 0}><ArrowLeft size={15} /></button><button type="button" aria-label={`Proyek ${portfolio} berikutnya`} onClick={() => scroll(1)} disabled={safePage >= pageCount - 1}><ArrowRight size={15} /></button></div>
    </div>}
    {mobile ? <div className="mobile-project-list" aria-live="polite">
      {visibleItems.map(({ project }) => <button
        type="button"
        key={project.name}
        className={selected === project.name ? 'is-selected' : ''}
        onClick={() => onSelect(project)}
        aria-label={`Buka proyek ${project.name} dari timeline`}
      >
        <span><strong>{project.name}</strong><small>{dateLabel(project.started_on ?? project.first_activity_on)} — {project.lifecycle_status === 'active' ? 'aktif' : dateLabel(project.completed_on ?? project.last_activity_on)}</small></span>
        <ArrowRight size={16} aria-hidden="true" />
      </button>)}
      {!items.length && <div className="vertical-timeline-empty"><strong>Belum ada proyek pada kuartal ini</strong><small>Timeline mengikuti marker Start/Selesai dan aktivitas sumber.</small></div>}
    </div> : <div className="vertical-timeline-shell">
      <div className="vertical-month-axis" aria-hidden="true">
        {window.months.map((month) => <span key={month.name}><b>{month.name}</b><i /></span>)}
      </div>
      <div className="vertical-project-page" aria-live="polite">
        <div className="vertical-project-lanes" style={{ '--lane-count': Math.max(visibleItems.length, 1) } as CSSProperties}>
        {visibleItems.map(({ project, style, accent }) => <button
          type="button"
          key={project.name}
          style={style ?? undefined}
          className={`vertical-project-bar ${accent} ${selected === project.name ? 'is-selected' : ''}`}
          onClick={() => onSelect(project)}
          aria-label={`Buka proyek ${project.name} dari timeline`}
        ><strong>{project.name}</strong><small>{project.lifecycle_status === 'completed' ? 'Selesai' : 'Aktif'}</small></button>)}
        {!items.length && <div className="vertical-timeline-empty"><strong>Belum ada proyek pada kuartal ini</strong><small>Timeline mengikuti marker Start/Selesai dan aktivitas sumber.</small></div>}
        </div>
      </div>
    </div>}
  </section>
}

export default function ProjectReportTimeline({ transactions, projects, asOf, dataThrough, onAddProject }: { transactions: Transaction[]; projects: ProjectSummary[]; asOf?: string | null; dataThrough?: string | null; onAddProject?: () => void }) {
  const window = useMemo(() => quarterWindow(asOf), [asOf])
  const revenueAnchor = parseDate(dataThrough) ?? window.anchor
  const [selected, setSelected] = useState<ProjectSummary | null>(null)
  const [readOnlyNotice, setReadOnlyNotice] = useState(false)
  const monthKey = `${revenueAnchor.getFullYear()}-${String(revenueAnchor.getMonth() + 1).padStart(2, '0')}`
  const previous = new Date(revenueAnchor.getFullYear(), revenueAnchor.getMonth() - 1, 1)
  const previousKey = `${previous.getFullYear()}-${String(previous.getMonth() + 1).padStart(2, '0')}`
  const periodLabels = {
    current: `${revenueAnchor.toLocaleDateString('id-ID', { month: 'long' })} · s.d. ${revenueAnchor.getDate()}`,
    previous: previous.toLocaleDateString('id-ID', { month: 'long' }),
  }
  const matrix = useMemo(() => {
    const result: Record<'current' | 'previous', Record<MatrixUnit, number>> = {
      current: { HOLLA: 0, TX: 0, HOJJA: 0 },
      previous: { HOLLA: 0, TX: 0, HOJJA: 0 },
    }
    transactions.forEach((row) => {
      if (row.transaction_type !== 'Pemasukan' || isInternal(row)) return
      const unit = matrixUnit(row)
      if (!unit) return
      const key = row.transaction_date.slice(0, 7)
      if (key === monthKey) result.current[unit] += row.amount
      if (key === previousKey) result.previous[unit] += row.amount
    })
    return result
  }, [monthKey, previousKey, transactions])

  const selectedTransactions = selected
    ? transactions.filter((row) => row.project.trim().toLocaleLowerCase('id-ID') === selected.name.trim().toLocaleLowerCase('id-ID'))
    : []
  const incoming = selectedTransactions.filter((row) => row.transaction_type === 'Pemasukan' && !isInternal(row)).reduce((sum, row) => sum + row.amount, 0)
  const outgoing = selectedTransactions.filter((row) => row.transaction_type === 'Pengeluaran' && !isInternal(row)).reduce((sum, row) => sum + row.amount, 0)

  return <section className="project-report-module" aria-label="Laporan omzet dan timeline proyek">
    <div className="holla-report-head">
      <div><p className="eyebrow">HOLLA REPORT</p><h2>Omzet dan rentang proyek</h2><span>Status proyek per {dateLabel(asOf)} · omzet transaksi s.d. {dateLabel(dataThrough)}</span></div>
      <div className="revenue-matrix" role="table" aria-label={`Omzet ${revenueAnchor.toLocaleDateString('id-ID', { month: 'long' })} dan ${previous.toLocaleDateString('id-ID', { month: 'long' })}`}>
        <div role="row" className="matrix-head"><span role="columnheader">Periode</span>{(['HOLLA', 'TX', 'HOJJA'] as MatrixUnit[]).map((unit) => <b role="columnheader" key={unit} aria-label={matrixLabel[unit]}>{matrixCode[unit]}</b>)}</div>
        {([['current', 'Bulan ini'], ['previous', 'Bulan lalu']] as const).map(([period, label]) => <div role="row" key={period}><span role="rowheader">{label}<small>{periodLabels[period]}</small></span>{(['HOLLA', 'TX', 'HOJJA'] as MatrixUnit[]).map((unit) => <strong role="cell" data-label={matrixLabel[unit]} key={unit}>{formatMatrixValue(matrix[period][unit])}</strong>)}</div>)}
      </div>
    </div>

    <div className="section-timeline-grid">
      <SectionTimeline portfolio="Hollawall" projects={projects} window={window} selected={selected?.name} onSelect={setSelected} onNew={() => onAddProject ? onAddProject() : setReadOnlyNotice(true)} />
      <SectionTimeline portfolio="Texturin" projects={projects} window={window} selected={selected?.name} onSelect={setSelected} onNew={() => onAddProject ? onAddProject() : setReadOnlyNotice(true)} />
    </div>

    {selected && <aside className="project-timeline-detail" aria-label={`Detail proyek ${selected.name}`}>
      <header><div><p className="eyebrow">PROYEK TERPILIH</p><h3>{selected.name}</h3><span>{selected.portfolio} · {selected.transaction_count ?? selectedTransactions.length} transaksi</span></div><button type="button" className="icon-button" aria-label="Tutup detail proyek" onClick={() => setSelected(null)}><X size={17} /></button></header>
      <div className="project-detail-dates"><span><small>Mulai</small><strong>{dateLabel(selected.started_on ?? selected.first_activity_on)}</strong></span><span><small>Selesai</small><strong>{selected.lifecycle_status === 'active' ? 'Masih aktif' : dateLabel(selected.completed_on ?? selected.last_activity_on)}</strong></span><span><small>Aktivitas terakhir</small><strong>{dateLabel(selected.last_activity_on)}</strong></span></div>
      <div className="project-detail-money"><span><ArrowDownRight size={17} /><small>Masuk</small><strong className="positive">{IDR.format(incoming)}</strong></span><span><ArrowUpRight size={17} /><small>Keluar</small><strong className="negative">{IDR.format(outgoing)}</strong></span><span><small>Bersih</small><strong>{IDR.format(incoming - outgoing)}</strong></span></div>
      <small className="project-source-key">{selected.source_key_latest ?? 'source key belum tersedia'}</small>
    </aside>}

    {readOnlyNotice && <div className="readonly-modal" role="dialog" aria-modal="true" aria-label="Dashboard read-only">
      <div><button type="button" className="icon-button" aria-label="Tutup pemberitahuan" onClick={() => setReadOnlyNotice(false)}><X size={18} /></button><p className="eyebrow">DASHBOARD READ-ONLY</p><h3>Tambah proyek dari sumber data</h3><p>Untuk menjaga audit trail, kelola proyek dari sumber data kanonis. Proyek akan muncul di timeline setelah marker Start atau aktivitas transaksi masuk ke snapshot.</p><button type="button" className="secondary-button" onClick={() => setReadOnlyNotice(false)}>Mengerti</button></div>
    </div>}
  </section>
}
