import { lazy, Suspense, useMemo, useState } from 'react'
import { ArrowDownRight, ArrowUpRight, Building2, WalletCards } from 'lucide-react'

const FinancialChart = lazy(() => import('./FinancialChart'))
import type { WalletSnapshot } from './snapshot'
import type { Transaction } from './types'

type Mode = 'company' | 'wallet'
type Portfolio = 'Hollawall' | 'Texturin'

type Unit = {
  key: string
  label: string
  portfolio: Portfolio
  mode: Mode
  wallet?: string
  company?: string
}

const COMPANY_UNITS: Unit[] = [
  { key: 'holla', label: 'Holla', portfolio: 'Hollawall', mode: 'company', company: 'HOLLA' },
  { key: 'hojja', label: 'Hojja', portfolio: 'Hollawall', mode: 'company', company: 'HOJJA' },
  { key: 'tx-surabaya', label: 'TX Surabaya', portfolio: 'Texturin', mode: 'company', company: 'TEXTURIN-Surabaya' },
  { key: 'tx-bali', label: 'TX Bali', portfolio: 'Texturin', mode: 'company', company: 'TEXTURIN-Bali' },
]

const WALLET_UNITS: Unit[] = [
  { key: 'cv-hb', label: 'CV HB (101)', portfolio: 'Hollawall', mode: 'wallet', wallet: 'CV HB(101)' },
  { key: 'tx-sby', label: 'TX SBY (216)', portfolio: 'Texturin', mode: 'wallet', wallet: 'TX SBY(216)' },
  { key: 'tx-bali-wallet', label: 'TX BALI (087)', portfolio: 'Texturin', mode: 'wallet', wallet: 'TX BALI(087)' },
]

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 2 })

function matches(unit: Unit, transaction: Transaction) {
  if (unit.mode === 'wallet') return transaction.wallet === unit.wallet
  const company = transaction.company.trim().toLocaleLowerCase('id-ID')
  const project = transaction.project.trim().toLocaleLowerCase('id-ID')
  if (company === unit.company?.toLocaleLowerCase('id-ID')) return true
  if (unit.key === 'holla') return project.startsWith('holla') || (company.startsWith('cv hb') && !project.startsWith('hojja'))
  if (unit.key === 'hojja') return project.startsWith('hojja')
  if (unit.key === 'tx-surabaya') return company.startsWith('tx sby') || company === 'texturin-surabaya'
  if (unit.key === 'tx-bali') return company.startsWith('tx bali') || company === 'texturin-bali'
  return transaction.company === unit.company
}

function UnitGroup({ portfolio, mode, active, onSelect }: { portfolio: Portfolio; mode: Mode; active: string; onSelect: (unit: Unit) => void }) {
  const units = (mode === 'company' ? COMPANY_UNITS : WALLET_UNITS).filter((unit) => unit.portfolio === portfolio)
  return <section className="unit-group" aria-label={`${portfolio} ${mode === 'company' ? 'perusahaan' : 'dompet'}`}>
    <div className="unit-group-label">
      <h3>{portfolio} Section</h3>
      <span>{units.length} {mode === 'company' ? 'perusahaan' : 'dompet'}</span>
    </div>
    <div className="unit-options">
      {units.map((unit) => <button
        type="button"
        key={unit.key}
        className={`unit-option ${active === unit.key ? 'is-active' : ''}`}
        aria-pressed={active === unit.key}
        aria-label={`Pilih ${mode === 'company' ? 'perusahaan' : 'dompet'} ${unit.label}`}
        onClick={() => onSelect(unit)}
      >{unit.label}</button>)}
    </div>
  </section>
}

export default function BusinessSectionReport({ transactions, wallets }: { transactions: Transaction[]; wallets: WalletSnapshot[] }) {
  const [mode, setMode] = useState<Mode>('company')
  const [focus, setFocus] = useState<Portfolio>('Hollawall')
  const [selected, setSelected] = useState<Record<Portfolio, string>>({ Hollawall: 'holla', Texturin: 'tx-surabaya' })
  const units = mode === 'company' ? COMPANY_UNITS : WALLET_UNITS
  const activeUnit = units.find((unit) => unit.key === selected[focus]) ?? units[0]

  const setModeAndSelection = (next: Mode) => {
    setMode(next)
    setFocus('Hollawall')
    setSelected(next === 'company'
      ? { Hollawall: 'holla', Texturin: 'tx-surabaya' }
      : { Hollawall: 'cv-hb', Texturin: 'tx-sby' })
  }

  const choose = (unit: Unit) => {
    setFocus(unit.portfolio)
    setSelected((current) => ({ ...current, [unit.portfolio]: unit.key }))
  }
  const filtered = useMemo(() => transactions.filter((transaction) => matches(activeUnit, transaction)), [activeUnit, transactions])
  const wallet = activeUnit.wallet ? wallets.find((item) => item.name === activeUnit.wallet) : undefined
  const unitDates = filtered.map((row) => row.transaction_date.slice(0, 10)).sort()
  const firstDate = unitDates.length ? new Date(`${unitDates[0]}T00:00:00`) : null
  const lastDate = unitDates.length ? new Date(`${unitDates.at(-1)}T00:00:00`) : null
  const unitPeriod = firstDate && lastDate
    ? `${firstDate.toLocaleDateString('id-ID', { month: 'short', year: 'numeric' })}–${lastDate.toLocaleDateString('id-ID', { month: 'short', year: 'numeric' })}`
    : 'belum ada periode'
  const chartStart = lastDate ? new Date(lastDate.getFullYear(), lastDate.getMonth() - 5, 1) : null
  const chartPeriod = chartStart && lastDate
    ? `${chartStart.toLocaleDateString('id-ID', { month: 'short' })}–${lastDate.toLocaleDateString('id-ID', { month: 'short', year: 'numeric' })}`
    : 'belum ada periode'
  const incoming = filtered.filter((row) => row.transaction_type === 'Pemasukan').reduce((sum, row) => sum + row.amount, 0)
  const outgoing = filtered.filter((row) => row.transaction_type === 'Pengeluaran').reduce((sum, row) => sum + row.amount, 0)
  const net = incoming - outgoing
  const headlineValue = mode === 'wallet' && wallet ? wallet.balance : net

  return <section className="business-report" aria-label="Laporan unit usaha">
    <header className="business-report-head">
      <div>
        <p className="eyebrow">UNIT USAHA</p>
        <h2>Arus kas per unit</h2>
        <p>Lihat arus kas perusahaan atau dompet.</p>
      </div>
      <div className="business-mode-switch" role="group" aria-label="Dasar laporan">
        <button type="button" className={mode === 'company' ? 'is-active' : ''} onClick={() => setModeAndSelection('company')}><Building2 size={15} />Perusahaan</button>
        <button type="button" aria-label="Lihat berdasarkan dompet" className={mode === 'wallet' ? 'is-active' : ''} onClick={() => setModeAndSelection('wallet')}><WalletCards size={15} />Dompet</button>
      </div>
    </header>

    <nav className="unit-navigator" aria-label="Pilih unit laporan">
      <UnitGroup portfolio="Hollawall" mode={mode} active={selected.Hollawall} onSelect={choose} />
      <UnitGroup portfolio="Texturin" mode={mode} active={selected.Texturin} onSelect={choose} />
    </nav>

    <div className="unit-workspace">
      <article className="unit-focus-canvas">
        <header className="unit-focus-head">
          <div>
            <p className="unit-context">{activeUnit.portfolio} · {mode === 'company' ? 'Perusahaan' : 'Dompet'}</p>
            <h3>{activeUnit.label}</h3>
            <p>{filtered.length} transaksi · data {unitPeriod} · grafik {chartPeriod}</p>
          </div>
          <div className="unit-balance">
            <small>{mode === 'wallet' ? 'Saldo dompet' : 'Arus kas bersih'}</small>
            <strong>{IDR.format(headlineValue)}</strong>
          </div>
        </header>

        <dl className="unit-metrics">
          <div><dt>Masuk</dt><dd className="positive">{compact.format(incoming)}</dd></div>
          <div><dt>Keluar</dt><dd className="negative">{compact.format(outgoing)}</dd></div>
          <div><dt>Bersih</dt><dd>{compact.format(net)}</dd></div>
        </dl>

        <div className="business-monthly-chart">{filtered.length > 0
          ? <Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="monthly" transactions={filtered} /></Suspense>
          : <div className="business-chart-empty"><strong>Belum ada grafik</strong><span>Grafik muncul setelah unit ini memiliki transaksi.</span></div>}
        </div>
      </article>

      <aside className="activity-stream" aria-label={`Aktivitas ${activeUnit.label}`}>
        <header><div><p className="eyebrow">AKTIVITAS</p><h3>Terbaru</h3></div><span>{filtered.length}</span></header>
        <div className="business-ledger-list">
          {filtered.slice(0, 6).map((row) => <div key={row.id} className="business-ledger-row">
            <span className={row.transaction_type === 'Pemasukan' ? 'income' : 'expense'}>{row.transaction_type === 'Pemasukan' ? <ArrowDownRight size={15} /> : <ArrowUpRight size={15} />}</span>
            <div><strong>{row.project || row.notes || 'Transaksi'}</strong><small>{row.notes || row.wallet} · {new Date(row.transaction_date).toLocaleDateString('id-ID', { day: '2-digit', month: 'short' })}</small></div>
            <b className={row.transaction_type === 'Pemasukan' ? 'positive' : 'negative'}>{row.transaction_type === 'Pemasukan' ? '+' : '−'}{compact.format(row.amount)}</b>
          </div>)}
          {filtered.length === 0 && <div className="business-empty"><strong>Belum ada transaksi</strong><p>Unit ini belum memiliki aktivitas pada snapshot aktif.</p></div>}
        </div>
      </aside>
    </div>
  </section>
}
