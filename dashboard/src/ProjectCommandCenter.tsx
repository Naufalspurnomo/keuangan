import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, CircleDot, Clock3, Pencil, Plus, Search, Trash2 } from 'lucide-react'

import { COMPANIES, projectYear, type CompanyId, type FinanceProject, type FinanceWorkspace, type ProjectStatus } from './financeWorkspace'
import { dateLabel, IDR, projectStatusLabel, projectView } from './financeView'

const PAGE_SIZE = 12
const DAY = 86_400_000
const statusOrder: ProjectStatus[] = ['active', 'planned', 'completed']

function age(project: FinanceProject, asOf: Date) {
  const end = project.completed_on ? new Date(`${project.completed_on}T00:00:00`) : asOf
  const start = new Date(`${project.started_on}T00:00:00`)
  return Math.max(0, Math.round((end.getTime() - start.getTime()) / DAY))
}

function ageColor(days: number) {
  const progress = Math.max(0, Math.min(1, days / 90))
  return `hsl(${Math.round(138 * (1 - progress))} 64% 39%)`
}

export default function ProjectCommandCenter({ workspace, onAdd, onEdit, onDelete, onOpen }: {
  workspace: FinanceWorkspace
  onAdd: () => void
  onEdit: (project: FinanceProject) => void
  onDelete: (project: FinanceProject) => void
  onOpen: (project: FinanceProject) => void
}) {
  const years = useMemo(() => [...new Set(workspace.projects.map(projectYear))].sort((a, b) => a - b), [workspace.projects])
  const [year, setYear] = useState(() => years.at(-1) ?? new Date().getFullYear())
  const [company, setCompany] = useState<'all' | CompanyId>('all')
  const [status, setStatus] = useState<'all' | ProjectStatus>('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const allYear = workspace.projects.filter((project) => projectYear(project) === year)
  const completed = allYear.filter((project) => project.status === 'completed').length
  const active = allYear.filter((project) => project.status === 'active').length
  const planned = allYear.filter((project) => project.status === 'planned').length
  const filtered = allYear.filter((project) => (company === 'all' || project.company === company)
    && (status === 'all' || project.status === status)
    && (!query.trim() || `${project.name} ${project.client}`.toLocaleLowerCase('id-ID').includes(query.trim().toLocaleLowerCase('id-ID'))))
    .sort((left, right) => statusOrder.indexOf(left.status) - statusOrder.indexOf(right.status) || right.updated_at.localeCompare(left.updated_at) || left.name.localeCompare(right.name, 'id-ID'))
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1) }, [page, pageCount])
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const yearIndex = years.indexOf(year)
  const changeYear = (next: number) => { setYear(next); setPage(0) }
  const asOf = new Date(`${year}-12-31T00:00:00`)

  return <section className="project-command-center">
    <header className="command-head"><div><p className="eyebrow">PROYEK · DATA DEMO</p><h1>Portfolio proyek per tahun</h1><p>Bandingkan proyek selesai, aktif, dan direncanakan dari satu sumber data.</p></div></header>

    <section className="year-command" aria-label="Pilih tahun proyek">
      <button type="button" aria-label="Tahun sebelumnya" title={yearIndex <= 0 ? 'Tidak ada tahun sebelumnya' : undefined} disabled={yearIndex <= 0} onClick={() => changeYear(years[yearIndex - 1])}><ArrowLeft size={19} /></button>
      <div><small>TAHUN PROYEK</small><strong>{year}</strong><span><b>{completed}</b>/{allYear.length} selesai</span></div>
      <button type="button" aria-label="Tahun berikutnya" title={yearIndex >= years.length - 1 ? 'Tahun terbaru yang tersedia' : undefined} disabled={yearIndex < 0 || yearIndex >= years.length - 1} onClick={() => changeYear(years[yearIndex + 1])}><ArrowRight size={19} /></button>
      <nav aria-label="Daftar tahun">{years.map((item) => {
        const projects = workspace.projects.filter((project) => projectYear(project) === item)
        const done = projects.filter((project) => project.status === 'completed').length
        return <button type="button" className={item === year ? 'active' : ''} aria-current={item === year ? 'page' : undefined} aria-label={`${item}, ${done} selesai dari ${projects.length} proyek`} key={item} onClick={() => changeYear(item)}><strong>{item}</strong><span>{done} selesai / {projects.length} total</span></button>
      })}</nav>
    </section>

    <div className="project-year-stats" aria-label={`Status proyek tahun ${year}`}>
      <article className="done"><CheckCircle2 /><span><small>Selesai</small><strong>{completed}</strong></span></article>
      <article className="active"><CircleDot /><span><small>Aktif</small><strong>{active}</strong></span></article>
      <article className="planned"><Clock3 /><span><small>Direncanakan</small><strong>{planned}</strong></span></article>
      <article className="ratio"><span><small>Tingkat selesai · {completed}/{allYear.length}</small><strong>{allYear.length ? Math.round((completed / allYear.length) * 100) : 0}%</strong></span><i><b style={{ width: `${allYear.length ? (completed / allYear.length) * 100 : 0}%` }} /></i></article>
    </div>

    <div className="project-controls"><label className="command-search"><Search size={17} /><span className="sr-only">Cari proyek</span><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0) }} placeholder="Cari proyek atau klien" /></label><label><span className="sr-only">Perusahaan</span><select value={company} onChange={(event) => { setCompany(event.target.value as 'all' | CompanyId); setPage(0) }}><option value="all">Semua perusahaan</option>{COMPANIES.map((item) => <option key={item}>{item}</option>)}</select></label><label><span className="sr-only">Status</span><select value={status} onChange={(event) => { setStatus(event.target.value as 'all' | ProjectStatus); setPage(0) }}><option value="all">Semua status</option>{statusOrder.map((item) => <option key={item} value={item}>{projectStatusLabel(item)}</option>)}</select></label><span><strong>{filtered.length}</strong> proyek</span></div>

    <p className="project-status-note"><strong>Lingkup {year}.</strong> Selesai: pekerjaan ditutup. Aktif: sedang berjalan. Direncanakan: belum dimulai.</p>

    {filtered.length ? <>
      <section className="year-candle-board" aria-label={`Chart proyek tahun ${year}`}>
        <header><div><p className="eyebrow">TIMELINE {year}</p><h3>Umur dan status proyek</h3><p>Klik candle untuk melihat transaksi proyek.</p></div><span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} dari {filtered.length}</span></header>
        <div className="year-candle-grid">{visible.map((project) => {
          const days = age(project, asOf)
          const view = projectView(project, workspace)
          const color = project.status === 'completed' ? 'var(--positive)' : project.status === 'planned' ? 'var(--chart-neutral-2)' : ageColor(days)
          return <button type="button" className={`year-candle ${project.status}`} key={project.id} onClick={() => onOpen(project)} aria-label={`Buka ${project.name}, ${projectStatusLabel(project.status)}, ${days} hari, arus kas ${IDR.format(view.net)}`}>
            <span className="candle-track"><i style={{ height: project.status === 'planned' ? '24%' : `${Math.max(18, Math.min(100, days / 1.2))}%`, background: color }} /><b style={{ background: color }} /></span>
            <strong>{project.name}</strong><small>{project.company}</small><em>{project.status === 'completed' ? `Selesai ${dateLabel(project.completed_on!)}` : project.status === 'planned' ? `Mulai ${dateLabel(project.started_on)}` : `${days} hari berjalan`}</em>
          </button>
        })}</div>
        <footer><div className="project-chart-legend"><span><i className="active-key" />Aktif: warna mengikuti umur</span><span><i className="done-key" />Selesai: berhenti pada tanggal selesai</span><span><i className="planned-key" />Direncanakan: belum berjalan</span></div>{pageCount > 1 && <nav aria-label="Halaman chart"><button type="button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}><ArrowLeft size={16} /> Sebelumnya</button><span>{page + 1} / {pageCount}</span><button type="button" disabled={page === pageCount - 1} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Berikutnya <ArrowRight size={16} /></button></nav>}</footer>
      </section>

      <section className="project-register"><header><div><p className="eyebrow">DAFTAR PROYEK</p><h3>Rincian {year}</h3></div></header><div className="project-register-headings" aria-hidden="true"><span>Proyek</span><span>Status</span><span>Periode</span><span>Arus kas</span><span>Aksi</span></div>{visible.map((project) => {
        const view = projectView(project, workspace)
        return <article key={project.id}><button className="project-register-main" onClick={() => onOpen(project)}><span><strong>{project.name}</strong><small>{project.company} · {project.wallet}{project.client ? ` · ${project.client}` : ''}</small></span><b className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</b><span><small>{dateLabel(project.started_on)}</small><strong>{project.completed_on ? dateLabel(project.completed_on) : 'Belum selesai'}</strong></span><span className={view.net >= 0 ? 'positive' : 'negative'}><small>{view.transactions} transaksi</small><strong>{IDR.format(view.net)}</strong></span></button><div className="row-actions"><button aria-label={`Ubah ${project.name}`} onClick={() => onEdit(project)}><Pencil size={16} /></button><button className="danger" aria-label={`Hapus ${project.name}`} onClick={() => onDelete(project)}><Trash2 size={16} /></button></div></article>
      })}</section>
    </> : <section className="command-empty"><strong>Belum ada proyek</strong><p>Ubah filter atau tambahkan proyek untuk tahun {year}.</p><button className="primary-button" onClick={onAdd}><Plus size={16} /> Tambah proyek</button></section>}
  </section>
}
