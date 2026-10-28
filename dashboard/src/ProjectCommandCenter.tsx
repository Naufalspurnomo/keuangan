import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, CircleDot, Clock3, Pencil, Plus, Search, Trash2 } from 'lucide-react'

import { COMPANIES, projectYear, type CompanyId, type FinanceProject, type FinanceWorkspace, type ProjectStatus } from './financeWorkspace'
import { dateLabel, IDR, projectStatusLabel, projectView } from './financeView'
import ProjectLifecycleMarketChart from './ProjectLifecycleMarketChart'

const PAGE_SIZE = 12
const statusOrder: ProjectStatus[] = ['active', 'planned', 'completed']

export function projectSnapshotYear(workspace: FinanceWorkspace) {
  return Number(workspace.updated_at.slice(0, 4)) || new Date().getFullYear()
}

export function projectSnapshotDate(workspace: FinanceWorkspace) {
  const [year, month, day] = workspace.updated_at.slice(0, 10).split('-').map(Number)
  return new Date(year, month - 1, day)
}

export function projectYearOptions(workspace: FinanceWorkspace) {
  const snapshotYear = projectSnapshotYear(workspace)
  const years = new Set([snapshotYear])
  for (const project of workspace.projects) {
    const start = projectYear(project)
    const end = project.completed_on
      ? Number(project.completed_on.slice(0, 4))
      : project.status === 'planned' ? start : snapshotYear
    for (let year = start; year <= Math.max(start, end); year += 1) years.add(year)
  }
  return [...years].sort((a, b) => a - b)
}

export function projectOverlapsYear(project: FinanceProject, year: number, snapshotDate: string) {
  const yearStart = `${year}-01-01`
  const yearEnd = `${year}-12-31`
  const projectEnd = project.completed_on ?? (project.status === 'planned' ? project.started_on : snapshotDate)
  return project.started_on <= yearEnd && projectEnd >= yearStart
}

export function projectAsOf(year: number, now = new Date()) {
  const yearEnd = new Date(`${year}-12-31T23:59:59`)
  return new Date(Math.min(now.getTime(), yearEnd.getTime()))
}

export default function ProjectCommandCenter({ workspace, onAdd, onEdit, onDelete, onOpen }: {
  workspace: FinanceWorkspace
  onAdd: () => void
  onEdit: (project: FinanceProject) => void
  onDelete: (project: FinanceProject) => void
  onOpen: (project: FinanceProject) => void
}) {
  const snapshotYear = projectSnapshotYear(workspace)
  const years = useMemo(() => projectYearOptions(workspace), [workspace])
  const [year, setYear] = useState(snapshotYear)
  const [company, setCompany] = useState<'all' | CompanyId>('all')
  const [status, setStatus] = useState<'all' | ProjectStatus>('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const yearNavRef = useRef<HTMLElement>(null)
  const activeYearRef = useRef<HTMLButtonElement>(null)
  const snapshotDate = workspace.updated_at.slice(0, 10)
  const allYear = workspace.projects.filter((project) => projectOverlapsYear(project, year, snapshotDate))
  const filtered = allYear.filter((project) => (company === 'all' || project.company === company)
    && (status === 'all' || project.status === status)
    && (!query.trim() || `${project.name} ${project.client}`.toLocaleLowerCase('id-ID').includes(query.trim().toLocaleLowerCase('id-ID'))))
    .sort((left, right) => statusOrder.indexOf(left.status) - statusOrder.indexOf(right.status) || right.updated_at.localeCompare(left.updated_at) || left.name.localeCompare(right.name, 'id-ID'))
  const yearCompleted = allYear.filter((project) => project.status === 'completed').length
  const completed = filtered.filter((project) => project.status === 'completed').length
  const active = filtered.filter((project) => project.status === 'active').length
  const planned = filtered.filter((project) => project.status === 'planned').length
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1) }, [page, pageCount])
  useEffect(() => { if (!years.includes(year)) setYear(snapshotYear) }, [snapshotYear, year, years])
  useEffect(() => {
    const nav = yearNavRef.current
    const reveal = () => activeYearRef.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
    reveal()
    if (!nav || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(reveal)
    observer.observe(nav)
    return () => observer.disconnect()
  }, [year, years])
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const yearIndex = years.indexOf(year)
  const changeYear = (next: number) => { setYear(next); setPage(0) }
  const asOf = projectAsOf(year, projectSnapshotDate(workspace))

  return <section className="project-command-center">
    <header className="command-head"><div><p className="eyebrow">PROYEK · DATA DEMO</p><h1>Portofolio proyek per tahun</h1><p>Bandingkan proyek selesai, aktif, dan direncanakan dari satu sumber data.</p></div></header>

    <section className="year-command" aria-label="Pilih tahun proyek">
      <button type="button" aria-label="Tahun sebelumnya" title={yearIndex <= 0 ? 'Tidak ada tahun sebelumnya' : undefined} disabled={yearIndex <= 0} onClick={() => changeYear(years[yearIndex - 1])}><ArrowLeft size={19} /></button>
      <div><small>TAHUN PROYEK</small><strong>{year}</strong><span><b>{yearCompleted}</b>/{allYear.length} selesai</span></div>
      <button type="button" aria-label="Tahun berikutnya" title={yearIndex >= years.length - 1 ? 'Tahun terbaru yang tersedia' : undefined} disabled={yearIndex < 0 || yearIndex >= years.length - 1} onClick={() => changeYear(years[yearIndex + 1])}><ArrowRight size={19} /></button>
      <nav ref={yearNavRef} aria-label="Daftar tahun">{years.map((item) => {
        const projects = workspace.projects.filter((project) => projectOverlapsYear(project, item, snapshotDate))
        const done = projects.filter((project) => project.status === 'completed').length
        return <button ref={item === year ? activeYearRef : undefined} type="button" className={item === year ? 'active' : ''} aria-current={item === year ? 'page' : undefined} aria-label={`${item}, ${done} selesai dari ${projects.length} proyek`} key={item} onClick={() => changeYear(item)}><strong>{item}</strong><span>{done} selesai / {projects.length} total</span></button>
      })}</nav>
    </section>

    <div className="project-year-stats" aria-label={`Status proyek tahun ${year}`}>
      <article className="done"><CheckCircle2 /><span><small>Selesai</small><strong>{completed}</strong></span></article>
      <article className="active"><CircleDot /><span><small>Aktif</small><strong>{active}</strong></span></article>
      <article className="planned"><Clock3 /><span><small>Direncanakan</small><strong>{planned}</strong></span></article>
      <article className="ratio"><span><small>Hasil filter · {completed}/{filtered.length}</small><strong>{filtered.length ? Math.round((completed / filtered.length) * 100) : 0}%</strong></span><i><b style={{ width: `${filtered.length ? (completed / filtered.length) * 100 : 0}%` }} /></i></article>
    </div>

    <div className="project-controls"><label className="command-search"><Search size={17} /><span className="sr-only">Cari proyek</span><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0) }} placeholder="Cari proyek atau klien" /></label><label><span className="sr-only">Perusahaan</span><select value={company} onChange={(event) => { setCompany(event.target.value as 'all' | CompanyId); setPage(0) }}><option value="all">Semua perusahaan</option>{COMPANIES.map((item) => <option key={item}>{item}</option>)}</select></label><label><span className="sr-only">Status</span><select value={status} onChange={(event) => { setStatus(event.target.value as 'all' | ProjectStatus); setPage(0) }}><option value="all">Semua status</option>{statusOrder.map((item) => <option key={item} value={item}>{projectStatusLabel(item)}</option>)}</select></label><span><strong>{filtered.length}</strong> proyek</span></div>

    <p className="project-status-note"><strong>Lingkup {year}.</strong> Selesai: pekerjaan ditutup. Aktif: sedang berjalan. Direncanakan: belum dimulai.</p>

    <ProjectLifecycleMarketChart projects={allYear} transactions={workspace.transactions} year={year} asOf={asOf} onOpen={onOpen} />

    {filtered.length ? <section className="project-register"><header><div><p className="eyebrow">DAFTAR PROYEK</p><h3>Rincian {year}</h3></div></header><div className="project-register-headings" aria-hidden="true"><span>Proyek</span><span>Status</span><span>Periode</span><span>Arus kas</span><span>Aksi</span></div>{visible.map((project) => {
        const view = projectView(project, workspace)
        return <article key={project.id}><button className="project-register-main" onClick={() => onOpen(project)}><span><strong>{project.name}</strong><small>{project.company} · {project.wallet}{project.client ? ` · ${project.client}` : ''}</small></span><b className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</b><span><small>{dateLabel(project.started_on)}</small><strong>{project.completed_on ? dateLabel(project.completed_on) : 'Belum selesai'}</strong></span><span className={view.net >= 0 ? 'positive' : 'negative'}><small>{view.transactions} transaksi</small><strong>{IDR.format(view.net)}</strong></span></button><div className="row-actions"><button aria-label={`Ubah ${project.name}`} onClick={() => onEdit(project)}><Pencil size={16} /></button><button className="danger" aria-label={`Hapus ${project.name}`} onClick={() => onDelete(project)}><Trash2 size={16} /></button></div></article>
      })}</section> : <section className="command-empty"><strong>Proyek tidak ditemukan</strong><p>Ubah filter atau tambahkan proyek untuk tahun {year}.</p><button className="primary-button" onClick={onAdd}><Plus size={16} /> Tambah proyek</button></section>}
  </section>
}
