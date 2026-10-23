import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { ArrowLeft, ArrowRight } from 'lucide-react'

import type { ProjectSummary } from './snapshot'

const PAGE_SIZE = 8

type Portfolio = NonNullable<ProjectSummary['portfolio']>

const identity: Record<string, { mark: string; copy: string }> = {
  Hollawall: { mark: 'H', copy: 'Produksi & aktivasi' },
  Texturin: { mark: 'T', copy: 'Tekstur & finishing' },
}

function ageBand(age: number) {
  if (age <= 7) return 'new'
  if (age <= 14) return 'growing'
  if (age < 30) return 'watch'
  return 'overdue'
}

function scalePosition(age: number, maxAge: number) {
  return 8 + (Math.min(age, maxAge) / maxAge) * 92
}

function barStyle(age: number, maxAge: number): CSSProperties {
  const position = `${scalePosition(age, maxAge)}%`
  return { '--project-age-height': position, '--project-age-width': position } as CSSProperties
}

function ActiveAgeSection({ portfolio, projects, onOpen }: { portfolio: Portfolio; projects: ProjectSummary[]; onOpen: (name: string) => void }) {
  const [page, setPage] = useState(0)
  const ordered = useMemo(() => [...projects].sort((left, right) => (left.age_days ?? 0) - (right.age_days ?? 0) || left.name.localeCompare(right.name, 'id-ID')), [projects])
  const pageCount = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE))
  const visible = ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const oldestAge = Math.max(0, ...ordered.map((project) => project.age_days ?? 0))
  const maxAge = Math.max(30, ...visible.map((project) => project.age_days ?? 0))
  const unit = identity[portfolio] ?? { mark: portfolio.charAt(0), copy: 'Unit usaha' }

  useEffect(() => setPage(0), [portfolio, projects])
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1) }, [page, pageCount])

  return <section className={`active-age-section portfolio-${portfolio.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`} aria-label={`Umur proyek aktif ${portfolio}`}>
    <header>
      <div className="active-age-identity"><i>{unit.mark}</i><div><p>{portfolio} Section</p><h3>Proyek aktif</h3><span>{unit.copy}</span></div></div>
      <div className="active-age-summary"><strong>{ordered.length}</strong><span>proyek aktif</span><em>Tertua {oldestAge} hari</em></div>
    </header>
    {visible.length ? <>
      <div className="active-age-chart-scroll">
        <div className="active-age-chart" style={{ '--age-columns': visible.length, '--threshold-30': `${scalePosition(30, maxAge)}%`, '--threshold-15': `${scalePosition(15, maxAge)}%`, '--threshold-8': `${scalePosition(8, maxAge)}%` } as CSSProperties}>
          <div className="active-age-axis" aria-hidden="true">
            {maxAge > 30 && <span className="threshold-max"><b>{maxAge}</b><i /></span>}
            <span className="threshold-30"><b>30+</b><i /></span>
            <span className="threshold-15"><b>15</b><i /></span>
            <span className="threshold-8"><b>8</b><i /></span>
            <span className="threshold-0"><b>0</b><i /></span>
          </div>
          <div className="active-age-bars">
            {visible.map((project) => {
              const age = project.age_days ?? 0
              return <button type="button" key={project.name} className={`active-age-bar age-${ageBand(age)}`} onClick={() => onOpen(project.name)} aria-label={`Buka proyek ${project.name}, aktif ${age} hari`}>
                <span className="active-age-bar-fill" style={barStyle(age, maxAge)}>
                  <small>{age} hari</small>
                  <strong>{project.name}</strong>
                </span>
                <span className="active-age-mobile-copy"><strong>{project.name}</strong><small>{age} hari</small></span>
              </button>
            })}
          </div>
        </div>
      </div>
      <footer>
        <p><b>Biru</b> 0–7 · <b>Hijau</b> 8–14 · <b>Kuning</b> 15–29 · <b>Merah</b> 30+ hari · Skala halaman 0–{maxAge}</p>
        {pageCount > 1 && <nav aria-label={`Pagination chart ${portfolio}`}><button type="button" onClick={() => setPage((value) => Math.max(0, value - 1))} disabled={page === 0} aria-label={`Halaman sebelumnya ${portfolio}`}><ArrowLeft size={15} /></button><span>{page + 1} / {pageCount}</span><button type="button" onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))} disabled={page === pageCount - 1} aria-label={`Halaman berikutnya ${portfolio}`}><ArrowRight size={15} /></button></nav>}
      </footer>
    </> : <p className="active-age-empty">Tidak ada proyek aktif pada unit ini.</p>}
  </section>
}

export default function ActiveProjectAgeChart({ projects, portfolios, query, onOpen }: { projects: ProjectSummary[]; portfolios: Portfolio[]; query: string; onOpen: (name: string) => void }) {
  const normalizedQuery = query.trim().toLocaleLowerCase('id-ID')
  const chartProjects = projects.filter((project) => project.lifecycle_status === 'active'
    && project.started_on
    && project.age_days !== null
    && project.age_days !== undefined
    && (!normalizedQuery || project.name.toLocaleLowerCase('id-ID').includes(normalizedQuery)))
  const sections = portfolios
    .map((portfolio) => ({ portfolio, projects: chartProjects.filter((project) => project.portfolio === portfolio) }))
    .filter((section) => section.projects.length)

  return <section className="active-project-age-report" aria-label="Chart umur proyek aktif">
    <header className="active-project-age-head"><div><p className="eyebrow">PROYEK AKTIF SAJA</p><h2>Durasi proyek berjalan</h2><span>Proyek selesai otomatis keluar dari chart. Panjang batang menunjukkan umur sejak tanggal mulai.</span></div><strong>{chartProjects.length} proyek aktif</strong></header>
    {sections.length ? <div className="active-age-sections">{sections.map((section) => <ActiveAgeSection key={section.portfolio} {...section} onOpen={onOpen} />)}</div> : <p className="active-age-empty">Tidak ada proyek aktif untuk filter ini.</p>}
  </section>
}
