import { ArrowLeft, CheckCircle2, Plus, RotateCcw, Search } from 'lucide-react'
import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'

import { TransactionRows } from './FinancePages'
import ProjectPresensiPanel from './ProjectPresensiPanel'
import { projectTotals, type FinanceProject, type FinanceTransaction, type FinanceWorkspace } from './financeWorkspace'
import { IDR, projectStatusLabel } from './financeView'
import { visibleProjectStatus } from './projectStatus'

type ProjectDetailTab = 'transactions' | 'presensi'

export default function ProjectTransactionsWorkspace({ workspace, project: sourceProject, onBack, onAdd, onEdit, onDelete, onComplete, onReactivate, readOnly = false, canCreateTransactions = false }: {
  workspace: FinanceWorkspace
  project: FinanceProject
  onBack: () => void
  onAdd: (project: FinanceProject) => void
  onEdit: (row: FinanceTransaction) => void
  onDelete: (row: FinanceTransaction) => void
  onComplete: (project: FinanceProject) => void
  onReactivate: (project: FinanceProject) => void
  readOnly?: boolean
  canCreateTransactions?: boolean
}) {
  const project = sourceProject.status === 'planned'
    ? { ...sourceProject, status: visibleProjectStatus(sourceProject.status) }
    : sourceProject
  const [tab, setTab] = useState<ProjectDetailTab>('transactions')
  const [query, setQuery] = useState('')
  useEffect(() => { setTab('transactions'); setQuery('') }, [project.id])
  const projectRows = useMemo(() => workspace.transactions
    .filter((row) => row.project_id === project.id)
    .sort((left, right) => right.date.localeCompare(left.date) || right.created_at.localeCompare(left.created_at)),
  [project.id, workspace.transactions])
  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('id-ID')
    return needle ? projectRows.filter((row) => `${row.notes} ${row.wallet} ${row.company ?? ''}`.toLocaleLowerCase('id-ID').includes(needle)) : projectRows
  }, [projectRows, query])
  const totals = projectTotals(project, workspace.transactions)
  const handleTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const tabs = [...event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    const current = tabs.indexOf(event.currentTarget)
    const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (current - 1 + tabs.length) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
    if (next < 0) return
    event.preventDefault()
    tabs[next].focus()
    tabs[next].click()
  }

  return <section className="finance-page-stack project-transaction-detail">
    <header className="project-detail-head">
      <div className="project-detail-identity"><button type="button" className="secondary-button project-detail-back" onClick={onBack}><ArrowLeft size={17} /> Kembali ke Project</button><div className="project-detail-copy"><p className="eyebrow">PROJECT{workspace.mode === 'demo' ? ' · DATA DEMO' : ''}</p><h1>{project.name}</h1><p>{project.company} · {project.wallet} · <span className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</span>{project.client ? ` · ${project.client}` : ''}</p></div></div>
      {project.status === 'active' && (!readOnly || (canCreateTransactions && project.write_mapping)) && tab === 'transactions' && <div className="project-lifecycle-actions"><button type="button" className="primary-button" onClick={() => onAdd(project)}><Plus size={16} /> Tambah transaksi</button></div>}
    </header>
    {readOnly && canCreateTransactions && !project.write_mapping && <p className="form-error" role="status">Pencatatan belum tersedia untuk Project ini.</p>}
    <section className="project-status-control" aria-label="Status Project">
      <div><small>STATUS Project</small><span className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</span><p>{project.status === 'active' ? 'Project sedang berjalan dan transaksi dapat dicatat.' : project.status === 'completed' ? 'Project telah selesai. Aktifkan kembali jika masih ada pekerjaan.' : 'Project dibatalkan. Aktifkan kembali sebelum mencatat transaksi.'}</p></div>
      {!readOnly && project.status === 'active' && <button type="button" className="primary-button" onClick={() => onComplete(project)}><CheckCircle2 size={16} /> Selesaikan Project</button>}
      {!readOnly && (project.status === 'completed' || project.status === 'cancelled') && <button type="button" className="secondary-button" onClick={() => onReactivate(project)}><RotateCcw size={16} /> Aktifkan kembali</button>}
    </section>
    <div className="project-detail-tabs" role="tablist" aria-label={`Data ${project.name}`}>
      <button id="project-transactions-tab" type="button" role="tab" aria-label="Transaksi" aria-selected={tab === 'transactions'} aria-controls="project-transactions-panel" tabIndex={tab === 'transactions' ? 0 : -1} onKeyDown={handleTabKey} onClick={() => setTab('transactions')}>Transaksi <span>{projectRows.length}</span></button>
      <button id="project-presensi-tab" type="button" role="tab" aria-label="Presensi" aria-selected={tab === 'presensi'} aria-controls="project-presensi-panel" tabIndex={tab === 'presensi' ? 0 : -1} onKeyDown={handleTabKey} onClick={() => setTab('presensi')}>Presensi</button>
    </div>
    {tab === 'presensi'
      ? <div id="project-presensi-panel" role="tabpanel" aria-labelledby="project-presensi-tab"><ProjectPresensiPanel project={{ id: project.presensi_project_id ?? (workspace.mode === 'demo' ? project.id : undefined), name: project.name }} /></div>
      : <div id="project-transactions-panel" role="tabpanel" aria-labelledby="project-transactions-tab">
        <section className="project-detail-summary" aria-label={`Ringkasan ${project.name}`}>
          <article><small>Pemasukan</small><strong className="positive">{IDR.format(totals.income)}</strong></article>
          <article><small>Pengeluaran</small><strong className="negative">{IDR.format(totals.expense)}</strong></article>
          <article><small>Arus bersih</small><strong className={totals.net >= 0 ? 'positive' : 'negative'}>{IDR.format(totals.net)}</strong></article>
          <article><small>Transaksi</small><strong>{totals.transactions}</strong></article>
        </section>
        <section className="workspace-filters project-detail-filter" aria-label="Cari transaksi Project">
          <label className="command-search"><Search size={17} /><input aria-label="Cari transaksi" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Cari di ${project.name}`} /></label>
          <span><strong>{rows.length}</strong> transaksi</span>
        </section>
        {rows.length
          ? <TransactionRows rows={rows} projects={workspace.projects} onEdit={readOnly ? undefined : onEdit} onDelete={readOnly ? undefined : onDelete} />
          : <div className="project-detail-empty"><strong>Belum ada transaksi untuk {project.name}</strong><span>Tambahkan transaksi pertama untuk memulai ledger Project ini.</span></div>}
      </div>}
  </section>
}
