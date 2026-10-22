import { useMemo, useState, type CSSProperties } from 'react'
import { ArrowDownRight, ArrowUpRight, Plus, X } from 'lucide-react'

import type { ProjectSummary } from './snapshot'
import type { Transaction } from './types'

type Portfolio = 'Hollawall' | 'Texturin'
type MatrixUnit = 'HOLLA' | 'TX' | 'HOJJA'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 1 })
const accents = ['coral', 'teal', 'gold', 'violet', 'blue', 'rose']

function parseDate(value?: string | null) {
  return value ? new Date(`${value}T00:00:00`) : null
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
  if (company === 'holla') return 'HOLLA'
  if (company === 'hojja') return 'HOJJA'
  if (company.startsWith('texturin')) return 'TX'
  return null
}

function quarterWindow(dataThrough?: string | null) {
  const anchor = parseDate(dataThrough) ?? new Date()
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
  const top = ((visibleStart - start.getTime()) / duration) * 100
  const height = Math.max(8, ((visibleEnd - visibleStart) / duration) * 100)
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
  const items = projects
    .filter((project) => project.portfolio === portfolio)
    .map((project, index) => ({ project, style: projectStyle(project, window.start, window.end, window.anchor), accent: accents[index % accents.length] }))
    .filter((item) => item.style)

  return <section className={`vertical-project-section ${portfolio.toLocaleLowerCase('id-ID')}`} aria-label={`Timeline proyek ${portfolio}`}>
    <header>
      <div><p>{portfolio.toUpperCase()} SECTION</p><h3>{portfolio} Project Timeline</h3></div>
      <button type="button" className="new-project-button" aria-label={`Tambah proyek ${portfolio}`} onClick={onNew}><Plus size={15} />Proyek Baru</button>
    </header>
    <div className="vertical-timeline-shell">
      <div className="vertical-month-axis" aria-hidden="true">
        {window.months.map((month) => <span key={month.name}><b>{month.name}</b><i /></span>)}
      </div>
      <div className="vertical-project-lanes">
        {items.map(({ project, style, accent }) => <button
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
  </section>
}

export default function ProjectReportTimeline({ transactions, projects, dataThrough }: { transactions: Transaction[]; projects: ProjectSummary[]; dataThrough?: string | null }) {
  const window = useMemo(() => quarterWindow(dataThrough), [dataThrough])
  const [selected, setSelected] = useState<ProjectSummary | null>(null)
  const [readOnlyNotice, setReadOnlyNotice] = useState(false)
  const monthKey = `${window.anchor.getFullYear()}-${String(window.anchor.getMonth() + 1).padStart(2, '0')}`
  const previous = new Date(window.anchor.getFullYear(), window.anchor.getMonth() - 1, 1)
  const previousKey = `${previous.getFullYear()}-${String(previous.getMonth() + 1).padStart(2, '0')}`
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
      <div><p className="eyebrow">HOLLA REPORT</p><h2>Omzet dan rentang proyek</h2><span>{window.months.map((month) => month.short).join(' · ')} {window.anchor.getFullYear()} · sumber transaksi dan marker lifecycle</span></div>
      <div className="revenue-matrix" role="table" aria-label="Omzet bulan ini dan bulan lalu">
        <div role="row" className="matrix-head"><span role="columnheader">Periode</span>{(['HOLLA', 'TX', 'HOJJA'] as MatrixUnit[]).map((unit) => <b role="columnheader" key={unit}>{unit}</b>)}</div>
        {([['current', 'Bulan ini'], ['previous', 'Bulan lalu']] as const).map(([period, label]) => <div role="row" key={period}><span role="rowheader">{label}</span>{(['HOLLA', 'TX', 'HOJJA'] as MatrixUnit[]).map((unit) => <strong role="cell" key={unit}>{compact.format(matrix[period][unit])}</strong>)}</div>)}
      </div>
    </div>

    <div className="section-timeline-grid">
      <SectionTimeline portfolio="Hollawall" projects={projects} window={window} selected={selected?.name} onSelect={setSelected} onNew={() => setReadOnlyNotice(true)} />
      <SectionTimeline portfolio="Texturin" projects={projects} window={window} selected={selected?.name} onSelect={setSelected} onNew={() => setReadOnlyNotice(true)} />
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
