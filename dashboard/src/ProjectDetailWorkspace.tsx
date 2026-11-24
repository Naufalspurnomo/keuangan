import { ArrowLeft, Ban, CheckCircle2, Landmark, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'

import { actionProps, type ActionId } from './actionRegistry'
import {
  NO_PROJECT_DOCUMENT_WRITES,
  projectStatusLabel,
  type ProductionProjectStatus,
  type ProjectDetailTab,
  type ProjectDocumentCapabilities,
  type ProjectRecord,
} from './projectDocuments'
import { visibleProjectStatus } from './projectStatus'

const TABS: Array<{ id: ProjectDetailTab; label: string }> = [
  { id: 'overview', label: 'Keuangan' },
  { id: 'transactions', label: 'Transaksi' },
  { id: 'debts', label: 'Pinjaman' },
  { id: 'presensi', label: 'Presensi' },
  { id: 'documents', label: 'Quotation & Invoice' },
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
  onDelete?: () => void
  busy?: boolean
}

export default function ProjectDetailWorkspace({
  project: sourceProject,
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
  onDelete,
  busy = false,
}: ProjectDetailWorkspaceProps) {
  const project = sourceProject.status === 'planned'
    ? { ...sourceProject, status: visibleProjectStatus(sourceProject.status) }
    : sourceProject
  const tabs: Array<{ id: ProjectDetailTab; label: string }> = project.status === 'completed'
    ? [...TABS.slice(0, 2), { id: 'profitability', label: 'Laba Rugi' }, ...TABS.slice(2)]
    : TABS
  const activeTab: ProjectDetailTab = tab === 'profitability' && project.status === 'completed' ? 'profitability' : tab === 'profitability' ? 'overview' : tab
  const activeTabRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    activeTabRef.current?.scrollIntoView?.({ block: 'nearest', inline: 'center' })
  }, [activeTab])
  const handleTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const tabs = [...event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    const current = tabs.indexOf(event.currentTarget)
    const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (current - 1 + tabs.length) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
    if (next < 0) return
    event.preventDefault()
    tabs[next].focus()
    const nextTab = tabs[next].id.replace(/^project-/, '').replace(/-tab$/, '') as ProjectDetailTab
    if (nextTab !== activeTab) onRouteChange({ tab: nextTab })
  }

  const panel = activeTab === 'overview' ? <>
    {overview && <section aria-label="Ikhtisar Project">{overview}</section>}
    {profitability && <section aria-label="Profitabilitas dan arus kas">{profitability}</section>}
  </>
    : tab === 'transactions' ? transactions
      : tab === 'debts' ? debts
        : tab === 'profitability' ? profitability
          : tab === 'presensi' ? presensi
            : tab === 'documents' ? documents
              : audit

  return <section className="finance-page-stack project-detail-workspace">
    <header className="project-detail-head">
      <div className="project-detail-identity">
        <button type="button" className="secondary-button project-detail-back" onClick={onBack}><ArrowLeft size={17} /> Kembali ke Project</button>
        <div className="project-detail-copy"><p className="eyebrow">PROJECT</p>
          <h1>{project.name}</h1>
          <p>{project.client_name}{project.client_company ? ` · ${project.client_company}` : ''}</p></div>

      </div>
      <div className="project-lifecycle-actions">
        {tab === 'transactions' && (project.status === 'active' || project.status === 'completed') && onAddTransaction && <button type="button" className="primary-button" disabled={busy} onClick={() => onAddTransaction(project)} {...actionProps('projects.transaction-create')}><Plus size={16} /> Tambah transaksi</button>}
        {tab === 'debts' && onOpenDebt && <button type="button" className="primary-button" disabled={busy} onClick={() => onOpenDebt(project)} {...actionProps('projects.tab-debts')}><Landmark size={16} /> Buka Hutang</button>}
        {capabilities.projectWrites && onEdit && <button type="button" className="secondary-button" disabled={busy} onClick={() => onEdit(project)} {...actionProps('projects.edit')}><Pencil size={16} /> Ubah Project</button>}
      </div>
    </header>

    <section className="project-status-control" aria-label="Status Project">
      <div><small>STATUS PROJECT</small><span className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</span></div>
      {capabilities.projectWrites ? <div className="project-lifecycle-actions">
        {project.status === 'active' && <button type="button" className="secondary-button" disabled={busy} onClick={() => onStatusChange?.('completed')} {...actionProps('projects.status-change')}><CheckCircle2 size={16} /> Selesaikan Project</button>}
        {(project.status === 'completed' || project.status === 'cancelled') && <button type="button" className="secondary-button" disabled={busy} onClick={() => onStatusChange?.('active')} {...actionProps('projects.status-change')}><RotateCcw size={16} /> Aktifkan Project</button>}
        {project.status === 'active' && <button type="button" className="secondary-button danger" disabled={busy} onClick={() => {
          if (window.confirm(`Batalkan Project ${project.name}? Project dapat diaktifkan kembali nanti.`)) onStatusChange?.('cancelled')
        }} {...actionProps('projects.status-change')}><Ban size={16} /> Batalkan Project</button>}
        {capabilities.hardDelete && <button type="button" className="secondary-button danger" disabled={busy} onClick={onDelete} {...actionProps('projects.delete')}><Trash2 size={16} /> Hapus Project permanen</button>}
      </div> : <p className="write-disabled-note">Perubahan Project belum diaktifkan.</p>}
    </section>

    <div className="project-detail-tabs" role="tablist" aria-label={`Data ${project.name}`}>
      {tabs.map((item) => <button
        id={`project-${item.id}-tab`}
        ref={activeTab === item.id ? activeTabRef : undefined}
        key={item.id}
        type="button"
        role="tab"
        aria-label={item.label}
        aria-selected={activeTab === item.id}
        aria-controls={`project-${item.id}-panel`}
        tabIndex={activeTab === item.id ? 0 : -1}
        onKeyDown={handleTabKey}
        onClick={() => { if (item.id !== tab) onRouteChange({ tab: item.id }) }}
        {...actionProps(TAB_ACTION[item.id])}
      >{item.label}</button>)}
    </div>
    <div id={`project-${activeTab}-panel`} role="tabpanel" aria-labelledby={`project-${activeTab}-tab`} tabIndex={0} className={activeTab === 'transactions' ? 'project-transaction-detail' : undefined}>{panel}</div>
  </section>
}

export type { ProjectDetailWorkspaceProps }
