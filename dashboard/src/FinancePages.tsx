import { lazy, Suspense } from 'react'
import { BarChart3, CircleDollarSign, Download, Pencil, Plus, RotateCcw, Trash2, WalletCards } from 'lucide-react'

import BusinessSectionReport from './BusinessSectionReport'
import { actionProps } from './actionRegistry'
import { CashflowWorkspace, WalletWorkspace } from './FinancialOperationsWorkspace'
import ProjectReportTimeline from './ProjectReportTimeline'
import { sumMoney, workspaceTotals, type FinanceDebt, type FinanceProject, type FinanceTransaction, type FinanceWorkspace } from './financeWorkspace'
import { cashTrend, chartProjects, chartTransactions, chartWallets, dateLabel, directionLabel, IDR, projectLabel, scopeLabel, walletBalances, workspaceDataThrough } from './financeView'

const FinancialChart = lazy(() => import('./FinancialChart'))

export function DemoBanner({ updatedAt, onReset }: { updatedAt: string; onReset: () => void }) {
  return <section className="demo-workspace-banner" aria-label="Status data demo"><div><strong>Data demo</strong><span>Data keuangan demo tersimpan di browser ini dan tidak terhubung ke buku besar produksi. Data Presensi privat dibaca dari server.</span></div><small>Diperbarui {new Date(updatedAt).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })}</small><button type="button" onClick={onReset}><RotateCcw size={15} /> Reset data demo</button></section>
}

export function OverviewWorkspace({ workspace, onOpenProjects, onAddProject, onOpenOffice, readOnly = false }: { workspace: FinanceWorkspace; onOpenProjects: () => void; onAddProject: () => void; onOpenOffice: () => void; readOnly?: boolean }) {
  const totals = workspaceTotals(workspace)
  const balances = walletBalances(workspace)
  const transactions = chartTransactions(workspace)
  const wallets = chartWallets(workspace)
  const projects = chartProjects(workspace)
  const trend = cashTrend(workspace)
  const active = workspace.projects.filter((project) => project.status === 'active').length
  const completed = workspace.projects.filter((project) => project.status === 'completed').length
  const openDebt = sumMoney(workspace.debts.map((debt) => debt.amount - debt.repaid), 'saldo hutang')
  const recent = [...workspace.transactions].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 6)
  const audit = [...workspace.audit].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 6)
  return <div className="finance-page-stack overview-showcase">
    <section className="overview-command"><div><p className="eyebrow">DASHBOARD{workspace.mode === 'demo' ? ' · DATA DEMO' : ''}</p><h1>Pusat kendali keuangan Hollawall</h1><p>{workspace.mode === 'demo' ? 'Saldo, arus kas, dompet, proyek, dan audit dihitung dari workspace demo yang sama.' : 'Saldo, arus kas, dompet, dan proyek dalam satu dashboard.'}</p></div><div className="quick-actions"><button className="primary-button" onClick={onOpenProjects} {...actionProps('dashboard.projects-view')}><Plus size={16} /> Transaksi proyek</button>{!readOnly && <button className="secondary-button" onClick={onAddProject} {...actionProps('dashboard.projects-view')}>Tambah proyek</button>}<button className="secondary-button" onClick={onOpenOffice} {...actionProps('dashboard.office-view')}>Operasional kantor</button></div></section>
    <section className="finance-kpis"><article><small>Posisi kas konsolidasi</small><strong className={totals.net >= 0 ? 'positive' : 'negative'}>{IDR.format(totals.net)}</strong><span>{IDR.format(totals.income)} masuk · {IDR.format(totals.expense)} keluar</span></article><article><small>Proyek aktif</small><strong>{active}</strong><span>{completed} proyek selesai</span></article><article><small>Biaya kantor</small><strong>{IDR.format(totals.office)}</strong><span>Terpisah dari seluruh proyek</span></article><article><small>Hutang internal terbuka</small><strong>{IDR.format(openDebt)}</strong><span>Tidak mengubah kas konsolidasi</span></article></section>
    <BusinessSectionReport transactions={transactions} wallets={wallets} />
    <section className="overview-chart-grid" aria-label="Analitik utama">
      <article className="showcase-chart"><header><div><p className="eyebrow">POSISI KAS</p><h2>Tren kas 12 bulan</h2></div><span>Saldo berjalan</span></header><div><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="cash" cashTrend={trend} /></Suspense></div></article>
      <article className="showcase-chart"><header><div><p className="eyebrow">LIKUIDITAS</p><h2>Sebaran saldo dompet</h2></div><span>{wallets.length} sumber dana</span></header><div><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="wallets" wallets={wallets} /></Suspense></div></article>
      <article className="showcase-chart"><header><div><p className="eyebrow">PORTOFOLIO</p><h2>Kontribusi proyek terbesar</h2></div><span>Arus bersih proyek</span></header><div><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="projects" projects={projects} /></Suspense></div></article>
    </section>
    <ProjectReportTimeline transactions={transactions} projects={projects} asOf={workspaceDataThrough(workspace)} dataThrough={workspaceDataThrough(workspace)} onAddProject={readOnly ? undefined : onAddProject} showSourceDetails={!readOnly} />
    <section className="wallet-command"><header><div><p className="eyebrow">POSISI DOMPET</p><h2>Tiga sumber dana</h2></div></header><div>{balances.map((item) => { const expenseShare = item.income ? Math.round((item.expense / item.income) * 100) : 0; return <article key={item.wallet}><span><WalletCards size={18} /><strong>{item.wallet}</strong></span><b>{IDR.format(item.balance)}</b><small>Saldo + piutang − hutang: {IDR.format(item.adjusted)}</small><i><em style={{ width: `${Math.max(4, Math.min(100, expenseShare))}%` }} /></i><small>{expenseShare}% pemasukan telah digunakan</small></article> })}</div></section>
    {!readOnly && <section className="recent-command"><header><div><p className="eyebrow">TRANSAKSI TERBARU</p><h2>Aktivitas terakhir</h2></div></header><TransactionRows rows={recent} projects={workspace.projects} compact /></section>}
    {!readOnly && <section className="audit-command"><header><div><p className="eyebrow">RIWAYAT PERUBAHAN</p><h2>{readOnly ? 'Riwayat perubahan' : 'Audit data demo'}</h2></div><small>{workspace.audit.length} perubahan tercatat</small></header>{audit.length ? <ol>{audit.map((event) => <li key={event.id}><span className={`audit-action ${event.action}`}>{event.action === 'create' ? 'Tambah' : event.action === 'update' ? 'Ubah' : event.action === 'delete' ? 'Hapus' : 'Reset'}</span><div><strong>{event.summary}</strong><small>{new Date(event.at).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })}</small></div></li>)}</ol> : <div className="audit-empty">Belum ada perubahan manual pada data demo.</div>}</section>}
  </div>
}

export function CashflowWorkspacePage({ workspace, onOpenProject }: { workspace: FinanceWorkspace; onOpenProject: (name: string) => void }) {
  const openDebt = sumMoney(workspace.debts.map((debt) => debt.amount - debt.repaid), 'saldo hutang')
  return <CashflowWorkspace transactions={chartTransactions(workspace, true)} cashTrend={cashTrend(workspace)} internalOpen={openDebt} dataThrough={workspaceDataThrough(workspace)} onOpenProject={onOpenProject} showSourceDetails={workspace.mode === 'demo'} />
}

export function WalletWorkspacePage({ workspace, onOpenProject }: { workspace: FinanceWorkspace; onOpenProject: (name: string) => void }) {
  return <WalletWorkspace transactions={chartTransactions(workspace, true)} wallets={chartWallets(workspace)} dataThrough={workspaceDataThrough(workspace)} onOpenProject={onOpenProject} showSourceDetails={workspace.mode === 'demo'} />
}

export function TransactionRows({
  rows,
  projects,
  compact,
  onEdit,
  onDelete,
  onCorrect,
  onReverse,
  lifecycleBusyId,
}: {
  rows: FinanceTransaction[]
  projects: FinanceProject[]
  compact?: boolean
  onEdit?: (row: FinanceTransaction) => void
  onDelete?: (row: FinanceTransaction) => void
  onCorrect?: (row: FinanceTransaction) => void
  onReverse?: (row: FinanceTransaction) => void
  lifecycleBusyId?: string | null
}) {
  const map = new Map(projects.map((project) => [project.id, project]))
  const actions = Boolean(onEdit || onDelete || onCorrect || onReverse)
  return <div className="workspace-table-wrap"><table className="workspace-table"><thead><tr><th>Tanggal</th><th>Keterangan</th><th>Aktivitas</th><th>Dompet</th><th>Jenis</th><th className="number">Jumlah</th>{!compact && actions && <th>Aksi</th>}</tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td data-label="Tanggal">{dateLabel(row.date)}</td><td data-label="Keterangan"><strong>{row.notes}</strong><small>{row.office_category ?? row.company ?? '—'}</small></td><td data-label="Aktivitas">{row.scope === 'project' ? projectLabel(map.get(row.project_id ?? '')) : 'Operasional Kantor'}</td><td data-label="Dompet"><span className="wallet-chip">{row.wallet}</span></td><td data-label="Jenis"><span className={`direction-chip ${row.direction}`}>{directionLabel(row.direction)}</span></td><td data-label="Jumlah" className={`number ${row.direction === 'income' ? 'positive' : 'negative'}`}>{row.direction === 'income' ? '+' : '−'}{IDR.format(row.amount)}</td>{!compact && actions && <td data-label="Aksi"><div className="row-actions">{onEdit && <button aria-label={`Ubah transaksi ${row.notes}`} onClick={() => onEdit(row)}><Pencil size={15} /></button>}{onDelete && <button className="danger" aria-label={`Hapus transaksi ${row.notes}`} onClick={() => onDelete(row)}><Trash2 size={15} /></button>}{onCorrect && row.canonical_transaction_id && row.transaction_version && <button disabled={lifecycleBusyId === row.id} aria-label={`Koreksi transaksi ${row.notes}`} onClick={() => onCorrect(row)} {...actionProps(row.scope === 'project' ? 'projects.transaction-correct' : 'office.transaction-correct')}><Pencil size={15} /></button>}{onReverse && row.canonical_transaction_id && row.transaction_version && <button disabled={lifecycleBusyId === row.id} className="danger" aria-label={`Balik transaksi ${row.notes}`} onClick={() => onReverse(row)} {...actionProps(row.scope === 'project' ? 'projects.transaction-reverse' : 'office.transaction-reverse')}><RotateCcw size={15} /></button>}</div></td>}</tr>)}</tbody></table></div>
}


export function OfficeWorkspace({ workspace, onAdd, onEdit, onDelete, onCorrect, onReverse, lifecycleBusyId, readOnly = false, canCreateTransactions = false }: { workspace: FinanceWorkspace; onAdd: () => void; onEdit: (row: FinanceTransaction) => void; onDelete: (row: FinanceTransaction) => void; onCorrect?: (row: FinanceTransaction) => void; onReverse?: (row: FinanceTransaction) => void; lifecycleBusyId?: string | null; readOnly?: boolean; canCreateTransactions?: boolean }) {
  const rows = workspace.transactions.filter((row) => row.scope === 'office').sort((a, b) => b.date.localeCompare(a.date))
  const total = sumMoney(rows.map((row) => row.amount), 'biaya kantor')
  const byWallet = walletBalances({ ...workspace, transactions: rows })
  return <section className="finance-page-stack"><header className="command-head"><div><p className="eyebrow">OPERASIONAL KANTOR{workspace.mode === 'demo' ? ' · DATA DEMO' : ''}</p><h2>Kebutuhan kantor</h2><p>Biaya kantor terpisah dari proyek dan dapat memakai salah satu dompet.</p></div>{(!readOnly || canCreateTransactions) && <button className="primary-button" onClick={onAdd}><Plus size={16} /> Catat biaya</button>}</header><section className="office-summary"><article><CircleDollarSign /><span><small>Total biaya kantor</small><strong>{IDR.format(total)}</strong></span></article>{byWallet.map((item) => <article key={item.wallet}><WalletCards /><span><small>{item.wallet}</small><strong>{IDR.format(item.expense)}</strong></span></article>)}</section><TransactionRows rows={rows} projects={workspace.projects} onEdit={readOnly ? undefined : onEdit} onDelete={readOnly ? undefined : onDelete} onCorrect={onCorrect} onReverse={onReverse} lifecycleBusyId={lifecycleBusyId} /></section>
}

export function DebtWorkspace({ workspace, onAdd, onEdit, onDelete }: { workspace: FinanceWorkspace; onAdd: () => void; onEdit: (row: FinanceDebt) => void; onDelete: (row: FinanceDebt) => void }) {
  const open = sumMoney(workspace.debts.map((debt) => debt.amount - debt.repaid), 'saldo hutang')
  return <section className="finance-page-stack"><header className="command-head"><div><p className="eyebrow">HUTANG INTERNAL{workspace.mode === 'demo' ? ' · DATA DEMO' : ''}</p><h2>Hutang antar-dompet</h2><p>Pergerakan internal ditampilkan terpisah dan tidak mengubah kas konsolidasi.</p></div><button className="primary-button" onClick={onAdd}><Plus size={16} /> Tambah hutang</button></header><section className="debt-total"><BarChart3 /><span><small>Saldo hutang terbuka</small><strong>{IDR.format(open)}</strong></span></section><div className="workspace-table-wrap"><table className="workspace-table"><thead><tr><th>Tanggal</th><th>Peminjam</th><th>Pemberi dana</th><th>Keterangan</th><th>Terbayar</th><th>Terbuka</th><th>Aksi</th></tr></thead><tbody>{workspace.debts.map((debt) => <tr key={debt.id}><td>{dateLabel(debt.date)}</td><td>{debt.borrower}</td><td>{debt.lender}</td><td>{debt.notes}</td><td>{IDR.format(debt.repaid)}</td><td><strong>{IDR.format(debt.amount - debt.repaid)}</strong></td><td><div className="row-actions"><button aria-label={`Ubah hutang ${debt.notes}`} onClick={() => onEdit(debt)}><Pencil size={15} /></button><button className="danger" aria-label={`Hapus hutang ${debt.notes}`} onClick={() => onDelete(debt)}><Trash2 size={15} /></button></div></td></tr>)}</tbody></table></div></section>
}

export function downloadCsv(workspace: FinanceWorkspace) {
  const header = ['Tanggal', 'Jenis', 'Aktivitas', 'Dompet', 'Perusahaan', 'Proyek', 'Kategori', 'Jumlah', 'Keterangan']
  const projectMap = new Map(workspace.projects.map((project) => [project.id, project.name]))
  const cell = (value: unknown) => { let text = String(value ?? ''); if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`; return /[;"\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text }
  const body = workspace.transactions.map((row) => [row.date, directionLabel(row.direction), scopeLabel(row.scope), row.wallet, row.company, projectMap.get(row.project_id ?? ''), row.office_category, row.amount, row.notes].map(cell).join(';'))
  const blob = new Blob([`\uFEFF${[header.join(';'), ...body].join('\r\n')}\r\n`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `hollawall-${workspace.mode}-${new Date().toISOString().slice(0, 10)}.csv`; anchor.click(); URL.revokeObjectURL(url)
}

export function ExportButton({ workspace }: { workspace: FinanceWorkspace }) {
  return <button className="secondary-button export-button" aria-label="Ekspor CSV" onClick={() => downloadCsv(workspace)} {...actionProps('reports.export-csv')}><Download size={16} /><span>Ekspor CSV</span></button>
}
