import { ExternalLink, Plus, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'

import type { ProjectDocumentSession } from './projectDocumentApi'
import { createProjectQuotationApi, type ProjectQuotationApi } from './projectQuotationApi'
import type { ProjectDocumentRecord, ProjectQuotation, ProjectRecord } from './projectDocuments'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const labels = { draft: 'Draf', sent: 'Terkirim', revised: 'Direvisi', accepted: 'Disetujui', rejected: 'Ditolak' }

export default function ProjectQuotationPanel({ project, salesOrder, session, api: suppliedApi, onApplied }: {
  project: ProjectRecord
  salesOrder?: ProjectDocumentRecord
  session: ProjectDocumentSession
  api?: ProjectQuotationApi
  onApplied: (documentId: string) => void | Promise<void>
}) {
  const api = useMemo(() => suppliedApi ?? createProjectQuotationApi(), [suppliedApi])
  const [items, setItems] = useState<ProjectQuotation[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [creating, setCreating] = useState(false)
  const [url, setUrl] = useState('')
  const [amount, setAmount] = useState('')
  const [channel, setChannel] = useState<ProjectQuotation['channel']>('whatsapp')
  const [notes, setNotes] = useState('')

  const load = useCallback(async () => {
    setError('')
    try { setItems(await api.list(project.id)) }
    catch { setItems([]); setError('Riwayat quotation belum dapat dimuat.') }
  }, [api, project.id])
  useEffect(() => { void load() }, [load])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const numeric = Number(amount.replace(/[^0-9]/g, ''))
    if (!Number.isSafeInteger(numeric) || numeric <= 0) { setError('Nilai quotation wajib berupa rupiah positif.'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      await api.create(project.id, { canva_url: url.trim(), amount: numeric, channel, negotiation_notes: notes.trim() }, session)
      setCreating(false); setUrl(''); setAmount(''); setNotes('')
      await load(); setNotice('Quotation Canva disimpan sebagai versi baru.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Quotation gagal disimpan.') }
    finally { setBusy(false) }
  }

  const transition = async (item: ProjectQuotation, status: 'sent' | 'accepted' | 'rejected' | 'revised') => {
    const needsNote = status === 'rejected' || status === 'revised'
    const note = needsNote ? window.prompt(status === 'rejected' ? 'Alasan penolakan:' : 'Catatan revisi:') : ''
    if (note === null || (needsNote && !note.trim())) return
    if (!window.confirm(status === 'sent' ? 'Tandai quotation sudah dikirim?' : status === 'accepted' ? 'Tandai quotation disetujui klien?' : 'Simpan keputusan ini?')) return
    setBusy(true); setError(''); setNotice('')
    try { await api.transition(item, status, note, session); await load(); setNotice('Status quotation dikonfirmasi dari server.') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Status quotation gagal diubah.') }
    finally { setBusy(false) }
  }

  const apply = async (item: ProjectQuotation) => {
    if (!salesOrder || salesOrder.status !== 'draft') { setError('Draft Sales Order diperlukan untuk menerima nilai quotation.'); return }
    if (!window.confirm(`Terapkan ${IDR.format(item.amount)} ke draft Sales Order?`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      const id = await api.apply(item, salesOrder.lock_version, session)
      await onApplied(id)
      setNotice('Nilai quotation diterapkan ke draft Sales Order. Periksa lalu terbitkan.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Quotation gagal diterapkan.') }
    finally { setBusy(false) }
  }

  return <section className="quotation-panel" aria-label="Quotation Canva">
    <header><div><p className="eyebrow">QUOTATION CANVA</p><h3>Handoff penawaran dan negosiasi</h3><p>Desain tetap di Canva. Dashboard menyimpan versi, keputusan, dan nilai final.</p></div><div><button type="button" className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} /> Muat ulang</button>{session.capabilities.documentWrites && <button type="button" className="secondary-button" onClick={() => setCreating((value) => !value)} disabled={busy}><Plus size={15} /> Versi baru</button>}</div></header>
    {error && <p role="alert" className="document-state-alert">{error}</p>}
    {notice && <p role="status" className="document-state-notice">{notice}</p>}
    {creating && <form className="quotation-form" onSubmit={submit}>
      <label>Link desain Canva<input type="url" placeholder="https://www.canva.com/design/..." value={url} onChange={(event) => setUrl(event.target.value)} required /></label>
      <label>Nilai penawaran<input inputMode="numeric" placeholder="10000000" value={amount} onChange={(event) => setAmount(event.target.value)} required /></label>
      <label>Saluran negosiasi<select value={channel} onChange={(event) => setChannel(event.target.value as ProjectQuotation['channel'])}><option value="whatsapp">WhatsApp</option><option value="phone">Telepon</option><option value="email">Email</option><option value="meeting">Pertemuan</option><option value="other">Lainnya</option></select></label>
      <label>Catatan negosiasi<textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setCreating(false)}>Batal</button><button type="submit" className="primary-button" disabled={busy}>Simpan versi</button></div>
    </form>}
    {!items.length ? <p>Belum ada handoff quotation.</p> : <div className="quotation-list">{items.map((item) => <article key={item.id}>
      <div><span className={`document-status ${item.status}`}>{labels[item.status]}</span><strong>Versi {item.version} · {IDR.format(item.amount)}</strong><small>{item.channel}{item.negotiation_notes ? ` · ${item.negotiation_notes}` : ''}</small></div>
      <div className="quotation-actions"><a className="secondary-button" href={item.canva_url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Canva</a>{item.status === 'draft' && <button type="button" className="secondary-button" onClick={() => void transition(item, 'sent')} disabled={busy}>Sudah dikirim</button>}{item.status === 'sent' && <><button type="button" className="secondary-button" onClick={() => void transition(item, 'accepted')} disabled={busy}>Disetujui</button><button type="button" className="secondary-button" onClick={() => void transition(item, 'revised')} disabled={busy}>Revisi</button><button type="button" className="danger-button" onClick={() => void transition(item, 'rejected')} disabled={busy}>Ditolak</button></>}{item.status === 'accepted' && <button type="button" className="primary-button" onClick={() => void apply(item)} disabled={busy || salesOrder?.status !== 'draft'}>Terapkan ke Sales Order</button>}</div>
    </article>)}</div>}
  </section>
}
