import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const cashTrend = [
  { day: '1 Okt', value: 612 }, { day: '4 Okt', value: 655 }, { day: '7 Okt', value: 634 },
  { day: '10 Okt', value: 702 }, { day: '13 Okt', value: 748 }, { day: '16 Okt', value: 791 },
  { day: '19 Okt', value: 832 }, { day: '21 Okt', value: 869 },
]

const projectBars = [
  { name: 'Surabaya Office', value: 146.2 }, { name: 'Grand Galaxy', value: 81.4 },
  { name: 'Mawar Residence', value: 52.7 }, { name: 'Ruko Nirwana', value: 25.1 },
]

export default function FinancialChart({ kind }: { kind: 'cash' | 'projects' }) {
  if (kind === 'cash') {
    return <ResponsiveContainer width="100%" height="100%"><AreaChart data={cashTrend} margin={{ top: 18, right: 18, bottom: 0, left: 0 }}><defs><linearGradient id="cashGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--chart-primary)" stopOpacity={0.32} /><stop offset="100%" stopColor="var(--chart-primary)" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="var(--border-subtle)" vertical={false} /><XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} /><YAxis width={48} axisLine={false} tickLine={false} domain={[580, 900]} ticks={[600, 700, 800, 900]} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => `${value} jt`} /><Tooltip contentStyle={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', borderRadius: 10 }} formatter={(value) => [`Rp ${value} jt`, 'Saldo']} /><Area type="monotone" dataKey="value" stroke="var(--chart-primary)" strokeWidth={2.5} fill="url(#cashGradient)" /></AreaChart></ResponsiveContainer>
  }
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={projectBars} layout="vertical" margin={{ top: 8, right: 52, bottom: 18, left: 0 }}><XAxis type="number" domain={[0, 160]} ticks={[0, 40, 80, 120, 160]} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} tickFormatter={(value) => `${value} jt`} /><YAxis type="category" dataKey="name" width={112} axisLine={false} tickLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} /><Tooltip cursor={{ fill: 'var(--surface-muted)' }} contentStyle={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', borderRadius: 10 }} formatter={(value) => [`Rp ${value} jt`, 'Arus kas bersih']} /><Bar dataKey="value" radius={[0, 5, 5, 0]} barSize={18}>{projectBars.map((_, index) => <Cell key={index} fill={index === 0 ? 'var(--chart-primary)' : 'var(--chart-secondary)'} />)}<LabelList dataKey="value" position="right" formatter={(value) => `${Number(value ?? 0).toLocaleString('id-ID')} jt`} fill="var(--text-secondary)" fontSize={10} /></Bar></BarChart></ResponsiveContainer>
}
