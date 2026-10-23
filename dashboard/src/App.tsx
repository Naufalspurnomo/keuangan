import { lazy, Suspense, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  BriefcaseBusiness,
  Building2,
  CreditCard,
  FileBarChart,
  Landmark,
  LayoutDashboard,
  ListFilter,
  LockKeyhole,
  Menu,
  Moon,
  RefreshCcw,
  Search,
  Sun,
  WalletCards,
  X,
} from 'lucide-react'

import ProjectHealthBoard from './ProjectHealthBoard'
import { loadSnapshot } from './snapshot'
import type { DebtSnapshot, ProjectSummary, WalletSnapshot } from './snapshot'
import { downloadTransactionsCsv, filterTransactions } from './transactions'
import type { TransactionTypeFilter } from './transactions'
import type { DashboardMeta, Overview, QualityRow, Transaction } from './types'
import BusinessSectionReport from './BusinessSectionReport'
import { CashflowWorkspace, WalletWorkspace } from './FinancialOperationsWorkspace'
import ProjectReportTimeline from './ProjectReportTimeline'

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

const emptyOverview: Overview = {
  metrics: { cash_balance: 0, operating_inflow: 0, operating_outflow: 0, net_operating_cashflow: 0, open_internal_debt: 0, project_cashflow: 0 },
  counts: { valid_rows: 0, invalid_rows: 0 },
  labels: demoOverview.labels,
  drilldowns: demoOverview.drilldowns,
}
const emptyMeta: DashboardMeta = {
  as_of: new Date().toISOString(),
  freshness: 'stale',
  source_status: 'degraded',
  data_completeness: { valid_rows: 0, invalid_rows: 0, completeness_pct: 0 },
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
      <div className="workspace-switch" aria-label="Ruang kerja aktif"><Building2 size={18} /><span><small>Ruang kerja aktif</small>Hollawall Group</span></div>
      <nav>{navigation.map(([key, label, Icon]) => <button key={key} className={active === key ? 'active' : ''} onClick={() => { setActive(key); setOpen(false) }}><Icon size={19} strokeWidth={1.8} /><span>{label}</span>{key === 'transactions' && <b>{transactionCount}</b>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="profile workspace-profile"><span><LockKeyhole size={15}/></span><div><strong>Workspace privat</strong><small>Read-only · Teraudit</small></div></div></div>
    </aside>
  </>
}

function ThemeToggle({ theme, setTheme }: { theme: string; setTheme: (value: string) => void }) {
  return <button className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label="Ubah tema">
    <Sun size={16} /><span className={theme === 'dark' ? 'dark' : 'light'}></span><Moon size={16} />
  </button>
}

function SnapshotContext({ dataThrough }: { dataThrough?: string | null }) {
  const period = dataThrough ? new Date(`${dataThrough}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' }) : 'periode tidak tersedia'
  return <section className="snapshot-context" aria-label="Konteks snapshot baca-saja">
    <span>Hollawall Group</span><i></i><span>Data s.d. {period}</span><i></i><span>Snapshot baca-saja</span>
  </section>
}

function PulseMetric({ label, value, tone, onClick }: { label: string; value: number; tone?: string; onClick?: () => void }) {
  const shownValue = formatAmount(value)
  return <button type="button" className={`pulse-metric ${tone ?? ''}`} aria-label={`${label}: ${shownValue}`} onClick={onClick}>
    <span>{label}</span><strong>{shownValue}</strong>
  </button>
}

function Freshness({ meta }: { meta: DashboardMeta }) {
  const snapshotDate = new Date(meta.as_of)
  const through = meta.data_through ? new Date(`${meta.data_through}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : 'tanggal tidak tersedia'
  const totalRows = meta.data_completeness.valid_rows + meta.data_completeness.invalid_rows
  return <div className="freshness neutral"><i></i><span>Transaksi tercatat sampai {through}<small>Snapshot dibuat {snapshotDate.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })} · {meta.data_completeness.valid_rows.toLocaleString('id-ID')} dari {totalRows.toLocaleString('id-ID')} baris impor valid</small></span></div>
}

function OverviewPage({ overview, transactions, meta, projects, walletSnapshots, setActive, setTransactionFilter }: { overview: Overview; transactions: Transaction[]; meta: DashboardMeta; projects: ProjectSummary[]; walletSnapshots: WalletSnapshot[]; setActive: (value: string) => void; setTransactionFilter: (value: TransactionTypeFilter) => void }) {
  const metrics = overview.metrics
  const openingPosition = metrics.cash_balance - metrics.net_operating_cashflow
  const period = meta.data_through ? new Date(`${meta.data_through}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : 'tanggal tidak tersedia'
  const labels = {
    operating_inflow: overview.labels.operating_inflow || 'Pemasukan operasional',
    operating_outflow: overview.labels.operating_outflow || 'Pengeluaran operasional',
    net_operating_cashflow: overview.labels.net_operating_cashflow || 'Arus kas operasional bersih',
    open_internal_debt: overview.labels.open_internal_debt || 'Hutang antar-dompet terbuka',
  }
  const drilldown = (metric: keyof Overview['metrics']) => {
    const target = overview.drilldowns?.[metric] ?? 'transactions'
    const [view, filter] = target.split(':')
    setActive(view)
    setTransactionFilter((filter ?? 'all') as TransactionTypeFilter)
  }
  return <>
    <section className="position-stage" aria-label="Posisi keuangan utama">
      <div className="position-primary">
        <p className="eyebrow">TOTAL POSISI KAS</p>
        <button type="button" aria-label={overview.labels.cash_balance ?? 'Saldo kas'} onClick={() => drilldown('cash_balance')}>
          <strong>{formatAmount(metrics.cash_balance)}</strong>
          <span>Semua dompet · per {period}</span>
        </button>
      </div>
      <div className="position-status"><Freshness meta={meta} /></div>
    </section>
    <BusinessSectionReport transactions={transactions} wallets={walletSnapshots} />
    <section className="operating-chapter" aria-label="Ringkasan arus kas">
      <header><div><p className="eyebrow">ARUS KAS OPERASIONAL</p><h2>Semua unit · s.d. {period}</h2></div><button type="button" aria-label="Kelengkapan data" onClick={() => setActive('reports')}>Baris impor valid <strong>{meta.data_completeness.completeness_pct.toLocaleString('id-ID')}%</strong></button></header>
      <p className="scope-bridge">Posisi awal {formatAmount(openingPosition)} + arus eksternal bersih {formatAmount(metrics.net_operating_cashflow)} = posisi kas {formatAmount(metrics.cash_balance)}. Transfer dan hutang internal tidak mengubah kas konsolidasi.</p>
      <div className="operating-pulse">
        <PulseMetric label={labels.operating_inflow} value={metrics.operating_inflow} tone="income" onClick={() => drilldown('operating_inflow')} />
        <PulseMetric label={labels.operating_outflow} value={metrics.operating_outflow} tone="expense" onClick={() => drilldown('operating_outflow')} />
        <PulseMetric label={labels.net_operating_cashflow} value={metrics.net_operating_cashflow} tone="net" onClick={() => drilldown('net_operating_cashflow')} />
        <PulseMetric label={labels.open_internal_debt} value={metrics.open_internal_debt} tone="debt" onClick={() => drilldown('open_internal_debt')} />
      </div>
    </section>
    <ProjectReportTimeline transactions={transactions} projects={projects} asOf={meta.as_of} dataThrough={meta.data_through} />
  </>
}

function TransactionTable({ rows, compact = false }: { rows: Transaction[]; compact?: boolean }) {
  return <div className="table-wrap"><table className="transaction-table"><thead><tr><th>Tanggal</th><th>Keterangan</th><th>Proyek</th><th>Dompet</th><th>Jenis</th><th className="number">Jumlah</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td data-label="Tanggal">{new Date(row.transaction_date).toLocaleDateString('id-ID', { day: '2-digit', month: 'short' })}</td><td data-label="Keterangan"><strong>{row.notes || 'Transaksi operasional'}</strong>{!compact && <small>{row.source_key ?? `ID #${row.id}`}</small>}</td><td data-label="Proyek">{row.project}</td><td data-label="Dompet"><span className="wallet-chip">{row.wallet}</span></td><td data-label="Jenis"><span className={`type-chip ${row.transaction_type === 'Pemasukan' ? 'income' : 'expense'}`}>{row.transaction_type === 'Pemasukan' ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}{row.transaction_type}</span></td><td data-label="Jumlah" className={`number amount ${row.transaction_type === 'Pemasukan' ? 'positive' : ''}`}>{row.transaction_type === 'Pemasukan' ? '+' : '−'}{formatAmount(row.amount)}</td></tr>)}</tbody></table></div>
}

function DetailPage({ active, transactions, overview, wallets, debts, projects, dataThrough, completeness, qualityRows, initialFilter, initialQuery, onOpenProject }: { active: string; transactions: Transaction[]; overview: Overview; wallets: WalletSnapshot[]; debts: DebtSnapshot[]; projects: ProjectSummary[]; dataThrough?: string | null; completeness: number; qualityRows: QualityRow[]; initialFilter: TransactionTypeFilter; initialQuery: string; onOpenProject: (name: string) => void }) {
  const [query, setQuery] = useState(initialQuery)
  const [typeFilter, setTypeFilter] = useState<TransactionTypeFilter>(initialFilter)
  useEffect(() => setTypeFilter(initialFilter), [initialFilter])
  useEffect(() => setQuery(initialQuery), [initialQuery])
  const filteredTransactions = filterTransactions(transactions, query, typeFilter)
  if (active === 'cashflow') return <CashflowWorkspace transactions={transactions} dataThrough={dataThrough} onOpenProject={onOpenProject} />
  if (active === 'wallets') return <WalletWorkspace transactions={transactions} wallets={wallets} dataThrough={dataThrough} onOpenProject={onOpenProject} />
  if (active === 'projects') return <ProjectHealthBoard projects={projects} asOf={dataThrough} onOpen={onOpenProject} />
  if (active === 'transactions') return <section className="panel detail-panel"><div className="detail-toolbar"><div className="search-field"><Search size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari transaksi, proyek, dompet, atau source key…" /></div><label className="type-select"><ListFilter size={17} /><span className="sr-only">Filter jenis</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as TransactionTypeFilter)}><option value="all">Semua jenis</option><option value="Pemasukan">Pemasukan</option><option value="Pengeluaran">Pengeluaran</option><option value="external-income">Pemasukan eksternal</option><option value="external-expense">Pengeluaran eksternal</option><option value="external">Eksternal</option><option value="projects">Proyek</option></select></label><button className="secondary-button" onClick={() => downloadTransactionsCsv(filteredTransactions)}>Ekspor CSV</button><span className="result-count">{filteredTransactions.length.toLocaleString('id-ID')} transaksi</span></div><TransactionTable rows={filteredTransactions} /></section>
  const content: Record<string, { stat: string; value: number; copy: string }> = {
    cashflow: { stat: 'Arus kas operasional bersih', value: overview.metrics.net_operating_cashflow, copy: 'Pemasukan dan pengeluaran operasional setelah pergerakan internal dieliminasi.' },
    wallets: { stat: 'Saldo kas terkonsolidasi', value: overview.metrics.cash_balance, copy: 'Posisi likuiditas perusahaan dari seluruh dompet dan rekening yang terhubung.' },
    projects: { stat: 'Arus kas proyek bersih', value: overview.metrics.project_cashflow, copy: 'Kontribusi kas proyek aktif pada periode yang dipilih.' },
    debts: { stat: 'Hutang antar-dompet terbuka', value: overview.metrics.open_internal_debt, copy: 'Kewajiban internal yang belum diselesaikan dan tidak masuk pendapatan atau beban.' },
    reports: { stat: 'Kelengkapan data', value: completeness, copy: 'Persentase baris transaksi valid pada snapshot yang dapat ditelusuri ke source key.' },
  }
  const item = content[active]
  const breakdownRows = active === 'wallets'
    ? wallets.map((row) => ({ name: `${row.name} · ${row.source_key}`, value: row.balance }))
    : active === 'debts'
      ? debts.filter((row) => row.status === 'OPEN').slice(0, 8).map((row) => ({ name: `${row.borrower} → ${row.lender} · ${row.source_key}`, value: row.amount }))
      : active === 'reports'
        ? qualityRows.map((row) => ({ name: `${row.source_key} — ${row.invalid_reason}`, value: row.source_key.length }))
        : projects.slice(0, 8).map((row) => ({ name: row.name, value: row.net_cashflow }))
  const maxValue = Math.max(...breakdownRows.map((row) => Math.abs(row.value)), 1)
  return <section className="detail-layout">
    <article className="detail-hero"><p className="eyebrow">PANDANGAN EKSEKUTIF</p><h2>{item.stat}</h2><strong>{active === 'reports' ? `${item.value.toLocaleString('id-ID')}%` : formatAmount(item.value)}</strong><p>{item.copy}</p>
      {(active === 'cashflow' || active === 'wallets' || active === 'debts') && <div className="detail-hero-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind={active === 'cashflow' ? 'waterfall' : active === 'wallets' ? 'wallets' : 'debts'} transactions={transactions} wallets={wallets} debts={debts} /></Suspense></div>}
    </article>
    <article className="panel breakdown"><div className="panel-head"><div><p className="eyebrow">RINCIAN</p><h3>{active === 'reports' ? 'Baris ditolak' : 'Komposisi snapshot'}</h3></div></div>{breakdownRows.length ? breakdownRows.map((row, index) => <div className="breakdown-row" key={`${row.name}-${index}`}><span><i style={{ background: row.value < 0 ? 'var(--danger)' : index === 0 ? 'var(--chart-primary)' : 'var(--chart-secondary)' }}></i>{row.name}</span><strong>{active === 'reports' ? 'Perlu tinjau' : formatAmount(row.value)}</strong><div><b style={{ width: `${(Math.abs(row.value) / maxValue) * 100}%` }}></b></div></div>) : <p className="empty-note">Tidak ada baris ditolak pada snapshot ini.</p>}</article>
  </section>
}

function Dashboard() {
  const [active, setActive] = useState('overview')
  const [transactionFilter, setTransactionFilter] = useState<TransactionTypeFilter>('all')
  const [selectedProject, setSelectedProject] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [theme, setTheme] = useState(() => localStorage.getItem('hollawall-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
  const queryEnabled = !PREVIEW_MODE || SNAPSHOT_MODE
  const snapshotQuery = useQuery({
    queryKey: ['snapshot', SNAPSHOT_MODE ? 'local' : 'live'],
    queryFn: () => loadSnapshot(SNAPSHOT_MODE),
    retry: 1,
    retryDelay: 1_000,
    enabled: queryEnabled,
    refetchInterval: SNAPSHOT_MODE ? 300_000 : 5_000,
    refetchIntervalInBackground: false,
  })

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('hollawall-theme', theme) }, [theme])
  useEffect(() => { document.title = `${pageMeta[active][1]} — Hollawall` }, [active])
  useEffect(() => { if (active !== 'transactions') setSelectedProject('') }, [active])

  const snapshot = snapshotQuery.data
  const coldLoading = queryEnabled && snapshotQuery.isPending && !snapshot
  const coldError = queryEnabled && snapshotQuery.isError && !snapshot
  const overview = snapshot?.overview ?? (PREVIEW_MODE ? demoOverview : emptyOverview)
  const meta = snapshot?.meta ?? (PREVIEW_MODE ? demoMeta : emptyMeta)
  const transactions = snapshot?.transactions ?? (PREVIEW_MODE ? demoTransactions : [])
  const wallets = snapshot?.wallets ?? []
  const debts = snapshot?.debts ?? []
  const projects = snapshot?.project_summaries ?? []
  const qualityRows = snapshot?.quality_rows ?? []
  const isDemo = !snapshot && PREVIEW_MODE
  const [eyebrow, title] = pageMeta[active]
  const sourceStatus = meta.source_status
  const statusLabel = sourceStatus === 'degraded' || sourceStatus === 'browser-cache'
    ? 'SUMBER CADANGAN'
    : 'SNAPSHOT PRODUKSI'
  const navigate = (value: string) => {
    setSelectedProject('')
    setTransactionFilter('all')
    setActive(value)
  }
  const openProject = (name: string) => {
    setSelectedProject(name)
    setTransactionFilter('projects')
    setActive('transactions')
  }
  const content = coldLoading
    ? <section className="inline-state loading-state" aria-live="polite" aria-busy="true"><span className="loading-pulse"></span><div><h2>Mengambil data keuangan</h2><p>Menu dan tampilan tetap bisa digunakan. Data akan muncul setelah sumber selesai merespons.</p></div></section>
    : coldError
      ? <section className="inline-state error-state" role="alert"><div><p className="eyebrow">SUMBER DATA TERGANGGU</p><h2>Dashboard belum bisa mengambil data</h2><p>Ini bukan masalah HP atau login. Coba lagi—halaman tidak akan mengunci layar.</p></div><button className="primary-button" onClick={() => snapshotQuery.refetch()}>Coba lagi</button></section>
      : active === 'overview'
        ? <OverviewPage overview={overview} transactions={transactions} meta={meta} projects={projects} walletSnapshots={wallets} setActive={setActive} setTransactionFilter={setTransactionFilter} />
        : <DetailPage active={active} transactions={transactions} overview={overview} wallets={wallets} debts={debts} projects={projects} dataThrough={meta.data_through} completeness={meta.data_completeness.completeness_pct} qualityRows={qualityRows} initialFilter={transactionFilter} initialQuery={selectedProject} onOpenProject={openProject} />

  return <div className="app-shell">
    <Sidebar active={active} setActive={navigate} open={menuOpen} setOpen={setMenuOpen} transactionCount={transactions.length} />
    <main className="main-canvas">
      <header className="topbar"><button className="icon-button mobile-only" onClick={() => setMenuOpen(true)} aria-label="Buka navigasi"><Menu size={21} /></button><div className="breadcrumbs"><span>Hollawall Group</span><b>/</b><strong>{title}</strong></div><div className="topbar-actions"><ThemeToggle theme={theme} setTheme={setTheme} /><button className={`icon-button ${snapshotQuery.isFetching ? 'is-spinning' : ''}`} aria-label="Segarkan snapshot" onClick={() => snapshotQuery.refetch()}><RefreshCcw size={17} /></button></div></header>
      <div className="content">
        {active === 'overview'
          ? <h1 className="sr-only">{title}</h1>
          : <section className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>Pandangan terukur atas posisi keuangan Hollawall.</p></div>{snapshot ? <div className={`demo-badge ${meta.freshness}`}>{statusLabel}</div> : isDemo && <div className="demo-badge">PRATINJAU · DATA DEMO</div>}</section>}
        {!coldLoading && !coldError && (active === 'overview'
          ? <div className="overview-provenance"><SnapshotContext dataThrough={meta.data_through} />{snapshot ? <span className="source-state">{statusLabel}</span> : isDemo && <span className="source-state">DATA DEMO</span>}</div>
          : <SnapshotContext dataThrough={meta.data_through} />)}
        {content}
      </div>
    </main>
  </div>
}

export default function App() {
  return <Dashboard />
}
