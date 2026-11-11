import { Archive, ArrowLeft, Ban, CheckCircle2, Landmark, Pencil, Plus, RotateCcw } from 'lucide-react'
import { type KeyboardEvent, type ReactNode } from 'react'

import { actionProps, type ActionId } from './actionRegistry'
import {
  NO_PROJECT_DOCUMENT_WRITES,
  projectStatusLabel,
  type ProductionProjectStatus,
  type ProjectDetailTab,
  type ProjectDocumentCapabilities,
  type ProjectRecord,
} from './projectDocuments'

const TABS: Array<{ id: ProjectDetailTab; label: string }> = [
  { id: 'overview', label: 'Ringkasan' },
  { id: 'transactions', label: 'Transaksi' },
  { id: 'debts', label: 'Pinjaman' },
  { id: 'profitability', label: 'Profitabilitas' },
  { id: 'presensi', label: 'Presensi' },
  { id: 'documents', label: 'Dokumen' },
  { id: 'audit', label: 'Audit' },
]

const TAB_ACTION: Record<ProjectDetailTab, ActionId> = {
  overview: 'projects.tab-overview',
  transactions: 'projects.tab-transactions',
  debts: 'projects.tab-debts',
  profitability: 'projects.tab-profitability',
  presensi: 'projects.tab-presensi',
  documents: 'projects.tab-documents',
  audit: 'projects.tab-audit',
}

interface ProjectDetailWorkspaceProps {
  project: ProjectRecord
  tab: ProjectDetailTab
  onRouteChange: (route: { tab: ProjectDetailTab }) => void
  onBack: () => void
  transactions: ReactNode
  presensi: ReactNode
  documents: ReactNode
  overview?: ReactNode
  debts?: ReactNode
  profitability?: ReactNode
  audit?: ReactNode
  capabilities?: ProjectDocumentCapabilities
  onEdit?: (project: ProjectRecord) => void
  onAddTransaction?: (project: ProjectRecord) => void
  onOpenDebt?: (project: ProjectRecord) => void
  onStatusChange?: (status: ProductionProjectStatus) => void
  onArchive?: () => void
}

export default function ProjectDetailWorkspace({
  project,
  tab,
  onRouteChange,
  onBack,
  transactions,
  presensi,
  documents,
  overview,
  debts,
  profitability,
  audit,
  capabilities = NO_PROJECT_DOCUMENT_WRITES,
  onEdit,
  onAddTransaction,
  onOpenDebt,
  onStatusChange,
  onArchive,
}: ProjectDetailWorkspaceProps) {
  const handleTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const tabs = [...event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    const current = tabs.indexOf(event.currentTarget)
    const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (current - 1 + tabs.length) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
    if (next < 0) return
    event.preventDefault()
    tabs[next].focus()
    const nextTab = TABS[next].id
    if (nextTab !== tab) onRouteChange({ tab: nextTab })
  }

  const panel = tab === 'overview' ? overview
    : tab === 'transactions' ? transactions
      : tab === 'debts' ? debts
        : tab === 'profitability' ? profitability
          : tab === 'presensi' ? presensi
            : tab === 'documents' ? documents
              : audit

  return <section className="finance-page-stack project-detail-workspace">
    <header className="project-detail-head">
      <button type="button" className="secondary-button project-detail-back" onClick={onBack}><ArrowLeft size={17} /> Kembali ke Proyek</button>
      <div className="project-detail-identity">
        <p className="eyebrow">PROYEK</p>
        <h1>{project.name}</h1>
        <p>{project.client_name}{project.client_company ? ` · ${project.client_company}` : ''} · <span className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</span></p>

      </div>
      <div className="project-lifecycle-actions">
        {tab === 'transactions' && project.status === 'active' && onAddTransaction && <button type="button" className="primary-button" onClick={() => onAddTransaction(project)} {...actionProps('projects.transaction-create')}><Plus size={16} /> Tambah transaksi</button>}
        {tab === 'debts' && onOpenDebt && <button type="button" className="primary-button" onClick={() => onOpenDebt(project)} {...actionProps('projects.tab-debts')}><Landmark size={16} /> Catat pinjaman</button>}
        {capabilities.projectWrites && onEdit && <button type="button" className="secondary-button" onClick={() => onEdit(project)} {...actionProps('projects.edit')}><Pencil size={16} /> Ubah proyek</button>}
      </div>
    </header>

    <section className="project-status-control" aria-label="Status proyek">
      <div><small>STATUS PROYEK</small><span className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</span></div>
      {capabilities.projectWrites ? <div className="project-lifecycle-actions">
        {project.status !== 'completed' && <button type="button" className="secondary-button" onClick={() => onStatusChange?.('completed')} {...actionProps('projects.status-change')}><CheckCircle2 size={16} /> Selesaikan proyek</button>}
        {project.status !== 'active' && <button type="button" className="secondary-button" onClick={() => onStatusChange?.('active')} {...actionProps('projects.status-change')}><RotateCcw size={16} /> Aktifkan proyek</button>}
        {project.status !== 'cancelled' && <button type="button" className="secondary-button danger" onClick={() => onStatusChange?.('cancelled')} {...actionProps('projects.status-change')}><Ban size={16} /> Batalkan proyek</button>}
        {!project.archived_at && <button type="button" className="secondary-button danger" onClick={onArchive} {...actionProps('projects.archive')}><Archive size={16} /> Arsipkan proyek</button>}
      </div> : <p className="write-disabled-note">Perubahan proyek belum diaktifkan.</p>}
    </section>

    <div className="project-detail-tabs" role="tablist" aria-label={`Data ${project.name}`}>
      {TABS.map((item) => <button
        id={`project-${item.id}-tab`}
        key={item.id}
        type="button"
        role="tab"
        aria-label={item.label}
        aria-selected={tab === item.id}
        aria-controls={`project-${item.id}-panel`}
        tabIndex={tab === item.id ? 0 : -1}
        onKeyDown={handleTabKey}
        onClick={() => { if (item.id !== tab) onRouteChange({ tab: item.id }) }}
        {...actionProps(TAB_ACTION[item.id])}
      >{item.label}</button>)}
    </div>
    <div id={`project-${tab}-panel`} role="tabpanel" aria-labelledby={`project-${tab}-tab`} tabIndex={0}>{panel}</div>
  </section>
}

export type { ProjectDetailWorkspaceProps }
