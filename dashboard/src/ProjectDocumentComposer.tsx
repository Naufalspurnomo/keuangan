import { Eye, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'

import ProjectDocumentPreview from './ProjectDocumentPreview'
import {
  createEmptyDocumentLine,
  validateDocumentDraft,
  type ProjectDocumentDraft,
  type ProjectDocumentRecord,
  type ProjectRecord,
  type ReceiptOptions,
} from './projectDocuments'

interface ProjectDocumentComposerProps {
  project: ProjectRecord
  document: ProjectDocumentDraft | ProjectDocumentRecord
  writesEnabled: boolean
  saving?: boolean
  receiptOptions?: ReceiptOptions | null
  onSave: (document: ProjectDocumentDraft) => void | Promise<void>
  onClose: () => void
}

function draftFrom(document: ProjectDocumentDraft | ProjectDocumentRecord): ProjectDocumentDraft {
  const { id, project_id, type, invoice_kind, applies_to_invoice_id, issue_date, due_date, valid_until, notes, payment_terms, prepared_by, client_signatory, project_image_url, lines, discount_mode, discount_value, tax_percent, allocations } = document
  return { id, project_id, type, invoice_kind, applies_to_invoice_id, issue_date, due_date, valid_until, notes, payment_terms, prepared_by, client_signatory, project_image_url, lines: lines.map((line) => ({ ...line })), discount_mode, discount_value, tax_percent, allocations: allocations.map((allocation) => ({ ...allocation })) }
}

export default function ProjectDocumentComposer({ project, document, writesEnabled, saving = false, receiptOptions = null, onSave, onClose }: ProjectDocumentComposerProps) {
  const [draft, setDraft] = useState(() => draftFrom(document))
  const [view, setView] = useState<'edit' | 'preview'>('edit')
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const alertRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    setDraft(draftFrom(document))
    setDirty(false)
    setError('')
  }, [document])

  const change = <K extends keyof ProjectDocumentDraft>(key: K, value: ProjectDocumentDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }))
    setDirty(true)
    setError('')
  }
  const changeLine = (index: number, key: keyof ProjectDocumentDraft['lines'][number], value: string | number) => {
    change('lines', draft.lines.map((line, lineIndex) => lineIndex === index ? { ...line, [key]: value } : line))
  }
  const toggleAllocation = (sourceKey: string, enabled: boolean) => {
    const candidate = receiptOptions?.transactions.find((item) => item.source_key === sourceKey)
    if (!candidate) return
    change('allocations', enabled
      ? [...draft.allocations, { ...candidate, amount: candidate.available_amount ?? candidate.amount }]
      : draft.allocations.filter((item) => item.source_key !== sourceKey))
  }
  const changeAllocationAmount = (sourceKey: string, amount: number) => {
    change('allocations', draft.allocations.map((item) => item.source_key === sourceKey ? { ...item, amount } : item))
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      const clean = validateDocumentDraft(draft)
      setError('')
      await onSave(clean)
      setDirty(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Dokumen belum dapat disimpan.')
      requestAnimationFrame(() => alertRef.current?.focus())
    }
  }
  const close = () => {
    if (dirty && !window.confirm('Tutup penyusun dan buang perubahan yang belum disimpan?')) return
    onClose()
  }

  return <section className="document-composer" aria-label="Penyusun dokumen">
    <header className="document-composer-head">
      <div><p className="eyebrow">PENYUSUN DOKUMEN</p><h2>{document.id ? 'Ubah draf' : 'Dokumen baru'}</h2></div>
      <button type="button" className="icon-button" aria-label="Tutup penyusun dokumen" onClick={close}><X size={20} /></button>
    </header>
    <div className="document-view-tabs" role="tablist" aria-label="Tampilan dokumen">
      <button type="button" role="tab" aria-selected={view === 'edit'} onClick={() => setView('edit')}><Pencil size={16} /> Edit</button>
      <button type="button" role="tab" aria-selected={view === 'preview'} onClick={() => setView('preview')}><Eye size={16} /> Pratinjau</button>
    </div>
    <div className="document-composer-layout">
      <form className={`document-editor${view === 'preview' ? ' mobile-hidden-panel' : ''}`} onSubmit={submit} noValidate>
        {error && <p ref={alertRef} tabIndex={-1} role="alert" className="form-error">{error}</p>}
        <div className="document-field-grid">
          <label>Jenis dokumen<input value={draft.type === 'sales_order' ? 'Sales Order' : draft.type === 'invoice' ? 'Invoice' : 'Kuitansi'} disabled /></label>
          {draft.type === 'invoice' && <label>Tahap invoice<select aria-label="Tahap invoice" value={draft.invoice_kind ?? 'DP'} onChange={(event) => change('invoice_kind', event.target.value as ProjectDocumentDraft['invoice_kind'])}><option value="DP">DP</option><option value="PROGRESS">Progress</option><option value="FINAL">Final</option></select></label>}
          <label>Tanggal dokumen<input type="date" value={draft.issue_date} onChange={(event) => change('issue_date', event.target.value)} /></label>
          {draft.type === 'invoice' && <label>Jatuh tempo<input type="date" value={draft.due_date ?? ''} onChange={(event) => change('due_date', event.target.value || null)} /></label>}
          {draft.type === 'sales_order' && <label>Berlaku sampai<input type="date" value={draft.valid_until ?? ''} onChange={(event) => change('valid_until', event.target.value || null)} /></label>}
        </div>

        {draft.type !== 'receipt' ? <fieldset className="document-lines"><legend>Item dokumen</legend>
          {draft.lines.map((line, index) => <div className="document-line" key={line.id}>
            <label className="line-description">Deskripsi item {index + 1}<input aria-label={`Deskripsi item ${index + 1}`} value={line.description} onChange={(event) => changeLine(index, 'description', event.target.value)} /></label>
            <label>Kuantitas<input aria-label={`Kuantitas item ${index + 1}`} inputMode="decimal" value={line.quantity} onChange={(event) => changeLine(index, 'quantity', event.target.value)} /></label>
            <label>Satuan<input aria-label={`Satuan item ${index + 1}`} value={line.unit} onChange={(event) => changeLine(index, 'unit', event.target.value)} /></label>
            <label>Harga satuan<input aria-label={`Harga satuan item ${index + 1}`} type="number" min="0" step="1" value={line.unit_price} onChange={(event) => changeLine(index, 'unit_price', Number(event.target.value))} /></label>
            <label>Diskon %<input aria-label={`Diskon item ${index + 1}`} inputMode="decimal" value={line.discount_percent} onChange={(event) => changeLine(index, 'discount_percent', event.target.value)} /></label>
            <button type="button" className="icon-button danger" aria-label={`Hapus item ${index + 1}`} disabled={draft.lines.length === 1} onClick={() => change('lines', draft.lines.filter((_, lineIndex) => lineIndex !== index))}><Trash2 size={17} /></button>
          </div>)}
          <button type="button" className="secondary-button" onClick={() => change('lines', [...draft.lines, createEmptyDocumentLine()])}><Plus size={16} /> Tambah item</button>
        </fieldset> : <section className="receipt-allocation-note"><strong>Alokasi pembayaran</strong>
          {document.id ? <>
            <p>Invoice tujuan dan transaksi dikunci setelah kuitansi dibuat. Untuk koreksi, batalkan kuitansi lalu buat kuitansi baru.</p>
            <div className="receipt-candidates">{draft.allocations.map((allocation) => <div key={allocation.source_key}><span>{allocation.transaction_date || 'Tanpa tanggal'} · {allocation.description}</span><strong>{allocation.amount.toLocaleString('id-ID')}</strong></div>)}</div>
          </> : <>
            <label>Invoice tujuan<select aria-label="Invoice tujuan" value={draft.applies_to_invoice_id ?? ''} onChange={(event) => change('applies_to_invoice_id', event.target.value || null)}><option value="">Belum dialokasikan ke invoice</option>{receiptOptions?.invoices.map((invoice) => <option key={invoice.invoice_id} value={invoice.invoice_id}>{invoice.invoice_kind} · {invoice.official_number} · sisa {invoice.outstanding.toLocaleString('id-ID')}</option>)}</select></label>
            {!receiptOptions?.transactions.length ? <p>Belum ada transaksi pemasukan proyek yang tersedia.</p> : <div className="receipt-candidates">{receiptOptions.transactions.map((candidate) => {
              const selected = draft.allocations.find((item) => item.source_key === candidate.source_key)
              return <label key={candidate.source_key}><span><input type="checkbox" checked={Boolean(selected)} onChange={(event) => toggleAllocation(candidate.source_key, event.target.checked)} /> {candidate.transaction_date || 'Tanpa tanggal'} · {candidate.description}</span><input aria-label={`Nominal ${candidate.description}`} type="number" min="1" max={candidate.available_amount} disabled={!selected} value={selected?.amount ?? candidate.available_amount ?? candidate.amount} onChange={(event) => changeAllocationAmount(candidate.source_key, Number(event.target.value))} /></label>
            })}</div>}
          </>}
        </section>}

        <div className="document-field-grid">
          {draft.type !== 'receipt' && draft.invoice_kind !== 'FINAL' && <>
            <label>Diskon dokumen<select value={draft.discount_mode} onChange={(event) => change('discount_mode', event.target.value as ProjectDocumentDraft['discount_mode'])}><option value="none">Tanpa diskon</option><option value="fixed">Nominal</option><option value="percent">Persen</option></select></label>
            {draft.discount_mode !== 'none' && <label>Nilai diskon<input inputMode="decimal" value={draft.discount_value} onChange={(event) => change('discount_value', event.target.value)} /></label>}
            <label>Pajak persen<input aria-label="Pajak persen" inputMode="decimal" value={draft.tax_percent} onChange={(event) => change('tax_percent', event.target.value)} /></label>
          </>}
          <label>Disiapkan oleh<input value={draft.prepared_by} onChange={(event) => change('prepared_by', event.target.value)} /></label>
          <label>Penanda tangan klien<input value={draft.client_signatory} onChange={(event) => change('client_signatory', event.target.value)} /></label>
          <label>Gambar proyek<input aria-label="Gambar proyek" value={draft.project_image_url ?? ''} onChange={(event) => change('project_image_url', event.target.value || null)} placeholder="data:image/png;base64,…" /></label>
        </div>
        <label>Catatan<textarea aria-label="Catatan" value={draft.notes} onChange={(event) => change('notes', event.target.value)} /></label>
        <label>Syarat pembayaran<textarea value={draft.payment_terms} onChange={(event) => change('payment_terms', event.target.value)} /></label>
        <div className="document-save-bar">
          {!writesEnabled && <span className="write-disabled-note">Penyimpanan dokumen belum diaktifkan.</span>}
          <button type="submit" className="primary-button" disabled={!writesEnabled || saving}>{saving ? 'Menyimpan…' : 'Simpan draf'}</button>
        </div>
      </form>
      <div className={`document-preview-pane${view === 'edit' ? ' mobile-hidden-panel' : ''}`}><ProjectDocumentPreview project={project} document={draft} /></div>
    </div>
  </section>
}

export type { ProjectDocumentComposerProps }
