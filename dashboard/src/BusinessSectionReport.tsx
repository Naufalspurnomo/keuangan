import { lazy, Suspense, useMemo, useState } from 'react'
import { ArrowDownRight, ArrowUpRight, Building2, ChevronRight, WalletCards } from 'lucide-react'

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
  accent: string
}

const COMPANY_UNITS: Unit[] = [
  { key: 'holla', label: 'Holla', portfolio: 'Hollawall', mode: 'company', company: 'HOLLA', accent: 'coral' },
  { key: 'hojja', label: 'Hojja', portfolio: 'Hollawall', mode: 'company', company: 'HOJJA', accent: 'gold' },
  { key: 'tx-surabaya', label: 'TX Surabaya', portfolio: 'Texturin', mode: 'company', company: 'TEXTURIN-Surabaya', accent: 'teal' },
  { key: 'tx-bali', label: 'TX Bali', portfolio: 'Texturin', mode: 'company', company: 'TEXTURIN-Bali', accent: 'violet' },
]

const WALLET_UNITS: Unit[] = [
  { key: 'cv-hb', label: 'CV HB (101)', portfolio: 'Hollawall', mode: 'wallet', wallet: 'CV HB(101)', accent: 'gold' },
  { key: 'tx-sby', label: 'TX SBY (216)', portfolio: 'Texturin', mode: 'wallet', wallet: 'TX SBY(216)', accent: 'teal' },
  { key: 'tx-bali-wallet', label: 'TX BALI (087)', portfolio: 'Texturin', mode: 'wallet', wallet: 'TX BALI(087)', accent: 'violet' },
]

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 2 })

function matches(unit: Unit, transaction: Transaction) {
  if (unit.mode === 'wallet') return transaction.wallet === unit.wallet
  return transaction.company.trim().toLocaleLowerCase('id-ID') === unit.company?.toLocaleLowerCase('id-ID')
}

function UnitRail({ portfolio, mode, active, onSelect }: { portfolio: Portfolio; mode: Mode; active: string; onSelect: (unit: Unit) => void }) {
  const units = (mode === 'company' ? COMPANY_UNITS : WALLET_UNITS).filter((unit) => unit.portfolio === portfolio)
  return <div className="business-unit-rail">
    {units.map((unit) => <button
      type="button"
      key={unit.key}
      className={`business-unit ${active === unit.key ? 'is-active' : ''}`}
      aria-label={`Pilih ${mode === 'company' ? 'perusahaan' : 'dompet'} ${unit.label}`}
      onClick={() => onSelect(unit)}
    >
      <i className={`business-unit-mark ${unit.accent}`} />
      <span><small>{mode === 'company' ? 'Perusahaan' : 'Dompet'}</small><strong>{unit.label}</strong></span>
      <ChevronRight size={16} />
    </button>)}
  </div>
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
  const incoming = filtered.filter((row) => row.transaction_type === 'Pemasukan').reduce((sum, row) => sum + row.amount, 0)
  const outgoing = filtered.filter((row) => row.transaction_type === 'Pengeluaran').reduce((sum, row) => sum + row.amount, 0)
  const net = incoming - outgoing
  const portfolio = activeUnit.portfolio

  return <section className="business-report" aria-label="Laporan unit usaha">
    <header className="business-report-head">
      <div><p className="eyebrow">PORTFOLIO REPORT</p><h2>Bedah perusahaan dan dompet</h2><p>Pilih satu unit. Grafik, proyek, dan transaksi mengikuti konteks pilihan.</p></div>
      <div className="business-mode-switch" role="group" aria-label="Dasar laporan">
        <button type="button" className={mode === 'company' ? 'is-active' : ''} onClick={() => setModeAndSelection('company')}><Building2 size={16} />4 Perusahaan</button>
        <button type="button" aria-label="Lihat berdasarkan dompet" className={mode === 'wallet' ? 'is-active' : ''} onClick={() => setModeAndSelection('wallet')}><WalletCards size={16} />3 Dompet</button>
      </div>
    </header>

    <div className="portfolio-sections">
      {(['Hollawall', 'Texturin'] as Portfolio[]).map((section) => <article key={section} className={`portfolio-section ${portfolio === section ? 'is-focused' : ''}`}>
        <div className="portfolio-section-head">
          <span>{section === 'Hollawall' ? 'HW' : 'TX'}</span>
          <div><p>{section.toUpperCase()}</p><h3>{section} Section</h3></div>
          <small>{mode === 'company' ? COMPANY_UNITS.filter((unit) => unit.portfolio === section).length + ' perusahaan' : WALLET_UNITS.filter((unit) => unit.portfolio === section).length + ' dompet'}</small>
        </div>
        <UnitRail portfolio={section} mode={mode} active={selected[section]} onSelect={choose} />
      </article>)}
    </div>

    <div className="business-report-detail">
      <article className="business-chart-card">
        <div className="business-detail-title">
          <div><p className="eyebrow">{portfolio.toUpperCase()} · {mode === 'company' ? 'PERUSAHAAN' : 'DOMPET'}</p><h3>{activeUnit.label}</h3><p>{filtered.length} transaksi dalam snapshot aktif</p></div>
          <strong>{mode === 'wallet' && wallet ? IDR.format(wallet.balance) : IDR.format(net)}<small>{mode === 'wallet' ? 'saldo dompet' : 'arus kas bersih'}</small></strong>
        </div>
        <div className="business-stat-row">
          <span><small>Masuk</small><b className="positive">{compact.format(incoming)}</b></span>
          <span><small>Keluar</small><b className="negative">{compact.format(outgoing)}</b></span>
          <span><small>Bersih</small><b>{compact.format(net)}</b></span>
        </div>
        <div className="business-monthly-chart"><Suspense fallback={<div className="chart-skeleton" />}><FinancialChart kind="monthly" transactions={filtered} /></Suspense></div>
      </article>

      <article className="business-ledger-card">
        <div className="panel-head"><div><p className="eyebrow">RINCIAN TERPILIH</p><h3>Aktivitas {activeUnit.label}</h3></div><span className="business-live-dot">LIVE</span></div>
        <div className="business-ledger-list">
          {filtered.slice(0, 6).map((row) => <div key={row.id} className="business-ledger-row">
            <span className={row.transaction_type === 'Pemasukan' ? 'income' : 'expense'}>{row.transaction_type === 'Pemasukan' ? <ArrowDownRight size={16} /> : <ArrowUpRight size={16} />}</span>
            <div><strong>{row.project || row.notes || 'Transaksi'}</strong><small>{row.notes || row.wallet} · {new Date(row.transaction_date).toLocaleDateString('id-ID', { day: '2-digit', month: 'short' })}</small></div>
            <b className={row.transaction_type === 'Pemasukan' ? 'positive' : 'negative'}>{row.transaction_type === 'Pemasukan' ? '+' : '−'}{compact.format(row.amount)}</b>
          </div>)}
          {filtered.length === 0 && <div className="business-empty"><strong>Belum ada transaksi</strong><p>Unit ini belum memiliki aktivitas pada snapshot aktif.</p></div>}
        </div>
      </article>
    </div>
  </section>
}
