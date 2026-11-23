import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react'
import { Plus, Trash2 } from 'lucide-react'

import { useModalDialog } from './CanonicalDebtForms'
import ProjectDocumentPreview from './ProjectDocumentPreview'
import RupiahAmountInput from './RupiahAmountInput'
import { commercialPolicy, normalizeCommercialLine } from './commercialDocumentPolicy'
import { projectTemplateKey } from './commercialDocumentViewModel'
import { compressProjectImage } from './projectDocumentImage'
import { ProjectDocumentApiError, type ProjectDocumentSession } from './projectDocumentApi'
import { createProjectQuotationApi, type ProjectQuotationApi } from './projectQuotationApi'
import { jakartaToday } from './transactionApi'
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
const MAX_INSTALLMENTS = 24

type EditorMode = 'create' | 'edit' | 'revise'

interface EditorState {
  mode: EditorMode
  source: ProjectQuotation | null
  values: ProjectQuotationValues
}

function newLine(project: ProjectRecord, index = 0): ProjectQuotationLine {
  const policy = commercialPolicy(projectTemplateKey(project))
  const base = { id: `line-${Date.now()}-${index}`, description: '', unit_price: 0, discount_percent: '0', pricing_mode: policy.pricing_mode }
  return policy.pricing_mode === 'fixed_artwork'
    ? { ...base, quantity: '1', unit: 'artwork', display_quantity: '1', width: '', height: '', dimension_unit: 'm', original_price: null }
    : { ...base, quantity: '', unit: 'm²', width: '', height: '', dimension_unit: 'm', billed_area_m2: '', area_rounding: 'half_up' }
}

function projectValues(project: ProjectRecord): ProjectQuotationValues {
  const policy = commercialPolicy(projectTemplateKey(project))
  return {
    template_key: policy.template_key,
    template_version: policy.template_version,
    payment_profile_key: project.issuer_key,
    recipient_name: project.client_name,
    recipient_company: project.client_company,
    recipient_address: project.client_address,
    recipient_contact: project.client_contact,
    project_name: project.name,
    subject: `Penawaran ${project.name}`,
    valid_until: null,
    project_image_url: null,
    lines: [newLine(project)],
    discount_mode: 'none',
    discount_value: '0',
    tax_percent: '0',
    deposit_percent: commercialPolicy(project.company).default_deposit_percent,
    payment_terms: '',
    content_notes: '',
    amount: 0,
  }
}

function valuesFromItem(project: ProjectRecord, item: ProjectQuotation): ProjectQuotationValues {
  const fallback = projectValues(project)
  return {
    template_key: item.template_key ?? fallback.template_key,
    template_version: item.template_version ?? fallback.template_version,
    payment_profile_key: item.payment_profile_key ?? fallback.payment_profile_key,
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
    deposit_percent: item.deposit_percent ?? fallback.deposit_percent,
    payment_terms: item.payment_terms ?? '',
    content_notes: item.content_notes ?? '',
    amount: item.amount,
  }
}

function quotationDraft(project: ProjectRecord, values: ProjectQuotationValues): ProjectDocumentDraft {
  return {
    id: null,
    project_id: project.id,
    type: 'sales_order',
    invoice_kind: null,
    applies_to_invoice_id: null,
    issue_date: jakartaToday(),
    due_date: null,
    valid_until: values.valid_until,
    notes: values.content_notes,
    payment_terms: values.payment_terms,
    prepared_by: '',
    client_signatory: values.recipient_name,
    project_image_url: values.project_image_url,
    template_key: values.template_key,
    template_version: values.template_version,
    payment_profile_key: values.payment_profile_key,
    lines: values.lines,
    discount_mode: values.discount_mode,
    discount_value: values.discount_value,
    tax_percent: values.tax_percent,
    deposit_percent: values.deposit_percent,
    allocations: [],
  }
}

function calculatedValues(project: ProjectRecord, values: ProjectQuotationValues) {
  const policy = commercialPolicy(values.template_key || projectTemplateKey(project))
  const lines = values.lines.map((line) => normalizeCommercialLine(line, policy))
  const normalized = { ...values, lines }
  const totals = calculateDocumentTotals(quotationDraft(project, normalized))
  return { totals, values: { ...normalized, amount: totals.total } }
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
  const [imageProcessing, setImageProcessing] = useState(false)
  const policy = commercialPolicy(values.template_key || projectTemplateKey(project))
  const calculation = useMemo(() => {
    try { return { value: calculatedValues(project, values), error: '' } }
    catch (reason) { return { value: null, error: messageFrom(reason) } }
  }, [project, values])
  const paperProject = {
    ...project,
    name: values.project_name.trim() || project.name,
    client_name: values.recipient_name.trim() || project.client_name,
    client_company: values.recipient_company.trim() || project.client_company,
    client_address: values.recipient_address.trim() || project.client_address,
    client_contact: values.recipient_contact.trim() || project.client_contact,
  }

  const field = <K extends keyof ProjectQuotationValues>(name: K, value: ProjectQuotationValues[K]) => {
    setValues((current) => ({ ...current, [name]: value }))
  }
  const lineField = <K extends keyof ProjectQuotationLine>(index: number, name: K, value: ProjectQuotationLine[K]) => {
    setValues((current) => ({
      ...current,
      lines: current.lines.map((line, lineIndex) => lineIndex === index ? { ...line, [name]: value, ...(name === 'display_quantity' ? { quantity: String(value) } : {}), ...(name === 'billed_area_m2' ? { quantity: String(value), width: null, height: null, raw_area_m2: null, dimension_unit: null, area_rounding: 'half_up' as const, area_override_reason: null } : {}) } : line),
    }))
  }
  const uploadImage = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file) return
    setImageProcessing(true)
    setError('')
    try { field('project_image_url', await compressProjectImage(file)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Gambar Project gagal diproses.') }
    finally { setImageProcessing(false); input.value = '' }
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (imageProcessing || busy) return
    setError('')
    try {
      if (!values.recipient_name.trim()) throw new Error('Nama penerima wajib diisi.')
      if (!values.project_name.trim()) throw new Error('Nama Project wajib diisi.')
      if (!values.subject.trim()) throw new Error('Subjek penawaran wajib diisi.')
      if (!values.project_image_url) throw new Error('Gambar Project wajib diunggah.')
      if (!/^data:image\/(?:png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(values.project_image_url)) throw new Error('Gambar Project harus berupa data PNG atau JPEG.')
      if (!values.lines.length) throw new Error('Tambahkan minimal satu item.')
      for (const line of values.lines) {
        if (!line.description.trim() || !line.unit.trim()) throw new Error('Deskripsi dan satuan setiap item wajib diisi.')
      }
      if (!calculation.value) throw new Error(calculation.error)
      if (calculation.value.values.amount <= 0) throw new Error('Total quotation harus lebih dari Rp0.')
      await onSave(calculation.value.values)
    } catch (reason) { setError(messageFrom(reason)) }
  }

  const editorTitle = state.mode === 'revise' ? `Revisi dari versi ${state.source?.version}` : state.mode === 'edit' ? `Edit versi ${state.source?.version}` : 'Buat quotation'
  return <form className="quotation-editor quotation-workspace" onSubmit={submit} aria-label={state.mode === 'create' ? 'Quotation baru' : 'Editor quotation'}>
    <header>
      <div><h4>{editorTitle}</h4><p>Simpan draf, periksa PDF, lalu kirim manual ke klien.</p></div>
      <label className="quotation-brand-field">Template merek<input value={`${policy.template_key.toUpperCase()} · ${policy.page_size}`} readOnly aria-readonly="true" /></label>
    </header>

    <div className="quotation-editor-layout"><div className="quotation-editor-main">
    <fieldset disabled={busy}>
      <legend className="sr-only">Data penerima dan Project</legend>
      <div className="quotation-section-heading"><h3>Data penerima dan Project</h3></div>
      <div className="quotation-field-grid">
        <label>Nama penerima<input value={values.recipient_name} onChange={(event) => field('recipient_name', event.target.value)} required /></label>
        <label>Perusahaan penerima<input value={values.recipient_company} onChange={(event) => field('recipient_company', event.target.value)} /></label>
        <label className="wide">Alamat penerima<textarea value={values.recipient_address} onChange={(event) => field('recipient_address', event.target.value)} /></label>
        <label>Kontak penerima<input value={values.recipient_contact} onChange={(event) => field('recipient_contact', event.target.value)} /></label>
        <label>Nama Project<input value={values.project_name} onChange={(event) => field('project_name', event.target.value)} required /></label>
        <label className="wide">Subjek<input value={values.subject} onChange={(event) => field('subject', event.target.value)} required /></label>
        <label>Berlaku sampai<input value={`Ditetapkan ${policy.default_validity_days} hari dari tanggal kirim`} readOnly aria-readonly="true" /></label>
        <label>Gambar Project (PNG/JPEG)<input aria-label="Gambar Project" type="file" accept="image/png,image/jpeg" required={!values.project_image_url} onChange={uploadImage} />{imageProcessing && <small role="status">Memproses gambar…</small>}</label>
      </div>
      {values.project_image_url && <div className="quotation-image-preview"><img src={values.project_image_url} alt="Pratinjau gambar Project" /><button type="button" onClick={() => field('project_image_url', null)}>Hapus gambar</button></div>}
    </fieldset>

    <fieldset disabled={busy}>
      <legend className="sr-only">Rincian item</legend>
      <div className="quotation-section-heading"><h3>Rincian item</h3></div>
      <div className="quotation-lines">
        {values.lines.map((line, index) => <article key={line.id} className="quotation-line">
          <strong>Item {index + 1}</strong>
          <label className="description">Deskripsi item {index + 1}<input value={line.description} onChange={(event) => lineField(index, 'description', event.target.value)} required /></label>
          {(!line.pricing_mode || line.pricing_mode === 'legacy_generic') ? <>
            <label>Kuantitas item {index + 1}<input type="number" min="0.000001" step="any" value={line.quantity} onChange={(event) => lineField(index, 'quantity', event.target.value)} required /></label>
            <label>Satuan item {index + 1}<input value={line.unit} onChange={(event) => lineField(index, 'unit', event.target.value)} required /></label>
          </> : policy.pricing_mode === 'fixed_artwork' ? <>
            <label>Jumlah artwork item {index + 1}<input type="number" min="1" step="1" value={line.display_quantity ?? line.quantity} onChange={(event) => lineField(index, 'display_quantity', event.target.value)} required /></label>
            <RupiahAmountInput label={`Harga awal item ${index + 1}`} value={line.original_price ?? null} required={false} disabled={busy || imageProcessing} onChange={(amount) => lineField(index, 'original_price', amount)} />
          </> : <>
            <label>Luas tagihan (m²)<input aria-label={`Luas tagihan item ${index + 1} (m²)`} inputMode="decimal" value={line.billed_area_m2 ?? line.quantity} onChange={(event) => lineField(index, 'billed_area_m2', event.target.value)} /></label>
            {(Boolean(line.width && line.height) || line.area_rounding === 'manual_override') && <>
              <label>Pembulatan<select aria-label={`Pembulatan luas item ${index + 1}`} value={line.area_rounding ?? 'half_up'} onChange={(event) => lineField(index, 'area_rounding', event.target.value as 'exact' | 'half_up' | 'truncate' | 'manual_override')}><option value="exact">Exact</option><option value="half_up">Half-up</option><option value="truncate">Potong</option><option value="manual_override">Override manual</option></select></label>
              {line.area_rounding === 'manual_override' && <label>Alasan penyesuaian luas<input aria-label={`Alasan penyesuaian luas item ${index + 1}`} value={line.area_override_reason ?? ''} onChange={(event) => lineField(index, 'area_override_reason', event.target.value)} required /></label>}
            </>}
          </>}
            <RupiahAmountInput label={`${policy.labels.unit_price} item ${index + 1}`} value={line.unit_price} disabled={busy || imageProcessing} onChange={(amount) => lineField(index, 'unit_price', amount ?? 0)} />
          {policy.pricing_mode !== 'fixed_artwork' && <label>Diskon item {index + 1} (%)<input type="number" min="0" max="100" step="0.01" value={line.discount_percent} onChange={(event) => lineField(index, 'discount_percent', event.target.value)} /></label>}
          {values.lines.length > 1 && <button type="button" className="icon-button danger" aria-label={`Hapus item ${index + 1}`} onClick={() => setValues((current) => ({ ...current, lines: current.lines.filter((_, lineIndex) => lineIndex !== index) }))}><Trash2 size={17} /></button>}
        </article>)}
      </div>
      <button type="button" className="icon-button quotation-add-item" aria-label="Tambah item" onClick={() => setValues((current) => ({ ...current, lines: [...current.lines, newLine(project, current.lines.length)] }))}><Plus size={18} /></button>
    </fieldset>

    <fieldset disabled={busy}>
      <legend className="sr-only">Ringkasan dan ketentuan</legend>
      <div className="quotation-section-heading"><h3>Ringkasan dan ketentuan</h3></div>
      <div className="quotation-field-grid">
        <label>Jenis diskon dokumen<select value={values.discount_mode} onChange={(event) => field('discount_mode', event.target.value as ProjectQuotationValues['discount_mode'])}><option value="none">Tanpa diskon</option><option value="percent">Persen</option><option value="fixed">Rupiah</option></select></label>
        {values.discount_mode === 'fixed'
          ? <RupiahAmountInput label="Nilai diskon dokumen" value={Number.isSafeInteger(Number(values.discount_value)) ? Number(values.discount_value) : null} required={false} disabled={busy || imageProcessing} onChange={(amount) => field('discount_value', String(amount ?? ''))} />
          : <label>Nilai diskon dokumen (%)<input type="number" min="0" step="0.01" value={values.discount_value} disabled={values.discount_mode === 'none' || busy || imageProcessing} onChange={(event) => field('discount_value', event.target.value)} /></label>}
        <label>Pajak (%)<input type="number" min="0" max="100" step="0.01" value={values.tax_percent} onChange={(event) => field('tax_percent', event.target.value)} /></label>
        <label>DP Project (%)<input type="number" min="1" max="99" step="1" value={values.deposit_percent} onChange={(event) => field('deposit_percent', Number(event.target.value))} required /><small>Default merek {policy.default_deposit_percent}%; boleh disesuaikan per Project.</small></label>
        <label className="wide">Ketentuan pembayaran<textarea value={values.payment_terms} onChange={(event) => field('payment_terms', event.target.value)} /></label>
        <label className="wide">Catatan quotation<textarea value={values.content_notes} onChange={(event) => field('content_notes', event.target.value)} /></label>
      </div>
    </fieldset>
    {(error || calculation.error) && <p className="document-state-alert" role="alert">{error || calculation.error}</p>}
    </div>
    <aside className="quotation-summary" aria-label="Ringkasan quotation">
      <div><span className="eyebrow">RINGKASAN NILAI</span><strong>{calculation.value ? IDR.format(calculation.value.totals.total) : '—'}</strong><small>Total quotation</small></div>
      <dl className="quotation-totals" aria-label="Total quotation">
        <div><dt>Subtotal</dt><dd>{calculation.value ? IDR.format(calculation.value.totals.subtotal) : '—'}</dd></div>
        <div><dt>Diskon</dt><dd>{calculation.value ? `− ${IDR.format(calculation.value.totals.document_discount)}` : '—'}</dd></div>
        <div><dt>Pajak</dt><dd>{calculation.value ? IDR.format(calculation.value.totals.tax) : '—'}</dd></div>
      </dl>
      <p>Nilai berubah otomatis saat item, diskon, atau pajak diedit.</p>
      {calculation.value && <div className="quotation-paper-proof"><span className="eyebrow">BUKTI KERTAS · {policy.page_size}</span><ProjectDocumentPreview project={paperProject} document={quotationDraft(project, calculation.value.values)} title="Quotation" /></div>}
    </aside></div>
    <footer className="quotation-actions quotation-save-bar">
      <span>{state.mode === 'revise' ? 'Versi sebelumnya tetap tersimpan.' : 'Simpan draf sebelum mengunduh PDF.'}</span>
      <div><button type="button" className="secondary" onClick={onCancel} disabled={busy || imageProcessing}>Batal</button><button type="submit" disabled={busy || imageProcessing}>{imageProcessing ? 'Memproses gambar…' : busy ? 'Menyimpan…' : state.mode === 'revise' ? 'Simpan sebagai revisi' : 'Simpan draf'}</button></div>
    </footer>
  </form>
}

function DealDialog({ item, busy, onCancel, onConfirm }: {
  item: ProjectQuotation
  busy: boolean
  onCancel: () => void
  onConfirm: (dpPercent: number, installments: number) => Promise<void>
}) {
  const dialog = useModalDialog(onCancel, true, !busy)
  const total = item.accepted_snapshot?.amount ?? item.amount
  const dp = item.deposit_percent ?? commercialPolicy(item.template_key || 'hollawall').default_deposit_percent
  const [countChoice, setCountChoice] = useState('1')
  const [customCount, setCustomCount] = useState('4')
  const [error, setError] = useState('')
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
        <fieldset className="quotation-choice-group"><legend>Persentase DP</legend><p><strong>DP {dp}%</strong> mengikuti quotation terkirim dan tidak dapat diubah saat Deal.</p></fieldset>
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

export default function ProjectQuotationPanel({ project, salesOrder, session, api: suppliedApi, onApplied, onNotice, additionalCreateActions }: {
  project: ProjectRecord
  salesOrder?: ProjectDocumentRecord
  session: ProjectDocumentSession
  api?: ProjectQuotationApi
  onApplied: (documentId: string) => void | Promise<void>
  onNotice?: (message: string) => void
  additionalCreateActions?: ReactNode
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
  const pendingCreate = useRef<{ signature: string; idempotencyKey: string; savedId?: string } | null>(null)
  const announce = (message: string) => {
    setNotice(message)
    onNotice?.(message)
  }
  const closeReject = () => { setRejectItem(null); setRejectNote('') }
  const rejectDialog = useModalDialog(closeReject, Boolean(rejectItem), !busy)

  const load = async () => {
    setLoading(true); setError('')
    try {
      const loaded = (await api.list(project.id)).sort((left, right) => right.version - left.version)
      setItems(loaded)
      const pending = pendingCreate.current
      if (pending?.savedId && loaded.some((item) => item.id === pending.savedId)) {
        pendingCreate.current = null
        setEditor(null)
        announce('Quotation tersimpan dan berhasil dipulihkan.')
      }
    }
    catch (reason) { setError(messageFrom(reason)) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [api, project.id])

  const save = async (values: ProjectQuotationValues) => {
    if (!editor) return
    setBusy(true); setError(''); setNotice('')
    try {
      const signature = JSON.stringify(values)
      if (editor.mode === 'create' && pendingCreate.current && pendingCreate.current.signature !== signature) {
        throw new Error('Hasil pembuatan quotation sebelumnya belum pasti. Ulangi data yang sama atau muat ulang daftar quotation.')
      }
      if (editor.mode === 'create' && !pendingCreate.current) pendingCreate.current = { signature, idempotencyKey: crypto.randomUUID() }
      let saved = editor.mode === 'create'
        ? pendingCreate.current?.savedId
          ? (await api.list(project.id)).find((item) => item.id === pendingCreate.current?.savedId)
          : await api.create(project.id, values, session, pendingCreate.current!.idempotencyKey)
        : editor.mode === 'revise'
          ? await api.revise(editor.source!, values, session)
          : await api.saveDraft(editor.source!, values, session)
      if (!saved) throw new ProjectDocumentApiError('Quotation tersimpan, tetapi readback belum tersedia.', { code: 'quotation_readback_uncertain', retryable: true, uncertain: true })
      if (editor.mode === 'create' && !pendingCreate.current!.savedId) {
        pendingCreate.current!.savedId = saved.id
        saved = (await api.list(project.id)).find((item) => item.id === saved!.id)
        if (!saved) throw new ProjectDocumentApiError('Quotation tersimpan, tetapi readback belum tersedia.', { code: 'quotation_readback_uncertain', retryable: true, uncertain: true })
      }
      setItems((current) => [saved, ...current.filter((item) => item.id !== saved.id)].sort((left, right) => right.version - left.version))
      if (editor.mode === 'create') pendingCreate.current = null
      setEditor(null)
      announce(editor.mode === 'revise' ? `Versi ${saved.version} dibuat. Versi sebelumnya tetap tersimpan.` : `Draf versi ${saved.version} tersimpan.`)
    } catch (reason) {
      if (editor.mode === 'create' && !pendingCreate.current?.savedId && !(reason instanceof ProjectDocumentApiError && reason.uncertain)) pendingCreate.current = null
      const message = messageFrom(reason); setError(message); throw reason instanceof Error ? reason : new Error(message)
    }
    finally { setBusy(false) }
  }
  const transition = async (item: ProjectQuotation, status: 'sent' | 'rejected', note = '') => {
    setBusy(true); setError(''); setNotice('')
    try {
      const saved = await api.transition(item, status, note, session)
      setItems((current) => current.map((entry) => entry.id === saved.id ? saved : entry))
      if (status === 'rejected') { setRejectItem(null); setRejectNote('') }
      announce(status === 'rejected' ? `Quotation versi ${saved.version} ditandai ditolak.` : `Quotation versi ${saved.version} ditandai sudah dikirim.`)
    } catch (reason) { setError(messageFrom(reason)) }
    finally { setBusy(false) }
  }
  const deal = async (dpPercent: number, remainingInstallments: number) => {
    if (!dealItem) return
    if (!salesOrder || salesOrder.status !== 'draft') {
      setError('Sales Order draf Project tidak tersedia. Muat ulang Project sebelum menandai Deal.')
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
      announce('Deal dikonfirmasi. Sales Order dan draf invoice DP dibuat; jadwal tagihan tersimpan.')
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
      announce(`Unduhan PDF quotation versi ${item.version} disiapkan.`)
    } catch (reason) { setError(messageFrom(reason)) }
    finally { setBusy(false) }
  }

  if (editor) return <section className="quotation-panel quotation-panel-editor" aria-label="Penyusun quotation">
    {error && <p className="document-state-alert" role="alert">{error} <button type="button" className="secondary" onClick={() => void load()}>Muat ulang</button></p>}
    {notice && <p className="document-state-notice" role="status">{notice}</p>}
    <QuotationEditor project={project} state={editor} busy={busy} onCancel={() => setEditor(null)} onSave={save} />
  </section>

  return <section className="quotation-panel" aria-labelledby="quotation-title">
    <header><div><span className="eyebrow">DOKUMEN</span><h3 id="quotation-title">Buat dokumen</h3><p>Quotation dan invoice tidak mencatat kas. Kuitansi memakai transaksi pemasukan yang sudah tercatat.</p></div><div><span className="status-pill">Template {commercialPolicy(projectTemplateKey(project)).template_key.toUpperCase()}</span><button type="button" className="primary-button" onClick={() => setEditor({ mode: 'create', source: null, values: projectValues(project) })} disabled={busy || loading}>Buat quotation</button>{additionalCreateActions}</div></header>
    {error && <p className="document-state-alert" role="alert">{error} <button type="button" className="secondary" onClick={() => void load()}>Muat ulang</button></p>}
    {notice && <p className="document-state-notice" role="status">{notice}</p>}

    {loading ? <p role="status">Memuat riwayat quotation…</p> : items.length === 0 ? <p className="empty-state">Belum ada quotation. Buat draf terstruktur pertama untuk Project ini.</p> : <div className="quotation-history" aria-label="Riwayat versi quotation">
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
          {item.status === 'draft' && <button type="button" className="secondary" onClick={() => void transition(item, 'sent')} disabled={busy}>Catat sudah dikirim</button>}
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
