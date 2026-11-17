import { ArrowRight, Eye, Pencil, Plus, ReceiptText, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'

import ProjectDocumentPreview from './ProjectDocumentPreview'
import {
  calculateDocumentTotals,
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
  onOpenTransactions?: () => void
  onSave: (document: ProjectDocumentDraft) => void | Promise<void>
  onClose: () => void
}

function draftFrom(document: ProjectDocumentDraft | ProjectDocumentRecord): ProjectDocumentDraft {
  const { id, project_id, type, invoice_kind, applies_to_invoice_id, issue_date, due_date, valid_until, notes, payment_terms, prepared_by, client_signatory, project_image_url, lines, discount_mode, discount_value, tax_percent, allocations } = document
  return { id, project_id, type, invoice_kind, applies_to_invoice_id, issue_date, due_date, valid_until, notes, payment_terms, prepared_by, client_signatory, project_image_url, lines: lines.map((line) => ({ ...line })), discount_mode, discount_value, tax_percent, allocations: allocations.map((allocation) => ({ ...allocation })) }
}

export default function ProjectDocumentComposer({ project, document, writesEnabled, saving = false, receiptOptions = null, onSave, onClose, onOpenTransactions }: ProjectDocumentComposerProps) {
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
  const typeName = draft.type === 'sales_order' ? 'sales order' : draft.type === 'invoice' ? 'invoice' : 'kuitansi'
  let total: number | null = null
  let calculationError = ''
  try { total = calculateDocumentTotals(draft).total }
  catch (reason) { calculationError = reason instanceof Error ? reason.message : 'Perhitungan dokumen tidak valid.' }
  const money = total === null ? '—' : new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(total).replace(/\s/g, '')
  const receiptIsNew = draft.type === 'receipt' && !document.id
  const hasReceiptSources = Boolean(receiptOptions?.transactions.length || draft.allocations.length)
  const receiptReady = !receiptIsNew || draft.allocations.length > 0
  const subtitle = draft.type === 'receipt'
    ? 'Pilih pembayaran yang sudah tercatat. Nominal kuitansi diambil otomatis dari transaksi.'
    : 'Lengkapi informasi dokumen, susun item, lalu periksa hasil akhirnya.'
  const termsTitle = draft.type === 'receipt' ? 'Pihak terkait & keterangan' : 'Ketentuan & persetujuan'
  const termsHelp = draft.type === 'receipt'
    ? 'Pastikan nama penyusun, penerima, dan keterangan pembayaran sudah benar.'
    : 'Atur diskon, pajak, catatan, dan pihak yang menyetujui dokumen.'

  return <section className="document-composer document-workspace" aria-label="Penyusun dokumen">
    <header className="document-composer-head">
      <div><p className="eyebrow">DOKUMEN KOMERSIAL</p><h2>{document.id ? `Ubah ${typeName}` : `Buat ${typeName}`}</h2><p>{subtitle}</p><div className="document-context"><span>{project.name}</span><span>{project.client_name}</span></div></div>
      <button type="button" className="icon-button" aria-label="Tutup penyusun dokumen" onClick={close}><X size={20} /></button>
    </header>
    <ol className="document-workflow" aria-label={`Alur pembuatan ${typeName}`}>
      <li><span>1</span><strong>{draft.type === 'invoice' ? 'Detail invoice' : draft.type === 'receipt' ? 'Detail kuitansi' : 'Detail dokumen'}</strong></li>
      <li><span>2</span><strong>{draft.type === 'receipt' ? 'Alokasi pembayaran' : 'Item & harga'}</strong></li>
      <li><span>3</span><strong>{draft.type === 'receipt' ? 'Keterangan' : 'Ketentuan'}</strong></li>
    </ol>
    {receiptIsNew && !hasReceiptSources ? <section className="receipt-blocked-state" aria-labelledby="receipt-blocked-title">
      <span className="receipt-blocked-icon"><ReceiptText size={28} /></span>
      <div><p className="eyebrow">PEMBAYARAN BELUM TERSEDIA</p><h3 id="receipt-blocked-title">Kuitansi belum bisa dibuat</h3><p>Catat pemasukan proyek terlebih dahulu. Nominal kuitansi selalu diambil dari transaksi pemasukan terverifikasi, bukan dari catatan atau input manual.</p></div>
      <div className="receipt-blocked-actions"><button type="button" className="secondary-button" onClick={close}>Kembali</button>{onOpenTransactions && <button type="button" className="primary-button" onClick={onOpenTransactions}>Buka transaksi proyek <ArrowRight size={16} /></button>}</div>
    </section> : <>
    <div className="document-view-tabs" role="tablist" aria-label="Tampilan dokumen">
      <button type="button" role="tab" aria-selected={view === 'edit'} onClick={() => setView('edit')}><Pencil size={16} /> Edit</button>
      <button type="button" role="tab" aria-selected={view === 'preview'} onClick={() => setView('preview')}><Eye size={16} /> Pratinjau</button>
    </div>
    <div className="document-composer-layout">
      <form className={`document-editor${view === 'preview' ? ' mobile-hidden-panel' : ''}`} onSubmit={submit} noValidate>
        {error && <p ref={alertRef} tabIndex={-1} role="alert" className="form-error">{error}</p>}
        <section className="document-form-section" aria-labelledby="document-detail-heading">
          <div className="document-section-heading"><span>1</span><div><h3 id="document-detail-heading">Detail {typeName}</h3><p>Tanggal dan jenis tagihan yang terlihat pada dokumen.</p></div></div>
          <div className="document-field-grid">
          <div className="document-type-summary"><small>Jenis dokumen</small><strong>{draft.type === 'sales_order' ? 'Sales Order' : draft.type === 'invoice' ? 'Invoice' : 'Kuitansi'}</strong></div>
          {draft.type === 'invoice' && <label>Tahap invoice<select aria-label="Tahap invoice" value={draft.invoice_kind ?? 'DP'} onChange={(event) => change('invoice_kind', event.target.value as ProjectDocumentDraft['invoice_kind'])}><option value="DP">DP</option><option value="PROGRESS">Progress</option><option value="FINAL">Final</option></select></label>}
          <label>Tanggal dokumen<input type="date" value={draft.issue_date} onChange={(event) => change('issue_date', event.target.value)} /></label>
          {draft.type === 'invoice' && <label>Jatuh tempo<input type="date" value={draft.due_date ?? ''} onChange={(event) => change('due_date', event.target.value || null)} /></label>}
          {draft.type === 'sales_order' && <label>Berlaku sampai<input type="date" value={draft.valid_until ?? ''} onChange={(event) => change('valid_until', event.target.value || null)} /></label>}
          </div>
        </section>

        {draft.type !== 'receipt' ? <fieldset className="document-lines document-form-section"><legend><span>2</span><div><strong>Item & harga</strong><small>Masukkan pekerjaan yang ditagihkan. Total dihitung otomatis.</small></div></legend>
          {draft.lines.map((line, index) => <div className="document-line" key={line.id}>
            <label className="line-description">Deskripsi item {index + 1}<input aria-label={`Deskripsi item ${index + 1}`} value={line.description} onChange={(event) => changeLine(index, 'description', event.target.value)} /></label>
            <label>Kuantitas<input aria-label={`Kuantitas item ${index + 1}`} inputMode="decimal" value={line.quantity} onChange={(event) => changeLine(index, 'quantity', event.target.value)} /></label>
            <label>Satuan<input aria-label={`Satuan item ${index + 1}`} value={line.unit} onChange={(event) => changeLine(index, 'unit', event.target.value)} /></label>
            <label>Harga satuan<input aria-label={`Harga satuan item ${index + 1}`} type="number" min="0" step="1" value={line.unit_price} onChange={(event) => changeLine(index, 'unit_price', Number(event.target.value))} /></label>
            <label>Diskon %<input aria-label={`Diskon item ${index + 1}`} inputMode="decimal" value={line.discount_percent} onChange={(event) => changeLine(index, 'discount_percent', event.target.value)} /></label>
            <button type="button" className="icon-button danger" aria-label={`Hapus item ${index + 1}`} disabled={draft.lines.length === 1} onClick={() => change('lines', draft.lines.filter((_, lineIndex) => lineIndex !== index))}><Trash2 size={17} /></button>
          </div>)}
          <button type="button" className="secondary-button" onClick={() => change('lines', [...draft.lines, createEmptyDocumentLine()])}><Plus size={16} /> Tambah item</button>
        </fieldset> : <section className="receipt-allocation-note document-form-section" aria-labelledby="receipt-allocation-heading"><div className="document-section-heading"><span>2</span><div><h3 id="receipt-allocation-heading">Pilih pembayaran untuk kuitansi</h3><p>Centang transaksi yang akan dibuktikan oleh kuitansi ini.</p></div></div>
          {document.id ? <>
            <p>Invoice tujuan dan transaksi dikunci setelah kuitansi dibuat. Untuk koreksi, batalkan kuitansi lalu buat kuitansi baru.</p>
            <div className="receipt-candidates">{draft.allocations.map((allocation) => <div key={allocation.source_key}><span>{allocation.transaction_date || 'Tanpa tanggal'} · {allocation.description}</span><strong>{allocation.amount.toLocaleString('id-ID')}</strong></div>)}</div>
          </> : <>
            <label className="receipt-invoice-target">Hubungkan ke invoice <span className="field-help">Opsional. Pilih invoice bila pembayaran ini khusus untuk tagihan tertentu.</span><select aria-label="Invoice tujuan" value={draft.applies_to_invoice_id ?? ''} onChange={(event) => change('applies_to_invoice_id', event.target.value || null)}><option value="">Tidak dihubungkan ke invoice</option>{receiptOptions?.invoices.map((invoice) => <option key={invoice.invoice_id} value={invoice.invoice_id}>{invoice.invoice_kind} · {invoice.official_number} · sisa {invoice.outstanding.toLocaleString('id-ID')}</option>)}</select></label>
            <div className="receipt-candidates">{receiptOptions?.transactions.map((candidate) => {
              const selected = draft.allocations.find((item) => item.source_key === candidate.source_key)
              const amount = candidate.available_amount ?? candidate.amount
              return <label key={candidate.source_key} className={`receipt-candidate${selected ? ' selected' : ''}`}><span className="receipt-candidate-check"><input type="checkbox" checked={Boolean(selected)} onChange={(event) => toggleAllocation(candidate.source_key, event.target.checked)} /><span><strong>{candidate.description}</strong><small>{candidate.transaction_date || 'Tanpa tanggal'} · tersedia {amount.toLocaleString('id-ID')}</small></span></span><span className="receipt-candidate-amount"><small>Nominal kuitansi</small><input aria-label={`Nominal ${candidate.description}`} type="number" min="1" max={candidate.available_amount} disabled={!selected} value={selected?.amount ?? amount} onChange={(event) => changeAllocationAmount(candidate.source_key, Number(event.target.value))} /></span></label>
            })}</div>
            {!draft.allocations.length && <p className="receipt-selection-hint" role="status">Pilih minimal satu pembayaran untuk mengaktifkan pratinjau dan penyimpanan.</p>}
          </>}
        </section>}

        <section className="document-form-section" aria-labelledby="document-terms-heading">
          <div className="document-section-heading"><span>3</span><div><h3 id="document-terms-heading">{termsTitle}</h3><p>{termsHelp}</p></div></div>
          <div className="document-field-grid">
          {draft.type !== 'receipt' && draft.invoice_kind !== 'FINAL' && <>
            <label>Diskon dokumen<select value={draft.discount_mode} onChange={(event) => change('discount_mode', event.target.value as ProjectDocumentDraft['discount_mode'])}><option value="none">Tanpa diskon</option><option value="fixed">Nominal</option><option value="percent">Persen</option></select></label>
            {draft.discount_mode !== 'none' && <label>Nilai diskon<input inputMode="decimal" value={draft.discount_value} onChange={(event) => change('discount_value', event.target.value)} /></label>}
            <label>Pajak persen<input aria-label="Pajak persen" inputMode="decimal" value={draft.tax_percent} onChange={(event) => change('tax_percent', event.target.value)} /></label>
          </>}
          <label>Disiapkan oleh <span className="field-help">Nama tim Hollawall yang membuat dokumen.</span><input value={draft.prepared_by} onChange={(event) => change('prepared_by', event.target.value)} placeholder="Nama penyusun" /></label>
          <label>{draft.type === 'receipt' ? 'Diterima oleh' : 'Penanda tangan klien'} <span className="field-help">Nama pihak klien yang menerima atau menyetujui.</span><input value={draft.client_signatory} onChange={(event) => change('client_signatory', event.target.value)} placeholder="Nama pihak klien" /></label>
          </div>
          <div className="document-text-grid">
            <label>{draft.type === 'receipt' ? 'Keterangan pembayaran' : 'Catatan'} <span className="field-help">{draft.type === 'receipt' ? 'Contoh: Pelunasan termin pertama.' : 'Informasi tambahan yang tampil di bawah total.'}</span><textarea aria-label="Catatan" value={draft.notes} onChange={(event) => change('notes', event.target.value)} placeholder={draft.type === 'receipt' ? 'Tulis keterangan bila diperlukan' : 'Tulis catatan bila diperlukan'} /></label>
            {draft.type !== 'receipt' && <label>Syarat pembayaran <span className="field-help">Contoh: DP 50%, pelunasan sebelum pengiriman.</span><textarea value={draft.payment_terms} onChange={(event) => change('payment_terms', event.target.value)} placeholder="Tulis ketentuan pembayaran" /></label>}
          </div>
          {draft.type !== 'receipt' && <details className="document-optional"><summary>Tambahkan gambar proyek</summary><label>Data gambar <span className="field-help">Opsional. Gunakan data PNG atau JPEG.</span><input aria-label="Gambar proyek" value={draft.project_image_url ?? ''} onChange={(event) => change('project_image_url', event.target.value || null)} placeholder="data:image/png;base64,…" /></label></details>}
        </section>
        <div className="document-save-bar">
          <div aria-label={`Total ${typeName}`} className="document-live-total"><span>{draft.type === 'receipt' && !receiptReady ? 'Pembayaran belum dipilih' : calculationError ? 'Periksa nilai item' : `Total ${typeName}`}</span><strong>{draft.type === 'receipt' && !receiptReady ? '—' : calculationError ? '—' : money}</strong>{calculationError && <small>{calculationError}</small>}</div>
          <div>{!writesEnabled && <span className="write-disabled-note">Penyimpanan dokumen belum diaktifkan.</span>}<button type="button" className="secondary-button" onClick={close}>Batal</button><button type="submit" className="primary-button" disabled={!writesEnabled || saving || !receiptReady}>{saving ? 'Menyimpan…' : 'Simpan draf'}</button></div>
        </div>
      </form>
      <aside className={`document-preview-pane${view === 'edit' ? ' mobile-hidden-panel' : ''}`} aria-label={`Pratinjau ${typeName}`}><div className="document-preview-label"><span>PRATINJAU LANGSUNG</span><small>{calculationError ? 'Periksa nilai item' : receiptReady ? 'Terbarui otomatis' : 'Menunggu pembayaran'}</small></div>{receiptReady && !calculationError ? <ProjectDocumentPreview project={project} document={draft} /> : <section className="document-preview-empty"><ReceiptText size={28} /><h3>{calculationError ? 'Pratinjau perlu diperbaiki' : 'Pratinjau belum tersedia'}</h3><p>{calculationError || 'Pilih pembayaran di sebelah kiri. Total dan isi kuitansi akan muncul otomatis.'}</p></section>}</aside>
    </div>
    </>}
  </section>
}

export type { ProjectDocumentComposerProps }
