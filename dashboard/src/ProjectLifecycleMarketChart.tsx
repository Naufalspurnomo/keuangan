import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { ChevronsRight, Minus, Move, Plus, RotateCcw } from 'lucide-react'

import { type CompanyId, type FinanceProject, type FinanceTransaction } from './financeWorkspace'
import { dateLabel, IDR, projectStatusLabel } from './financeView'

const DAY = 86_400_000
const BASE_HEIGHT = 540
const BASE_COLUMN = 76
const MIN_ZOOM = 1
const MAX_ZOOM = 2.4
const MARKET_COMPANIES: CompanyId[] = ['Holla', 'Hojja', 'Texturin Bali', 'Texturin Surabaya']

const identity: Record<CompanyId, { mark: string; copy: string }> = {
  Holla: { mark: 'H', copy: 'Produksi mural & aktivasi' },
  Hojja: { mark: 'HJ', copy: 'Produksi Hojja' },
  'Texturin Bali': { mark: 'TB', copy: 'Tekstur & finishing Bali' },
  'Texturin Surabaya': { mark: 'TS', copy: 'Tekstur & finishing Surabaya' },
}

function parseDate(value: string | null | undefined) {
  if (!value) return null
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!match) return null
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return date.getFullYear() === Number(match[1]) && date.getMonth() === Number(match[2]) - 1 && date.getDate() === Number(match[3]) ? date : null
}

function isoDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function calendarDay(date: Date) {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / DAY
}

function age(project: FinanceProject, asOf: Date) {
  const start = parseDate(project.started_on) ?? asOf
  const end = project.completed_on ? (parseDate(project.completed_on) ?? asOf) : asOf
  return Math.max(0, calendarDay(end) - calendarDay(start))
}

function ageColor(days: number) {
  const progress = Math.max(0, Math.min(1, days / 90))
  return `hsl(${Math.round(138 * (1 - progress))} 64% 39%)`
}

function candleTone(project: FinanceProject, asOf: Date) {
  if (project.status === 'completed') {
    return {
      '--bar-color': '#64748b',
      '--bar-mid-color': '#7b8a9d',
      '--bar-start-color': '#94a3b8',
    } as CSSProperties
  }
  if (project.status === 'planned') {
    return {
      '--bar-color': 'var(--chart-neutral-2)',
      '--bar-mid-color': 'var(--chart-neutral-2)',
      '--bar-start-color': 'var(--chart-neutral-2)',
    } as CSSProperties
  }
  const days = age(project, asOf)
  return {
    '--bar-color': ageColor(days),
    '--bar-mid-color': ageColor(days / 2),
    '--bar-start-color': ageColor(0),
  } as CSSProperties
}

function yearModel(year: number, asOf: Date) {
  const start = new Date(year, 0, 1)
  const end = new Date(year, 11, 31)
  const span = Math.max(1, calendarDay(end) - calendarDay(start))
  const clip = (date: Date) => new Date(Math.max(start.getTime(), Math.min(end.getTime(), date.getTime())))
  const positionFor = (value: string | null | undefined, fallback = asOf) => ((calendarDay(end) - calendarDay(clip(parseDate(value) ?? fallback))) / span) * 100
  const months = Array.from({ length: 12 }, (_, index) => {
    const date = new Date(year, index, 1)
    return {
      key: `${year}-${index}`,
      label: new Intl.DateTimeFormat('id-ID', { month: 'short' }).format(date).toLocaleUpperCase('id-ID'),
      position: positionFor(isoDate(date)),
    }
  })
  return { months, positionFor }
}

type ViewportApi = { latest: () => void; reset: () => void; zoomBy: (factor: number) => void }
type CompanyCanvasProps = {
  company: CompanyId
  projects: FinanceProject[]
  transactions: FinanceTransaction[]
  year: number
  asOf: Date
  register: (company: CompanyId, api: ViewportApi | null) => void
  onOpen: (project: FinanceProject) => void
}

type ZoomAnchor = { x: number; y: number; xRatio: number; yRatio: number }

function CompanyCanvas({ company, projects, transactions, year, asOf, register, onOpen }: CompanyCanvasProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const drag = useRef({ active: false, moved: false, pointerId: 0, x: 0, y: 0, left: 0, top: 0, pageOverflow: 0, lastX: 0, lastY: 0, lastAt: 0, velocityX: 0, velocityY: 0 })
  const momentumFrame = useRef<number | null>(null)
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinchDistance = useRef<number | null>(null)
  const [zoom, setZoom] = useState(1)
  const zoomRef = useRef(1)
  const zoomAnchor = useRef<ZoomAnchor | null>(null)
  const ordered = useMemo(() => projects
    .filter((project) => project.company === company)
    .sort((left, right) => left.started_on.localeCompare(right.started_on) || left.name.localeCompare(right.name, 'id-ID')),
  [company, projects])
  const model = yearModel(year, asOf)
  const active = ordered.filter((project) => project.status === 'active').length
  const completed = ordered.filter((project) => project.status === 'completed').length
  const planned = ordered.filter((project) => project.status === 'planned').length
  const chartWidth = Math.max(620, 104 + Math.max(ordered.length, 7) * BASE_COLUMN * zoom)
  const chartHeight = BASE_HEIGHT * zoom
  const meta = identity[company]

  const stopMomentum = () => {
    if (momentumFrame.current == null) return
    cancelAnimationFrame(momentumFrame.current)
    momentumFrame.current = null
  }
  const latest = () => {
    stopMomentum()
    const viewport = viewportRef.current
    if (viewport) viewport.scrollLeft = Math.max(0, viewport.scrollWidth - viewport.clientWidth)
  }
  const setBoundedZoom = (next: number, clientX?: number, clientY?: number) => {
    const viewport = viewportRef.current
    const bounded = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, next))
    if (Math.abs(bounded - zoomRef.current) < .001) return false
    if (viewport) {
      const rect = viewport.getBoundingClientRect()
      const x = clientX == null ? viewport.clientWidth / 2 : Math.max(0, Math.min(viewport.clientWidth, clientX - rect.left))
      const y = clientY == null ? viewport.clientHeight / 2 : Math.max(0, Math.min(viewport.clientHeight, clientY - rect.top))
      zoomAnchor.current = {
        x,
        y,
        xRatio: (viewport.scrollLeft + x) / Math.max(1, viewport.scrollWidth),
        yRatio: (viewport.scrollTop + y) / Math.max(1, viewport.scrollHeight),
      }
    }
    zoomRef.current = bounded
    setZoom(bounded)
    return true
  }
  const zoomBy = (factor: number) => { setBoundedZoom(zoomRef.current * factor) }
  const reset = () => {
    stopMomentum()
    zoomAnchor.current = null
    zoomRef.current = 1
    setZoom(1)
    const viewport = viewportRef.current
    if (viewport) viewport.scrollTop = 0
    requestAnimationFrame(latest)
  }

  useEffect(() => {
    register(company, { latest, reset, zoomBy })
    return () => {
      register(company, null)
      if (momentumFrame.current != null) cancelAnimationFrame(momentumFrame.current)
    }
  }, [company, chartWidth])
  useEffect(() => {
    const frame = requestAnimationFrame(latest)
    return () => cancelAnimationFrame(frame)
  }, [company, ordered.length])
  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const handleWheel = (event: WheelEvent) => {
      if (!event.deltaY || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
      const delta = event.deltaY * (event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? viewport.clientHeight : 1)
      if (setBoundedZoom(zoomRef.current * Math.exp(-delta * .0014), event.clientX, event.clientY)) {
        event.preventDefault()
        return
      }
      const maxTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight)
      const atBoundary = event.deltaY < 0 ? viewport.scrollTop <= 0 : viewport.scrollTop >= maxTop
      if (atBoundary) {
        event.preventDefault()
        window.scrollBy(0, delta)
      }
    }
    viewport.addEventListener('wheel', handleWheel, { passive: false })
    return () => viewport.removeEventListener('wheel', handleWheel)
  }, [])
  useLayoutEffect(() => {
    const viewport = viewportRef.current
    const anchor = zoomAnchor.current
    if (!viewport || !anchor) return
    viewport.scrollLeft = anchor.xRatio * viewport.scrollWidth - anchor.x
    viewport.scrollTop = anchor.yRatio * viewport.scrollHeight - anchor.y
    zoomAnchor.current = null
  }, [zoom])

  const startPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    stopMomentum()
    drag.current.moved = false
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (pointers.current.size === 2) {
      const [first, second] = [...pointers.current.values()]
      pinchDistance.current = Math.hypot(second.x - first.x, second.y - first.y)
      drag.current.active = false
      return
    }
    if (event.pointerType === 'mouse' && event.button !== 0) return
    const viewport = viewportRef.current
    if (!viewport) return
    drag.current = { active: true, moved: false, pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop, pageOverflow: 0, lastX: event.clientX, lastY: event.clientY, lastAt: performance.now(), velocityX: 0, velocityY: 0 }
    viewport.classList.add('is-panning')
  }
  const movePointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (pointers.current.size === 2) {
      const [first, second] = [...pointers.current.values()]
      const distance = Math.hypot(second.x - first.x, second.y - first.y)
      if (pinchDistance.current) setBoundedZoom(zoomRef.current * (distance / pinchDistance.current), (first.x + second.x) / 2, (first.y + second.y) / 2)
      pinchDistance.current = distance
      return
    }
    if (!drag.current.active || drag.current.pointerId !== event.pointerId || !viewportRef.current) return
    const dx = event.clientX - drag.current.x
    const dy = event.clientY - drag.current.y
    if (Math.abs(dx) + Math.abs(dy) > 5) {
      drag.current.moved = true
      if (!event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.setPointerCapture(event.pointerId)
    }
    const viewport = viewportRef.current
    viewport.scrollLeft = drag.current.left - dx
    const desiredTop = drag.current.top - dy
    const maxTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight)
    viewport.scrollTop = Math.max(0, Math.min(maxTop, desiredTop))
    if (event.pointerType === 'touch') {
      const overflow = desiredTop < 0 ? desiredTop : desiredTop > maxTop ? desiredTop - maxTop : 0
      const pageDelta = overflow - drag.current.pageOverflow
      if (pageDelta) window.scrollBy(0, pageDelta)
      drag.current.pageOverflow = overflow
    }
    const now = performance.now()
    const elapsed = Math.max(8, now - drag.current.lastAt)
    const sampleX = (drag.current.lastX - event.clientX) / elapsed
    const sampleY = (drag.current.lastY - event.clientY) / elapsed
    drag.current.velocityX = drag.current.velocityX * .55 + sampleX * .45
    drag.current.velocityY = drag.current.velocityY * .55 + sampleY * .45
    drag.current.lastX = event.clientX
    drag.current.lastY = event.clientY
    drag.current.lastAt = now
  }
  const stopPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.delete(event.pointerId)
    pinchDistance.current = null
    if (drag.current.pointerId === event.pointerId) drag.current.active = false
    viewportRef.current?.classList.remove('is-panning')
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    const viewport = viewportRef.current
    if (!viewport || !drag.current.moved || pointers.current.size) return
    let velocityX = Math.max(-2.2, Math.min(2.2, drag.current.velocityX))
    let velocityY = Math.max(-2.2, Math.min(2.2, drag.current.velocityY))
    let lastAt = performance.now()
    const glide = (now: number) => {
      const elapsed = Math.min(32, now - lastAt)
      lastAt = now
      const beforeLeft = viewport.scrollLeft
      const beforeTop = viewport.scrollTop
      viewport.scrollLeft += velocityX * elapsed
      viewport.scrollTop += velocityY * elapsed
      const hitX = Math.abs(viewport.scrollLeft - beforeLeft) < .1 && Math.abs(velocityX) > .03
      const hitY = Math.abs(viewport.scrollTop - beforeTop) < .1 && Math.abs(velocityY) > .03
      velocityX = hitX ? 0 : velocityX * Math.pow(.91, elapsed / 16)
      velocityY = hitY ? 0 : velocityY * Math.pow(.91, elapsed / 16)
      if (Math.hypot(velocityX, velocityY) < .025) {
        momentumFrame.current = null
        return
      }
      momentumFrame.current = requestAnimationFrame(glide)
    }
    if (Math.hypot(velocityX, velocityY) >= .08) momentumFrame.current = requestAnimationFrame(glide)
  }

  return <section className={`project-market-canvas company-${company.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`} data-project-company={company} role="region" aria-label={`Chart lifecycle ${company}`}>
    <header>
      <div className="project-market-identity"><i>{meta.mark}</i><div><p>{company}</p><h3>Project lifecycle</h3><span>{meta.copy}</span></div></div>
      <div className="project-market-summary" aria-label={`Ringkasan ${company}`}><strong>{active} / {ordered.length}</strong><span>aktif / total {year}</span><em>{completed} selesai{planned ? ` · ${planned} rencana` : ''}</em></div>
    </header>
    <div className="project-market-toolbar"><span><Move size={13} /> Seret bebas · zoom {Math.round(zoom * 100)}%</span><button type="button" onClick={latest} aria-label={`Kembali ke proyek terbaru ${company}`}><ChevronsRight size={15} /> Terbaru</button></div>
    <div ref={viewportRef} className="project-market-viewport" onPointerDown={startPointer} onPointerMove={movePointer} onPointerUp={stopPointer} onPointerCancel={stopPointer}>
      <div className="project-market-chart" style={{ '--market-width': `${chartWidth}px`, '--market-height': `${chartHeight}px`, '--market-column': `${BASE_COLUMN * zoom}px` } as CSSProperties}>
        <div className="project-market-axis" aria-hidden="true">
          {model.months.map((month) => <span className="project-market-month" key={month.key} style={{ '--month-position': `${month.position}%` } as CSSProperties}><b>{month.label}</b><i /></span>)}
          {asOf.getFullYear() === year && <span className="project-market-snapshot" style={{ '--month-position': `${model.positionFor(isoDate(asOf))}%` } as CSSProperties}><b>SNAPSHOT {dateLabel(isoDate(asOf))}</b><i /></span>}
        </div>
        <div className="project-market-columns" style={{ '--project-columns': Math.max(ordered.length, 1) } as CSSProperties}>
          {ordered.map((project) => {
            const rows = transactions.filter((row) => row.project_id === project.id).sort((left, right) => left.date.localeCompare(right.date))
            const firstActivity = rows.at(0)?.date
            const lastActivity = rows.at(-1)?.date
            const end = project.status === 'completed' ? (parseDate(project.completed_on) ?? asOf) : project.status === 'planned' ? (parseDate(project.started_on) ?? asOf) : asOf
            const startPosition = model.positionFor(project.started_on)
            const endPosition = model.positionFor(isoDate(end))
            const candleTop = Math.min(startPosition, endPosition)
            const candleSpan = project.status === 'planned' ? 2.8 : Math.max(2.8, Math.abs(startPosition - endPosition))
            const activityStart = model.positionFor(firstActivity, parseDate(project.started_on) ?? asOf)
            const activityEnd = model.positionFor(lastActivity, end)
            const activityTop = Math.min(activityStart, activityEnd)
            const activitySpan = Math.max(1.4, Math.abs(activityStart - activityEnd))
            const days = age(project, asOf)
            const income = rows.filter((row) => row.direction === 'income').reduce((sum, row) => sum + row.amount, 0)
            const expense = rows.filter((row) => row.direction === 'expense').reduce((sum, row) => sum + row.amount, 0)
            const accessible = `${company}, ${projectStatusLabel(project.status)}, mulai ${dateLabel(project.started_on)}, ${project.status === 'completed' ? `selesai ${dateLabel(project.completed_on!)}` : project.status === 'planned' ? 'belum berjalan' : `snapshot ${dateLabel(isoDate(asOf))}`}, umur ${days} hari, transaksi pertama ${firstActivity ? dateLabel(firstActivity) : 'belum ada'}, transaksi terakhir ${lastActivity ? dateLabel(lastActivity) : 'belum ada'}, ${rows.length} transaksi, arus kas ${IDR.format(income - expense)}`
            return <button
              type="button"
              key={project.id}
              data-project-id={project.id}
              data-project-candle={project.name}
              className={`project-market-candle is-${project.status}`}
              style={{ '--candle-top': `${candleTop}%`, '--candle-span': `${candleSpan}%`, '--activity-top': `${activityTop}%`, '--activity-span': `${activitySpan}%`, ...candleTone(project, asOf) } as CSSProperties}
              onPointerDown={() => { drag.current.moved = false }}
              onClick={(event) => { if (event.detail === 0 || !drag.current.moved) onOpen(project); drag.current.moved = false }}
              aria-label={`Buka ${project.name}, ${accessible}`}
              title={`${project.name} · ${accessible}`}
            >
              {firstActivity && lastActivity && <span className="project-market-wick" aria-hidden="true" />}
              <span className="project-market-body"><small>{project.status === 'planned' ? 'Rencana' : `${days} hari`}</small><strong>{project.name}</strong></span>
              <span className="project-market-start" aria-hidden="true"><i /><small>{dateLabel(project.started_on)}</small></span>
            </button>
          })}
          {!ordered.length && <div className="project-market-empty"><strong>Belum ada proyek {year}</strong><span>Canvas tetap siap menerima data {company}.</span></div>}
        </div>
      </div>
    </div>
  </section>
}

export default function ProjectLifecycleMarketChart({ projects, transactions, year, asOf, onOpen }: { projects: FinanceProject[]; transactions: FinanceTransaction[]; year: number; asOf: Date; onOpen: (project: FinanceProject) => void }) {
  const api = useRef(new Map<CompanyId, ViewportApi>())
  const register = (company: CompanyId, value: ViewportApi | null) => { if (value) api.current.set(company, value); else api.current.delete(company) }
  const zoomAll = (factor: number) => api.current.forEach((value) => value.zoomBy(factor))
  const resetAll = () => api.current.forEach((value) => value.reset())
  const latestAll = () => api.current.forEach((value) => value.latest())
  const active = projects.filter((project) => project.status === 'active').length

  return <section className="project-market-report" aria-label={`Project lifecycle market ${year}`}>
    <header className="project-market-report-head"><div><p className="eyebrow">PROJECT LIFECYCLE MARKET · {year}</p><h3>Umur dan status proyek</h3><p>Empat canvas tahunan. Proyek terbaru berada di kanan; geser bebas, zoom, dan klik candle untuk melihat transaksi.</p></div><strong>{active} / {projects.length} aktif</strong></header>
    <div className="project-market-global-toolbar" role="group" aria-label="Kontrol zoom semua chart">
      <span>Kontrol semua chart</span>
      <button type="button" onClick={() => zoomAll(1 / 1.2)} aria-label="Perkecil semua chart"><Minus size={16} /></button>
      <button type="button" onClick={() => zoomAll(1.2)} aria-label="Perbesar semua chart"><Plus size={16} /></button>
      <button type="button" onClick={resetAll} aria-label="Reset tampilan semua chart"><RotateCcw size={15} /> Reset</button>
      <button type="button" onClick={latestAll} aria-label="Kembali ke proyek terbaru semua chart"><ChevronsRight size={15} /> Terbaru</button>
    </div>
    <div className="project-market-grid">{MARKET_COMPANIES.map((company) => <CompanyCanvas key={company} company={company} projects={projects} transactions={transactions} year={year} asOf={asOf} register={register} onOpen={onOpen} />)}</div>
    <footer className="project-market-legend" aria-label="Keterangan project lifecycle">
      <div><span className="age-gradient" aria-hidden="true" /><p><strong>Aktif: warna mengikuti umur</strong><small>Hijau baru · kuning/oranye menua · merah 90+ hari</small></p></div>
      <div><span className="completed-key" aria-hidden="true" /><p><strong>Selesai</strong><small>Candle abu berhenti pada tanggal selesai</small></p></div>
      <div><span className="planned-key" aria-hidden="true" /><p><strong>Direncanakan</strong><small>Marker putus-putus pada tanggal mulai</small></p></div>
      <div><span className="activity-key" aria-hidden="true" /><p><strong>Garis putih = rentang transaksi</strong><small>Transaksi pertama sampai transaksi terakhir</small></p></div>
    </footer>
  </section>
}
