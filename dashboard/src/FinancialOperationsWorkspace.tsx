import { lazy, Suspense, useMemo, useState } from 'react'
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Landmark, Search, WalletCards } from 'lucide-react'

import type { CashTrendPoint, WalletSnapshot } from './snapshot'
import type { Transaction } from './types'

const FinancialChart = lazy(() => import('./FinancialChart'))
const IDR = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 0 })
const PERIODS = [{ key: '30', label: '30 hari' }, { key: '90', label: '90 hari' }, { key: 'all', label: 'Semua data' }] as const

type PeriodKey = typeof PERIODS[number]['key']
type MovementScope = 'all' | 'external' | 'internal' | 'income' | 'expense'

function amount(value: number) { return `Rp ${IDR.format(value)}` }
function day(value: string) { return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(`${value.slice(0, 10)}T12:00:00Z`)) }
function isInternal(row: Transaction) { return row.internal_movement === true || row.transfer_scope === 'internal' }
function signed(row: Transaction) { return row.transaction_type === 'Pemasukan' ? row.amount : -row.amount }
function latest(rows: Transaction[]) { return [...rows].sort((a, b) => b.transaction_date.localeCompare(a.transaction_date) || b.id - a.id) }
function recentMonths(rows: Transaction[], count = 6) {
  const anchor = latest(rows)[0]?.transaction_date
  if (!anchor) return []
  const date = new Date(`${anchor.slice(0, 7)}-01T00:00:00Z`)
  const cutoff = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() - (count - 1), 1))
  const key = `${cutoff.getUTCFullYear()}-${String(cutoff.getUTCMonth() + 1).padStart(2, '0')}`
  return rows.filter((row) => row.transaction_date.slice(0, 7) >= key && row.transaction_date.slice(0, 7) <= anchor.slice(0, 7))
}
function walletCompanies(name: string) {
  if (name === 'CV HB') return 'Holla · Hojja'
  if (name === 'TX SBY') return 'Texturin Surabaya'
  if (name === 'TX Bali') return 'Texturin Bali'
  return 'Sumber dana'
}
function rangeLabel(rows: Transaction[]) {
  if (!rows.length) return 'tanpa transaksi'
  const dates = rows.map((row) => row.transaction_date.slice(0, 10)).sort()
  return `${day(dates[0])}–${day(dates[dates.length - 1])}`
}

function filterPeriod(rows: Transaction[], period: PeriodKey, dataThrough?: string | null) {
  if (period === 'all') return rows
  const anchor = new Date(`${(dataThrough || rows.reduce((max, row) => row.transaction_date > max ? row.transaction_date : max, '1970-01-01')).slice(0, 10)}T12:00:00Z`)
  const cutoff = new Date(anchor)
  cutoff.setUTCDate(cutoff.getUTCDate() - Number(period) + 1)
  return rows.filter((row) => new Date(`${row.transaction_date.slice(0, 10)}T12:00:00Z`) >= cutoff)
}

function trendFromRows(rows: Transaction[], dataThrough?: string | null): CashTrendPoint[] {
  const latest = (dataThrough || rows.reduce((max, row) => row.transaction_date > max ? row.transaction_date : max, '1970-01-01')).slice(0, 7)
  const anchor = new Date(`${latest}-01T00:00:00Z`)
  let balance = 0
  return Array.from({ length: 12 }, (_, index) => {
    const date = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() - 11 + index, 1))
    const month = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
    const net_movement = rows.filter((row) => row.transaction_date.startsWith(month)).reduce((sum, row) => sum + signed(row), 0)
    balance += net_movement
    return { month, balance, net_movement }
  })
}

function FlowMetrics({ rows, internalOpen }: { rows: Transaction[]; internalOpen: number }) {
  const inflow = rows.filter((row) => row.transaction_type === 'Pemasukan').reduce((sum, row) => sum + row.amount, 0)
  const outflow = rows.filter((row) => row.transaction_type === 'Pengeluaran').reduce((sum, row) => sum + row.amount, 0)
  const net = inflow - outflow
  const metrics = [
    { label: 'Kas masuk eksternal', value: inflow, icon: ArrowDownLeft, tone: 'positive' },
    { label: 'Kas keluar eksternal', value: outflow, icon: ArrowUpRight, tone: 'negative' },
    { label: 'Arus bersih eksternal', value: net, icon: Landmark, tone: net >= 0 ? 'positive' : 'negative' },
    { label: 'Transfer internal terbuka', value: internalOpen, icon: ArrowLeftRight, tone: 'neutral' },
  ]
  return <div className="ops-metric-strip">
    {metrics.map(({ label, value, icon: Icon, tone }) => <article key={label} className={tone}>
      <span><Icon size={15} />{label}</span><strong>{amount(value)}</strong>
    </article>)}
  </div>
}

function MovementLedger({ rows, onOpenProject }: { rows: Transaction[]; onOpenProject?: (name: string) => void }) {
  const PAGE_SIZE = 8
  const [page, setPage] = useState(0)
  const ordered = latest(rows)
  const pages = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE))
  const visible = ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  if (!rows.length) return <div className="ops-empty"><strong>Belum ada pergerakan</strong><span>Ubah periode atau lingkup untuk melihat transaksi lain.</span></div>
  return <><div className="ops-ledger">
    {visible.map((row) => <article key={row.id}>
      <time>{day(row.transaction_date)}</time>
      <div><strong>{row.notes || row.project || 'Transaksi umum'}</strong><span>{[row.company, row.wallet].filter((value, index, all) => value && all.indexOf(value) === index).join(' · ')}</span></div>
      {row.project && !['-', 'Operasional Kantor', 'Hutang internal'].includes(row.project) ? <button type="button" onClick={() => onOpenProject?.(row.project)}>{row.project}</button> : <span>{isInternal(row) ? 'Hutang internal' : 'Tanpa proyek'}</span>}
      <em className={row.transaction_type === 'Pemasukan' ? 'positive' : 'negative'}>{row.transaction_type === 'Pemasukan' ? '+' : '−'}{amount(row.amount)}</em>
      <small>{isInternal(row) ? 'Internal' : 'Eksternal'} · Source {row.source_key || `ID ${row.id}`}</small>
    </article>)}
  </div>{pages > 1 && <nav className="ops-pagination" aria-label="Halaman mutasi"><button type="button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Sebelumnya</button><span>Halaman {page + 1} dari {pages} · {rows.length} transaksi</span><button type="button" disabled={page >= pages - 1} onClick={() => setPage((value) => Math.min(pages - 1, value + 1))}>Berikutnya</button></nav>}</>
}

export function CashflowWorkspace({ transactions, cashTrend, internalOpen = 0, dataThrough, onOpenProject }: { transactions: Transaction[]; cashTrend: CashTrendPoint[]; internalOpen?: number; dataThrough?: string | null; onOpenProject: (name: string) => void }) {
  const [period, setPeriod] = useState<PeriodKey>('90')
  const [company, setCompany] = useState('Semua unit')
  const years = useMemo(() => [...new Set(transactions.map((row) => row.transaction_date.slice(0, 4)))].sort((a, b) => b.localeCompare(a)), [transactions])
  const [year, setYear] = useState(years[0] ?? 'all')
  const companies = useMemo(() => [...new Set(transactions.filter((row) => !isInternal(row)).map((row) => row.company).filter(Boolean))].sort(), [transactions])
  const yearRows = useMemo(() => transactions.filter((row) => year === 'all' || row.transaction_date.startsWith(year)), [transactions, year])
  const activeDataThrough = yearRows.reduce((latest, row) => row.transaction_date > latest ? row.transaction_date : latest, '') || dataThrough
  const periodRows = useMemo(() => filterPeriod(yearRows, period, activeDataThrough), [yearRows, period, activeDataThrough])
  const scoped = useMemo(() => periodRows.filter((row) => company === 'Semua unit' || row.company === company), [periodRows, company])
  const operating = scoped.filter((row) => !isInternal(row))
  const activeTrend = period === 'all' && company === 'Semua unit' && year === 'all' ? cashTrend : trendFromRows(operating, activeDataThrough)
  const unitRows = useMemo(() => {
    const grouped = new Map<string, { incoming: number; outgoing: number; count: number }>()
    for (const row of periodRows.filter((item) => !isInternal(item))) {
      const item = grouped.get(row.company) ?? { incoming: 0, outgoing: 0, count: 0 }
      if (row.transaction_type === 'Pemasukan') item.incoming += row.amount
      else item.outgoing += row.amount
      item.count += 1
      grouped.set(row.company, item)
    }
    return [...grouped].map(([name, value]) => ({ name, ...value, net: value.incoming - value.outgoing })).sort((a, b) => Math.abs(b.net) - Math.abs(a.net))
  }, [periodRows])
  const inflow = operating.filter((row) => row.transaction_type === 'Pemasukan').reduce((sum, row) => sum + row.amount, 0)
  const outflow = operating.filter((row) => row.transaction_type === 'Pengeluaran').reduce((sum, row) => sum + row.amount, 0)

  return <section className="financial-ops cashflow-workspace">
    <header className="ops-heading"><div><p className="eyebrow">ARUS KAS</p><h2>Aliran kas, bukan sekadar saldo</h2><p>Pemasukan dan pengeluaran ditelusuri per periode dan perusahaan. Hutang internal tetap terpisah dari arus eksternal.</p></div><div className="ops-asof"><span>Data hingga</span><strong>{dataThrough ? day(dataThrough) : '—'}</strong></div></header>
    <div className="ops-filter-block">
      <div className="ops-filter-row"><label>Tahun<select aria-label="Tahun arus kas" value={year} onChange={(event) => setYear(event.target.value)}><option value="all">Semua tahun</option>{years.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><nav aria-label="Periode arus kas">{PERIODS.map((item) => <button type="button" className={period === item.key ? 'active' : ''} key={item.key} onClick={() => setPeriod(item.key)}>{item.label}</button>)}</nav></div>
      <nav className="ops-unit-filters" aria-label="Perusahaan"><button type="button" className={company === 'Semua unit' ? 'active' : ''} onClick={() => setCompany('Semua unit')}>Semua perusahaan</button>{companies.map((name) => <button type="button" className={company === name ? 'active' : ''} key={name} onClick={() => setCompany(name)}>{name}</button>)}</nav>
      <p className="ops-scope">Lingkup aktif: <strong>{company}</strong> · {year === 'all' ? 'semua tahun' : year} · {rangeLabel(operating)}. Hutang internal ditampilkan sebagai posisi terbuka dan tidak masuk arus bersih.</p>
    </div>
    <FlowMetrics rows={operating} internalOpen={internalOpen} />
    <div className="ops-chart-duo">
      <article className="ops-chart-panel showcase-chart"><header><div><p className="eyebrow">POLA BULANAN</p><h3>Masuk vs keluar bulanan</h3></div><span>{operating.length.toLocaleString('id-ID')} transaksi</span></header><div className="ops-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="monthly" transactions={operating} /></Suspense></div></article>
      <article className="ops-chart-panel showcase-chart"><header><div><p className="eyebrow">ARUS TERCATAT</p><h3>Tren arus kas tercatat</h3></div><span>12 bulan · lingkup aktif</span></header><div className="ops-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="cash" cashTrend={activeTrend} cashLabel="Arus kas tercatat" /></Suspense></div></article>
    </div>
    <div className="cashflow-insight-grid">
      <article className="ops-ratio-panel"><p className="eyebrow">TEKANAN KAS</p><h3>{inflow > 0 ? `${((outflow / inflow) * 100).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%` : '—'}</h3><span>pengeluaran terhadap pemasukan</span><div><i style={{ width: `${Math.min(inflow > 0 ? (outflow / inflow) * 100 : 0, 100)}%` }} /></div><p>{inflow === 0 ? 'Tidak ada pemasukan pada lingkup ini.' : outflow > inflow ? 'Kas keluar melampaui kas masuk pada periode ini.' : 'Kas masuk masih menutup kas keluar pada periode ini.'}</p></article>
      <section className="ops-unit-section"><header><div><p className="eyebrow">KONTRIBUSI BERSIH</p><h3>Kontribusi bersih per perusahaan</h3></div></header><div className="ops-unit-list">{unitRows.map((row) => <button type="button" key={row.name} onClick={() => setCompany(row.name)}><span><strong>{row.name}</strong><small>{row.count} transaksi</small></span><i><b style={{ width: `${Math.max(4, Math.min(Math.abs(row.net) / Math.max(...unitRows.map((item) => Math.abs(item.net)), 1) * 100, 100))}%` }} className={row.net >= 0 ? 'positive' : 'negative'} /></i><em className={row.net >= 0 ? 'positive' : 'negative'}>{amount(row.net)}</em></button>)}</div></section>
    </div>
    <section className="ops-ledger-section"><header><div><p className="eyebrow">MUTASI TERBARU</p><h3>Ledger transaksi</h3><p className="ops-ledger-scope">{company} · {year === 'all' ? 'semua tahun' : year} · {PERIODS.find((item) => item.key === period)?.label}</p></div><span>{scoped.length} transaksi</span></header><MovementLedger key={`${year}-${period}-${company}`} rows={scoped} onOpenProject={onOpenProject} /></section>
  </section>
}

export function WalletWorkspace({ transactions, wallets, dataThrough, onOpenProject }: { transactions: Transaction[]; wallets: WalletSnapshot[]; dataThrough?: string | null; onOpenProject: (name: string) => void }) {
  const [selectedName, setSelectedName] = useState(wallets[0]?.name ?? '')
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<MovementScope>('all')
  const selected = wallets.find((wallet) => wallet.name === selectedName) ?? wallets[0]
  const rows = selected ? transactions.filter((row) => row.wallet === selected.name) : []
  const visible = rows.filter((row) => [row.notes, row.project, row.company, row.source_key].some((value) => String(value ?? '').toLowerCase().includes(query.toLowerCase())))
  const external = rows.filter((row) => !isInternal(row))
  const internal = rows.filter(isInternal)
  const chartRows = recentMonths(external)
  const inflow = external.filter((row) => row.transaction_type === 'Pemasukan').reduce((sum, row) => sum + row.amount, 0)
  const outflow = external.filter((row) => row.transaction_type === 'Pengeluaran').reduce((sum, row) => sum + row.amount, 0)
  const gross = wallets.reduce((sum, wallet) => sum + Math.abs(wallet.balance), 0)
  const deficitCount = wallets.filter((wallet) => wallet.balance < 0).length
  const lastMovement = latest(rows)[0]
  const internalIn = internal.filter((row) => row.transaction_type === 'Pemasukan').reduce((sum, row) => sum + row.amount, 0)
  const internalOut = internal.filter((row) => row.transaction_type === 'Pengeluaran').reduce((sum, row) => sum + row.amount, 0)
  const scopedVisible = visible.filter((row) => scope === 'all' || scope === 'external' && !isInternal(row) || scope === 'internal' && isInternal(row) || scope === 'income' && row.transaction_type === 'Pemasukan' || scope === 'expense' && row.transaction_type === 'Pengeluaran')
  const selectedIndex = Math.max(0, wallets.findIndex((wallet) => wallet.name === selected?.name))

  return <section className="financial-ops wallet-workspace">
    <header className="ops-heading"><div><p className="eyebrow">DOMPET & REKENING</p><h2>Posisi kas per sumber</h2><p>Pilih satu dompet untuk menelusuri saldo, perusahaan pemilik, tren, mutasi, dan sumber pencatatannya.</p></div><div className="ops-asof"><span>Data hingga</span><strong>{dataThrough ? day(dataThrough) : '—'}</strong></div></header>
    <div className="wallet-summary-line"><span><WalletCards size={17} />{wallets.length} dompet terhubung</span><strong className={deficitCount ? 'negative' : 'positive'}>{deficitCount} saldo negatif · {wallets.length - deficitCount} saldo positif</strong></div>
    <article className="wallet-distribution showcase-chart"><header><div><p className="eyebrow">KONSOLIDASI DOMPET</p><h3>Sebaran saldo semua dompet</h3></div><span>Total bersih {amount(wallets.reduce((sum, wallet) => sum + wallet.balance, 0))}</span></header><div className="wallet-distribution-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="wallets" wallets={wallets} /></Suspense></div></article>
    <div className="wallet-rail-context"><span>Dompet {selectedIndex + 1} dari {wallets.length}</span><b><span className="desktop-wallet-hint">Pilih dompet lain</span><span className="mobile-wallet-hint">Geser untuk dompet lain →</span></b></div>
    <nav className="wallet-rail" aria-label="Pilih dompet">{wallets.map((wallet) => <button type="button" key={wallet.source_key} className={wallet.name === selected?.name ? 'active' : ''} onClick={() => { setSelectedName(wallet.name); setScope('all'); setQuery('') }}><span>{wallet.name}</span><small>{walletCompanies(wallet.name)}</small><strong className={wallet.balance >= 0 ? 'positive' : 'negative'}>{amount(wallet.balance)}</strong><small>Jejak · {wallet.source_key}</small></button>)}</nav>
    {selected && <>
      <section className="wallet-position"><div><p className="eyebrow">SALDO DOMPET TERPILIH</p><h3>{selected.name}</h3><p className="wallet-company-line">{walletCompanies(selected.name)}</p><strong className={selected.balance >= 0 ? 'positive' : 'negative'}>{amount(selected.balance)}</strong><span>{selected.balance >= 0 ? 'Saldo positif' : 'Saldo negatif'} · {gross ? `${((Math.abs(selected.balance) / gross) * 100).toLocaleString('id-ID', { maximumFractionDigits: 1 })}% dari total absolut saldo semua dompet` : 'tanpa saldo'}</span></div><dl><div><dt>Masuk · seluruh data</dt><dd className="positive">{amount(inflow)}</dd></div><div><dt>Keluar · seluruh data</dt><dd className="negative">{amount(outflow)}</dd></div><div><dt>Arus bersih · seluruh data</dt><dd className={inflow - outflow >= 0 ? 'positive' : 'negative'}>{amount(inflow - outflow)}</dd></div><div><dt>Aktivitas terakhir</dt><dd>{lastMovement ? day(lastMovement.transaction_date) : '—'}</dd></div></dl></section>
      <div className="wallet-analysis-grid">
        <article className="ops-chart-panel showcase-chart"><header><div><p className="eyebrow">POLA DOMPET</p><h3>Arus bulanan dompet terpilih</h3></div><span>6 bulan terakhir · {chartRows.length} transaksi eksternal</span></header><div className="ops-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="monthly" transactions={chartRows} /></Suspense></div></article>
        <article className="wallet-source-panel"><p className="eyebrow">TRANSPARANSI DATA</p><h3>Jejak sumber</h3><code>{selected.source_key}</code><dl><div><dt>Transaksi eksternal</dt><dd>{external.length.toLocaleString('id-ID')}</dd></div><div><dt>Masuk eksternal</dt><dd>{external.filter((row) => row.transaction_type === 'Pemasukan').length} · {amount(inflow)}</dd></div><div><dt>Keluar eksternal</dt><dd>{external.filter((row) => row.transaction_type === 'Pengeluaran').length} · {amount(outflow)}</dd></div><div><dt>Transfer internal terbuka</dt><dd>{internal.length} · masuk {amount(internalIn)} · keluar {amount(internalOut)}</dd></div></dl><p>Ringkasan posisi memakai transaksi eksternal. Transfer internal ditampilkan terpisah. Grafik menampilkan enam bulan terakhir. Semuanya berasal dari workspace demo yang sama.</p></article>
      </div>
      <section className="ops-ledger-section"><header><div><p className="eyebrow">RIWAYAT DOMPET</p><h3>Mutasi dompet</h3><p className="ops-ledger-scope">{selected.name} · {scopedVisible.length} hasil</p></div><label className="ops-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari mutasi…" aria-label="Cari mutasi dompet" /></label></header><nav className="movement-filters" aria-label="Filter mutasi">{([['all','Semua'],['external','Eksternal'],['internal','Internal'],['income','Masuk'],['expense','Keluar']] as Array<[MovementScope,string]>).map(([key,label]) => <button type="button" key={key} className={scope === key ? 'active' : ''} onClick={() => setScope(key)}>{label}</button>)}</nav><MovementLedger key={`${selected.name}-${scope}-${query}`} rows={scopedVisible} onOpenProject={onOpenProject} /></section>
    </>}
  </section>
}
