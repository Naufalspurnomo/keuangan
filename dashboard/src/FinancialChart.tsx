import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CashTrendPoint, ProjectSummary } from './snapshot'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
const compact = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 1 })

function monthLabel(value: unknown) {
  const [year, month] = String(value ?? '').split('-').map(Number)
  return month >= 1 && month <= 12 ? `${MONTHS[month - 1]} ${String(year).slice(2)}` : String(value ?? '')
}

export default function FinancialChart({ kind, cashTrend = [], projects = [] }: { kind: 'cash' | 'projects'; cashTrend?: CashTrendPoint[]; projects?: ProjectSummary[] }) {
  if (kind === 'cash') {
    return <ResponsiveContainer width="100%" height="100%"><AreaChart data={cashTrend} margin={{ top: 18, right: 18, bottom: 0, left: 0 }}><defs><linearGradient id="cashGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--chart-primary)" stopOpacity={0.32} /><stop offset="100%" stopColor="var(--chart-primary)" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="var(--border-subtle)" vertical={false} /><XAxis dataKey="month" tickFormatter={monthLabel} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} /><YAxis width={58} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => compact.format(value)} /><Tooltip contentStyle={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', borderRadius: 10 }} labelFormatter={monthLabel} formatter={(value) => [`Rp ${compact.format(Number(value ?? 0))}`, 'Saldo']} /><Area type="monotone" dataKey="balance" stroke="var(--chart-primary)" strokeWidth={2.5} fill="url(#cashGradient)" /></AreaChart></ResponsiveContainer>
  }
  const rows = projects.slice(0, 4)
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={rows} layout="vertical" margin={{ top: 8, right: 62, bottom: 18, left: 0 }}><XAxis type="number" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => compact.format(value)} /><YAxis type="category" dataKey="name" width={112} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} /><Tooltip cursor={{ fill: 'var(--surface-muted)' }} contentStyle={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', borderRadius: 10 }} formatter={(value) => [`Rp ${compact.format(Number(value ?? 0))}`, 'Arus kas bersih']} /><Bar dataKey="net_cashflow" radius={[0, 5, 5, 0]} barSize={18}>{rows.map((row, index) => <Cell key={row.name} fill={row.net_cashflow < 0 ? 'var(--danger)' : index === 0 ? 'var(--chart-primary)' : 'var(--chart-secondary)'} />)}<LabelList dataKey="net_cashflow" position="right" formatter={(value) => compact.format(Number(value ?? 0))} fill="var(--text-secondary)" fontSize={10} /></Bar></BarChart></ResponsiveContainer>
}
