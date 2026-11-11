import { Pencil, Plus } from 'lucide-react'

import { actionProps } from './actionRegistry'
import ProjectCommandCenter from './ProjectCommandCenter'
import type { FinanceWorkspace } from './financeWorkspace'
import { projectStatusLabel, type ProjectDocumentCapabilities, type ProjectRecord } from './projectDocuments'

interface ProductionProjectsWorkspaceProps {
  projects: ProjectRecord[]
  capabilities: ProjectDocumentCapabilities
  loading: boolean
  onAdd: () => void
  onEdit: (project: ProjectRecord) => void
  onOpen: (project: ProjectRecord) => void
  workspace?: FinanceWorkspace
}

export default function ProductionProjectsWorkspace({ projects, capabilities, loading, onAdd, onEdit, onOpen, workspace }: ProductionProjectsWorkspaceProps) {
  if (workspace && projects.length) return <ProjectCommandCenter
    workspace={workspace}
    onAdd={onAdd}
    onEdit={(project) => { const record = projects.find((item) => item.id === project.id); if (record) onEdit(record) }}
    onComplete={(project) => { const record = projects.find((item) => item.id === project.id); if (record) onOpen(record) }}
    onQuickComplete={(project) => { const record = projects.find((item) => item.id === project.id); if (record) onOpen(record) }}
    onDelete={(project) => { const record = projects.find((item) => item.id === project.id); if (record) onOpen(record) }}
    onOpen={(project) => { const record = projects.find((item) => item.id === project.id); if (record) onOpen(record) }}
    readOnly
    canAdd={capabilities.projectWrites}
  />
  return <section className="project-command-center production-projects-workspace">
    <header className="command-head"><div><p className="eyebrow">PROYEK</p><h1>Daftar proyek</h1><p>Buat proyek aktif, lalu kelola transaksi, presensi, dan dokumennya dari satu halaman.</p></div>{capabilities.projectWrites && <button type="button" className="primary-button" onClick={onAdd} {...actionProps('projects.create')}><Plus size={16} /> Buat proyek</button>}</header>
    {loading ? <section className="command-empty" role="status"><strong>Memuat proyek</strong><p>Menyiapkan data terbaru.</p></section>
      : projects.length ? <section className="project-register" aria-label="Daftar proyek"><header><div><p className="eyebrow">PORTOFOLIO</p><h3>{projects.length} proyek</h3></div></header><div className="project-register-headings" aria-hidden="true"><span>Proyek</span><span>Status</span><span>Klien</span><span>Mulai</span><span>Aksi</span></div>{projects.map((project) => <article key={project.id}>
        <button type="button" className="project-register-main" aria-label={`Buka proyek ${project.name}`} onClick={() => onOpen(project)} {...actionProps('projects.open')}>
          <span><strong>{project.name}</strong><small>{project.company || 'Hollawall'} · {project.wallet || 'Dompet belum dipetakan'}</small></span>
          <b className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</b>
          <span><small>{project.client_name}</small><strong>{project.client_company || 'Perorangan'}</strong></span>
          <span><small>Tanggal mulai</small><strong>{project.started_on}</strong></span>
        </button>
        {capabilities.projectWrites && <div className="row-actions" aria-label={`Aksi ${project.name}`}><button type="button" aria-label={`Ubah ${project.name}`} onClick={() => onEdit(project)} {...actionProps('projects.edit')}><Pencil size={16} /><span className="row-action-label">Ubah</span></button></div>}
      </article>)}</section>
      : <section className="command-empty"><strong>Belum ada proyek</strong><p>Buat proyek pertama setelah perubahan proyek diaktifkan.</p>{capabilities.projectWrites && <button type="button" className="primary-button" onClick={onAdd}><Plus size={16} /> Buat proyek</button>}</section>}
  </section>
}
