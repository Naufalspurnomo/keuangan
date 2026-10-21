import { FormEvent, lazy, Suspense, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  BriefcaseBusiness,
  Building2,
  ChevronDown,
  CircleDollarSign,
  CreditCard,
  FileBarChart,
  Landmark,
  LayoutDashboard,
  ListFilter,
  Menu,
  Moon,
  RefreshCcw,
  Search,
  Sun,
  WalletCards,
  X,
} from 'lucide-react'

import { ApiError, dashboardApi, login } from './api'
import { loadSnapshot } from './snapshot'
import type { CashTrendPoint, DebtSnapshot, ProjectSummary, WalletSnapshot } from './snapshot'
import type { DashboardMeta, Overview, Transaction } from './types'

const FinancialChart = lazy(() => import('./FinancialChart'))
const PREVIEW_MODE = import.meta.env.VITE_DEMO_PREVIEW === 'true'
const SNAPSHOT_MODE = import.meta.env.VITE_SNAPSHOT_PREVIEW === 'true'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })

const demoTransactions: Transaction[] = [
  { id: 1, transaction_date: '2026-10-21', transaction_type: 'Pemasukan', amount: 125_000_000, wallet: 'TX SBY(216)', company: 'Hollawall', project: 'Surabaya Office', notes: 'Termin pekerjaan utama' },
  { id: 2, transaction_date: '2026-10-20', transaction_type: 'Pengeluaran', amount: 18_400_000, wallet: 'BCA(056)', company: 'Hollawall', project: 'Grand Galaxy', notes: 'Material dan vendor' },
  { id: 3, transaction_date: '2026-10-19', transaction_type: 'Pemasukan', amount: 87_500_000, wallet: 'KPR BRI(031)', company: 'Hollawall', project: 'Mawar Residence', notes: 'Pembayaran progres' },
  { id: 4, transaction_date: '2026-10-18', transaction_type: 'Pengeluaran', amount: 26_750_000, wallet: 'TX SBY(216)', company: 'Hollawall', project: 'Surabaya Office', notes: 'Operasional lapangan' },
  { id: 5, transaction_date: '2026-10-17', transaction_type: 'Pemasukan', amount: 70_000_000, wallet: 'BCA(056)', company: 'Hollawall', project: 'Grand Galaxy', notes: 'Termin kedua' },
  { id: 6, transaction_date: '2026-10-16', transaction_type: 'Pengeluaran', amount: 35_400_000, wallet: 'KPR BRI(031)', company: 'Hollawall', project: 'Mawar Residence', notes: 'Pembelian material' },
]

const demoOverview: Overview = {
  metrics: {
    cash_balance: 868_900_000,
    operating_inflow: 497_500_000,
    operating_outflow: 192_150_000,
    net_operating_cashflow: 305_350_000,
    open_internal_debt: 28_500_000,
    project_cashflow: 305_350_000,
  },
  counts: { valid_rows: 148, invalid_rows: 2 },
  labels: {
    cash_balance: 'Saldo kas',
    operating_inflow: 'Pemasukan operasional',
    operating_outflow: 'Pengeluaran operasional',
    net_operating_cashflow: 'Arus kas operasional bersih',
    open_internal_debt: 'Hutang antar-dompet terbuka',
    project_cashflow: 'Arus kas proyek bersih',
  },
  drilldowns: {},
}

const demoMeta: DashboardMeta = {
  as_of: new Date().toISOString(),
  freshness: 'fresh',
  data_completeness: { valid_rows: 148, invalid_rows: 2, completeness_pct: 98.7 },
}


const pageMeta: Record<string, [string, string]> = {
  overview: ['Ringkasan keuangan', 'Ringkasan Perusahaan'],
  cashflow: ['Pergerakan kas', 'Arus Kas'],
  wallets: ['Likuiditas', 'Dompet & Rekening'],
  transactions: ['Rincian transaksi', 'Semua Transaksi'],
  projects: ['Kinerja proyek', 'Proyek'],
  debts: ['Penyelesaian internal', 'Hutang Antar-Dompet'],
  reports: ['Dukungan keputusan', 'Laporan'],
}

function formatAmount(value: number) {
  return IDR.format(value).replace('Rp', 'Rp ')
}

function LoginScreen({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('naufalspurnomo@gmail.com')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      await login(email, password)
      onDone()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Login gagal. Coba lagi.')
    } finally {
      setPending(false)
    }
  }

  return <main className="login-shell">
    <section className="login-story">
      <div className="brand-lockup"><span className="brand-mark">H</span><span>HOLLAWALL</span></div>
      <div className="story-copy">
        <p className="eyebrow">FINANCIAL COMMAND CENTER</p>
        <h1>Keuangan perusahaan.<br /><em>Terlihat utuh.</em></h1>
        <p>Satu ruang kerja privat untuk memahami kas, proyek, dompet, dan pergerakan operasional—tanpa mengubah ledger.</p>
      </div>
      <p className="login-footnote">Private access · Owner only · Read-only</p>
    </section>
    <section className="login-panel">
      <form className="login-card" onSubmit={submit}>
        <div className="mobile-brand"><span className="brand-mark">H</span> HOLLAWALL</div>
        <p className="eyebrow">OWNER ACCESS</p>
        <h2>Masuk ke pusat kendali</h2>
        <p className="muted">Gunakan akun privat yang telah diundang.</p>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="primary-button" disabled={pending}>{pending ? 'Memverifikasi…' : 'Masuk'} <ArrowRight size={18} /></button>
        <p className="security-note">Sesi dilindungi cookie aman dan berakhir otomatis.</p>
      </form>
    </section>
  </main>
}

function Sidebar({ active, setActive, open, setOpen, transactionCount }: { active: string; setActive: (value: string) => void; open: boolean; setOpen: (value: boolean) => void; transactionCount: number }) {
  const navigation = [
    ['overview', 'Ringkasan', LayoutDashboard], ['cashflow', 'Arus Kas', BarChart3],
    ['wallets', 'Dompet', WalletCards], ['transactions', 'Transaksi', CreditCard],
    ['projects', 'Proyek', BriefcaseBusiness], ['debts', 'Hutang Internal', Landmark],
    ['reports', 'Laporan', FileBarChart],
  ] as const
  return <>
    <div className={`mobile-overlay ${open ? 'is-open' : ''}`} onClick={() => setOpen(false)} />
    <aside className={`sidebar ${open ? 'is-open' : ''}`}>
      <div className="sidebar-head"><div className="brand-lockup"><span className="brand-mark">H</span><span>HOLLAWALL</span></div><button className="icon-button mobile-only" onClick={() => setOpen(false)} aria-label="Tutup navigasi"><X size={20} /></button></div>
      <div className="workspace-switch"><Building2 size={18} /><span><small>Ruang kerja</small>Hollawall Group</span><ChevronDown size={16} /></div>
      <nav>{navigation.map(([key, label, Icon]) => <button key={key} className={active === key ? 'active' : ''} onClick={() => { setActive(key); setOpen(false) }}><Icon size={19} strokeWidth={1.8} /><span>{label}</span>{key === 'transactions' && <b>{transactionCount}</b>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="profile"><span>NS</span><div><strong>Naufal Spurnomo</strong><small>Owner</small></div></div></div>
    </aside>
  </>
}

function ThemeToggle({ theme, setTheme }: { theme: string; setTheme: (value: string) => void }) {
  return <button className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label="Ubah tema">
    <Sun size={16} /><span className={theme === 'dark' ? 'dark' : 'light'}></span><Moon size={16} />
  </button>
}

function FilterBar({ dataThrough }: { dataThrough?: string | null }) {
  const period = dataThrough ? `Semua data · s.d. ${new Date(`${dataThrough}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' })}` : 'Semua periode'
  return <div className="filter-bar">
    <button><span><small>Periode</small>{period}</span><ChevronDown size={15} /></button>
    <button><span><small>Perusahaan</small>Semua perusahaan</span><ChevronDown size={15} /></button>
    <button><span><small>Dompet</small>Semua dompet</span><ChevronDown size={15} /></button>
    <button><span><small>Proyek</small>Semua proyek</span><ChevronDown size={15} /></button>
    <button className="filter-action" aria-label="Filter tambahan"><ListFilter size={18} /></button>
  </div>
}

function MetricCard({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return <article className={`metric-card ${tone ?? ''}`}>
    <div className="metric-top"><span>{label}</span><CircleDollarSign size={18} /></div>
    <strong>{formatAmount(value)}</strong>
    <div className="metric-foot"><small>Seluruh snapshot</small></div>
  </article>
}

function Freshness({ meta }: { meta: DashboardMeta }) {
  const date = new Date(meta.as_of)
  const through = meta.data_through ? new Date(`${meta.data_through}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : 'tanggal tidak tersedia'
  return <div className={`freshness ${meta.freshness}`}><i></i><span>{meta.freshness === 'fresh' ? 'Data terkini' : meta.freshness === 'aging' ? 'Data mulai menua' : 'Snapshot perlu diperbarui'}<small>Data s.d. {through} · file {date.toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} · {meta.data_completeness.completeness_pct}% valid</small></span></div>
}

function OverviewPage({ overview, transactions, meta, cashTrend, projects, setActive }: { overview: Overview; transactions: Transaction[]; meta: DashboardMeta; cashTrend: CashTrendPoint[]; projects: ProjectSummary[]; setActive: (value: string) => void }) {
  const metrics = overview.metrics
  return <>
    <section className="hero-balance">
      <div><p className="eyebrow">TOTAL POSISI KAS</p><h2>{formatAmount(metrics.cash_balance)}</h2><p>Saldo sistem dari seluruh dompet pada snapshot terakhir.</p></div>
      <Freshness meta={meta} />
    </section>
    <section className="metric-grid">
      <MetricCard label={overview.labels.operating_inflow} value={metrics.operating_inflow} tone="income" />
      <MetricCard label={overview.labels.operating_outflow} value={metrics.operating_outflow} tone="expense" />
      <MetricCard label={overview.labels.net_operating_cashflow} value={metrics.net_operating_cashflow} tone="net" />
      <MetricCard label={overview.labels.open_internal_debt} value={metrics.open_internal_debt} tone="debt" />
    </section>
    <section className="overview-grid">
      <article className="panel chart-panel">
        <div className="panel-head"><div><p className="eyebrow">POSISI KAS</p><h3>Pergerakan saldo kas</h3></div><button className="text-button">Lihat arus kas <ArrowRight size={15} /></button></div>
        <div className="chart-value"><strong>{formatAmount(metrics.cash_balance)}</strong><span className={metrics.net_operating_cashflow >= 0 ? 'positive' : 'negative'}>{formatAmount(metrics.net_operating_cashflow)} bersih</span></div>
        <div className="area-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="cash" cashTrend={cashTrend} /></Suspense></div>
      </article>
      <article className="panel project-panel">
        <div className="panel-head"><div><p className="eyebrow">KINERJA PROYEK</p><h3>Arus kas proyek bersih</h3></div><button className="icon-button"><BarChart3 size={18} /></button></div>
        <div className="bar-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="projects" projects={projects} /></Suspense></div>
      </article>
    </section>
    <section className="panel activity-panel">
      <div className="panel-head"><div><p className="eyebrow">AKTIVITAS TERBARU</p><h3>Transaksi terbaru</h3></div><button className="text-button" onClick={() => setActive('transactions')}>Semua transaksi <ArrowRight size={15} /></button></div>
      <TransactionTable rows={transactions.slice(0, 5)} compact />
    </section>
  </>
}

function TransactionTable({ rows, compact = false }: { rows: Transaction[]; compact?: boolean }) {
  return <div className="table-wrap"><table className="transaction-table"><thead><tr><th>Tanggal</th><th>Keterangan</th><th>Proyek</th><th>Dompet</th><th>Jenis</th><th className="number">Jumlah</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td data-label="Tanggal">{new Date(row.transaction_date).toLocaleDateString('id-ID', { day: '2-digit', month: 'short' })}</td><td data-label="Keterangan"><strong>{row.notes || 'Transaksi operasional'}</strong>{!compact && <small>ID #{row.id}</small>}</td><td data-label="Proyek">{row.project}</td><td data-label="Dompet"><span className="wallet-chip">{row.wallet}</span></td><td data-label="Jenis"><span className={`type-chip ${row.transaction_type === 'Pemasukan' ? 'income' : 'expense'}`}>{row.transaction_type === 'Pemasukan' ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}{row.transaction_type}</span></td><td data-label="Jumlah" className={`number amount ${row.transaction_type === 'Pemasukan' ? 'positive' : ''}`}>{row.transaction_type === 'Pemasukan' ? '+' : '−'}{formatAmount(row.amount)}</td></tr>)}</tbody></table></div>
}

function DetailPage({ active, transactions, overview, wallets, debts, projects, completeness }: { active: string; transactions: Transaction[]; overview: Overview; wallets: WalletSnapshot[]; debts: DebtSnapshot[]; projects: ProjectSummary[]; completeness: number }) {
  if (active === 'transactions') return <section className="panel detail-panel"><div className="detail-toolbar"><div className="search-field"><Search size={18} /><input placeholder="Cari transaksi, proyek, atau catatan…" /></div><button className="secondary-button"><ListFilter size={17} /> Filter</button><button className="secondary-button">Ekspor</button></div><TransactionTable rows={transactions} /></section>
  const content: Record<string, { stat: string; value: number; copy: string }> = {
    cashflow: { stat: 'Arus kas operasional bersih', value: overview.metrics.net_operating_cashflow, copy: 'Pemasukan dan pengeluaran operasional setelah pergerakan internal dieliminasi.' },
    wallets: { stat: 'Saldo kas terkonsolidasi', value: overview.metrics.cash_balance, copy: 'Posisi likuiditas perusahaan dari seluruh dompet dan rekening yang terhubung.' },
    projects: { stat: 'Arus kas proyek bersih', value: overview.metrics.project_cashflow, copy: 'Kontribusi kas proyek aktif pada periode yang dipilih.' },
    debts: { stat: 'Hutang antar-dompet terbuka', value: overview.metrics.open_internal_debt, copy: 'Kewajiban internal yang belum diselesaikan dan tidak masuk pendapatan atau beban.' },
    reports: { stat: 'Kelengkapan data', value: completeness, copy: 'Persentase baris transaksi valid pada snapshot yang dapat ditelusuri ke source key.' },
  }
  const item = content[active]
  const breakdownRows = active === 'wallets'
    ? wallets.map((row) => ({ name: row.name, value: row.balance }))
    : active === 'debts'
      ? debts.filter((row) => row.status === 'OPEN').slice(0, 8).map((row) => ({ name: `${row.borrower} → ${row.lender}`, value: row.amount }))
      : projects.slice(0, 8).map((row) => ({ name: row.name, value: row.net_cashflow }))
  const maxValue = Math.max(...breakdownRows.map((row) => Math.abs(row.value)), 1)
  return <section className="detail-layout">
    <article className="detail-hero"><p className="eyebrow">PANDANGAN EKSEKUTIF</p><h2>{item.stat}</h2><strong>{active === 'reports' ? `${item.value.toLocaleString('id-ID')}%` : formatAmount(item.value)}</strong><p>{item.copy}</p><button className="primary-button">Buka rincian <ArrowRight size={17} /></button></article>
    <article className="panel breakdown"><div className="panel-head"><div><p className="eyebrow">RINCIAN</p><h3>Komposisi snapshot</h3></div></div>{breakdownRows.map((row, index) => <div className="breakdown-row" key={`${row.name}-${index}`}><span><i style={{ background: row.value < 0 ? 'var(--danger)' : index === 0 ? 'var(--chart-primary)' : 'var(--chart-secondary)' }}></i>{row.name}</span><strong>{formatAmount(row.value)}</strong><div><b style={{ width: `${(Math.abs(row.value) / maxValue) * 100}%` }}></b></div></div>)}</article>
  </section>
}

function Dashboard() {
  const [active, setActive] = useState('overview')
  const [menuOpen, setMenuOpen] = useState(false)
  const [theme, setTheme] = useState(() => localStorage.getItem('hollawall-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
  const snapshotQuery = useQuery({ queryKey: ['snapshot'], queryFn: loadSnapshot, retry: false, enabled: SNAPSHOT_MODE, refetchInterval: SNAPSHOT_MODE ? 300_000 : false })
  const overviewQuery = useQuery({ queryKey: ['overview'], queryFn: () => dashboardApi.overview(), retry: false, refetchInterval: 30_000, enabled: !SNAPSHOT_MODE })
  const transactionQuery = useQuery({ queryKey: ['transactions'], queryFn: () => dashboardApi.transactions('?limit=50'), retry: false, refetchInterval: 30_000, enabled: !SNAPSHOT_MODE })

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('hollawall-theme', theme) }, [theme])
  useEffect(() => { document.title = `${pageMeta[active][1]} — Hollawall` }, [active])

  const snapshot = snapshotQuery.data
  const overview = snapshot?.overview ?? overviewQuery.data?.data ?? demoOverview
  const meta = snapshot?.meta ?? overviewQuery.data?.meta ?? demoMeta
  const transactions = snapshot?.transactions ?? transactionQuery.data?.data.items ?? demoTransactions
  const wallets = snapshot?.wallets ?? []
  const debts = snapshot?.debts ?? []
  const projects = snapshot?.project_summaries ?? []
  const cashTrend = snapshot?.cash_trend ?? []
  const isDemo = !snapshot && (PREVIEW_MODE || overviewQuery.isError || transactionQuery.isError)
  const [eyebrow, title] = pageMeta[active]

  return <div className="app-shell">
    <Sidebar active={active} setActive={setActive} open={menuOpen} setOpen={setMenuOpen} transactionCount={transactions.length} />
    <main className="main-canvas">
      <header className="topbar"><button className="icon-button mobile-only" onClick={() => setMenuOpen(true)} aria-label="Buka navigasi"><Menu size={21} /></button><div className="breadcrumbs"><span>Hollawall Group</span><b>/</b><strong>{title}</strong></div><div className="topbar-actions"><button className="icon-button"><Search size={18} /></button><ThemeToggle theme={theme} setTheme={setTheme} /><button className="icon-button" onClick={() => { snapshotQuery.refetch(); overviewQuery.refetch(); transactionQuery.refetch() }}><RefreshCcw size={17} /></button></div></header>
      <div className="content">
        <section className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>Pandangan terukur atas posisi keuangan Hollawall.</p></div>{snapshot ? <div className={`demo-badge ${meta.freshness}`}>SNAPSHOT PRODUKSI · {meta.freshness === 'stale' ? 'PERLU DIPERBARUI' : 'READ-ONLY'}</div> : isDemo && <div className="demo-badge">PRATINJAU · DATA DEMO</div>}</section>
        <FilterBar dataThrough={meta.data_through} />
        {active === 'overview' ? <OverviewPage overview={overview} transactions={transactions} meta={meta} cashTrend={cashTrend} projects={projects} setActive={setActive} /> : <DetailPage active={active} transactions={transactions} overview={overview} wallets={wallets} debts={debts} projects={projects} completeness={meta.data_completeness.completeness_pct} />}
      </div>
    </main>
  </div>
}

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(PREVIEW_MODE || SNAPSHOT_MODE ? true : null)
  const identityQuery = useQuery({ queryKey: ['identity'], queryFn: dashboardApi.me, retry: false, enabled: !PREVIEW_MODE && !SNAPSHOT_MODE })
  useEffect(() => { if (identityQuery.isSuccess) setAuthenticated(true); if (identityQuery.isError) setAuthenticated(false) }, [identityQuery.isSuccess, identityQuery.isError])
  if (authenticated === null) return <div className="boot-screen"><span className="brand-mark">H</span><p>Menyiapkan pusat kendali…</p></div>
  return authenticated ? <Dashboard /> : <LoginScreen onDone={() => setAuthenticated(true)} />
}
