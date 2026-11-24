import { Eye, RefreshCw, ScanLine, ShieldCheck, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { projectProfitAndLoss, type FinanceProject, type FinanceTransaction } from './financeWorkspace'
import type { ExpenseClassification, ProjectDocumentApi, ProjectDocumentSession } from './projectDocumentApi'
import { createProjectEvidenceApi, type ProjectEvidenceApi, type ProjectTransactionEvidence } from './projectEvidenceApi'
import type { ProjectPaymentSummary } from './projectDocuments'
import { visibleProjectStatus } from './projectStatus'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const COMPACT = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 1 })
const SALARY = /\b(?:gaji|upah|honor|fee\s+(?:tukang|pekerja)|borongan|lembur|mandor|kuli|buruh|salary|wage)\b/i

function sum(rows: FinanceTransaction[]) {
  return rows.reduce((total, row) => total + row.amount, 0)
}

function evidenceLabel(row: FinanceTransaction) {
  if (row.evidence_source === 'media_ocr') return row.ocr_mode ? `Media OCR · ${row.ocr_mode}` : 'Media OCR'
  if (row.evidence_source === 'message') return 'Pesan sumber tercatat'
  return row.input_source || 'Input manual'
}

function monthLabel(value: string) {
  const parsed = new Date(`${value}-01T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('id-ID', { month: 'short', year: '2-digit', timeZone: 'UTC' })
}

export default function ProjectProfitabilityWorkspace({ project, rows, api, session, evidenceApi: suppliedEvidenceApi, initialView = 'summary', showProfitability = visibleProjectStatus(project.status) === 'completed' }: {
  project: FinanceProject
  rows: FinanceTransaction[]
  api: ProjectDocumentApi
  session?: ProjectDocumentSession
  evidenceApi?: ProjectEvidenceApi
  initialView?: 'summary' | 'profit' | 'cash'
  showProfitability?: boolean
}) {
  const evidenceApi = useMemo(() => suppliedEvidenceApi ?? createProjectEvidenceApi(), [suppliedEvidenceApi])
  const [summary, setSummary] = useState<ProjectPaymentSummary | null>(null)
  const [evidence, setEvidence] = useState<ProjectTransactionEvidence[]>([])
  const [loading, setLoading] = useState(true)
  const [evidenceBusy, setEvidenceBusy] = useState('')
  const [error, setError] = useState('')
  const [evidenceError, setEvidenceError] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [view, setView] = useState<'summary' | 'profit' | 'cash'>(initialView)
  const [showAllRows, setShowAllRows] = useState(false)
  const [showAllExpenses, setShowAllExpenses] = useState(false)
  const [classifications, setClassifications] = useState<ExpenseClassification[] | null>(null)
  const [classificationError, setClassificationError] = useState('')
  const [classifying, setClassifying] = useState('')
  const activeController = useRef(0)
  const classificationController = useRef(0)
  const activeProjectId = useRef(project.id)
  activeProjectId.current = project.id

  const load = useCallback(async () => {
    const request = ++activeController.current
    setLoading(true)
    setError('')
    setSummary(null)
    try {
      const next = await api.getPaymentSummary(project.id)
      if (request === activeController.current) setSummary(next)
    } catch {
      if (request === activeController.current) {
        setSummary(null)
        setError('Nilai kontrak dan sisa kontrak belum dapat dimuat.')
      }
    } finally {
      if (request === activeController.current) setLoading(false)
    }
  }, [api, project.id])

  useEffect(() => {
    void load()
    return () => { activeController.current += 1 }
  }, [load])

  const loadClassifications = useCallback(async () => {
    const request = ++classificationController.current
    setClassifications(null)
    setClassificationError('')
    try {
      const result = await api.listExpenseClassifications(project.id)
      if (request === classificationController.current) setClassifications(result)
    } catch {
      if (request === classificationController.current) setClassificationError('Pemeriksaan jenis pengeluaran belum dapat dimuat.')
    }
  }, [api, project.id])
  useEffect(() => { void loadClassifications(); return () => { classificationController.current += 1 } }, [loadClassifications])

  const classify = async (row: FinanceTransaction, classification: ExpenseClassification['classification']) => {
    if (!session) return
    setClassifying(row.id)
    setClassificationError('')
    try {
      await api.classifyExpense(project.id, row.id, classification, { amount: row.amount, date: row.date, description: row.notes, category: row.category ?? null }).submit(session)
      if (activeProjectId.current === project.id) await loadClassifications()
    } catch (reason) {
      if (activeProjectId.current === project.id) setClassificationError(reason instanceof Error ? reason.message : 'Jenis pengeluaran belum dapat disimpan.')
    } finally {
      setClassifying('')
    }
  }

  const loadEvidence = useCallback(async () => {
    setEvidenceError('')
    try {
      setEvidence(await evidenceApi.list(project.id))
    } catch {
      setEvidence([])
      setEvidenceError('Bukti transaksi belum dapat dimuat.')
    }
  }, [evidenceApi, project.id])

  useEffect(() => { void loadEvidence() }, [loadEvidence])

  const uploadEvidence = async (row: FinanceTransaction, file: File | undefined) => {
    if (!file || !session) return
    setEvidenceBusy(row.id)
    setEvidenceError('')
    try {
      await evidenceApi.upload(project.id, row.id, file, session)
      await loadEvidence()
    } catch (uploadError) {
      setEvidenceError(uploadError instanceof Error ? uploadError.message : 'Bukti gagal diunggah.')
    } finally {
      setEvidenceBusy('')
    }
  }

  const reviewEvidence = async (item: ProjectTransactionEvidence, status: 'approved' | 'rejected') => {
    if (!session) return
    const note = status === 'rejected' ? window.prompt('Alasan penolakan bukti:') : ''
    if (note === null || (status === 'rejected' && !note.trim())) return
    if (!window.confirm(status === 'approved' ? 'Setujui bukti ini?' : 'Tolak bukti ini?')) return
    setEvidenceBusy(item.id)
    setEvidenceError('')
    try {
      await evidenceApi.review(item, status, note, session)
      await loadEvidence()
    } catch (reviewError) {
      setEvidenceError(reviewError instanceof Error ? reviewError.message : 'Review bukti gagal.')
    } finally {
      setEvidenceBusy('')
    }
  }

  const openEvidence = async (item: ProjectTransactionEvidence) => {
    setEvidenceBusy(item.id)
    setEvidenceError('')
    try {
      const blob = await evidenceApi.download(item.id)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener,noreferrer')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (downloadError) {
      setEvidenceError(downloadError instanceof Error ? downloadError.message : 'Bukti gagal dibuka.')
    } finally {
      setEvidenceBusy('')
    }
  }

  const evidenceBySource = useMemo(() => {
    const map = new Map<string, ProjectTransactionEvidence>()
    evidence.forEach((item) => { if (!map.has(item.ledger_source_key)) map.set(item.ledger_source_key, item) })
    return map
  }, [evidence])

  const filteredRows = useMemo(() => rows.filter((row) => (!dateFrom || row.date >= dateFrom) && (!dateTo || row.date <= dateTo)), [rows, dateFrom, dateTo])
  const report = useMemo(() => {
    const pnl = projectProfitAndLoss(project, rows)
    const salary = sum(rows.filter((row) => row.direction === 'expense' && SALARY.test(`${row.category || ''} ${row.notes}`)))
    const monthly = [...filteredRows.reduce((map, row) => {
      const key = row.date.slice(0, 7)
      const item = map.get(key) || { month: key, income: 0, expense: 0 }
      item[row.direction] += row.amount
      map.set(key, item)
      return map
    }, new Map<string, { month: string; income: number; expense: number }>())].map(([, value]) => value).sort((a, b) => a.month.localeCompare(b.month))
    return { ...pnl, salary, monthly }
  }, [project, rows, filteredRows])

  const contract = summary?.contract_total ?? null
  const expenses = rows.filter((row) => row.direction === 'expense')
  const margin = report.finalized ? report.net : null
  const marginPct = contract && margin !== null ? (margin / contract) * 100 : null
  const financeViews = showProfitability
    ? ([['summary', 'Ringkasan'], ['profit', 'Laba Rugi'], ['cash', 'Arus Kas']] as const)
    : ([['summary', 'Ringkasan'], ['cash', 'Arus Kas']] as const)

  return <section className="project-profitability" aria-busy={loading}>
    <header className="project-profitability-head">
      <div><p className="eyebrow">KEUANGAN PROJECT</p><h2>Ringkasan keuangan</h2><p>Dompet {project.wallet} · {rows.length} transaksi tercatat</p></div>
      <button type="button" className="secondary-button" onClick={() => { void load(); void loadClassifications() }} disabled={loading}><RefreshCw size={15} /> Perbarui ringkasan</button>
    </header>
    {error && <p role="alert" className="document-state-alert">{error}</p>}
    {classificationError && <p role="alert" className="document-state-alert">{classificationError}</p>}
    <nav className="project-finance-nav" aria-label="Bagian keuangan proyek">{financeViews.map(([id, label]) => <button type="button" key={id} aria-pressed={view === id} onClick={() => setView(id)}>{label}</button>)}</nav>
    <div className="project-finance-pane" hidden={view !== 'summary'}>
    <section className="project-profitability-metrics" aria-label={`Ringkasan kas ${project.name}`}>
      <article><small>Nilai kontrak</small><strong>{contract === null ? '—' : IDR.format(contract)}</strong></article>
      <article><small>Kas masuk</small><strong className="positive">{IDR.format(report.income)}</strong></article>
      <article><small>Sisa nilai kontrak</small><strong>{summary?.contract_outstanding == null ? '—' : IDR.format(summary.contract_outstanding)}</strong><span>Menurut alokasi pembayaran</span></article>
      <article><small>Invoice belum lunas</small><strong>{summary == null ? '—' : IDR.format(summary.invoices.reduce((total, invoice) => total + invoice.outstanding, 0))}</strong><span>Berbeda dari sisa nilai kontrak</span></article>
      <article><small>Pengeluaran Project tercatat</small><strong className="negative">{IDR.format(report.expense)}</strong></article>
      <article><small>Gaji/upah tercatat</small><strong>{IDR.format(report.salary)}</strong></article>
      <article><small>Arus kas bersih</small><strong className={report.net >= 0 ? 'positive' : 'negative'}>{IDR.format(report.net)}</strong></article>
      <article><small>Perkiraan laba/rugi sementara</small><strong className={margin === null || margin >= 0 ? 'positive' : 'negative'}>{margin === null ? '—' : IDR.format(margin)}</strong>{marginPct !== null && <span>{marginPct.toLocaleString('id-ID', { maximumFractionDigits: 1 })}% dari nilai kontrak</span>}</article>
    </section>
    <p className="payment-summary-warning">{report.finalized ? 'Laba rugi final berdasarkan seluruh pemasukan dan pengeluaran Project. Transaksi baru tetap memperbarui angka ini secara realtime.' : 'Laba rugi akan tersedia setelah Project dinyatakan selesai.'}</p>
    </div>
    <div className="project-finance-pane" hidden={view !== 'profit'}>
    <section id="project-finance-profit" className="project-cost-breakdown" aria-label="Laba rugi proyek">
      <h3>{report.finalized ? 'Laba Rugi Final' : 'Laba Rugi'}</h3>
      {!report.finalized ? <p>Laporan muncul otomatis setelah Project berstatus Selesai.</p> : <>
        <div className="project-profitability-metrics">
          <article><small>Total pemasukan</small><strong className="positive">{IDR.format(report.income)}</strong></article>
          <article><small>Total pengeluaran</small><strong className="negative">{IDR.format(report.expense)}</strong></article>
          <article><small>Laba sebelum investor</small><strong className={report.net >= 0 ? 'positive' : 'negative'}>{IDR.format(report.net)}</strong></article>
          <article><small>Potongan investor</small><strong>{report.investorRate ? IDR.format(report.investorShare) : 'Tidak berlaku'}</strong><span>{report.investorRate ? '5% · Holla / Texturin Surabaya' : 'Perusahaan lain'}</span></article>
          <article><small>Laba bersih</small><strong className={(report.netAfterInvestor ?? 0) >= 0 ? 'positive' : 'negative'}>{IDR.format(report.netAfterInvestor ?? report.net)}</strong></article>
        </div>
        <p className="payment-summary-warning">Rumus: pemasukan − seluruh pengeluaran. Transaksi baru setelah Project selesai tetap masuk realtime.</p>
      </>}
    </section>
    </div>
    <div className="project-finance-pane" hidden={view !== 'cash'}>
    <section id="project-finance-cash" className="project-finance-filters" aria-label="Filter arus kas">
      <h3>Arus Kas</h3><p>Ringkasan di atas mencakup seluruh transaksi tercatat. Filter berikut berlaku untuk tren dan daftar transaksi.</p>
      <label>Dari tanggal <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label>Sampai tanggal <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      {dateFrom && dateTo && dateFrom > dateTo && <p role="alert">Tanggal awal harus sebelum atau sama dengan tanggal akhir.</p>}
    </section>
    <div className="project-profitability-grid">
      <section className="project-profitability-chart" aria-label="Tren pemasukan dan biaya Project">
        <h3>Tren bulanan</h3>
        {report.monthly.length ? <>
          <ResponsiveContainer width="100%" height={260}><BarChart data={report.monthly} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}><CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 3" /><XAxis dataKey="month" tickFormatter={monthLabel} axisLine={false} tickLine={false} /><YAxis width={58} tickFormatter={(value) => COMPACT.format(Number(value))} axisLine={false} tickLine={false} /><Tooltip formatter={(value) => IDR.format(Number(value))} labelFormatter={(value) => monthLabel(String(value))} /><Legend /><Bar dataKey="income" name="Pemasukan" fill="var(--positive)" radius={[4, 4, 0, 0]} /><Bar dataKey="expense" name="Pengeluaran" fill="var(--negative)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
          <div className="project-monthly-table-wrap"><table className="project-monthly-table"><caption>Data tren bulanan</caption><thead><tr><th>Bulan</th><th>Pemasukan</th><th>Pengeluaran</th><th>Arus kas bersih</th></tr></thead><tbody>{report.monthly.map((item) => <tr key={item.month}><td>{monthLabel(item.month)}</td><td>{IDR.format(item.income)}</td><td>{IDR.format(item.expense)}</td><td>{IDR.format(item.income - item.expense)}</td></tr>)}</tbody></table></div>
        </> : <p>Belum ada tren transaksi.</p>}
      </section>
    </div>
    <section className="project-evidence-list" aria-label="Bukti transaksi Project">
      <header><div><ShieldCheck size={17} /><strong>Bukti transaksi</strong></div><span>File privat · review manual</span></header>
      {evidenceError && <p role="alert" className="document-state-alert">{evidenceError}</p>}
      {!filteredRows.length && <p>Tidak ada transaksi untuk periode ini.</p>}
      {(showAllRows ? filteredRows : filteredRows.slice(0, 5)).map((row) => {
        const item = evidenceBySource.get(row.id)
        return <article key={row.id}>
          <ScanLine size={16} />
          <div><strong>{row.notes || row.category || 'Transaksi Project'}</strong><span>{evidenceLabel(row)}{row.recorded_by ? ` · ${row.recorded_by}` : ''}</span>{item && <span>SHA-256 {item.sha256.slice(0, 12)}… · {item.review_status === 'pending' ? 'Menunggu review' : item.review_status === 'approved' ? 'Disetujui' : 'Ditolak'}</span>}</div>
          <b className={row.direction === 'income' ? 'positive' : 'negative'}>{row.direction === 'income' ? '+' : '−'}{IDR.format(row.amount)}</b>
          <div className="project-evidence-actions">
            {item ? <>
              <button type="button" className="secondary-button" disabled={evidenceBusy === item.id} onClick={() => void openEvidence(item)}><Eye size={14} /> Buka</button>
              {item.review_status === 'pending' && session?.capabilities.documentWrites && <>
                <button type="button" className="secondary-button" disabled={evidenceBusy === item.id} onClick={() => void reviewEvidence(item, 'approved')}>Setujui</button>
                <button type="button" className="danger-button" disabled={evidenceBusy === item.id} onClick={() => void reviewEvidence(item, 'rejected')}>Tolak</button>
              </>}
            </> : session?.capabilities.documentWrites ? <label className="secondary-button evidence-upload"><Upload size={14} /> {evidenceBusy === row.id ? 'Mengunggah…' : 'Unggah bukti'}<input aria-label={`Unggah bukti ${row.notes || row.id}`} type="file" accept="image/jpeg,image/png,image/webp" disabled={evidenceBusy === row.id} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; void uploadEvidence(row, file) }} /></label> : <span>Belum ada file bukti</span>}
          </div>
        </article>
      })}
      {filteredRows.length > 5 && <button type="button" className="secondary-button" onClick={() => setShowAllRows((current) => !current)}>{showAllRows ? 'Tampilkan lebih sedikit' : `Lihat semua ${filteredRows.length} transaksi`}</button>}
    </section>
    </div>
  </section>
}
