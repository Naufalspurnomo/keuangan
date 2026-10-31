import { ArrowLeft, Clock3, LocateFixed, Plus, Search, UserRoundCheck } from 'lucide-react'
import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'

import { TransactionRows } from './FinancePages'
import { projectTotals, type FinanceProject, type FinanceTransaction, type FinanceWorkspace } from './financeWorkspace'
import { IDR, projectStatusLabel } from './financeView'

type ProjectDetailTab = 'transactions' | 'presensi'

interface PresensiEvidence {
  id: string
  occurred_at: string
  accuracy_m: number
  distance_m: number
  radius_m: number
  photo_url: string
}

interface PresensiRecord {
  id: string
  employee_id: string
  employee_name: string
  project_id: string
  project_name: string
  check_in: PresensiEvidence
  check_out: PresensiEvidence | null
  status: 'active' | 'completed'
  duration_minutes: number | null
}

const DATE_TIME = new Intl.DateTimeFormat('id-ID', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta',
})

function durationLabel(minutes: number | null) {
  if (minutes === null) return 'Belum Check-out'
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (!hours) return `${rest} menit`
  if (!rest) return `${hours} jam`
  return `${hours} jam ${rest} menit`
}

function EvidenceCard({ label, employee, evidence }: { label: string; employee: string; evidence: PresensiEvidence | null }) {
  if (!evidence) return <article className="presensi-evidence is-empty"><div className="presensi-photo-placeholder"><Clock3 size={24} /></div><div><small>{label}</small><strong>Belum dilakukan</strong><span>Menunggu selfie dan lokasi baru.</span></div></article>
  return <article className="presensi-evidence">
    <img src={evidence.photo_url} alt={`Selfie ${label.toLocaleLowerCase('id-ID')} ${employee}`} loading="lazy" />
    <div>
      <small>{label}</small>
      <strong>{DATE_TIME.format(new Date(evidence.occurred_at))} WIB</strong>
      <span><LocateFixed size={13} /> {Math.round(evidence.distance_m)} m dari titik proyek</span>
      <span>Akurasi {Math.round(evidence.accuracy_m)} m</span>
    </div>
  </article>
}

function PresensiPanel({ project }: { project: FinanceProject }) {
  const [query, setQuery] = useState('')
  const [records, setRecords] = useState<PresensiRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    setRecords([])
    fetch(`/admin/api/presensi.php?project_id=${encodeURIComponent(project.id)}`, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Presensi unavailable (${response.status})`)
        return response.json() as Promise<{ version: string; records: PresensiRecord[] }>
      })
      .then((payload) => {
        if (payload.version !== 'presensi.admin.v1' || !Array.isArray(payload.records)) throw new Error('Invalid presensi response')
        setRecords(payload.records.filter((row) => row.project_id === project.id))
      })
      .catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === 'AbortError')) setError(true) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [project.id])

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('id-ID')
    return needle ? records.filter((record) => `${record.employee_name} ${record.status}`.toLocaleLowerCase('id-ID').includes(needle)) : records
  }, [query, records])
  const active = records.filter((record) => record.status === 'active').length
  const completed = records.length - active
  const radius = records[0]?.check_in.radius_m ?? 0

  if (error) return <div className="project-detail-empty presensi-error" role="alert"><strong>Data presensi belum dapat dimuat.</strong><span>Coba muat ulang halaman. Data lama tidak ditampilkan.</span></div>
  if (loading) return <div className="project-detail-empty"><strong>Memuat data presensi…</strong><span>Mengambil bukti terbaru dari server.</span></div>

  return <div className="project-presensi-panel">
    <section className="project-detail-summary presensi-summary" aria-label={`Ringkasan presensi ${project.name}`}>
      <article><small>Total presensi</small><strong>{records.length}</strong></article>
      <article><small>Sedang bekerja</small><strong className="positive">{active}</strong></article>
      <article><small>Selesai</small><strong>{completed}</strong></article>
      <article><small>Radius proyek</small><strong className="presensi-radius">{radius ? `≤ ${Math.round(radius)} m` : 'Belum ada data'}</strong></article>
    </section>
    <section className="workspace-filters project-detail-filter" aria-label="Cari presensi proyek">
      <label className="command-search"><Search size={17} /><input aria-label="Cari presensi" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari nama pegawai" /></label>
      <span><strong>{filtered.length}</strong> presensi</span>
    </section>
    {filtered.length ? <div className="presensi-record-list">{filtered.map((record) => <article className="presensi-record" key={record.id}>
      <header>
        <div className="presensi-avatar"><UserRoundCheck size={20} /></div>
        <div><strong>{record.employee_name}</strong><span>{record.project_name}</span></div>
        <span className={`presensi-status ${record.status}`}>{record.status === 'active' ? 'Sedang bekerja' : 'Selesai'}</span>
      </header>
      <div className="presensi-evidence-grid">
        <EvidenceCard label="Check-in" employee={record.employee_name} evidence={record.check_in} />
        <EvidenceCard label="Check-out" employee={record.employee_name} evidence={record.check_out} />
      </div>
      <footer><Clock3 size={15} /><span>Durasi kerja</span><strong>{durationLabel(record.duration_minutes)}</strong></footer>
    </article>)}</div> : <div className="project-detail-empty"><strong>Belum ada presensi untuk {project.name}</strong><span>Check-in pegawai dari /absen/presensi akan muncul di sini.</span></div>}
  </div>
}

export default function ProjectTransactionsWorkspace({ workspace, project, onBack, onAdd, onEdit, onDelete }: {
  workspace: FinanceWorkspace
  project: FinanceProject
  onBack: () => void
  onAdd: (project: FinanceProject) => void
  onEdit: (row: FinanceTransaction) => void
  onDelete: (row: FinanceTransaction) => void
}) {
  const [tab, setTab] = useState<ProjectDetailTab>('transactions')
  const [query, setQuery] = useState('')
  useEffect(() => { setTab('transactions'); setQuery('') }, [project.id])
  const projectRows = useMemo(() => workspace.transactions
    .filter((row) => row.project_id === project.id)
    .sort((left, right) => right.date.localeCompare(left.date) || right.created_at.localeCompare(left.created_at)),
  [project.id, workspace.transactions])
  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('id-ID')
    return needle ? projectRows.filter((row) => `${row.notes} ${row.wallet} ${row.company ?? ''}`.toLocaleLowerCase('id-ID').includes(needle)) : projectRows
  }, [projectRows, query])
  const totals = projectTotals(project, workspace.transactions)
  const handleTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const tabs = [...event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    const current = tabs.indexOf(event.currentTarget)
    const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (current - 1 + tabs.length) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
    if (next < 0) return
    event.preventDefault()
    tabs[next].focus()
    tabs[next].click()
  }

  return <section className="finance-page-stack project-transaction-detail">
    <header className="project-detail-head">
      <button type="button" className="secondary-button project-detail-back" onClick={onBack}><ArrowLeft size={17} /> Kembali ke Proyek</button>
      <div className="project-detail-identity"><p className="eyebrow">DETAIL PROYEK · DATA DEMO</p><h1>{project.name}</h1><p>{project.company} · {project.wallet} · <span className={`status-chip ${project.status}`}>{projectStatusLabel(project.status)}</span>{project.client ? ` · ${project.client}` : ''}</p></div>
      {tab === 'transactions' && <button type="button" className="primary-button" onClick={() => onAdd(project)}><Plus size={16} /> Tambah transaksi</button>}
    </header>
    <div className="project-detail-tabs" role="tablist" aria-label={`Data ${project.name}`}>
      <button id="project-transactions-tab" type="button" role="tab" aria-label="Transaksi" aria-selected={tab === 'transactions'} aria-controls="project-transactions-panel" tabIndex={tab === 'transactions' ? 0 : -1} onKeyDown={handleTabKey} onClick={() => setTab('transactions')}>Transaksi <span>{projectRows.length}</span></button>
      <button id="project-presensi-tab" type="button" role="tab" aria-label="Presensi" aria-selected={tab === 'presensi'} aria-controls="project-presensi-panel" tabIndex={tab === 'presensi' ? 0 : -1} onKeyDown={handleTabKey} onClick={() => setTab('presensi')}>Presensi</button>
    </div>
    {tab === 'presensi'
      ? <div id="project-presensi-panel" role="tabpanel" aria-labelledby="project-presensi-tab"><PresensiPanel project={project} /></div>
      : <div id="project-transactions-panel" role="tabpanel" aria-labelledby="project-transactions-tab">
        <section className="project-detail-summary" aria-label={`Ringkasan ${project.name}`}>
          <article><small>Pemasukan</small><strong className="positive">{IDR.format(totals.income)}</strong></article>
          <article><small>Pengeluaran</small><strong className="negative">{IDR.format(totals.expense)}</strong></article>
          <article><small>Arus bersih</small><strong className={totals.net >= 0 ? 'positive' : 'negative'}>{IDR.format(totals.net)}</strong></article>
          <article><small>Transaksi</small><strong>{totals.transactions}</strong></article>
        </section>
        <section className="workspace-filters project-detail-filter" aria-label="Cari transaksi proyek">
          <label className="command-search"><Search size={17} /><input aria-label="Cari transaksi" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Cari di ${project.name}`} /></label>
          <span><strong>{rows.length}</strong> transaksi</span>
        </section>
        {rows.length
          ? <TransactionRows rows={rows} projects={[project]} onEdit={onEdit} onDelete={onDelete} />
          : <div className="project-detail-empty"><strong>Belum ada transaksi untuk {project.name}</strong><span>Tambahkan transaksi pertama untuk memulai ledger proyek ini.</span></div>}
      </div>}
  </section>
}
