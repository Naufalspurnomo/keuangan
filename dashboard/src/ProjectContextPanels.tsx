import type { FinanceProject, FinanceWorkspace } from './financeWorkspace'
import { IDR, projectStatusLabel } from './financeView'

function projectRows(project: FinanceProject, workspace: Readonly<FinanceWorkspace>) {
  return workspace.transactions.filter((row) => row.project_id === project.id)
}

export function ProjectOverviewPanel({ project, workspace }: { project: FinanceProject; workspace: Readonly<FinanceWorkspace> }) {
  const rows = projectRows(project, workspace)
  const income = rows.filter((row) => row.direction === 'income').reduce((sum, row) => sum + row.amount, 0)
  const expense = rows.filter((row) => row.direction === 'expense').reduce((sum, row) => sum + row.amount, 0)
  return <section className="project-context-panel">
    <header><p className="eyebrow">RINGKASAN Project</p><h2>Ringkasan Project</h2><p>{project.name}</p></header>
    <div className="project-profitability-metrics" aria-label={`Ringkasan ${project.name}`}>
      <article><small>Status</small><strong>{projectStatusLabel(project.status)}</strong></article>
      <article><small>Dompet</small><strong>{project.wallet}</strong></article>
      <article><small>Kas masuk</small><strong className="positive">{IDR.format(income)}</strong></article>
      <article><small>Kas keluar</small><strong className="negative">{IDR.format(expense)}</strong></article>
      <article><small>Aktivitas</small><strong>{rows.length}</strong><span>transaksi tercatat</span></article>
    </div>
  </section>
}

export function ProjectDebtPanel({ project, workspace }: { project: FinanceProject; workspace: Readonly<FinanceWorkspace> }) {
  const debts = workspace.debts.filter((debt) => debt.project_id === project.id)
  return <section className="project-context-panel">
    <header><p className="eyebrow">PINJAMAN Project</p><h2>Pinjaman terkait Project</h2><p>Hanya pinjaman yang ditautkan langsung ke Project ini yang ditampilkan.</p></header>
    {debts.length ? <div className="project-context-list">{debts.map((debt) => <article key={debt.id}>
      <div><strong>{debt.notes || 'Pinjaman antar-dompet'}</strong><span>{debt.lender} → {debt.borrower}</span></div>
      <b>{IDR.format(debt.amount - debt.repaid)}</b>
    </article>)}</div> : <p className="write-disabled-note">Belum ada pinjaman yang tertaut langsung ke Project ini.</p>}
  </section>
}

export function ProjectAuditPanel({ project, workspace }: { project: FinanceProject; workspace: Readonly<FinanceWorkspace> }) {
  const events = workspace.audit.filter((event) => event.entity === 'project' && event.entity_id === project.id)
  return <section className="project-context-panel">
    <header><p className="eyebrow">AUDIT Project</p><h2>Riwayat perubahan Project</h2><p>Jejak audit hanya untuk identitas Project terpilih.</p></header>
    {events.length ? <ol className="project-context-list">{events.map((event) => <li key={event.id}>
      <div><strong>{event.summary}</strong><span>{new Date(event.at).toLocaleString('id-ID')}</span></div>
    </li>)}</ol> : <p className="write-disabled-note">Belum ada peristiwa audit Project.</p>}
  </section>
}
