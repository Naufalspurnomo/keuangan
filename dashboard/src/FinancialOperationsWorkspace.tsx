import { lazy, Suspense, useMemo, useState } from 'react'
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Landmark, Search, WalletCards } from 'lucide-react'

import type { WalletSnapshot } from './snapshot'
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

function FlowMetrics({ rows, internalRows }: { rows: Transaction[]; internalRows: Transaction[] }) {
  const inflow = rows.filter((row) => row.transaction_type === 'Pemasukan').reduce((sum, row) => sum + row.amount, 0)
  const outflow = rows.filter((row) => row.transaction_type === 'Pengeluaran').reduce((sum, row) => sum + row.amount, 0)
  const net = inflow - outflow
  const internal = internalRows.reduce((sum, row) => sum + row.amount, 0)
  const metrics = [
    { label: 'Kas masuk eksternal', value: inflow, icon: ArrowDownLeft, tone: 'positive' },
    { label: 'Kas keluar eksternal', value: outflow, icon: ArrowUpRight, tone: 'negative' },
    { label: 'Arus bersih eksternal', value: net, icon: Landmark, tone: net >= 0 ? 'positive' : 'negative' },
    { label: 'Transfer internal bruto', value: internal, icon: ArrowLeftRight, tone: 'neutral' },
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
      <div><strong>{row.notes || row.project || 'Transaksi operasional'}</strong><span>{[row.company, row.wallet].filter((value, index, all) => value && all.indexOf(value) === index).join(' · ')}</span></div>
      {row.project && row.project !== '-' ? <button type="button" onClick={() => onOpenProject?.(row.project)}>{row.project}</button> : <span>Tanpa proyek</span>}
      <em className={row.transaction_type === 'Pemasukan' ? 'positive' : 'negative'}>{row.transaction_type === 'Pemasukan' ? '+' : '−'}{amount(row.amount)}</em>
      <small>{isInternal(row) ? 'Internal' : 'Eksternal'} · Source {row.source_key || `ID ${row.id}`}</small>
    </article>)}
  </div>{pages > 1 && <nav className="ops-pagination" aria-label="Halaman mutasi"><button type="button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Sebelumnya</button><span>Halaman {page + 1} dari {pages} · {rows.length} transaksi</span><button type="button" disabled={page >= pages - 1} onClick={() => setPage((value) => Math.min(pages - 1, value + 1))}>Berikutnya</button></nav>}</>
}

export function CashflowWorkspace({ transactions, dataThrough, onOpenProject }: { transactions: Transaction[]; dataThrough?: string | null; onOpenProject: (name: string) => void }) {
  const [period, setPeriod] = useState<PeriodKey>('90')
  const [company, setCompany] = useState('Semua unit')
  const companies = useMemo(() => [...new Set(transactions.map((row) => row.company).filter(Boolean))].sort(), [transactions])
  const periodRows = useMemo(() => filterPeriod(transactions, period, dataThrough), [transactions, period, dataThrough])
  const scoped = useMemo(() => periodRows.filter((row) => company === 'Semua unit' || row.company === company), [periodRows, company])
  const operating = scoped.filter((row) => !isInternal(row))
  const internal = scoped.filter(isInternal)
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
    <header className="ops-heading"><div><p className="eyebrow">ARUS KAS</p><h2>Aliran operasi, bukan sekadar saldo</h2><p>Transfer internal dipisahkan agar kas masuk dan keluar eksternal tidak terhitung dua kali.</p></div><div className="ops-asof"><span>Data s.d.</span><strong>{dataThrough ? day(dataThrough) : '—'}</strong></div></header>
    <div className="ops-filter-block">
      <nav aria-label="Periode arus kas">{PERIODS.map((item) => <button type="button" className={period === item.key ? 'active' : ''} key={item.key} onClick={() => setPeriod(item.key)}>{item.label}</button>)}</nav>
      <nav className="ops-unit-filters" aria-label="Unit usaha"><button type="button" className={company === 'Semua unit' ? 'active' : ''} onClick={() => setCompany('Semua unit')}>Semua unit</button>{companies.map((name) => <button type="button" className={company === name ? 'active' : ''} key={name} onClick={() => setCompany(name)}>{name}</button>)}</nav>
      <p className="ops-scope">Lingkup aktif: <strong>{company}</strong> · {rangeLabel(operating)} · transaksi eksternal. Transfer internal bruto ditampilkan terpisah dan tidak masuk arus bersih.</p>
    </div>
    <FlowMetrics rows={operating} internalRows={internal} />
    <div className="ops-analysis-grid">
      <article className="ops-chart-panel"><header><div><p className="eyebrow">POLA BULANAN</p><h3>Masuk vs keluar eksternal</h3></div><span>{operating.length.toLocaleString('id-ID')} transaksi eksternal</span></header><div className="ops-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="monthly" transactions={operating} /></Suspense></div></article>
      <article className="ops-ratio-panel"><p className="eyebrow">TEKANAN KAS</p><h3>{inflow > 0 ? `${((outflow / inflow) * 100).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%` : '—'}</h3><span>pengeluaran terhadap pemasukan</span><div><i style={{ width: `${Math.min(inflow > 0 ? (outflow / inflow) * 100 : 0, 100)}%` }} /></div><p>{inflow === 0 ? 'Tidak ada pemasukan eksternal pada lingkup ini.' : outflow > inflow ? 'Kas keluar melampaui kas masuk pada periode ini.' : 'Kas masuk masih menutup kas keluar pada periode ini.'}</p></article>
    </div>
    <section className="ops-unit-section"><header><div><p className="eyebrow">KONTRIBUSI NET EKSTERNAL</p><h3>Siapa menghasilkan atau menyerap kas</h3></div></header><div className="ops-unit-list">{unitRows.map((row) => <button type="button" key={row.name} onClick={() => setCompany(row.name)}><span><strong>{row.name}</strong><small>{row.count} transaksi eksternal</small></span><i><b style={{ width: `${Math.max(4, Math.min(Math.abs(row.net) / Math.max(...unitRows.map((item) => Math.abs(item.net)), 1) * 100, 100))}%` }} className={row.net >= 0 ? 'positive' : 'negative'} /></i><em className={row.net >= 0 ? 'positive' : 'negative'}>{amount(row.net)}</em></button>)}</div></section>
    <section className="ops-ledger-section"><header><div><p className="eyebrow">LEDGER OPERASIONAL</p><h3>{company} · {PERIODS.find((item) => item.key === period)?.label}</h3></div><span>{operating.length} eksternal · {internal.length} internal</span></header><MovementLedger key={`${period}-${company}`} rows={[...operating, ...internal]} onOpenProject={onOpenProject} /></section>
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
    <header className="ops-heading"><div><p className="eyebrow">DOMPET & REKENING</p><h2>Posisi kas per sumber</h2><p>Pilih satu dompet untuk menelusuri saldo, movement, transfer internal, dan sumber datanya.</p></div><div className="ops-asof"><span>Data s.d.</span><strong>{dataThrough ? day(dataThrough) : '—'}</strong></div></header>
    <div className="wallet-summary-line"><span><WalletCards size={17} />{wallets.length} dompet terhubung</span><strong className={deficitCount ? 'negative' : 'positive'}>{deficitCount} defisit · {wallets.length - deficitCount} surplus</strong></div>
    <div className="wallet-rail-context"><span>Dompet {selectedIndex + 1} dari {wallets.length}</span><b>Geser untuk dompet lain →</b></div>
    <nav className="wallet-rail" aria-label="Pilih dompet">{wallets.map((wallet) => <button type="button" key={wallet.source_key} className={wallet.name === selected?.name ? 'active' : ''} onClick={() => { setSelectedName(wallet.name); setScope('all'); setQuery('') }}><span>{wallet.name}</span><strong className={wallet.balance >= 0 ? 'positive' : 'negative'}>{amount(wallet.balance)}</strong><small>Kunci snapshot · {wallet.source_key}</small></button>)}</nav>
    {selected && <>
      <section className="wallet-position"><div><p className="eyebrow">SALDO SNAPSHOT</p><h3>{selected.name}</h3><strong className={selected.balance >= 0 ? 'positive' : 'negative'}>{amount(selected.balance)}</strong><span>{selected.balance >= 0 ? 'Posisi surplus' : 'Posisi defisit'} · {gross ? `${((Math.abs(selected.balance) / gross) * 100).toLocaleString('id-ID', { maximumFractionDigits: 1 })}% dari total absolut saldo semua dompet` : 'tanpa saldo'}</span></div><dl><div><dt>Masuk eksternal · seluruh data</dt><dd className="positive">{amount(inflow)}</dd></div><div><dt>Keluar eksternal · seluruh data</dt><dd className="negative">{amount(outflow)}</dd></div><div><dt>Net eksternal · seluruh data</dt><dd className={inflow - outflow >= 0 ? 'positive' : 'negative'}>{amount(inflow - outflow)}</dd></div><div><dt>Aktivitas terakhir</dt><dd>{lastMovement ? day(lastMovement.transaction_date) : '—'}</dd></div></dl></section>
      <div className="wallet-analysis-grid">
        <article className="ops-chart-panel"><header><div><p className="eyebrow">POLA DOMPET</p><h3>Arus eksternal bulanan</h3></div><span>{external.length} eksternal · {internal.length} internal</span></header><div className="ops-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="monthly" transactions={external} /></Suspense></div></article>
        <article className="wallet-source-panel"><p className="eyebrow">JEJAK SUMBER</p><h3>Kunci snapshot · {selected.source_key}</h3><dl><div><dt>Seluruh transaksi</dt><dd>{rows.length.toLocaleString('id-ID')}</dd></div><div><dt>Internal masuk</dt><dd>{internal.filter((row) => row.transaction_type === 'Pemasukan').length} · {amount(internalIn)}</dd></div><div><dt>Internal keluar</dt><dd>{internal.filter((row) => row.transaction_type === 'Pengeluaran').length} · {amount(internalOut)}</dd></div></dl><p>Saldo snapshot tetap kanonis; movement dipakai untuk penelusuran, bukan menghitung ulang saldo secara diam-diam.</p></article>
      </div>
      <section className="ops-ledger-section"><header><div><p className="eyebrow">MUTASI DOMPET</p><h3>{selected.name}</h3><span>{scopedVisible.length} hasil</span></div><label className="ops-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari mutasi…" aria-label="Cari mutasi dompet" /></label></header><nav className="movement-filters" aria-label="Filter mutasi">{([['all','Semua'],['external','Eksternal'],['internal','Internal'],['income','Masuk'],['expense','Keluar']] as Array<[MovementScope,string]>).map(([key,label]) => <button type="button" key={key} className={scope === key ? 'active' : ''} onClick={() => setScope(key)}>{label}</button>)}</nav><MovementLedger key={`${selected.name}-${scope}-${query}`} rows={scopedVisible} onOpenProject={onOpenProject} /></section>
    </>}
  </section>
}
