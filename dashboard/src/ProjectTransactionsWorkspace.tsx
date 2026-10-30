import { ArrowLeft, Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { TransactionRows } from './FinancePages'
import { projectTotals, type FinanceProject, type FinanceTransaction, type FinanceWorkspace } from './financeWorkspace'
import { IDR, projectStatusLabel } from './financeView'

export default function ProjectTransactionsWorkspace({ workspace, project, onBack, onAdd, onEdit, onDelete }: {
  workspace: FinanceWorkspace
  project: FinanceProject
  onBack: () => void
  onAdd: (project: FinanceProject) => void
  onEdit: (row: FinanceTransaction) => void
  onDelete: (row: FinanceTransaction) => void
}) {
  const [query, setQuery] = useState('')
  const projectRows = useMemo(() => workspace.transactions
    .filter((row) => row.project_id === project.id)
    .sort((left, right) => right.date.localeCompare(left.date) || right.created_at.localeCompare(left.created_at)),
  [project.id, workspace.transactions])
  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('id-ID')
    return needle ? projectRows.filter((row) => `${row.notes} ${row.wallet} ${row.company ?? ''}`.toLocaleLowerCase('id-ID').includes(needle)) : projectRows
  }, [projectRows, query])
  const totals = projectTotals(project, workspace.transactions)

  return <section className="finance-page-stack project-transaction-detail">
    <header className="project-detail-head">
      <button type="button" className="secondary-button project-detail-back" onClick={onBack}><ArrowLeft size={17} /> Kembali ke Proyek</button>
      <div className="project-detail-identity"><p className="eyebrow">TRANSAKSI PROYEK · DATA DEMO</p><h1>{project.name}</h1><p>{project.company} · {project.wallet} · <span className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</span>{project.client ? ` · ${project.client}` : ''}</p></div>
      <button type="button" className="primary-button" onClick={() => onAdd(project)}><Plus size={16} /> Tambah transaksi</button>
    </header>
    <section className="project-detail-summary" aria-label={`Ringkasan ${project.name}`}>
      <article><small>Pemasukan</small><strong className="positive">{IDR.format(totals.income)}</strong></article>
      <article><small>Pengeluaran</small><strong className="negative">{IDR.format(totals.expense)}</strong></article>
      <article><small>Arus bersih</small><strong className={totals.net >= 0 ? 'positive' : 'negative'}>{IDR.format(totals.net)}</strong></article>
      <article><small>Transaksi</small><strong>{totals.transactions}</strong></article>
    </section>
    <section className="workspace-filters project-detail-filter" aria-label="Cari transaksi proyek">
      <label className="command-search"><Search size={17} /><input aria-label="Cari transaksi" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Cari di ${project.name}`} /></label>
      <span><strong>{rows.length}</strong> transaksi</span>
    </section>
    {rows.length
      ? <TransactionRows rows={rows} projects={[project]} onEdit={onEdit} onDelete={onDelete} />
      : <div className="project-detail-empty"><strong>Belum ada transaksi untuk {project.name}</strong><span>Tambahkan transaksi pertama untuk memulai ledger proyek ini.</span></div>}
  </section>
}
