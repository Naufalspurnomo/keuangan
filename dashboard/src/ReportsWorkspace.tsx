import { useMemo, useState } from 'react'
import { Download, Eye, FileText, SlidersHorizontal } from 'lucide-react'

import { PROJECT_STATUSES, type CompanyId, type FinanceWorkspace, type ProjectStatus, type TransactionDirection, type TransactionScope, type WalletId } from './financeWorkspace'
import { availableReportOptions, buildReportModel, dateLabel, defaultReportFilters, directionLabel, IDR, projectStatusLabel, scopeLabel, type ReportFilters, type ReportModel } from './financeView'

export async function exportReportPdf(model: ReportModel) {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
  const width = doc.internal.pageSize.getWidth()
  doc.setFillColor(43, 41, 38); doc.rect(0, 0, width, 28, 'F')
  doc.setTextColor(255, 255, 255); doc.setFontSize(18); doc.setFont('helvetica', 'bold'); doc.text('Hollawall Group', 14, 12)
  doc.setFontSize(10); doc.setFont('helvetica', 'normal'); doc.text('Laporan Keuangan · DATA DEMO', 14, 20)
  doc.setTextColor(122, 48, 51); doc.setFontSize(34); doc.setFont('helvetica', 'bold'); doc.text('DEMO', width - 46, 20)
  doc.setTextColor(41, 40, 37); doc.setFontSize(9); doc.setFont('helvetica', 'normal')
  const generatedLabel = new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(model.generatedAt)).replace(/\.(?=\d{2}$)/, ':')
  doc.text(`Dibuat ${generatedLabel}`, 14, 36)
  const filterLines = doc.splitTextToSize(`Filter aktif: ${model.scopeText.join(' · ')}`, width - 28)
  doc.text(filterLines, 14, 42)
  const metrics = [
    ['Pemasukan', IDR.format(model.totals.income)], ['Pengeluaran', IDR.format(model.totals.expense)], ['Arus kas bersih', IDR.format(model.totals.net)],
    ['Biaya proyek', IDR.format(model.totals.projectExpense)], ['Operasional Kantor', IDR.format(model.totals.officeExpense)], ['Jumlah transaksi', String(model.rows.length)],
  ]
  autoTable(doc, { startY: 44 + filterLines.length * 4, head: [metrics.map((item) => item[0])], body: [metrics.map((item) => item[1])], theme: 'grid', styles: { fontSize: 8, cellPadding: 2.5 }, headStyles: { fillColor: [75, 72, 66] } })
  autoTable(doc, {
    startY: (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 7,
    head: [['Tanggal', 'Aktivitas', 'Dompet', 'Perusahaan / Proyek', 'Jenis', 'Keterangan', 'Jumlah']],
    body: model.rows.map((row) => [dateLabel(row.date), scopeLabel(row.scope), row.wallet, row.project ? `${row.company ?? ''} · ${row.project}` : row.category ?? 'Operasional Kantor', directionLabel(row.direction), row.notes, `${row.direction === 'income' ? '+' : '-'}${IDR.format(row.amount)}`]),
    theme: 'striped', styles: { fontSize: 7.5, cellPadding: 2, overflow: 'linebreak' }, headStyles: { fillColor: [75, 72, 66] }, alternateRowStyles: { fillColor: [245, 243, 238] },
    didDrawPage: () => { doc.setFontSize(7); doc.setTextColor(100); doc.text('Data demo · bukan laporan produksi', 14, doc.internal.pageSize.getHeight() - 7); doc.text(`Halaman ${doc.getNumberOfPages()}`, width - 30, doc.internal.pageSize.getHeight() - 7) },
  })
  doc.save(`hollawall-laporan-demo-${new Date().toISOString().slice(0, 10)}.pdf`)
  return doc.output('arraybuffer')
}

function Filters({ filters, setFilters, workspace }: { filters: ReportFilters; setFilters: (value: ReportFilters) => void; workspace: FinanceWorkspace }) {
  const options = availableReportOptions(workspace)
  const set = <K extends keyof ReportFilters>(key: K, value: ReportFilters[K]) => setFilters({ ...filters, [key]: value })
  return <section className="report-filter-panel"><header><SlidersHorizontal size={18} /><div><h3>Filter laporan</h3><p>Filter diterapkan langsung ke preview dan PDF.</p></div><button type="button" className="text-button" onClick={() => setFilters(defaultReportFilters(workspace))}>Reset filter</button></header><div className="report-filter-grid"><label><span>Dari tanggal</span><input lang="id-ID" type="date" value={filters.dateFrom} onChange={(event) => set('dateFrom', event.target.value)} /><small>{dateLabel(filters.dateFrom)}</small></label><label><span>Sampai tanggal</span><input lang="id-ID" type="date" min={filters.dateFrom} value={filters.dateTo} onChange={(event) => set('dateTo', event.target.value)} /><small>{dateLabel(filters.dateTo)}</small></label><label><span>Aktivitas</span><select value={filters.scope} onChange={(event) => set('scope', event.target.value as 'all' | TransactionScope)}><option value="all">Semua aktivitas</option><option value="project">Proyek</option><option value="office">Operasional Kantor</option></select></label><label><span>Dompet</span><select value={filters.wallet} onChange={(event) => set('wallet', event.target.value as 'all' | WalletId)}><option value="all">Semua dompet</option>{options.wallets.map((item) => <option key={item}>{item}</option>)}</select></label><label><span>Perusahaan</span><select value={filters.company} onChange={(event) => set('company', event.target.value as 'all' | CompanyId)}><option value="all">Semua perusahaan</option>{options.companies.map((item) => <option key={item}>{item}</option>)}</select></label><label><span>Proyek</span><select value={filters.projectId} onChange={(event) => set('projectId', event.target.value)}><option value="all">Semua proyek</option>{options.projects.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.company}</option>)}</select></label><label><span>Jenis</span><select value={filters.direction} onChange={(event) => set('direction', event.target.value as 'all' | TransactionDirection)}><option value="all">Pemasukan & pengeluaran</option><option value="income">Pemasukan</option><option value="expense">Pengeluaran</option></select></label><label><span>Status proyek</span><select value={filters.projectStatus} onChange={(event) => set('projectStatus', event.target.value as 'all' | ProjectStatus)}><option value="all">Semua status</option>{PROJECT_STATUSES.map((item) => <option key={item} value={item}>{projectStatusLabel(item)}</option>)}</select></label></div></section>
}

export default function ReportsWorkspace({ workspace }: { workspace: FinanceWorkspace }) {
  const [filters, setFilters] = useState(() => defaultReportFilters(workspace))
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const model = useMemo(() => buildReportModel(workspace, filters), [filters, workspace])
  const exportPdf = async () => { setExporting(true); setError(''); try { await exportReportPdf(model) } catch { setError('PDF belum dapat dibuat. Coba lagi.') } finally { setExporting(false) } }
  return <section className="finance-page-stack report-workspace"><header className="command-head"><div><p className="eyebrow">LAPORAN · DATA DEMO</p><h1>Preview dan ekspor PDF</h1><p>Pilih data, periksa hasil, lalu unduh PDF A4 lanskap.</p></div><button className="primary-button" disabled={exporting || !model.rows.length} onClick={exportPdf}><Download size={17} /> {exporting ? 'Membuat PDF…' : 'Ekspor PDF'}</button></header><Filters filters={filters} setFilters={setFilters} workspace={workspace} />{error && <p className="form-error" role="alert">{error}</p>}<section className="report-preview" aria-label="Preview laporan"><header><div><span><Eye size={16} /> PREVIEW PDF · A4 LANDSCAPE</span><h2>Hollawall Group</h2><p>Laporan Keuangan · Data Demo · Dibuat {new Date(model.generatedAt).toLocaleString('id-ID')}</p></div><FileText aria-hidden="true" size={32} /></header><div className="preview-scope" aria-label="Filter aktif">{model.scopeText.map((item) => <span key={item}>{item}</span>)}</div><div className="preview-metrics"><article><small>Pemasukan</small><strong>{IDR.format(model.totals.income)}</strong></article><article><small>Pengeluaran</small><strong>{IDR.format(model.totals.expense)}</strong></article><article><small>Arus kas bersih</small><strong className={model.totals.net >= 0 ? 'positive' : 'negative'}>{IDR.format(model.totals.net)}</strong></article><article><small>Biaya proyek</small><strong>{IDR.format(model.totals.projectExpense)}</strong></article><article><small>Operasional Kantor</small><strong>{IDR.format(model.totals.officeExpense)}</strong></article><article><small>Transaksi</small><strong>{model.rows.length}</strong></article></div>{model.rows.length ? <div className="workspace-table-wrap"><table className="workspace-table preview-table"><thead><tr><th>Tanggal</th><th>Aktivitas</th><th>Dompet</th><th>Perusahaan / Proyek</th><th>Jenis</th><th>Keterangan</th><th className="number">Jumlah</th></tr></thead><tbody>{model.rows.slice(0, 50).map((row) => <tr key={row.id}><td>{dateLabel(row.date)}</td><td>{scopeLabel(row.scope)}</td><td>{row.wallet}</td><td>{row.project ? <><strong>{row.project}</strong><small>{row.company}</small></> : row.category}</td><td><span className={`direction-chip ${row.direction}`}>{directionLabel(row.direction)}</span></td><td>{row.notes}</td><td className={`number ${row.direction === 'income' ? 'positive' : 'negative'}`}>{row.direction === 'income' ? '+' : '−'}{IDR.format(row.amount)}</td></tr>)}</tbody></table>{model.rows.length > 50 && <p className="preview-note">Preview menampilkan 50 dari {model.rows.length} transaksi. PDF memuat seluruh transaksi.</p>}</div> : <div className="command-empty"><strong>Tidak ada data</strong><p>Ubah filter untuk menampilkan transaksi.</p></div>}<span className="report-watermark">DEMO</span></section></section>
}
