import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { COMPANIES, projectYear, type CompanyId, type FinanceProject, type FinanceWorkspace, type ProjectStatus } from './financeWorkspace'
import { dateLabel, IDR, projectStatusLabel, projectView } from './financeView'
import ProjectLifecycleMarketChart from './ProjectLifecycleMarketChart'
import { visibleProjectStatus } from './projectStatus'

const PAGE_SIZE = 12
const PROJECT_VIEW_KEY = 'hollawall-project-view-v1'
const statusOrder: ProjectStatus[] = ['active', 'completed', 'cancelled']

type StoredProjectView = { year?: number; company?: 'all' | CompanyId; status?: 'all' | ProjectStatus; query?: string; page?: number }

function storedProjectView(): StoredProjectView {
  try { return JSON.parse(sessionStorage.getItem(PROJECT_VIEW_KEY) ?? '{}') as StoredProjectView } catch { return {} }
}

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
    const status = visibleProjectStatus(project.status)
    const end = project.completed_on
      ? Number(project.completed_on.slice(0, 4))
      : status === 'cancelled' ? start : snapshotYear
    for (let year = start; year <= Math.max(start, end); year += 1) years.add(year)
  }
  return [...years].sort((a, b) => a - b)
}

export function projectOverlapsYear(project: FinanceProject, year: number, snapshotDate: string) {
  const yearStart = `${year}-01-01`
  const yearEnd = `${year}-12-31`
  const projectEnd = project.completed_on ?? (visibleProjectStatus(project.status) === 'cancelled' ? project.started_on : snapshotDate)
  return project.started_on <= yearEnd && projectEnd >= yearStart
}

export function projectAsOf(year: number, now = new Date()) {
  const yearEnd = new Date(`${year}-12-31T23:59:59`)
  return new Date(Math.min(now.getTime(), yearEnd.getTime()))
}

export default function ProjectCommandCenter({ workspace, onAdd, onEdit, onComplete, onQuickComplete, onDelete, onOpen, readOnly = false, canAdd = !readOnly, destructiveActionLabel = 'Hapus', busy = false, headerAction }: {
  workspace: FinanceWorkspace
  onAdd: () => void
  onEdit: (project: FinanceProject) => void
  onComplete: (project: FinanceProject) => void
  onQuickComplete: (project: FinanceProject) => void
  onDelete: (project: FinanceProject) => void
  onOpen: (project: FinanceProject) => void
  readOnly?: boolean
  canAdd?: boolean
  destructiveActionLabel?: string
  busy?: boolean
  headerAction?: ReactNode
}) {
  const snapshotYear = projectSnapshotYear(workspace)
  const projects = useMemo(() => workspace.projects.map((project) => {
    const status = visibleProjectStatus(project.status)
    return status === project.status ? project : { ...project, status }
  }), [workspace.projects])
  const years = useMemo(() => projectYearOptions(workspace), [workspace])
  const initialView = useRef(storedProjectView()).current
  const [year, setYear] = useState(() => initialView.year && years.includes(initialView.year) ? initialView.year : snapshotYear)
  const [company, setCompany] = useState<'all' | CompanyId>(() => initialView.company && ['all', ...COMPANIES].includes(initialView.company) ? initialView.company : 'all')
  const [status, setStatus] = useState<'all' | ProjectStatus>(() => initialView.status && ['all', ...statusOrder].includes(initialView.status) ? initialView.status : 'all')
  const [query, setQuery] = useState(() => typeof initialView.query === 'string' ? initialView.query : '')
  const [page, setPage] = useState(() => Number.isInteger(initialView.page) && (initialView.page ?? 0) >= 0 ? initialView.page! : 0)
  const snapshotDate = workspace.updated_at.slice(0, 10)
  const allYear = projects.filter((project) => projectOverlapsYear(project, year, snapshotDate))
  const filtered = allYear.filter((project) => (company === 'all' || project.company === company)
    && (status === 'all' || project.status === status)
    && (!query.trim() || `${project.name} ${project.client}`.toLocaleLowerCase('id-ID').includes(query.trim().toLocaleLowerCase('id-ID'))))
    .sort((left, right) => statusOrder.indexOf(left.status) - statusOrder.indexOf(right.status) || right.updated_at.localeCompare(left.updated_at) || left.name.localeCompare(right.name, 'id-ID'))
  const completed = filtered.filter((project) => project.status === 'completed').length
  const active = filtered.filter((project) => project.status === 'active').length
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1) }, [page, pageCount])
  useEffect(() => { if (!years.includes(year)) setYear(snapshotYear) }, [snapshotYear, year, years])
  useEffect(() => { sessionStorage.setItem(PROJECT_VIEW_KEY, JSON.stringify({ year, company, status, query, page })) }, [year, company, status, query, page])
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const changeYear = (next: number) => { setYear(next); setPage(0) }
  const asOf = projectAsOf(year, projectSnapshotDate(workspace))

  return <section className="project-command-center" aria-busy={busy}>
    <header className="command-head project-command-heading"><div><h1>Project</h1></div><div className="project-header-actions">{headerAction}{canAdd && <button type="button" className="primary-button" disabled={busy} onClick={onAdd}>Buat Project</button>}</div></header>

    <div className="project-year-selector"><label><span>Project per tahun</span><select value={year} onChange={(event) => changeYear(Number(event.target.value))} aria-label="Project per tahun">{years.map((item) => <option value={item} key={item}>{item}</option>)}</select></label><span aria-live="polite">{filtered.length} Project · {completed} selesai</span></div>

    <div className="project-year-stats" aria-label={`Status Project tahun ${year}`}>
      <article className="done"><span><small>Selesai</small><strong>{completed}</strong></span></article>
      <article className="active"><span><small>Aktif</small><strong>{active}</strong></span></article>
      <article className="ratio"><span><small>Hasil filter · {completed}/{filtered.length}</small><strong>{filtered.length ? Math.round((completed / filtered.length) * 100) : 0}%</strong></span><i><b style={{ width: `${filtered.length ? (completed / filtered.length) * 100 : 0}%` }} /></i></article>
    </div>

    <ProjectLifecycleMarketChart projects={allYear} transactions={workspace.transactions} year={year} asOf={asOf} onOpen={onOpen} onQuickComplete={(project) => { if (!busy) onQuickComplete(project) }} />
    {busy && <p role="status" className="project-status-note"><strong>Menyelesaikan Project…</strong> Status sedang dikonfirmasi ke server.</p>}

    <section className="project-controls" aria-label="Filter daftar Project"><label className="command-search"><span className="sr-only">Cari Project</span><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0) }} placeholder="Cari Project atau klien" /></label><label><span className="sr-only">Perusahaan</span><select value={company} onChange={(event) => { setCompany(event.target.value as 'all' | CompanyId); setPage(0) }}><option value="all">Semua perusahaan</option>{COMPANIES.map((item) => <option key={item}>{item}</option>)}</select></label><label><span className="sr-only">Status</span><select value={status} onChange={(event) => { setStatus(event.target.value as 'all' | ProjectStatus); setPage(0) }}><option value="all">Semua status</option>{statusOrder.map((item) => <option key={item} value={item}>{projectStatusLabel(item)}</option>)}</select></label><span aria-live="polite"><strong>{filtered.length}</strong> Project</span></section>

    {filtered.length ? <section className="project-register" aria-label={`Daftar Project ${year}`}><header><div><p className="eyebrow">DAFTAR Project</p><h3>Rincian {year}</h3></div></header><div className="project-register-headings" aria-hidden="true"><span>Project</span><span>Status</span><span>Periode</span><span>Arus kas</span><span>Aksi</span></div>{visible.map((project) => {
        const view = projectView(project, workspace)
        return <article key={project.id}><button type="button" className="project-register-main" aria-label={`Buka Project ${project.name}`} onClick={() => onOpen(project)}><span><strong>{project.name}</strong><small>{project.company} · {project.wallet}{project.client ? ` · ${project.client}` : ''}</small></span><b className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</b><span><small>Mulai {dateLabel(project.started_on)}</small><strong>{project.completed_on ? `Selesai ${dateLabel(project.completed_on)}` : 'Masih berjalan'}</strong></span><span className={view.net >= 0 ? 'positive' : 'negative'}><small>{view.transactions} transaksi · arus kas bersih</small><strong>{IDR.format(view.net)}</strong></span></button>{!readOnly && <div className="row-actions" aria-label={`Aksi ${project.name}`}>{project.status === 'active' && <button type="button" className="complete-project-action" aria-label={`Selesaikan ${project.name}`} disabled={busy} onClick={() => { if (!busy) onComplete(project) }}>{busy ? 'Menyelesaikan…' : 'Selesaikan'}</button>}<button type="button" aria-label={`Ubah ${project.name}`} disabled={busy} onClick={() => onEdit(project)}><span className="row-action-label">Ubah</span></button><button type="button" className="danger" aria-label={`${destructiveActionLabel} ${project.name}`} disabled={busy} onClick={() => onDelete(project)}><span className="row-action-label">{destructiveActionLabel}</span></button></div>}</article>
    })}</section> : <section className="command-empty" aria-label={`Daftar Project ${year}`}><strong>Project tidak ditemukan</strong><p>{readOnly ? 'Ubah filter untuk melihat Project lain.' : `Ubah filter atau tambahkan Project untuk tahun ${year}.`}</p>{!readOnly && <button className="primary-button" onClick={onAdd}>Tambah Project</button>}</section>}
    {pageCount > 1 && <nav className="project-ledger-pagination" aria-label="Pagination Project">
      <button type="button" onClick={() => setPage((value) => Math.max(0, value - 1))} disabled={page === 0} aria-label="Halaman Project sebelumnya">Sebelumnya</button>
      <span>Halaman {page + 1} / {pageCount}</span>
      <button type="button" onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))} disabled={page === pageCount - 1} aria-label="Halaman Project berikutnya">Berikutnya</button>
    </nav>}
  </section>
}
