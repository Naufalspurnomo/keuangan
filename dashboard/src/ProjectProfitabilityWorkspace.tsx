import { Eye, RefreshCw, ScanLine, ShieldCheck, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { FinanceProject, FinanceTransaction } from './financeWorkspace'
import type { ProjectDocumentApi, ProjectDocumentSession } from './projectDocumentApi'
import { createProjectEvidenceApi, type ProjectEvidenceApi, type ProjectTransactionEvidence } from './projectEvidenceApi'
import type { ProjectPaymentSummary } from './projectDocuments'

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

export default function ProjectProfitabilityWorkspace({ project, rows, api, session, evidenceApi: suppliedEvidenceApi }: {
  project: FinanceProject
  rows: FinanceTransaction[]
  api: ProjectDocumentApi
  session?: ProjectDocumentSession
  evidenceApi?: ProjectEvidenceApi
}) {
  const evidenceApi = useMemo(() => suppliedEvidenceApi ?? createProjectEvidenceApi(), [suppliedEvidenceApi])
  const [summary, setSummary] = useState<ProjectPaymentSummary | null>(null)
  const [evidence, setEvidence] = useState<ProjectTransactionEvidence[]>([])
  const [loading, setLoading] = useState(true)
  const [evidenceBusy, setEvidenceBusy] = useState('')
  const [error, setError] = useState('')
  const [evidenceError, setEvidenceError] = useState('')
  const activeController = useRef(0)

  const load = useCallback(async () => {
    const request = ++activeController.current
    setLoading(true)
    setError('')
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

  const report = useMemo(() => {
    const incomeRows = rows.filter((row) => row.direction === 'income')
    const expenseRows = rows.filter((row) => row.direction === 'expense')
    const income = sum(incomeRows)
    const expense = sum(expenseRows)
    const salary = sum(expenseRows.filter((row) => SALARY.test(`${row.category || ''} ${row.notes}`)))
    const categories = [...expenseRows.reduce((map, row) => {
      const key = row.category || 'Belum dikategorikan'
      map.set(key, (map.get(key) || 0) + row.amount)
      return map
    }, new Map<string, number>())].sort((left, right) => right[1] - left[1])
    const monthly = [...rows.reduce((map, row) => {
      const key = row.date.slice(0, 7)
      const item = map.get(key) || { month: key, income: 0, expense: 0 }
      item[row.direction] += row.amount
      map.set(key, item)
      return map
    }, new Map<string, { month: string; income: number; expense: number }>())].map(([, value]) => value).sort((a, b) => a.month.localeCompare(b.month))
    return { income, expense, salary, net: income - expense, categories, monthly }
  }, [rows])

  const contract = summary?.contract_total ?? null
  const margin = contract === null ? null : contract - report.expense
  const marginPct = contract && margin !== null ? (margin / contract) * 100 : null

  return <section className="project-profitability" aria-busy={loading}>
    <header className="project-profitability-head">
      <div><p className="eyebrow">KINERJA KAS PROYEK</p><h2>Kas masuk dan pengeluaran tercatat</h2><p>Angka kas berasal dari transaksi proyek. Nilai kontrak berasal dari Sales Order terbit.</p></div>
      <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} /> Perbarui</button>
    </header>
    {error && <p role="alert" className="document-state-alert">{error}</p>}
    <section className="project-profitability-metrics" aria-label={`Ringkasan kas ${project.name}`}>
      <article><small>Nilai kontrak</small><strong>{contract === null ? '—' : IDR.format(contract)}</strong></article>
      <article><small>Kas masuk</small><strong className="positive">{IDR.format(report.income)}</strong></article>
      <article><small>Pengeluaran proyek tercatat</small><strong className="negative">{IDR.format(report.expense)}</strong></article>
      <article><small>Gaji/upah tercatat</small><strong>{IDR.format(report.salary)}</strong></article>
      <article><small>Arus kas bersih</small><strong className={report.net >= 0 ? 'positive' : 'negative'}>{IDR.format(report.net)}</strong></article>
      <article><small>Sisa kontrak setelah kas keluar</small><strong className={margin === null || margin >= 0 ? 'positive' : 'negative'}>{margin === null ? '—' : IDR.format(margin)}</strong>{marginPct !== null && <span>{marginPct.toLocaleString('id-ID', { maximumFractionDigits: 1 })}%</span>}</article>
    </section>
    <p className="payment-summary-warning">Bukan laba akuntansi: angka ini hanya mengurangi nilai kontrak dengan pengeluaran kas yang sudah tercatat. Overhead kantor, pajak, kewajiban belum dibayar, dan biaya yang belum dialokasikan tidak termasuk.</p>
    <div className="project-profitability-grid">
      <section className="project-profitability-chart" aria-label="Tren pemasukan dan biaya proyek">
        <h3>Tren bulanan</h3>
        {report.monthly.length ? <>
          <ResponsiveContainer width="100%" height={260}><BarChart data={report.monthly} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}><CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 3" /><XAxis dataKey="month" tickFormatter={monthLabel} axisLine={false} tickLine={false} /><YAxis width={58} tickFormatter={(value) => COMPACT.format(Number(value))} axisLine={false} tickLine={false} /><Tooltip formatter={(value) => IDR.format(Number(value))} labelFormatter={(value) => monthLabel(String(value))} /><Legend /><Bar dataKey="income" name="Pemasukan" fill="var(--positive)" radius={[4, 4, 0, 0]} /><Bar dataKey="expense" name="Pengeluaran" fill="var(--negative)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
          <table className="project-monthly-table"><caption>Data tren bulanan</caption><thead><tr><th>Bulan</th><th>Pemasukan</th><th>Pengeluaran</th><th>Arus kas bersih</th></tr></thead><tbody>{report.monthly.map((item) => <tr key={item.month}><td>{monthLabel(item.month)}</td><td>{IDR.format(item.income)}</td><td>{IDR.format(item.expense)}</td><td>{IDR.format(item.income - item.expense)}</td></tr>)}</tbody></table>
        </> : <p>Belum ada tren transaksi.</p>}
      </section>
      <section className="project-cost-breakdown" aria-label="Rincian biaya proyek"><h3>Rincian biaya</h3>{report.categories.length ? report.categories.map(([category, amount]) => <div key={category}><span>{category}</span><strong>{IDR.format(amount)}</strong></div>) : <p>Belum ada biaya proyek.</p>}</section>
    </div>
    <section className="project-evidence-list" aria-label="Bukti transaksi proyek">
      <header><div><ShieldCheck size={17} /><strong>Bukti transaksi</strong></div><span>File privat · review manual</span></header>
      {evidenceError && <p role="alert" className="document-state-alert">{evidenceError}</p>}
      {rows.map((row) => {
        const item = evidenceBySource.get(row.id)
        return <article key={row.id}>
          <ScanLine size={16} />
          <div><strong>{row.notes || row.category || 'Transaksi proyek'}</strong><span>{evidenceLabel(row)}{row.recorded_by ? ` · ${row.recorded_by}` : ''}</span>{item && <span>SHA-256 {item.sha256.slice(0, 12)}… · {item.review_status === 'pending' ? 'Menunggu review' : item.review_status === 'approved' ? 'Disetujui' : 'Ditolak'}</span>}</div>
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
    </section>
  </section>
}
