import { useMemo, useState } from 'react'
import { Download, Eye, FileText, SlidersHorizontal } from 'lucide-react'

import { actionProps } from './actionRegistry'
import {
  CANONICAL_REPORT_TYPES,
  buildCanonicalReportDataset,
  canonicalDatasetHash,
  type CanonicalReportDataset,
  type CanonicalReportType,
} from './canonicalReports'
import {
  PROJECT_STATUSES,
  type CompanyId,
  type FinanceWorkspace,
  type ProjectStatus,
  type TransactionDirection,
  type TransactionScope,
  type WalletId,
} from './financeWorkspace'
import {
  availableReportOptions,
  buildReportModel,
  dateLabel,
  defaultReportFilters,
  projectStatusLabel,
  type ReportFilters,
} from './financeView'

const dateTimeLabel = (value: string) => new Intl.DateTimeFormat('id-ID', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta',
}).format(new Date(value)).replace(/\.(?=\d{2}$)/, ':')

function downloadBlob(bytes: BlobPart, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([bytes], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

const safeCsvCell = (value: string) => {
  const safe = /^[=+\-@]/.test(value) ? `'${value}` : value
  return `"${safe.replace(/"/g, '""')}"`
}

export function exportReportCsv(dataset: CanonicalReportDataset) {
  const rows = [dataset.headers, ...dataset.rows]
  const csv = `\uFEFF${rows.map((row) => row.map(safeCsvCell).join(',')).join('\r\n')}`
  downloadBlob(csv, `hollawall-${dataset.type}-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv;charset=utf-8')
}

export async function exportReportPdf(dataset: CanonicalReportDataset) {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const datasetHash = await canonicalDatasetHash(dataset)
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
  const width = doc.internal.pageSize.getWidth()
  doc.setFillColor(43, 41, 38)
  doc.rect(0, 0, width, 28, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(18)
  doc.setFont('helvetica', 'bold')
  doc.text('Hollawall Group', 14, 12)
  doc.setFontSize(10)
  doc.setFont('helvetica', 'normal')
  doc.text(dataset.title, 14, 20)
  doc.setTextColor(41, 40, 37)
  doc.setFontSize(8)
  const metadata = [
    `Dibuat: ${dateTimeLabel(dataset.generatedAt)}`,
    `Data sampai: ${dataset.dataThrough ? dateTimeLabel(dataset.dataThrough) : 'belum ada transaksi'}`,
    `Sumber: ${dataset.source}`,
    `Jumlah record: ${dataset.rows.length}`,
    `Dataset SHA-256: ${datasetHash}`,
    `Filter: ${dataset.scope.join(' · ')}`,
  ]
  doc.text(metadata, 14, 35)
  autoTable(doc, {
    startY: 63,
    head: [dataset.totals.map(([label]) => label)],
    body: [dataset.totals.map(([, value]) => value)],
    theme: 'grid', styles: { fontSize: 8, cellPadding: 2.5 }, headStyles: { fillColor: [75, 72, 66] },
  })
  autoTable(doc, {
    startY: (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 7,
    head: [dataset.headers], body: dataset.rows,
    theme: 'striped', styles: { fontSize: 7, cellPadding: 1.8, overflow: 'linebreak' },
    headStyles: { fillColor: [75, 72, 66] }, alternateRowStyles: { fillColor: [245, 243, 238] },
    didDrawPage: () => {
      doc.setFontSize(7)
      doc.setTextColor(100)
      doc.text(`Dataset ${datasetHash.slice(0, 16)}…`, 14, doc.internal.pageSize.getHeight() - 7)
      doc.text(`Halaman ${doc.getNumberOfPages()}`, width - 30, doc.internal.pageSize.getHeight() - 7)
    },
  })
  const bytes = doc.output('arraybuffer')
  const artifactHash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('')
  const baseName = `hollawall-${dataset.type}-${new Date().toISOString().slice(0, 10)}`
  downloadBlob(bytes, `${baseName}.pdf`, 'application/pdf')
  downloadBlob(JSON.stringify({ dataset_hash: datasetHash, artifact_hash: artifactHash, report_type: dataset.type, generated_at: dataset.generatedAt }, null, 2), `${baseName}.manifest.json`, 'application/json')
  return { bytes, datasetHash, artifactHash }
}

function Filters({ filters, setFilters, workspace }: { filters: ReportFilters; setFilters: (value: ReportFilters) => void; workspace: FinanceWorkspace }) {
  const options = availableReportOptions(workspace)
  const set = <K extends keyof ReportFilters>(key: K, value: ReportFilters[K]) => setFilters({ ...filters, [key]: value })
  return <section className="report-filter-panel">
    <header><SlidersHorizontal size={18} /><div><h3>Filter laporan</h3><p>Filter diterapkan ke dataset, CSV, dan PDF.</p></div><button type="button" className="text-button" onClick={() => setFilters(defaultReportFilters(workspace))} {...actionProps('reports.filters-reset')}>Reset filter</button></header>
    <div className="report-filter-grid">
      <label><span>Dari tanggal</span><input type="date" value={filters.dateFrom} onChange={(event) => set('dateFrom', event.target.value)} /></label>
      <label><span>Sampai tanggal</span><input type="date" min={filters.dateFrom} value={filters.dateTo} onChange={(event) => set('dateTo', event.target.value)} /></label>
      <label><span>Aktivitas</span><select value={filters.scope} onChange={(event) => set('scope', event.target.value as 'all' | TransactionScope)}><option value="all">Semua aktivitas</option><option value="project">Proyek</option><option value="office">Operasional Kantor</option></select></label>
      <label><span>Dompet</span><select value={filters.wallet} onChange={(event) => set('wallet', event.target.value as 'all' | WalletId)}><option value="all">Semua dompet</option>{options.wallets.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label><span>Perusahaan</span><select value={filters.company} onChange={(event) => set('company', event.target.value as 'all' | CompanyId)}><option value="all">Semua perusahaan</option>{options.companies.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label><span>Proyek</span><select value={filters.projectId} onChange={(event) => set('projectId', event.target.value)}><option value="all">Semua proyek</option>{options.projects.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.company}</option>)}</select></label>
      <label><span>Jenis</span><select value={filters.direction} onChange={(event) => set('direction', event.target.value as 'all' | TransactionDirection)}><option value="all">Pemasukan & pengeluaran</option><option value="income">Pemasukan</option><option value="expense">Pengeluaran</option></select></label>
      <label><span>Status proyek</span><select value={filters.projectStatus} onChange={(event) => set('projectStatus', event.target.value as 'all' | ProjectStatus)}><option value="all">Semua status</option>{PROJECT_STATUSES.map((item) => <option key={item} value={item}>{projectStatusLabel(item)}</option>)}</select></label>
    </div>
  </section>
}

export default function ReportsWorkspace({ workspace }: { workspace: FinanceWorkspace }) {
  const [filters, setFilters] = useState(() => defaultReportFilters(workspace))
  const [reportType, setReportType] = useState<CanonicalReportType>('cashflow')
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const model = useMemo(() => buildReportModel(workspace, filters), [filters, workspace])
  const dataset = useMemo(() => buildCanonicalReportDataset(workspace, model, reportType), [model, reportType, workspace])
  const exportPdf = async () => {
    setExporting(true)
    setError('')
    try { await exportReportPdf(dataset) } catch { setError('PDF belum dapat dibuat. Coba lagi.') } finally { setExporting(false) }
  }
  const demoSuffix = workspace.mode === 'demo' ? ' · DATA DEMO' : ''
  return <section className="finance-page-stack report-workspace">
    <header className="command-head"><div><p className="eyebrow">LAPORAN{demoSuffix}</p><h1>Pusat laporan kanonis</h1><p>Pilih dataset, periksa provenance, lalu ekspor CSV atau PDF terverifikasi.</p></div><div className="report-export-actions"><button className="secondary-button export-button" disabled={!dataset.rows.length} onClick={() => exportReportCsv(dataset)} {...actionProps('reports.export-csv')}><Download size={16} /> Ekspor CSV</button><button className="primary-button" disabled={exporting || !dataset.rows.length} onClick={exportPdf} {...actionProps('reports.export-pdf')}><Download size={17} /> {exporting ? 'Membuat PDF…' : 'Ekspor PDF'}</button></div></header>
    <label className="field"><span>Jenis laporan</span><select aria-label="Jenis laporan" value={reportType} onChange={(event) => setReportType(event.target.value as CanonicalReportType)}>{CANONICAL_REPORT_TYPES.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
    <Filters filters={filters} setFilters={setFilters} workspace={workspace} />
    {error && <p className="form-error" role="alert">{error}</p>}
    <section className="report-preview" aria-label="Pratinjau laporan">
      <header><div><span><Eye size={16} /> PRATINJAU DATASET KANONIS</span><h2>{dataset.title}</h2><p>{dataset.source}</p><p>Data sampai {dataset.dataThrough ? dateTimeLabel(dataset.dataThrough) : 'belum ada transaksi'} · Dibuat {dateTimeLabel(dataset.generatedAt)}</p></div><FileText aria-hidden="true" size={32} /></header>
      <div className="preview-scope" aria-label="Filter aktif">{dataset.scope.map((item) => <span key={item}>{item}</span>)}</div>
      <div className="preview-metrics">{dataset.totals.map(([label, value]) => <article key={label}><small>{label}</small><strong>{value}</strong></article>)}</div>
      {dataset.rows.length ? <div className="workspace-table-wrap"><table className="workspace-table preview-table"><thead><tr>{dataset.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{dataset.rows.map((row, index) => <tr key={`${reportType}-${index}`}>{row.map((cell, cellIndex) => <td key={`${cellIndex}-${cell}`}>{cell}</td>)}</tr>)}</tbody></table></div> : <div className="empty-report"><FileText size={26} /><strong>Tidak ada data pada filter ini.</strong><span>Ubah filter atau tambahkan data kanonis terlebih dahulu.</span></div>}
    </section>
  </section>
}
