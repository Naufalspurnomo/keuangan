import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react'

import { useModalDialog } from './CanonicalDebtForms'
import { ProjectDocumentApiError, type ProjectDocumentSession } from './projectDocumentApi'
import { createProjectQuotationApi, type ProjectQuotationApi } from './projectQuotationApi'
import {
  calculateDocumentTotals,
  type ProjectDocumentDraft,
  type ProjectDocumentRecord,
  type ProjectQuotation,
  type ProjectQuotationDealResult,
  type ProjectQuotationLine,
  type ProjectQuotationValues,
  type ProjectRecord,
  type QuotationInstallment,
} from './projectDocuments'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const compactIDR = (value: number) => IDR.format(value).replace(/\s/g, '')
const labels = { draft: 'Draf', sent: 'Terkirim', revised: 'Direvisi', accepted: 'Deal', rejected: 'Ditolak' }
const MAX_IMAGE_DATA_URL = 196_608
const MAX_IMAGE_BYTES = 144 * 1024
const MAX_IMAGE_DIMENSION = 1600
const MAX_INSTALLMENTS = 24

type EditorMode = 'create' | 'edit' | 'revise'

interface EditorState {
  mode: EditorMode
  source: ProjectQuotation | null
  values: ProjectQuotationValues
}

function newLine(index = 0): ProjectQuotationLine {
  return { id: `line-${Date.now()}-${index}`, description: '', quantity: '1', unit: 'unit', unit_price: 0, discount_percent: '0' }
}

function dateAfter(days: number) {
  const value = new Date()
  value.setHours(12, 0, 0, 0)
  value.setDate(value.getDate() + days)
  return value.toISOString().slice(0, 10)
}

function projectValues(project: ProjectRecord): ProjectQuotationValues {
  return {
    recipient_name: project.client_name,
    recipient_company: project.client_company,
    recipient_address: project.client_address,
    recipient_contact: project.client_contact,
    project_name: project.name,
    subject: `Penawaran ${project.name}`,
    valid_until: dateAfter(30),
    project_image_url: null,
    lines: [newLine()],
    discount_mode: 'none',
    discount_value: '0',
    tax_percent: '0',
    payment_terms: '',
    content_notes: '',
    amount: 0,
  }
}

function valuesFromItem(project: ProjectRecord, item: ProjectQuotation): ProjectQuotationValues {
  const fallback = projectValues(project)
  return {
    recipient_name: item.recipient_name ?? fallback.recipient_name,
    recipient_company: item.recipient_company ?? fallback.recipient_company,
    recipient_address: item.recipient_address ?? fallback.recipient_address,
    recipient_contact: item.recipient_contact ?? fallback.recipient_contact,
    project_name: item.project_name ?? fallback.project_name,
    subject: item.subject ?? fallback.subject,
    valid_until: item.valid_until ?? fallback.valid_until,
    project_image_url: item.project_image_url ?? null,
    lines: item.lines?.length ? item.lines.map((line) => ({ ...line })) : fallback.lines,
    discount_mode: item.discount_mode ?? 'none',
    discount_value: item.discount_value ?? '0',
    tax_percent: item.tax_percent ?? '0',
    payment_terms: item.payment_terms ?? '',
    content_notes: item.content_notes ?? '',
    amount: item.amount,
  }
}

function brandFor(project: ProjectRecord) {
  const source = `${project.issuer_key} ${project.company}`.toLowerCase()
  if (source.includes('hojja')) return 'HOJJA'
  if (source.includes('texturin')) return 'TEXTURIN'
  return 'HOLLAWALL'
}

function quotationDraft(project: ProjectRecord, values: ProjectQuotationValues): ProjectDocumentDraft {
  return {
    id: null,
    project_id: project.id,
    type: 'sales_order',
    invoice_kind: null,
    applies_to_invoice_id: null,
    issue_date: new Date().toISOString().slice(0, 10),
    due_date: null,
    valid_until: values.valid_until,
    notes: values.content_notes,
    payment_terms: values.payment_terms,
    prepared_by: '',
    client_signatory: values.recipient_name,
    project_image_url: values.project_image_url,
    lines: values.lines,
    discount_mode: values.discount_mode,
    discount_value: values.discount_value,
    tax_percent: values.tax_percent,
    allocations: [],
  }
}

function calculatedValues(project: ProjectRecord, values: ProjectQuotationValues) {
  const totals = calculateDocumentTotals(quotationDraft(project, values))
  return { totals, values: { ...values, amount: totals.total } }
}

export function calculateInstallmentSchedule(total: number, dpPercent: number, remainingInstallments: number): QuotationInstallment[] {
  if (!Number.isSafeInteger(total) || total <= 0) throw new Error('Total quotation harus berupa rupiah bulat positif.')
  if (!Number.isFinite(dpPercent) || dpPercent <= 0 || dpPercent >= 100) throw new Error('DP harus lebih dari 0% dan kurang dari 100%.')
  if (!Number.isInteger(remainingInstallments) || remainingInstallments < 1 || remainingInstallments > MAX_INSTALLMENTS) {
    throw new Error(`Jumlah pelunasan minimal 1 dan maksimal ${MAX_INSTALLMENTS}.`)
  }
  const dp = Math.round(total * dpPercent / 100)
  const remaining = total - dp
  const base = Math.floor(remaining / remainingInstallments)
  const remainder = remaining - base * remainingInstallments
  return [
    { sequence: 1, kind: 'DP', label: `DP ${dpPercent}%`, amount: dp, percent: dpPercent },
    ...Array.from({ length: remainingInstallments }, (_, index) => ({
      sequence: index + 2,
      kind: 'INSTALLMENT' as const,
      label: `Pelunasan ${index + 1}`,
      amount: base + (index < remainder ? 1 : 0),
    })),
  ]
}

function messageFrom(error: unknown) {
  if (error instanceof ProjectDocumentApiError) {
    if (error.stale) return 'Versi quotation sudah berubah. Muat ulang riwayat sebelum mencoba lagi.'
    if (error.uncertain) return 'Hasil perubahan belum dapat dipastikan. Muat ulang riwayat sebelum mengulang.'
  }
  return error instanceof Error ? error.message : 'Operasi quotation gagal.'
}

function QuotationEditor({ project, state, busy, onCancel, onSave }: {
  project: ProjectRecord
  state: EditorState
  busy: boolean
  onCancel: () => void
  onSave: (values: ProjectQuotationValues) => Promise<void>
}) {
  const [values, setValues] = useState(state.values)
  const [error, setError] = useState('')
  const calculation = useMemo(() => {
    try { return { value: calculatedValues(project, values), error: '' } }
    catch (reason) { return { value: null, error: messageFrom(reason) } }
  }, [project, values])

  const field = <K extends keyof ProjectQuotationValues>(name: K, value: ProjectQuotationValues[K]) => {
    setValues((current) => ({ ...current, [name]: value }))
  }
  const lineField = <K extends keyof ProjectQuotationLine>(index: number, name: K, value: ProjectQuotationLine[K]) => {
    setValues((current) => ({
      ...current,
      lines: current.lines.map((line, lineIndex) => lineIndex === index ? { ...line, [name]: value } : line),
    }))
  }
  const uploadImage = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (!['image/png', 'image/jpeg'].includes(file.type)) {
      setError('Gambar proyek harus PNG atau JPEG.')
      event.target.value = ''
      return
    }
    const reader = new FileReader()
    reader.onerror = () => setError('Gambar proyek gagal dibaca.')
    reader.onload = () => {
      const source = String(reader.result || '')
      const image = new Image()
      image.onerror = () => setError('Gambar proyek gagal diproses.')
      image.onload = () => {
        const scale = Math.min(1, MAX_IMAGE_DIMENSION / Math.max(image.naturalWidth, image.naturalHeight))
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
        canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
        const context = canvas.getContext('2d')
        if (!context) { setError('Gambar proyek gagal diproses.'); return }
        context.drawImage(image, 0, 0, canvas.width, canvas.height)
        let data = canvas.toDataURL('image/jpeg', 0.86)
        if (data.length > MAX_IMAGE_DATA_URL) data = canvas.toDataURL('image/jpeg', 0.68)
        const approximateBytes = Math.ceil((data.split(',')[1]?.length ?? 0) * 0.75)
        if (
          data.length > MAX_IMAGE_DATA_URL
          || approximateBytes > MAX_IMAGE_BYTES
          || !/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(data)
        ) {
          setError('Gambar masih terlalu besar setelah dikompresi. Gunakan gambar yang lebih sederhana.')
          return
        }
        setError('')
        field('project_image_url', data)
      }
      image.src = source
    }
    reader.readAsDataURL(file)
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    try {
      if (!values.recipient_name.trim()) throw new Error('Nama penerima wajib diisi.')
      if (!values.project_name.trim()) throw new Error('Nama proyek wajib diisi.')
      if (!values.subject.trim()) throw new Error('Subjek penawaran wajib diisi.')
      if (!values.valid_until) throw new Error('Masa berlaku wajib diisi.')
      if (!values.lines.length) throw new Error('Tambahkan minimal satu item.')
      for (const line of values.lines) {
        if (!line.description.trim() || !line.unit.trim()) throw new Error('Deskripsi dan satuan setiap item wajib diisi.')
      }
      if (!calculation.value) throw new Error(calculation.error)
      if (calculation.value.values.amount <= 0) throw new Error('Total quotation harus lebih dari Rp0.')
      await onSave(calculation.value.values)
    } catch (reason) { setError(messageFrom(reason)) }
  }

  return <form className="quotation-editor" onSubmit={submit} aria-label={state.mode === 'create' ? 'Quotation baru' : 'Editor quotation'}>
    <header>
      <div><span className="eyebrow">Editor terstruktur</span><h4>{state.mode === 'revise' ? `Revisi dari versi ${state.source?.version}` : state.mode === 'edit' ? `Edit versi ${state.source?.version}` : 'Quotation baru'}</h4></div>
      <label className="quotation-brand-field">Template merek<input value={brandFor(project)} readOnly aria-readonly="true" /></label>
    </header>
    <fieldset disabled={busy}>
      <legend>Data penerima dan proyek</legend>
      <div className="quotation-field-grid">
        <label>Nama penerima<input value={values.recipient_name} onChange={(event) => field('recipient_name', event.target.value)} required /></label>
        <label>Perusahaan penerima<input value={values.recipient_company} onChange={(event) => field('recipient_company', event.target.value)} /></label>
        <label className="wide">Alamat penerima<textarea value={values.recipient_address} onChange={(event) => field('recipient_address', event.target.value)} /></label>
        <label>Kontak penerima<input value={values.recipient_contact} onChange={(event) => field('recipient_contact', event.target.value)} /></label>
        <label>Nama proyek<input value={values.project_name} onChange={(event) => field('project_name', event.target.value)} required /></label>
        <label className="wide">Subjek<input value={values.subject} onChange={(event) => field('subject', event.target.value)} required /></label>
        <label>Berlaku sampai<input type="date" value={values.valid_until ?? ''} onChange={(event) => field('valid_until', event.target.value || null)} required /></label>
        <label>Gambar proyek (PNG/JPEG)<input aria-label="Gambar proyek" type="file" accept="image/png,image/jpeg" onChange={uploadImage} /></label>
      </div>
      {values.project_image_url && <div className="quotation-image-preview"><img src={values.project_image_url} alt="Pratinjau gambar proyek" /><button type="button" onClick={() => field('project_image_url', null)}>Hapus gambar</button></div>}
    </fieldset>

    <fieldset disabled={busy}>
      <legend>Rincian item</legend>
      <div className="quotation-lines">
        {values.lines.map((line, index) => <article key={line.id} className="quotation-line">
          <strong>Item {index + 1}</strong>
          <label className="description">Deskripsi item {index + 1}<input value={line.description} onChange={(event) => lineField(index, 'description', event.target.value)} required /></label>
          <label>Kuantitas item {index + 1}<input type="number" min="0.000001" step="any" value={line.quantity} onChange={(event) => lineField(index, 'quantity', event.target.value)} required /></label>
          <label>Satuan item {index + 1}<input value={line.unit} onChange={(event) => lineField(index, 'unit', event.target.value)} required /></label>
          <label>Harga satuan item {index + 1}<input type="number" min="0" step="1" value={line.unit_price} onChange={(event) => lineField(index, 'unit_price', Number(event.target.value))} required /></label>
          <label>Diskon item {index + 1} (%)<input type="number" min="0" max="100" step="0.01" value={line.discount_percent} onChange={(event) => lineField(index, 'discount_percent', event.target.value)} /></label>
          {values.lines.length > 1 && <button type="button" className="danger-secondary" onClick={() => setValues((current) => ({ ...current, lines: current.lines.filter((_, lineIndex) => lineIndex !== index) }))}>Hapus item {index + 1}</button>}
        </article>)}
      </div>
      <button type="button" className="secondary" onClick={() => setValues((current) => ({ ...current, lines: [...current.lines, newLine(current.lines.length)] }))}>Tambah item</button>
    </fieldset>

    <fieldset disabled={busy}>
      <legend>Ringkasan dan ketentuan</legend>
      <div className="quotation-field-grid">
        <label>Jenis diskon dokumen<select value={values.discount_mode} onChange={(event) => field('discount_mode', event.target.value as ProjectQuotationValues['discount_mode'])}><option value="none">Tanpa diskon</option><option value="percent">Persen</option><option value="fixed">Rupiah</option></select></label>
        <label>Nilai diskon dokumen<input type="number" min="0" step={values.discount_mode === 'fixed' ? '1' : '0.01'} value={values.discount_value} disabled={values.discount_mode === 'none'} onChange={(event) => field('discount_value', event.target.value)} /></label>
        <label>Pajak (%)<input type="number" min="0" max="100" step="0.01" value={values.tax_percent} onChange={(event) => field('tax_percent', event.target.value)} /></label>
        <label className="wide">Ketentuan pembayaran<textarea value={values.payment_terms} onChange={(event) => field('payment_terms', event.target.value)} /></label>
        <label className="wide">Catatan quotation<textarea value={values.content_notes} onChange={(event) => field('content_notes', event.target.value)} /></label>
      </div>
      <dl className="quotation-totals" aria-label="Total quotation">
        <div><dt>Subtotal</dt><dd>{calculation.value ? IDR.format(calculation.value.totals.subtotal) : '—'}</dd></div>
        <div><dt>Diskon dokumen</dt><dd>{calculation.value ? IDR.format(calculation.value.totals.document_discount) : '—'}</dd></div>
        <div><dt>Pajak</dt><dd>{calculation.value ? IDR.format(calculation.value.totals.tax) : '—'}</dd></div>
        <div className="grand-total"><dt>Total</dt><dd>{calculation.value ? IDR.format(calculation.value.totals.total) : '—'}</dd></div>
      </dl>
    </fieldset>
    {(error || calculation.error) && <p className="document-state-alert" role="alert">{error || calculation.error}</p>}
    <footer className="quotation-actions">
      <button type="button" className="secondary" onClick={onCancel}>Batal</button>
      <button type="submit" disabled={busy}>{busy ? 'Menyimpan…' : state.mode === 'revise' ? 'Simpan sebagai revisi' : 'Simpan draf'}</button>
    </footer>
  </form>
}

function DealDialog({ item, busy, onCancel, onConfirm }: {
  item: ProjectQuotation
  busy: boolean
  onCancel: () => void
  onConfirm: (dpPercent: number, installments: number) => Promise<void>
}) {
  const dialog = useModalDialog(onCancel)
  const total = item.accepted_snapshot?.amount ?? item.amount
  const [dpChoice, setDpChoice] = useState('30')
  const [customDp, setCustomDp] = useState('35')
  const [countChoice, setCountChoice] = useState('1')
  const [customCount, setCustomCount] = useState('4')
  const [error, setError] = useState('')
  const dp = Number(dpChoice === 'custom' ? customDp : dpChoice)
  const installments = Number(countChoice === 'custom' ? customCount : countChoice)
  let schedule: QuotationInstallment[] = []
  let scheduleError = ''
  try { schedule = calculateInstallmentSchedule(total, dp, installments) }
  catch (reason) { scheduleError = messageFrom(reason) }
  const allocated = schedule.reduce((sum, entry) => sum + entry.amount, 0)
  const installmentEntries = schedule.slice(1)
  const minimumInstallment = installmentEntries.length ? Math.min(...installmentEntries.map((entry) => entry.amount)) : 0
  const conceptualRemainderRecipients = installmentEntries.filter((entry) => entry.amount > minimumInstallment).length

  return <div className="modal-backdrop" role="presentation">
    <section ref={dialog.dialogRef} onKeyDown={dialog.onKeyDown} className="modal-card quotation-deal-dialog" role="dialog" aria-modal="true" aria-labelledby="deal-dialog-title" tabIndex={-1}>
      <header><div><span className="eyebrow">Kunci versi {item.version}</span><h2 id="deal-dialog-title">Setup DP dan cicilan</h2><p>Nilai deal {IDR.format(total)}. Konfirmasi membuat Sales Order, draf invoice DP, dan jadwal tagihan.</p></div></header>
      <div className="modal-body">
        <fieldset className="quotation-choice-group"><legend>Persentase DP</legend>{['30', '40', '50'].map((value) => <label key={value}><input type="radio" name="dp-choice" value={value} aria-label={`DP ${value}%`} checked={dpChoice === value} onChange={() => setDpChoice(value)} />{value}%</label>)}<label><input type="radio" name="dp-choice" value="custom" checked={dpChoice === 'custom'} onChange={() => setDpChoice('custom')} />DP kustom</label></fieldset>
        {dpChoice === 'custom' && <label>Persentase DP kustom<input type="number" min="0.01" max="99.99" step="0.01" value={customDp} onChange={(event) => setCustomDp(event.target.value)} /></label>}
        <fieldset className="quotation-choice-group"><legend>Jumlah pelunasan</legend>{['1', '2', '3'].map((value) => <label key={value}><input type="radio" name="count-choice" value={value} checked={countChoice === value} onChange={() => setCountChoice(value)} />{value} kali pelunasan</label>)}<label><input type="radio" name="count-choice" value="custom" checked={countChoice === 'custom'} onChange={() => setCountChoice('custom')} />Jumlah pelunasan kustom</label></fieldset>
        {countChoice === 'custom' && <label>Jumlah pelunasan kustom<input type="number" min="1" max={MAX_INSTALLMENTS} step="1" value={customCount} onChange={(event) => setCustomCount(event.target.value)} /></label>}
        {schedule.length > 0 && <div className="installment-preview">
          <h3>Alokasi tepat</h3>
          <ol>{schedule.map((entry) => <li key={entry.sequence}><span>{entry.label}</span><strong>{compactIDR(entry.amount)}</strong></li>)}</ol>
          <p>{conceptualRemainderRecipients > 0 ? `Selisih pembulatan dibagi deterministik; ${conceptualRemainderRecipients} pembayaran pertama menerima tambahan Rp1.` : 'Tidak ada selisih pembagian cicilan pada alokasi ini.'}</p>
          <p>Total alokasi <strong>{compactIDR(allocated)}</strong>.</p>
        </div>}
        <p className="document-state-notice">Dokumen yang dibuat masih mengikuti alur invoice dan pembayaran yang ada.</p>
        {(error || scheduleError) && <p className="document-state-alert" role="alert">{error || scheduleError}</p>}
      </div>
      <footer className="modal-actions"><button type="button" className="secondary" onClick={onCancel} disabled={busy}>Batal</button><button type="button" disabled={busy || Boolean(scheduleError)} onClick={async () => { setError(''); try { await onConfirm(dp, installments) } catch (reason) { setError(messageFrom(reason)) } }}>{busy ? 'Mengonfirmasi…' : 'Konfirmasi Deal & Buat Draf DP'}</button></footer>
    </section>
  </div>
}

export default function ProjectQuotationPanel({ project, salesOrder, session, api: suppliedApi, onApplied }: {
  project: ProjectRecord
  salesOrder?: ProjectDocumentRecord
  session: ProjectDocumentSession
  api?: ProjectQuotationApi
  onApplied: (documentId: string) => void | Promise<void>
}) {
  const api = useMemo(() => suppliedApi ?? createProjectQuotationApi(), [suppliedApi])
  const [items, setItems] = useState<ProjectQuotation[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [dealItem, setDealItem] = useState<ProjectQuotation | null>(null)
  const [rejectItem, setRejectItem] = useState<ProjectQuotation | null>(null)
  const [rejectNote, setRejectNote] = useState('')
  const closeReject = () => { setRejectItem(null); setRejectNote('') }
  const rejectDialog = useModalDialog(closeReject, Boolean(rejectItem))

  const load = async () => {
    setLoading(true); setError('')
    try { setItems((await api.list(project.id)).sort((left, right) => right.version - left.version)) }
    catch (reason) { setError(messageFrom(reason)) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [api, project.id])

  const save = async (values: ProjectQuotationValues) => {
    if (!editor) return
    setBusy(true); setError(''); setNotice('')
    try {
      const saved = editor.mode === 'create'
        ? await api.create(project.id, values, session)
        : editor.mode === 'revise'
          ? await api.revise(editor.source!, values, session)
          : await api.saveDraft(editor.source!, values, session)
      setItems((current) => [saved, ...current.filter((item) => item.id !== saved.id)].sort((left, right) => right.version - left.version))
      setEditor(null)
      setNotice(editor.mode === 'revise' ? `Versi ${saved.version} dibuat. Versi sebelumnya tetap tersimpan.` : `Draf versi ${saved.version} tersimpan.`)
    } catch (reason) { const message = messageFrom(reason); setError(message); throw reason instanceof Error ? reason : new Error(message) }
    finally { setBusy(false) }
  }
  const transition = async (item: ProjectQuotation, status: 'sent' | 'rejected', note = '') => {
    setBusy(true); setError(''); setNotice('')
    try {
      const saved = await api.transition(item, status, note, session)
      setItems((current) => current.map((entry) => entry.id === saved.id ? saved : entry))
      if (status === 'rejected') { setRejectItem(null); setRejectNote('') }
    } catch (reason) { setError(messageFrom(reason)) }
    finally { setBusy(false) }
  }
  const deal = async (dpPercent: number, remainingInstallments: number) => {
    if (!dealItem) return
    if (!salesOrder || salesOrder.status !== 'draft') {
      setError('Sales Order draf proyek tidak tersedia. Muat ulang proyek sebelum menandai Deal.')
      return
    }
    setBusy(true); setError(''); setNotice('')
    try {
      const result: ProjectQuotationDealResult = await api.deal(dealItem, {
        sales_order_id: salesOrder.id,
        sales_order_version: salesOrder.lock_version,
        dp_percent: dpPercent,
        remaining_installments: remainingInstallments,
      }, session)
      setItems((current) => current.map((entry) => entry.id === result.quotation.id ? result.quotation : entry))
      setDealItem(null)
      setNotice('Deal dikonfirmasi. Sales Order dan draf invoice DP dibuat; jadwal tagihan tersimpan.')
      await onApplied(result.sales_order_id)
    } catch (reason) { setError(messageFrom(reason)); throw reason }
    finally { setBusy(false) }
  }
  const download = async (item: ProjectQuotation) => {
    setBusy(true); setError('')
    try {
      const blob = await api.download(item)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `quotation-v${item.version}.pdf`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (reason) { setError(messageFrom(reason)) }
    finally { setBusy(false) }
  }

  return <section className="quotation-panel" aria-labelledby="quotation-title">
    <header><div><span className="eyebrow">Komersial</span><h3 id="quotation-title">Quotation proyek</h3><p>Susun penawaran, simpan riwayat versi, lalu kunci versi yang disepakati.</p></div><div><span className="status-pill">Template {brandFor(project)}</span><button type="button" onClick={() => setEditor({ mode: 'create', source: null, values: projectValues(project) })} disabled={busy || Boolean(editor)}>Buat quotation</button></div></header>
    {error && <p className="document-state-alert" role="alert">{error} <button type="button" className="secondary" onClick={() => void load()}>Muat ulang</button></p>}
    {notice && <p className="document-state-notice" role="status">{notice}</p>}
    {editor && <QuotationEditor project={project} state={editor} busy={busy} onCancel={() => setEditor(null)} onSave={save} />}
    {loading ? <p role="status">Memuat riwayat quotation…</p> : items.length === 0 ? <p className="empty-state">Belum ada quotation. Buat draf terstruktur pertama untuk proyek ini.</p> : <div className="quotation-history" aria-label="Riwayat versi quotation">
      {items.map((item) => <article key={item.id} className={item.status === 'accepted' ? 'accepted' : ''}>
        <div className="quotation-version"><strong>Versi {item.version}</strong><span className={`status-pill status-${item.status}`}>{labels[item.status]}</span></div>
        <div><span>{item.subject || `Quotation ${project.name}`}</span><strong>{IDR.format(item.accepted_snapshot?.amount ?? item.amount)}</strong></div>
        <small>Dibuat {new Date(item.created_at).toLocaleDateString('id-ID')}{item.valid_until ? ` · Berlaku sampai ${new Date(`${item.valid_until}T00:00:00`).toLocaleDateString('id-ID')}` : ''}</small>
        {item.canva_url && <p className="legacy-reference">Referensi desain lama: <a href={item.canva_url} target="_blank" rel="noreferrer">Buka tautan historis</a></p>}
        <div className="quotation-actions">
          {item.lines?.length && item.project_image_url
            ? <button type="button" className="secondary" aria-label={`Unduh PDF versi ${item.version}`} onClick={() => void download(item)} disabled={busy}>Unduh PDF</button>
            : null}
          {item.status === 'draft' && <button type="button" className="secondary" aria-label={`Edit versi ${item.version}`} onClick={() => setEditor({ mode: 'edit', source: item, values: valuesFromItem(project, item) })} disabled={busy || Boolean(editor)}>Edit</button>}
          {(item.status === 'draft' || item.status === 'sent') && <button type="button" className="secondary" aria-label={`Buat revisi versi ${item.version}`} onClick={() => setEditor({ mode: 'revise', source: item, values: valuesFromItem(project, item) })} disabled={busy || Boolean(editor)}>Buat revisi</button>}
          {item.status === 'draft' && <button type="button" className="secondary" onClick={() => void transition(item, 'sent')} disabled={busy}>Tandai terkirim</button>}
          {item.status === 'sent' && <button type="button" aria-label={`Tandai Deal versi ${item.version}`} onClick={() => setDealItem(item)} disabled={busy}>Tandai Deal</button>}
          {item.status === 'sent' && <button type="button" className="danger-secondary" onClick={() => { setRejectItem(item); setRejectNote('') }} disabled={busy}>Tandai ditolak</button>}
        </div>
        {item.status === 'accepted' && item.installment_schedule?.length ? <div className="accepted-schedule"><strong>Jadwal nilai diterima</strong><ul>{item.installment_schedule.map((entry) => <li key={entry.sequence}>{entry.label}: {IDR.format(entry.amount)}</li>)}</ul></div> : null}
      </article>)}
    </div>}
    {dealItem && <DealDialog item={dealItem} busy={busy} onCancel={() => setDealItem(null)} onConfirm={deal} />}
    {rejectItem && <div className="modal-backdrop" role="presentation">
      <section ref={rejectDialog.dialogRef} onKeyDown={rejectDialog.onKeyDown} className="modal-card" role="dialog" aria-modal="true" aria-labelledby="reject-dialog-title" tabIndex={-1}>
        <header><div><span className="eyebrow">Versi {rejectItem.version}</span><h2 id="reject-dialog-title">Catat alasan penolakan</h2><p>Alasan tersimpan pada audit quotation dan tidak mengubah versi yang pernah dikirim.</p></div></header>
        <div className="modal-body"><label>Alasan penolakan<textarea aria-label="Alasan penolakan" value={rejectNote} onChange={(event) => setRejectNote(event.target.value)} required /></label></div>
        <footer className="modal-actions"><button type="button" className="secondary" onClick={closeReject} disabled={busy}>Batal</button><button type="button" className="danger-secondary" disabled={busy || !rejectNote.trim()} onClick={() => void transition(rejectItem, 'rejected', rejectNote.trim())}>{busy ? 'Menyimpan…' : 'Konfirmasi ditolak'}</button></footer>
      </section>
    </div>}
  </section>
}
