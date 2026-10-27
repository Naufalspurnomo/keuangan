import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { ArrowLeft, ArrowRight, Move } from 'lucide-react'

import type { ProjectSummary } from './snapshot'

const PAGE_SIZE = 10
const DAY = 86_400_000

type Portfolio = NonNullable<ProjectSummary['portfolio']>

const identity: Record<string, { mark: string; copy: string }> = {
  Hollawall: { mark: 'H', copy: 'Produksi & aktivasi' },
  Texturin: { mark: 'T', copy: 'Tekstur & finishing' },
}

function parseDate(value?: string | null) {
  if (!value) return null
  const date = new Date(`${value.slice(0, 10)}T00:00:00`)
  return Number.isNaN(date.getTime()) ? null : date
}

function monthStart(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function previousMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth() - 1, 1)
}

function monthLabel(date: Date) {
  return new Intl.DateTimeFormat('id-ID', { month: 'long' }).format(date).toLocaleUpperCase('id-ID')
}

function formatShortDate(date: Date) {
  return new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short' }).format(date)
}

function shortDate(value?: string | null) {
  const date = parseDate(value)
  return date ? formatShortDate(date) : '—'
}

function snapshotLabel(date: Date) {
  return `SNAPSHOT ${new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short' }).format(date).toLocaleUpperCase('id-ID')}`
}

function ageColor(age: number) {
  const progress = Math.max(0, Math.min(1, age / 75))
  const hue = Math.round(138 * (1 - progress))
  return `hsl(${hue} 64% 40%)`
}

function candleTone(age: number) {
  return {
    '--bar-color': ageColor(age),
    '--bar-mid-color': ageColor(age / 2),
    '--bar-start-color': ageColor(0),
  } as CSSProperties
}

function calendarModel(projects: ProjectSummary[], asOfValue?: string | null) {
  const today = new Date()
  const asOf = parseDate(asOfValue) ?? new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const starts = projects.map((project) => parseDate(project.started_on)).filter((value): value is Date => Boolean(value))
  const earliest = starts.length ? new Date(Math.min(...starts.map((date) => date.getTime()))) : asOf
  const windowStart = monthStart(earliest)
  const span = Math.max(DAY, asOf.getTime() - windowStart.getTime())
  const markers: Array<{ key: string; label: string; position: number }> = [{ key: `current-${asOf.toISOString()}`, label: snapshotLabel(asOf), position: 0 }]

  for (let cursor = monthStart(asOf); cursor >= windowStart; cursor = previousMonth(cursor)) {
    markers.push({
      key: cursor.toISOString(),
      label: monthLabel(cursor),
      position: Math.min(100, ((asOf.getTime() - cursor.getTime()) / span) * 100),
    })
  }

  return {
    markers,
    height: Math.max(360, markers.length * 72),
    snapshotLabel: formatShortDate(asOf),
    positionFor(value?: string | null) {
      const date = parseDate(value) ?? asOf
      const position = ((asOf.getTime() - date.getTime()) / span) * 100
      return Math.max(0, Math.min(100, position))
    },
    spanFor(startedOn?: string | null) {
      const start = parseDate(startedOn) ?? asOf
      const position = ((asOf.getTime() - start.getTime()) / span) * 100
      return `${Math.max(3, Math.min(100, position))}%`
    },
  }
}

function ActiveCalendarSection({ portfolio, projects, asOf, onOpen }: { portfolio: Portfolio; projects: ProjectSummary[]; asOf?: string | null; onOpen: (name: string) => void }) {
  const [page, setPage] = useState(0)
  const [canScrollRight, setCanScrollRight] = useState(false)
  const viewportRef = useRef<HTMLDivElement>(null)
  const drag = useRef({ active: false, moved: false, x: 0, y: 0, left: 0, top: 0 })
  const ordered = useMemo(() => [...projects].sort((left, right) => (left.age_days ?? 0) - (right.age_days ?? 0) || left.name.localeCompare(right.name, 'id-ID')), [projects])
  const pageCount = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE))
  const visible = ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const calendar = calendarModel(visible, asOf)
  const oldestAge = Math.max(0, ...ordered.map((project) => project.age_days ?? 0))
  const unit = identity[portfolio] ?? { mark: portfolio.charAt(0), copy: 'Unit usaha' }

  const syncPanCue = () => {
    const viewport = viewportRef.current
    if (!viewport) return
    setCanScrollRight(viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 12)
  }

  useEffect(() => setPage(0), [portfolio, projects, asOf])
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1) }, [page, pageCount])
  useEffect(() => {
    if (!viewportRef.current) return
    viewportRef.current.scrollLeft = 0
    viewportRef.current.scrollTop = 0
    const frame = requestAnimationFrame(syncPanCue)
    return () => cancelAnimationFrame(frame)
  }, [page, visible.length])

  const startPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse' || event.button !== 0 || !viewportRef.current) return
    if ((event.target as HTMLElement).closest('button, a, input, select, textarea')) return
    drag.current = { active: true, moved: false, x: event.clientX, y: event.clientY, left: viewportRef.current.scrollLeft, top: viewportRef.current.scrollTop }
    viewportRef.current.setPointerCapture(event.pointerId)
    viewportRef.current.classList.add('is-panning')
  }
  const movePan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current.active || !viewportRef.current) return
    const dx = event.clientX - drag.current.x
    const dy = event.clientY - drag.current.y
    if (Math.abs(dx) + Math.abs(dy) > 5) drag.current.moved = true
    viewportRef.current.scrollLeft = drag.current.left - dx
    viewportRef.current.scrollTop = drag.current.top - dy
  }
  const stopPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current.active || !viewportRef.current) return
    drag.current.active = false
    if (viewportRef.current.hasPointerCapture(event.pointerId)) viewportRef.current.releasePointerCapture(event.pointerId)
    viewportRef.current.classList.remove('is-panning')
  }

  return <section className={`active-age-section portfolio-${portfolio.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`} aria-label={`Timeline proyek aktif ${portfolio}`}>
    <header>
      <div className="active-age-identity"><i>{unit.mark}</i><div><p>{portfolio} Section</p><h3>Project candles</h3><span>{unit.copy}</span></div></div>
      <div className="active-age-summary"><strong>{ordered.length}</strong><span>proyek aktif</span><em>Tertua {oldestAge} hari</em></div>
    </header>
    {visible.length ? <>
      <div className="active-calendar-toolbar"><span><Move size={14} /> Seret area kosong · klik candle untuk detail</span><b>Snapshot {calendar.snapshotLabel} · {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, ordered.length)} dari {ordered.length}</b></div>
      <div className={`active-calendar-frame ${canScrollRight ? 'has-more-right' : ''}`}>
        <div ref={viewportRef} className="active-calendar-viewport" onScroll={syncPanCue} onPointerDown={startPan} onPointerMove={movePan} onPointerUp={stopPan} onPointerCancel={stopPan}>
          <div className="active-calendar" style={{ '--calendar-height': `${calendar.height}px`, '--project-columns': visible.length } as CSSProperties}>
          <div className="active-calendar-project-heads">
            {visible.map((project) => <span key={project.name}><strong>{project.name}</strong><small>{project.age_days ?? 0} hari</small></span>)}
          </div>
          <div className="active-calendar-axis" aria-hidden="true">
            {calendar.markers.map((marker) => <span key={marker.key} style={{ '--month-position': `${marker.position}%` } as CSSProperties}><b>{marker.label}</b><i /></span>)}
          </div>
          <div className="active-calendar-bars">
            {visible.map((project) => {
              const age = project.age_days ?? 0
              const activityStart = calendar.positionFor(project.last_activity_on)
              const activityEnd = calendar.positionFor(project.first_activity_on)
              const activityStyle = {
                '--activity-top': `${Math.min(activityStart, activityEnd)}%`,
                '--activity-span': `${Math.max(2, Math.abs(activityEnd - activityStart))}%`,
              } as CSSProperties
              return <button type="button" key={project.name} data-project-candle={project.name} className="active-calendar-bar" style={{ '--project-calendar-span': calendar.spanFor(project.started_on), ...candleTone(age) } as CSSProperties} onPointerDown={() => { drag.current.moved = false }} onClick={() => { if (!drag.current.moved) onOpen(project.name) }} aria-label={`Buka detail proyek ${project.name}, mulai ${shortDate(project.started_on)}, umur ${age} hari`} title={`Klik untuk buka ${project.name} · mulai ${shortDate(project.started_on)} · umur ${age} hari`}>
                {(project.first_activity_on || project.last_activity_on) && <span className="active-calendar-activity" style={activityStyle} title={`Rentang transaksi: pertama ${shortDate(project.first_activity_on)}, terakhir ${shortDate(project.last_activity_on)}`} />}
                <span className="active-calendar-fill">
                  <small>{age} hari</small>
                  <strong>{project.name}</strong>
                </span>
                <span className="active-calendar-start"><i /><small>Mulai {shortDate(project.started_on)}</small></span>
              </button>
            })}
          </div>
          </div>
        </div>
        {canScrollRight && <button type="button" className="active-calendar-pan-cue" aria-label={`Geser chart ${portfolio} ke kanan`} onClick={() => {
          if (!viewportRef.current) return
          viewportRef.current.scrollLeft += Math.max(220, viewportRef.current.clientWidth * .72)
          requestAnimationFrame(syncPanCue)
        }}><ArrowRight size={18} /></button>}
      </div>
      <footer>
        <div className="candle-legend" aria-label="Keterangan project candle">
          <div><span className="age-gradient" aria-hidden="true" /><p><strong>Warna umur bergerak bertahap</strong><small>Hijau: baru · kuning/oranye: menua · merah: 75+ hari</small></p></div>
          <div><span className="activity-key" aria-hidden="true" /><p><strong>Garis putih = rentang transaksi</strong><small>Titik bawah: transaksi pertama · titik atas: transaksi terakhir</small></p></div>
        </div>
        {pageCount > 1 && <nav aria-label={`Pagination chart ${portfolio}`}><button type="button" onClick={() => setPage((value) => Math.max(0, value - 1))} disabled={page === 0} aria-label={`Halaman sebelumnya ${portfolio}`}><ArrowLeft size={15} /></button><span>{page + 1} / {pageCount}</span><button type="button" onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))} disabled={page === pageCount - 1} aria-label={`Halaman berikutnya ${portfolio}`}><ArrowRight size={15} /></button></nav>}
      </footer>
    </> : <p className="active-age-empty">Tidak ada proyek aktif pada unit ini.</p>}
  </section>
}

export default function ActiveProjectAgeChart({ projects, portfolios, query, asOf, onOpen }: { projects: ProjectSummary[]; portfolios: Portfolio[]; query: string; asOf?: string | null; onOpen: (name: string) => void }) {
  const normalizedQuery = query.trim().toLocaleLowerCase('id-ID')
  const chartProjects = projects.filter((project) => project.lifecycle_status === 'active'
    && project.started_on
    && project.age_days !== null
    && project.age_days !== undefined
    && (!normalizedQuery || project.name.toLocaleLowerCase('id-ID').includes(normalizedQuery)))
  const sections = portfolios
    .map((portfolio) => ({ portfolio, projects: chartProjects.filter((project) => project.portfolio === portfolio) }))
    .filter((section) => section.projects.length)

  return <section className="active-project-age-report" aria-label="Timeline kalender proyek aktif">
    <header className="active-project-age-head"><div><p className="eyebrow">ACTIVE PROJECT MARKET</p><h2>Timeline kalender proyek aktif</h2><span>Setiap candle adalah proyek. Posisi bulan, tanggal mulai, panjang durasi, dan warna umur memakai data snapshot yang sama.</span></div><strong>{chartProjects.length} proyek aktif</strong></header>
    {sections.length ? <div className="active-age-sections">{sections.map((section) => <ActiveCalendarSection key={section.portfolio} {...section} asOf={asOf} onOpen={onOpen} />)}</div> : <p className="active-age-empty">Tidak ada proyek aktif untuk filter ini.</p>}
  </section>
}
