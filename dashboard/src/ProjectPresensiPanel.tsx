import { Clock3, LocateFixed, RefreshCw, Search, UserRoundCheck } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

type WhatsAppDeliveryStatus = 'sent' | 'pending' | 'failed' | 'unknown'

interface WhatsAppDelivery {
  status?: WhatsAppDeliveryStatus
  attempts?: number
}

interface PresensiEvidence {
  id: string
  occurred_at: string
  accuracy_m: number
  latitude: number | null
  longitude: number | null
  photo_url: string
  whatsapp_delivery?: WhatsAppDelivery
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

const WHATSAPP_DELIVERY_LABELS: Record<WhatsAppDeliveryStatus, string> = {
  sent: 'Terkirim',
  pending: 'Menunggu',
  failed: 'Gagal',
  unknown: 'Belum diketahui',
}

function WhatsAppDeliveryBadge({ label, delivery }: { label: string; delivery?: WhatsAppDelivery }) {
  const status = delivery?.status && delivery.status in WHATSAPP_DELIVERY_LABELS ? delivery.status : 'unknown'
  const attempts = typeof delivery?.attempts === 'number' && Number.isFinite(delivery.attempts) && delivery.attempts > 0
    ? Math.floor(delivery.attempts)
    : 0
  return <div className="presensi-whatsapp-delivery">
    <span className={`presensi-whatsapp-status ${status}`} aria-label={`Status WhatsApp ${label}: ${WHATSAPP_DELIVERY_LABELS[status]}`}><span aria-hidden="true">WA</span>{WHATSAPP_DELIVERY_LABELS[status]}</span>
    {attempts > 0 ? <span>{attempts} percobaan pengiriman</span> : null}
  </div>
}

function EvidenceCard({ label, employee, evidence }: { label: string; employee: string; evidence: PresensiEvidence | null }) {
  if (!evidence) return <article className="presensi-evidence is-empty"><div className="presensi-photo-placeholder"><Clock3 size={24} /></div><div><small>{label}</small><strong>Belum dilakukan</strong><span>Menunggu selfie dan lokasi baru.</span></div></article>
  const hasLocation = typeof evidence.latitude === 'number' && Number.isFinite(evidence.latitude)
    && typeof evidence.longitude === 'number' && Number.isFinite(evidence.longitude)
  const coordinate = hasLocation ? `${evidence.latitude},${evidence.longitude}` : ''
  const locationLabel = hasLocation ? `${evidence.latitude!.toFixed(6)}, ${evidence.longitude!.toFixed(6)}` : ''
  return <article className="presensi-evidence">
    <img src={evidence.photo_url} alt={`Selfie ${label.toLocaleLowerCase('id-ID')} ${employee}`} loading="lazy" />
    <div>
      <small>{label}</small>
      <strong>{DATE_TIME.format(new Date(evidence.occurred_at))} WIB</strong>
      {hasLocation ? <>
        <span>{locationLabel}</span>
        <span>Akurasi {Math.round(evidence.accuracy_m)} m</span>
        <a href={`https://www.google.com/maps?q=${encodeURIComponent(coordinate)}`} target="_blank" rel="noreferrer" aria-label={`Buka lokasi ${label} ${employee} di peta`}><LocateFixed size={13} /> Buka peta</a>
      </> : <span>Lokasi tidak tersedia pada data lama.</span>}
      <WhatsAppDeliveryBadge label={label} delivery={evidence.whatsapp_delivery} />
    </div>
  </article>
}

export default function ProjectPresensiPanel({ project }: { project: { id?: string; name: string } }) {
  const [query, setQuery] = useState('')
  const [records, setRecords] = useState<PresensiRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const activeController = useRef<AbortController | null>(null)

  const loadRecords = useCallback((clear = false) => {
    if (!project.id) { setLoading(false); return }
    activeController.current?.abort()
    const controller = new AbortController()
    activeController.current = controller
    setLoading(true)
    setError(false)
    if (clear) setRecords([])
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
  }, [project.id])

  useEffect(() => {
    loadRecords(true)
    const refreshOnFocus = () => loadRecords()
    window.addEventListener('focus', refreshOnFocus)
    return () => {
      window.removeEventListener('focus', refreshOnFocus)
      activeController.current?.abort()
    }
  }, [loadRecords])

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('id-ID')
    return needle ? records.filter((record) => `${record.employee_name} ${record.status}`.toLocaleLowerCase('id-ID').includes(needle)) : records
  }, [query, records])
  const active = records.filter((record) => record.status === 'active').length
  const completed = records.length - active

  if (!project.id) return <div className="project-detail-empty" role="status"><strong>Presensi belum tersedia</strong><span>Proyek ini belum terhubung ke presensi.</span></div>
  if (error) return <div className="project-detail-empty presensi-error" role="alert"><strong>Data presensi belum dapat dimuat.</strong><span>Data lama tidak ditampilkan.</span><button type="button" className="secondary-button" onClick={() => loadRecords(true)}>Coba lagi</button></div>
  if (loading && !records.length) return <div className="project-detail-empty" role="status" aria-live="polite"><strong>Memuat data presensi…</strong><span>Mengambil bukti terbaru dari server.</span></div>

  return <div className="project-presensi-panel" aria-busy={loading}>
    <div className="presensi-panel-actions">
      <span role="status" aria-live="polite">{loading ? 'Memperbarui data…' : 'Data presensi terbaru'}</span>
      <button type="button" className="secondary-button" onClick={() => loadRecords()} disabled={loading}><RefreshCw size={15} /> Perbarui presensi</button>
    </div>
    <section className="project-detail-summary presensi-summary" aria-label={`Ringkasan presensi ${project.name}`}>
      <article><small>Total presensi</small><strong>{records.length}</strong></article>
      <article><small>Sedang bekerja</small><strong className="positive">{active}</strong></article>
      <article><small>Selesai</small><strong>{completed}</strong></article>
      <article><small>Bukti lokasi</small><strong className="presensi-location-summary">GPS per selfie</strong></article>
    </section>
    <section className="workspace-filters project-detail-filter" aria-label="Cari presensi proyek">
      <label className="command-search"><Search size={17} /><input aria-label="Cari presensi" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari nama pegawai" /></label>
      <span><strong>{filtered.length}</strong> presensi</span>
    </section>
    {filtered.length ? <div className="presensi-record-list">{filtered.map((record) => <article className="presensi-record" key={record.id}>
      <header><div className="presensi-avatar"><UserRoundCheck size={20} /></div><div><strong>{record.employee_name}</strong><span>{record.project_name}</span></div><span className={`presensi-status ${record.status}`}>{record.status === 'active' ? 'Sedang bekerja' : 'Selesai'}</span></header>
      <div className="presensi-evidence-grid"><EvidenceCard label="Check-in" employee={record.employee_name} evidence={record.check_in} /><EvidenceCard label="Check-out" employee={record.employee_name} evidence={record.check_out} /></div>
      <footer><Clock3 size={15} /><span>Durasi kerja</span><strong>{durationLabel(record.duration_minutes)}</strong></footer>
    </article>)}</div> : records.length
      ? <div className="project-detail-empty"><strong>Tidak ada presensi yang cocok dengan pencarian.</strong><span>Coba kata kunci lain atau tampilkan kembali semua data.</span><button type="button" className="secondary-button" onClick={() => setQuery('')}>Hapus pencarian</button></div>
      : <div className="project-detail-empty"><strong>Belum ada presensi untuk {project.name}</strong><span>Check-in pegawai akan muncul di sini.</span><a className="secondary-button" href="/absen/presensi/" target="_blank" rel="noreferrer">Buka halaman presensi pegawai</a></div>}
  </div>
}

export { ProjectPresensiPanel, type PresensiRecord }
