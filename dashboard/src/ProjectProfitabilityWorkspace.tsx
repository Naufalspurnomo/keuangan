import { RefreshCw, ScanLine, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { TransactionRows } from './FinancePages'
import type { FinanceProject, FinanceTransaction } from './financeWorkspace'
import type { ProjectDocumentApi } from './projectDocumentApi'
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

export default function ProjectProfitabilityWorkspace({ project, rows, projects, api }: {
  project: FinanceProject
  rows: FinanceTransaction[]
  projects: FinanceProject[]
  api: ProjectDocumentApi
}) {
  const [summary, setSummary] = useState<ProjectPaymentSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
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
    <section className="project-evidence-list" aria-label="Provenance transaksi proyek"><header><div><ShieldCheck size={17} /><strong>Provenance transaksi</strong></div><span>Metadata sumber yang tercatat</span></header>{rows.map((row) => <article key={row.id}><ScanLine size={16} /><div><strong>{row.notes || row.category || 'Transaksi proyek'}</strong><span>{evidenceLabel(row)}{row.recorded_by ? ` · ${row.recorded_by}` : ''}</span></div><b className={row.direction === 'income' ? 'positive' : 'negative'}>{row.direction === 'income' ? '+' : '−'}{IDR.format(row.amount)}</b></article>)}</section>
    <section className="recent-command"><header><div><p className="eyebrow">TRANSAKSI PROYEK</p><h2>Aktivitas tercatat</h2></div></header><TransactionRows rows={rows} projects={projects} /></section>
  </section>
}
