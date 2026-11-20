import { Ban, Download, FilePlus2, Plus, RefreshCw, RotateCcw, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import ProjectDocumentComposer from './ProjectDocumentComposer'
import ProjectDocumentPreview from './ProjectDocumentPreview'
import ProjectQuotationPanel from './ProjectQuotationPanel'
import { useModalDialog } from './CanonicalDebtForms'
import { jakartaToday } from './transactionApi'
import type { ProjectDocumentApi, ProjectDocumentCommand, ProjectDocumentSession } from './projectDocumentApi'
import {
  createEmptyDocumentDraft,
  documentStatusLabel,
  documentTypeLabel,
  type ProjectDocumentDraft,
  type ProjectDocumentRecord,
  type ProjectDocumentRoute,
  type ProjectPaymentSummary,
  type ProjectRecord,
  type ReceiptOptions,
} from './projectDocuments'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const DATE = new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })

type RetryCommand = ProjectDocumentCommand<ProjectDocumentRecord> | null

interface ProjectDocumentsWorkspaceProps {
  project: ProjectRecord
  api: ProjectDocumentApi
  session: ProjectDocumentSession
  route: ProjectDocumentRoute
  onRouteChange: (route: ProjectDocumentRoute) => void
  onNotice?: (message: string) => void
}

function displayDate(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : DATE.format(parsed)
}

function errorFlags(reason: unknown) {
  const error = reason && typeof reason === 'object' ? reason as { stale?: boolean; uncertain?: boolean; retryable?: boolean; message?: string } : {}
  return { stale: error.stale === true, uncertain: error.uncertain === true, retryable: error.retryable === true, message: error.message || 'Permintaan belum dapat diselesaikan.' }
}

export default function ProjectDocumentsWorkspace({ project, api, session, route, onRouteChange, onNotice }: ProjectDocumentsWorkspaceProps) {
  const [documents, setDocuments] = useState<ProjectDocumentRecord[]>([])
  const [paymentSummary, setPaymentSummary] = useState<ProjectPaymentSummary | null>(null)
  const [receiptOptions, setReceiptOptions] = useState<ReceiptOptions | null>(null)
  const [active, setActive] = useState<ProjectDocumentRecord | ProjectDocumentDraft | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const mutationInFlight = useRef(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [retryCommand, setRetryCommand] = useState<RetryCommand>(null)
  const [retryAfter, setRetryAfter] = useState<((document: ProjectDocumentRecord) => Promise<void>) | null>(null)
  const [voiding, setVoiding] = useState(false)
  const [voidReason, setVoidReason] = useState('')
  const voidDialog = useModalDialog(() => setVoiding(false), voiding)

  const writesEnabled = session.capabilities.documentWrites
  const today = jakartaToday()
  const preparingReceipt = route.type === 'receipt' && loading && !active
  const announce = useCallback((message: string) => {
    setNotice(message)
    onNotice?.(message)
  }, [onNotice])

  const loadList = useCallback(async () => {
    setLoading(true)
    setError('')
    setNotice('')
    const appendError = (message: string) => setError((current) => current ? `${current} ${message}` : message)
    const documentsRequest = api.listDocuments(project.id).then((result) => {
      setDocuments(result.documents)
    }).catch(() => {
      setDocuments([])
      appendError('Dokumen belum dapat dimuat. Periksa koneksi lalu coba lagi.')
    })
    const paymentRequest = api.getPaymentSummary(project.id).then((summary) => {
      setPaymentSummary(summary)
    }).catch(() => {
      setPaymentSummary(null)
      appendError('Ringkasan pembayaran belum dapat dimuat.')
    })
    await Promise.all([documentsRequest, paymentRequest])
    setLoading(false)
  }, [api, project.id])

  useEffect(() => { void loadList() }, [loadList])

  useEffect(() => {
    let cancelled = false
    setError('')
    setNotice('')
    setRetryCommand(null)
    if (route.document) {
      setLoading(true)
      api.getDocument(route.document).then((document) => {
        if (!cancelled) setActive(document)
      }).catch(() => {
        if (!cancelled) { setActive(null); setError('Dokumen belum dapat dibuka.') }
      }).finally(() => { if (!cancelled) setLoading(false) })
    } else if (route.type === 'receipt') {
      setLoading(true)
      api.getReceiptOptions(project.id).then((options) => {
        if (!cancelled) {
          setReceiptOptions(options)
          setActive(createEmptyDocumentDraft(project.id, 'receipt', today))
        }
      }).catch(() => {
        if (!cancelled) { setActive(null); setReceiptOptions(null); setError('Pilihan pembayaran belum dapat dimuat.') }
      }).finally(() => { if (!cancelled) setLoading(false) })
    } else if (route.type) {
      setReceiptOptions(null)
      setActive(createEmptyDocumentDraft(project.id, route.type, today))
    } else {
      setReceiptOptions(null)
      setActive(null)
    }
    return () => { cancelled = true }
  }, [api, project.id, route.document, route.type, today])

  const replaceDocument = (document: ProjectDocumentRecord) => {
    setDocuments((current) => current.some((item) => item.id === document.id)
      ? current.map((item) => item.id === document.id ? document : item)
      : [document, ...current])
    setActive(document)
  }

  const authoritativeReadback = useCallback(async (id: string) => {
    const current = await api.getDocument(id)
    replaceDocument(current)
    try {
      const summary = await api.getPaymentSummary(project.id)
      setPaymentSummary(summary)
      announce('Perubahan dikonfirmasi dan dibaca kembali dari server.')
    } catch {
      announce('Perubahan dokumen sudah dikonfirmasi. Ringkasan pembayaran belum dapat dimuat ulang; gunakan Coba lagi.')
    }
  // replaceDocument only uses stable React setters.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [announce, api, project.id])

  const execute = async (command: ProjectDocumentCommand<ProjectDocumentRecord>, after?: (document: ProjectDocumentRecord) => Promise<void>) => {
    if (mutationInFlight.current) return false
    mutationInFlight.current = true
    setBusy(true)
    setError('')
    setNotice('')
    setRetryCommand(null)
    setRetryAfter(null)
    try {
      const result = await command.submit(session)
      replaceDocument(result)
      if (after) await after(result)
      else await authoritativeReadback(result.id)
      return true
    } catch (reason) {
      const flags = errorFlags(reason)
      if (flags.stale) {
        setError('Data berubah di server. Versi terbaru telah dimuat; periksa kembali sebelum mengulangi.')
        if (active?.id) {
          try { await authoritativeReadback(active.id) } catch { setNotice('Versi terbaru belum dapat dibaca kembali.') }
        }
      } else if (flags.uncertain) {
        setError(`Hasil perubahan belum pasti: ${flags.message}`)
        if (flags.retryable) {
          setRetryCommand(command)
          setRetryAfter(() => after ?? null)
        }
      } else setError(flags.message)
      return false
    } finally {
      mutationInFlight.current = false
      setBusy(false)
    }
  }

  const saveDraft = async (draft: ProjectDocumentDraft) => {
    if (mutationInFlight.current || retryCommand) return false
    const record = active && 'status' in active ? active : null
    const command = record ? api.updateDocument(record.id, draft, record.lock_version) : api.createDocument(draft)
    return execute(command, async (saved) => {
      await authoritativeReadback(saved.id)
      onRouteChange({ tab: 'documents', projectId: project.id, document: saved.id })
    })
  }

  const issue = () => {
    if (!active || !('status' in active) || active.status !== 'draft') return
    if (!window.confirm('Terbitkan dokumen? Nomor resmi akan diberikan dan isi tidak dapat diedit.')) return
    void execute(api.issueDocument(active.id, active.lock_version), async () => authoritativeReadback(active.id))
  }

  const revise = () => {
    if (!active || !('status' in active) || active.status !== 'issued') return
    if (!window.confirm('Buat draf revisi dari dokumen terbit ini?')) return
    void execute(api.reviseDocument(active.id, active.lock_version), async (revision) => {
      await authoritativeReadback(revision.id)
      onRouteChange({ tab: 'documents', projectId: project.id, document: revision.id })
    })
  }

  const confirmVoid = () => {
    if (!active || !('status' in active) || active.status !== 'issued') return
    const reason = voidReason.trim()
    if (!reason) { setError('Alasan pembatalan wajib diisi.'); return }
    setVoiding(false)
    void execute(api.voidDocument(active.id, reason, active.lock_version), async () => authoritativeReadback(active.id))
  }

  const download = async () => {
    if (!active?.id) return
    setBusy(true)
    setError('')
    try {
      const blob = await api.downloadDocument(active.id)
      const url = URL.createObjectURL(blob)
      const anchor = window.document.createElement('a')
      anchor.href = url
      anchor.download = `${'number' in active && active.number ? active.number.replaceAll('/', '-') : active.id}.pdf`
      anchor.click()
      URL.revokeObjectURL(url)
      announce('Unduhan PDF disiapkan.')
    } catch (reason) {
      setError(errorFlags(reason).message)
    } finally { setBusy(false) }
  }

  const close = () => onRouteChange({ tab: 'documents', projectId: project.id })
  const open = (document: ProjectDocumentRecord) => onRouteChange({ tab: 'documents', projectId: project.id, document: document.id })
  const create = (type: 'invoice' | 'receipt') => onRouteChange({ tab: 'documents', projectId: project.id, type })
  const retrySame = () => { if (retryCommand) void execute(retryCommand, retryAfter ?? undefined) }

  const sorted = useMemo(() => [...documents].sort((left, right) => right.updated_at.localeCompare(left.updated_at)), [documents])

  if (active) {
    const composing = !('status' in active) || active.status === 'draft'
    return <div className={`project-documents-active${composing ? ' document-compose-shell' : ''}`} aria-busy={busy}>
    {error && <div role="alert" className="document-state-alert"><strong>{error}</strong>{retryCommand && <button type="button" className="secondary-button" onClick={retrySame} disabled={busy}>Ulangi permintaan yang sama</button>}</div>}
    {notice && <p role="status" className="document-state-notice">{notice}</p>}
    {'status' in active && active.status !== 'draft' ? <>
      <header className="document-record-actions">
        <button type="button" className="secondary-button" onClick={close}><X size={16} /> Tutup dokumen</button>
        <div>
          <button type="button" className="secondary-button" onClick={download} disabled={busy}><Download size={16} /> Unduh PDF</button>
          {active.status === 'issued' && <button type="button" className="secondary-button" onClick={revise} disabled={!writesEnabled || busy}><RotateCcw size={16} /> Buat revisi</button>}
          {active.status === 'issued' && <button type="button" className="secondary-button danger" onClick={() => setVoiding(true)} disabled={!writesEnabled || busy}><Ban size={16} /> Batalkan dokumen</button>}
        </div>
      </header>
      {!writesEnabled && <p className="write-disabled-note">Perubahan dokumen belum diaktifkan.</p>}
      <ProjectDocumentPreview project={project} document={active} />
    </> : <>
      {!writesEnabled && <p className="write-disabled-note">Perubahan dokumen belum diaktifkan.</p>}
      <ProjectDocumentComposer project={project} document={active} writesEnabled={writesEnabled} saving={busy || Boolean(retryCommand)} receiptOptions={receiptOptions} onSave={saveDraft} onClose={close} onOpenTransactions={() => onRouteChange({ tab: 'transactions', projectId: project.id })} />
      {'status' in active && <div className="document-issue-bar"><button type="button" className="primary-button" onClick={issue} disabled={!writesEnabled || busy}>Terbitkan dokumen</button></div>}
    </>}
    {voiding && <div className="modal-backdrop" role="presentation"><section ref={voidDialog.dialogRef} onKeyDown={voidDialog.onKeyDown} className="modal-card document-void-dialog" role="dialog" aria-modal="true" aria-label="Batalkan dokumen" tabIndex={-1}>
      <header><h2>Batalkan dokumen</h2><button type="button" className="icon-button" aria-label="Tutup pembatalan" onClick={() => setVoiding(false)}><X size={19} /></button></header>
      <p>Pembatalan disimpan sebagai jejak audit. Dokumen tidak dihapus.</p>
      <label>Alasan pembatalan<textarea aria-label="Alasan pembatalan" value={voidReason} onChange={(event) => setVoidReason(event.target.value)} autoFocus /></label>
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setVoiding(false)}>Kembali</button><button type="button" className="primary-button danger" onClick={confirmVoid}>Konfirmasi pembatalan</button></div>
    </section></div>}
  </div>
  }

  return <section className="project-documents-workspace" aria-busy={loading}>
    {!writesEnabled && <p className="write-disabled-note">Perubahan dokumen belum diaktifkan.</p>}
    {error && <div role="alert" className="document-state-alert"><strong>{error}</strong><button type="button" className="secondary-button" onClick={() => void loadList()}><RefreshCw size={16} /> Coba lagi</button></div>}
    {notice && <p role="status" className="document-state-notice">{notice}</p>}
    {preparingReceipt && <p role="status" className="document-state-notice"><strong>Menyiapkan kuitansi…</strong> Memeriksa invoice dan transaksi pemasukan yang tersedia.</p>}
    <ProjectQuotationPanel
      project={project}
      salesOrder={documents.find((document) => document.type === 'sales_order' && document.status === 'draft')}
      session={session}
      onNotice={onNotice}
      onApplied={async (documentId) => {
        await authoritativeReadback(documentId)
        onRouteChange({ tab: 'documents', projectId: project.id, document: documentId })
      }}
      additionalCreateActions={<><button type="button" className="secondary-button" onClick={() => create('invoice')} disabled={!writesEnabled}><FilePlus2 size={16} /> Buat invoice</button><button type="button" className="secondary-button" onClick={() => create('receipt')} disabled={!writesEnabled || loading || preparingReceipt}>{preparingReceipt ? <RefreshCw className="is-spinning" size={16} /> : <Plus size={16} />} {preparingReceipt ? 'Menyiapkan kuitansi…' : 'Buat kuitansi'}</button></>}
    />
    {paymentSummary && <section className="payment-summary" aria-label="Ringkasan pembayaran"><header><div><p className="eyebrow">STATUS PEMBAYARAN</p><h3>{paymentSummary.payment_status === 'NOT_CONTRACTED' ? 'Sales Order belum diterbitkan' : paymentSummary.payment_status === 'PAID' ? 'Lunas' : paymentSummary.payment_status === 'PARTIALLY_PAID' ? 'Dibayar sebagian' : 'Belum dibayar'}</h3></div></header><div className="payment-summary-grid"><span><small>Nilai kontrak</small><strong>{paymentSummary.contract_total === null ? '—' : IDR.format(paymentSummary.contract_total)}</strong></span><span><small>Sudah ditagihkan</small><strong>{IDR.format(paymentSummary.invoiced_total)}</strong></span><span><small>Sudah dibayar</small><strong>{IDR.format(paymentSummary.paid_total)}</strong></span><span><small>Belum dibayar</small><strong>{paymentSummary.contract_outstanding === null ? '—' : IDR.format(paymentSummary.contract_outstanding)}</strong></span><span><small>Belum ditagihkan</small><strong>{paymentSummary.unbilled_total === null ? '—' : IDR.format(paymentSummary.unbilled_total)}</strong></span></div>{paymentSummary.unapplied_total > 0 && <p className="payment-summary-warning">{IDR.format(paymentSummary.unapplied_total)} sudah diterima tetapi belum dialokasikan ke invoice aktif.</p>}{paymentSummary.overpaid_total > 0 && <p className="payment-summary-warning">Kelebihan pembayaran {IDR.format(paymentSummary.overpaid_total)} perlu direkonsiliasi.</p>}{paymentSummary.invoices.length > 0 && <div className="invoice-payment-list">{paymentSummary.invoices.map((invoice) => <article key={invoice.invoice_id}><div><strong>{invoice.invoice_kind} · {invoice.official_number}</strong><span>{invoice.payment_status === 'PAID' ? 'Lunas' : invoice.payment_status === 'PARTIALLY_PAID' ? 'Dibayar sebagian' : 'Belum dibayar'}</span></div><small>{IDR.format(invoice.paid_total)} dibayar · {IDR.format(invoice.outstanding)} tersisa</small></article>)}</div>}</section>}
    {loading && !sorted.length ? <div className="project-detail-empty project-document-empty" role="status"><strong>Memuat dokumen…</strong><span>Mengambil daftar terbaru dari server tanpa menahan Quotation dan Invoice.</span></div> : !error && !sorted.length ? <div className="project-detail-empty project-document-empty"><strong>Belum ada Invoice atau kuitansi.</strong><span>Dokumen tersimpan dan dapat dibuka kembali dari daftar ini.</span></div> : <div className="project-document-list">{sorted.map((document) => <article key={document.id} className="project-document-card" aria-label={document.number ?? `${documentTypeLabel(document.type)} draf`}>
      <div><span className={`document-status ${document.status}`}>{documentStatusLabel(document.status)}</span><small>{documentTypeLabel(document.type)}</small><strong>{document.number ?? `${documentTypeLabel(document.type)} draf`}</strong><span>Diperbarui {displayDate(document.updated_at)}</span></div>
      <div><strong>{IDR.format(document.totals.total)}</strong><button type="button" className="secondary-button" aria-label={`Buka ${document.number ?? `${documentTypeLabel(document.type)} draf`}`} onClick={() => open(document)}>Buka</button></div>
    </article>)}</div>}
  </section>
}

export type { ProjectDocumentsWorkspaceProps }
