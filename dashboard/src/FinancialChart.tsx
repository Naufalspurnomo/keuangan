import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, LabelList, Legend, Line, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { CashTrendPoint, DebtSnapshot, ProjectSummary, WalletSnapshot } from './snapshot'
import type { Transaction } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
const compact = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 1 })
const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })

function monthLabel(value: unknown) {
  const [year, month] = String(value ?? '').split('-').map(Number)
  return month >= 1 && month <= 12 ? `${MONTHS[month - 1]} ${String(year).slice(2)}` : String(value ?? '')
}

function ChartFallback() {
  return <div className="chart-skeleton" />
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name?: string; value?: number; dataKey?: string; color?: string }>; label?: string }) {
  if (!active || !payload?.length) return null
  return <div className="chart-tooltip">
    <strong>{typeof label === 'string' ? label : monthLabel(label)}</strong>
    {payload.map((entry) => <span key={String(entry.dataKey ?? entry.name)}>{entry.name ?? 'Nilai'}: <b>{IDR.format(Number(entry.value ?? 0))}</b></span>)}
  </div>
}

export default function FinancialChart({ kind, cashTrend = [], projects = [], wallets = [], debts = [], transactions = [] }: {
  kind: 'cash' | 'projects' | 'wallets' | 'monthly' | 'debts' | 'waterfall'
  cashTrend?: CashTrendPoint[]
  projects?: ProjectSummary[]
  wallets?: WalletSnapshot[]
  debts?: DebtSnapshot[]
  transactions?: Transaction[]
}) {
  if (kind === 'cash') {
    return <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={cashTrend} margin={{ top: 18, right: 18, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="cashGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-primary)" stopOpacity={0.32} />
            <stop offset="100%" stopColor="var(--chart-primary)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="month" tickFormatter={monthLabel} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
        <YAxis width={58} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => compact.format(value)} />
        <Tooltip content={<ChartTooltip />} />
        <Area type="monotone" dataKey="balance" name="Saldo kas" connectNulls isAnimationActive={false} stroke="none" fill="url(#cashGradient)" />
        <Line type="monotone" dataKey="balance" name="Saldo kas" connectNulls isAnimationActive={false} dot={{ r: 3, fill: 'var(--surface)', stroke: 'var(--chart-primary)', strokeWidth: 2 }} activeDot={{ r: 5 }} stroke="var(--chart-primary)" strokeWidth={2.5} />
      </ComposedChart>
    </ResponsiveContainer>
  }

  if (kind === 'projects') {
    const rows = [...projects].sort((a, b) => Math.abs(b.net_cashflow) - Math.abs(a.net_cashflow)).slice(0, 5)
    return <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 62, bottom: 18, left: 0 }}>
        <XAxis type="number" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => compact.format(value)} />
        <YAxis type="category" dataKey="name" width={112} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
        <Tooltip cursor={{ fill: 'var(--surface-muted)' }} content={<ChartTooltip />} />
        <Bar dataKey="net_cashflow" name="Arus kas bersih" radius={[0, 5, 5, 0]} barSize={18}>
          {rows.map((row, index) => <Cell key={row.name} fill={row.net_cashflow < 0 ? 'var(--negative)' : index === 0 ? 'var(--chart-primary)' : 'var(--chart-secondary)'} />)}
          <LabelList dataKey="net_cashflow" position="right" formatter={(value) => compact.format(Number(value ?? 0))} fill="var(--text-secondary)" fontSize={10} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  }

  if (kind === 'wallets') {
    const sorted = [...wallets].sort((a, b) => Math.abs(b.balance) - Math.abs(a.balance))
    const total = sorted.reduce((sum, row) => sum + row.balance, 0)
    const gross = sorted.reduce((sum, row) => sum + Math.abs(row.balance), 0)
    const leading = sorted.slice(0, 5).map((row) => ({
      name: row.name.length > 20 ? `${row.name.slice(0, 18)}…` : row.name,
      value: Math.abs(row.balance),
      signed: row.balance,
      full: row.name,
    }))
    const remainder = sorted.slice(5)
    const rows = remainder.length === 0
      ? leading
      : [...leading, {
          name: 'Lainnya',
          value: remainder.reduce((sum, row) => sum + Math.abs(row.balance), 0),
          signed: remainder.reduce((sum, row) => sum + row.balance, 0),
          full: `${remainder.length} dompet lainnya`,
        }]
    const COLORS = ['var(--chart-primary)', 'var(--chart-neutral-1)', 'var(--chart-neutral-2)', 'var(--chart-neutral-3)', 'var(--chart-neutral-4)', 'var(--chart-neutral-5)']
    return <div className="donut-with-legend">
      <div className="donut-chart-figure">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={rows} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="86%" paddingAngle={2} stroke="var(--surface)" strokeWidth={2}>
              {rows.map((_, index) => <Cell key={index} fill={COLORS[index % COLORS.length]} />)}
            </Pie>
            <Tooltip content={<ChartTooltip />} formatter={(value, name) => [IDR.format(Number(value ?? 0)), String(name)]} />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center"><small>Total</small><strong>{compact.format(total)}</strong></div>
      </div>
      <ul className="donut-legend">
        {rows.map((row, index) => <li key={row.full}>
          <i style={{ background: COLORS[index % COLORS.length] }} />
          <span title={row.full}>{row.name}</span>
          <b>{compact.format(row.signed)}</b>
          <small>{gross > 0 ? `${((row.value / gross) * 100).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%` : '0%'}</small>
        </li>)}
      </ul>
    </div>
  }

  if (kind === 'monthly') {
    const monthly = Array.from({ length: 6 }, (_, i) => {
      const date = new Date()
      date.setMonth(date.getMonth() - (5 - i))
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
      const rows = transactions.filter((t) => t.transaction_date.startsWith(key))
      return {
        month: key,
        masuk: rows.filter((t) => t.transaction_type === 'Pemasukan').reduce((sum, t) => sum + t.amount, 0),
        keluar: rows.filter((t) => t.transaction_type === 'Pengeluaran').reduce((sum, t) => sum + t.amount, 0),
        empty: rows.length === 0,
      }
    })
    const hasGap = monthly.some((m) => m.empty)
    return <div className="monthly-chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={monthly} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <defs>
            <pattern id="expenseHatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="var(--negative)" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--surface)" strokeOpacity=".38" strokeWidth="2" />
            </pattern>
          </defs>
          <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
          <XAxis dataKey="month" tickFormatter={monthLabel} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
          <YAxis width={58} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => compact.format(value)} />
          <Tooltip cursor={{ fill: 'var(--surface-muted)' }} content={<ChartTooltip />} />
          <Legend verticalAlign="top" align="right" height={26} iconType="circle" iconSize={8} formatter={(value: unknown) => <span className="chart-legend-label">{String(value)}</span>} />
          <Bar dataKey="masuk" name="Pemasukan" fill="var(--positive)" radius={[3, 3, 0, 0]} barSize={18} />
          <Bar dataKey="keluar" name="Pengeluaran" fill="url(#expenseHatch)" radius={[3, 3, 0, 0]} barSize={18} />
        </ComposedChart>
      </ResponsiveContainer>
      {hasGap && <p className="chart-note">Beberapa periode belum memiliki transaksi tercatat pada snapshot.</p>}
    </div>
  }

  if (kind === 'debts') {
    const rows = debts.filter((d) => d.status === 'OPEN').slice(0, 5).map((d) => ({ name: `${d.borrower.slice(0, 14)}→${d.lender.slice(0, 14)}`, value: d.amount }))
    return <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} />
        <YAxis width={58} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => compact.format(value)} />
        <Tooltip cursor={{ fill: 'var(--surface-muted)' }} content={<ChartTooltip />} />
        <Bar dataKey="value" name="Hutang terbuka" fill="var(--warning)" radius={[5, 5, 0, 0]} barSize={32} />
      </BarChart>
    </ResponsiveContainer>
  }

  if (kind === 'waterfall') {
    const totals = transactions.reduce((acc, t) => {
      const type = t.transaction_type === 'Pemasukan' ? 'income' : 'expense'
      acc[type] += t.amount
      return acc
    }, { income: 0, expense: 0 })
    const net = totals.income - totals.expense
    const points = [
      { name: 'Total masuk', base: 0, value: totals.income, kind: 'income' },
      { name: 'Total keluar', base: net, value: totals.expense, kind: 'expense' },
      { name: 'Kas bersih', base: 0, value: net, kind: 'net' },
    ]
    return <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} />
        <YAxis width={58} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => compact.format(value)} />
        <Tooltip cursor={{ fill: 'var(--surface-muted)' }} content={<ChartTooltip />} />
        <Bar dataKey="base" name="Basis" stackId="waterfall" fill="transparent" barSize={40} />
        <Bar dataKey="value" name="Jumlah" stackId="waterfall" radius={[4, 4, 0, 0]} barSize={40}>
          {points.map((p) => <Cell key={p.name} fill={p.kind === 'income' ? 'var(--positive)' : p.kind === 'expense' ? 'var(--negative)' : 'var(--chart-primary)'} />)}
        </Bar>
      </ComposedChart>
    </ResponsiveContainer>
  }

  return <ChartFallback />
}
