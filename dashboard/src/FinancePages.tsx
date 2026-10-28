import { useEffect, useMemo, useState } from 'react'
import { BarChart3, CircleDollarSign, Download, Pencil, Plus, RotateCcw, Search, Trash2, WalletCards } from 'lucide-react'

import { sumMoney, workspaceTotals, type FinanceDebt, type FinanceProject, type FinanceTransaction, type FinanceWorkspace, type TransactionScope } from './financeWorkspace'
import { dateLabel, directionLabel, IDR, monthlyCashflow, projectLabel, projectView, scopeLabel, walletBalances } from './financeView'

export function DemoBanner({ updatedAt, onReset }: { updatedAt: string; onReset: () => void }) {
  return <section className="demo-workspace-banner" aria-label="Status data demo"><div><strong>Data demo</strong><span>Perubahan tersimpan di browser ini. Tidak terhubung ke buku besar produksi.</span></div><small>Diperbarui {new Date(updatedAt).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })}</small><button type="button" onClick={onReset}><RotateCcw size={15} /> Reset demo</button></section>
}

export function OverviewWorkspace({ workspace, onAddTransaction, onAddProject, onAddOffice }: { workspace: FinanceWorkspace; onAddTransaction: () => void; onAddProject: () => void; onAddOffice: () => void }) {
  const totals = workspaceTotals(workspace)
  const balances = walletBalances(workspace)
  const active = workspace.projects.filter((project) => project.status === 'active').length
  const completed = workspace.projects.filter((project) => project.status === 'completed').length
  const openDebt = sumMoney(workspace.debts.map((debt) => debt.amount - debt.repaid), 'saldo hutang')
  const recent = [...workspace.transactions].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 6)
  const audit = [...workspace.audit].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 6)
  return <div className="finance-page-stack">
    <section className="overview-command"><div><p className="eyebrow">RINGKASAN · DATA DEMO</p><h1>Posisi keuangan Hollawall</h1><p>Angka berikut dihitung dari transaksi demo yang sama.</p></div><div className="quick-actions"><button className="primary-button" onClick={onAddTransaction}><Plus size={16} /> Transaksi</button><button className="secondary-button" onClick={onAddProject}>Tambah proyek</button><button className="secondary-button" onClick={onAddOffice}>Biaya kantor</button></div></section>
    <section className="finance-kpis"><article><small>Arus kas bersih</small><strong className={totals.net >= 0 ? 'positive' : 'negative'}>{IDR.format(totals.net)}</strong><span>{IDR.format(totals.income)} masuk · {IDR.format(totals.expense)} keluar</span></article><article><small>Proyek aktif</small><strong>{active}</strong><span>{completed} proyek selesai</span></article><article><small>Operasional Kantor</small><strong>{IDR.format(totals.office)}</strong><span>Pengeluaran kantor tercatat</span></article><article><small>Hutang internal terbuka</small><strong>{IDR.format(openDebt)}</strong><span>Tidak mengubah kas konsolidasi</span></article></section>
    <section className="wallet-command"><header><div><p className="eyebrow">POSISI DOMPET</p><h2>Tiga sumber dana</h2></div></header><div>{balances.map((item) => { const expenseShare = item.income ? Math.round((item.expense / item.income) * 100) : 0; return <article key={item.wallet}><span><WalletCards size={18} /><strong>{item.wallet}</strong></span><b>{IDR.format(item.balance)}</b><small>Penyesuaian hutang: {IDR.format(item.adjusted)}</small><i><em style={{ width: `${Math.max(4, Math.min(100, expenseShare))}%` }} /></i><small>{expenseShare}% pemasukan telah digunakan</small></article> })}</div></section>
    <section className="recent-command"><header><div><p className="eyebrow">TRANSAKSI TERBARU</p><h2>Aktivitas terakhir</h2></div></header><TransactionRows rows={recent} projects={workspace.projects} compact /></section>
    <section className="audit-command"><header><div><p className="eyebrow">RIWAYAT PERUBAHAN</p><h2>Audit data demo</h2></div><small>{workspace.audit.length} perubahan tercatat</small></header>{audit.length ? <ol>{audit.map((event) => <li key={event.id}><span className={`audit-action ${event.action}`}>{event.action === 'create' ? 'Tambah' : event.action === 'update' ? 'Ubah' : event.action === 'delete' ? 'Hapus' : 'Reset'}</span><div><strong>{event.summary}</strong><small>{new Date(event.at).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })}</small></div></li>)}</ol> : <div className="audit-empty">Belum ada perubahan manual pada data demo.</div>}</section>
  </div>
}

export function CashflowWorkspacePage({ workspace }: { workspace: FinanceWorkspace }) {
  const years = [...new Set(workspace.transactions.map((row) => Number(row.date.slice(0, 4))))].sort((a, b) => a - b)
  const [year, setYear] = useState(years.at(-1) ?? new Date().getFullYear())
  const months = monthlyCashflow(workspace.transactions, year)
  const max = Math.max(...months.flatMap((month) => [month.income, month.expense]), 1)
  const labels = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
  const annual = months.reduce((sum, row) => sum + row.net, 0)
  return <section className="finance-page-stack"><header className="command-head"><div><p className="eyebrow">ARUS KAS · DATA DEMO</p><h2>Pergerakan kas bulanan</h2><p>Transfer dan hutang internal tidak dihitung sebagai pemasukan atau pengeluaran.</p></div><select aria-label="Tahun arus kas" value={year} onChange={(event) => setYear(Number(event.target.value))}>{years.map((item) => <option key={item}>{item}</option>)}</select></header><section className="cashflow-bars"><header><span><i className="income" /> Pemasukan</span><span><i className="expense" /> Pengeluaran</span><strong className={annual >= 0 ? 'positive' : 'negative'}>Bersih {IDR.format(annual)}</strong></header><div>{months.map((month) => <article key={month.month}><div><i className="income" style={{ height: `${(month.income / max) * 100}%` }} /><i className="expense" style={{ height: `${(month.expense / max) * 100}%` }} /></div><strong>{labels[month.month]}</strong><small>{IDR.format(month.net)}</small></article>)}</div></section></section>
}

export function WalletWorkspacePage({ workspace }: { workspace: FinanceWorkspace }) {
  return <section className="finance-page-stack"><header className="command-head"><div><p className="eyebrow">DOMPET · DATA DEMO</p><h2>Sumber dana dan perusahaan</h2><p>Saldo berasal dari seluruh transaksi demo pada setiap dompet.</p></div></header><section className="wallet-detail-grid">{walletBalances(workspace).map((item) => { const companies = item.wallet === 'CV HB' ? ['Holla', 'Hojja'] : item.wallet === 'TX SBY' ? ['Texturin Surabaya'] : ['Texturin Bali']; const projects = workspace.projects.filter((project) => project.wallet === item.wallet); return <article key={item.wallet}><header><WalletCards /><div><h3>{item.wallet}</h3><p>{companies.join(' · ')}</p></div></header><strong>{IDR.format(item.balance)}</strong><div><span><small>Pemasukan</small><b>{IDR.format(item.income)}</b></span><span><small>Pengeluaran</small><b>{IDR.format(item.expense)}</b></span><span><small>Dipinjam</small><b>{IDR.format(item.borrowed)}</b></span><span><small>Dipinjamkan</small><b>{IDR.format(item.lent)}</b></span></div><footer>{projects.length} proyek · posisi setelah hutang {IDR.format(item.adjusted)}</footer></article> })}</section></section>
}

function TransactionRows({ rows, projects, compact, onEdit, onDelete }: { rows: FinanceTransaction[]; projects: FinanceProject[]; compact?: boolean; onEdit?: (row: FinanceTransaction) => void; onDelete?: (row: FinanceTransaction) => void }) {
  const map = new Map(projects.map((project) => [project.id, project]))
  return <div className="workspace-table-wrap"><table className="workspace-table"><thead><tr><th>Tanggal</th><th>Keterangan</th><th>Aktivitas</th><th>Dompet</th><th>Jenis</th><th className="number">Jumlah</th>{!compact && <th>Aksi</th>}</tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td data-label="Tanggal">{dateLabel(row.date)}</td><td data-label="Keterangan"><strong>{row.notes}</strong><small>{row.office_category ?? row.company ?? '—'}</small></td><td data-label="Aktivitas">{row.scope === 'project' ? projectLabel(map.get(row.project_id ?? '')) : 'Operasional Kantor'}</td><td data-label="Dompet"><span className="wallet-chip">{row.wallet}</span></td><td data-label="Jenis"><span className={`direction-chip ${row.direction}`}>{directionLabel(row.direction)}</span></td><td data-label="Jumlah" className={`number ${row.direction === 'income' ? 'positive' : 'negative'}`}>{row.direction === 'income' ? '+' : '−'}{IDR.format(row.amount)}</td>{!compact && <td data-label="Aksi"><div className="row-actions"><button aria-label={`Ubah transaksi ${row.notes}`} onClick={() => onEdit?.(row)}><Pencil size={15} /></button><button className="danger" aria-label={`Hapus transaksi ${row.notes}`} onClick={() => onDelete?.(row)}><Trash2 size={15} /></button></div></td>}</tr>)}</tbody></table></div>
}

export function TransactionsWorkspace({ workspace, initialProjectId, onAdd, onEdit, onDelete }: { workspace: FinanceWorkspace; initialProjectId?: string; onAdd: () => void; onEdit: (row: FinanceTransaction) => void; onDelete: (row: FinanceTransaction) => void }) {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'all' | TransactionScope>('all')
  const [projectId, setProjectId] = useState(initialProjectId ?? 'all')
  useEffect(() => setProjectId(initialProjectId ?? 'all'), [initialProjectId])
  const rows = workspace.transactions.filter((row) => (scope === 'all' || row.scope === scope) && (projectId === 'all' || row.project_id === projectId) && (!query.trim() || `${row.notes} ${row.wallet} ${row.company ?? ''} ${row.office_category ?? ''}`.toLocaleLowerCase('id-ID').includes(query.trim().toLocaleLowerCase('id-ID')))).sort((a, b) => b.date.localeCompare(a.date))
  return <section className="finance-page-stack"><header className="command-head"><div><p className="eyebrow">TRANSAKSI · DATA DEMO</p><h2>Semua transaksi</h2><p>Ubah data demo dan lihat seluruh ringkasan diperbarui otomatis.</p></div><button className="primary-button" onClick={onAdd}><Plus size={16} /> Tambah transaksi</button></header><div className="workspace-filters"><label className="command-search"><Search size={17} /><input aria-label="Cari transaksi" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari transaksi" /></label><select aria-label="Filter aktivitas" value={scope} onChange={(event) => setScope(event.target.value as 'all' | TransactionScope)}><option value="all">Semua aktivitas</option><option value="project">Proyek</option><option value="office">Operasional Kantor</option></select><select aria-label="Filter proyek" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="all">Semua proyek</option>{workspace.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.company}</option>)}</select><span><strong>{rows.length}</strong> transaksi</span></div><TransactionRows rows={rows} projects={workspace.projects} onEdit={onEdit} onDelete={onDelete} /></section>
}

export function OfficeWorkspace({ workspace, onAdd, onEdit, onDelete }: { workspace: FinanceWorkspace; onAdd: () => void; onEdit: (row: FinanceTransaction) => void; onDelete: (row: FinanceTransaction) => void }) {
  const rows = workspace.transactions.filter((row) => row.scope === 'office').sort((a, b) => b.date.localeCompare(a.date))
  const total = sumMoney(rows.map((row) => row.amount), 'biaya kantor')
  const byWallet = walletBalances({ ...workspace, transactions: rows })
  return <section className="finance-page-stack"><header className="command-head"><div><p className="eyebrow">OPERASIONAL KANTOR · DATA DEMO</p><h2>Kebutuhan kantor</h2><p>Biaya kantor terpisah dari proyek dan dapat memakai salah satu dompet.</p></div><button className="primary-button" onClick={onAdd}><Plus size={16} /> Catat biaya</button></header><section className="office-summary"><article><CircleDollarSign /><span><small>Total biaya kantor</small><strong>{IDR.format(total)}</strong></span></article>{byWallet.map((item) => <article key={item.wallet}><WalletCards /><span><small>{item.wallet}</small><strong>{IDR.format(item.expense)}</strong></span></article>)}</section><TransactionRows rows={rows} projects={workspace.projects} onEdit={onEdit} onDelete={onDelete} /></section>
}

export function DebtWorkspace({ workspace, onAdd, onEdit, onDelete }: { workspace: FinanceWorkspace; onAdd: () => void; onEdit: (row: FinanceDebt) => void; onDelete: (row: FinanceDebt) => void }) {
  const open = sumMoney(workspace.debts.map((debt) => debt.amount - debt.repaid), 'saldo hutang')
  return <section className="finance-page-stack"><header className="command-head"><div><p className="eyebrow">HUTANG INTERNAL · DATA DEMO</p><h2>Hutang antar-dompet</h2><p>Pergerakan internal ditampilkan terpisah dan tidak mengubah kas konsolidasi.</p></div><button className="primary-button" onClick={onAdd}><Plus size={16} /> Tambah hutang</button></header><section className="debt-total"><BarChart3 /><span><small>Saldo hutang terbuka</small><strong>{IDR.format(open)}</strong></span></section><div className="workspace-table-wrap"><table className="workspace-table"><thead><tr><th>Tanggal</th><th>Peminjam</th><th>Pemberi dana</th><th>Keterangan</th><th>Terbayar</th><th>Terbuka</th><th>Aksi</th></tr></thead><tbody>{workspace.debts.map((debt) => <tr key={debt.id}><td>{dateLabel(debt.date)}</td><td>{debt.borrower}</td><td>{debt.lender}</td><td>{debt.notes}</td><td>{IDR.format(debt.repaid)}</td><td><strong>{IDR.format(debt.amount - debt.repaid)}</strong></td><td><div className="row-actions"><button aria-label={`Ubah hutang ${debt.notes}`} onClick={() => onEdit(debt)}><Pencil size={15} /></button><button className="danger" aria-label={`Hapus hutang ${debt.notes}`} onClick={() => onDelete(debt)}><Trash2 size={15} /></button></div></td></tr>)}</tbody></table></div></section>
}

export function downloadCsv(workspace: FinanceWorkspace) {
  const header = ['Tanggal', 'Jenis', 'Aktivitas', 'Dompet', 'Perusahaan', 'Proyek', 'Kategori', 'Jumlah', 'Keterangan']
  const projectMap = new Map(workspace.projects.map((project) => [project.id, project.name]))
  const cell = (value: unknown) => { let text = String(value ?? ''); if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`; return /[;"\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text }
  const body = workspace.transactions.map((row) => [row.date, directionLabel(row.direction), scopeLabel(row.scope), row.wallet, row.company, projectMap.get(row.project_id ?? ''), row.office_category, row.amount, row.notes].map(cell).join(';'))
  const blob = new Blob([`\uFEFF${[header.join(';'), ...body].join('\r\n')}\r\n`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `hollawall-demo-${new Date().toISOString().slice(0, 10)}.csv`; anchor.click(); URL.revokeObjectURL(url)
}

export function ExportButton({ workspace }: { workspace: FinanceWorkspace }) {
  return <button className="secondary-button" onClick={() => downloadCsv(workspace)}><Download size={16} /> Ekspor CSV</button>
}
