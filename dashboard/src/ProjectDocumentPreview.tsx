import hojjaMaster from './assets/hojja-master.png'
import hollawallMaster from './assets/hollawall-master.png'
import texturinBaliMaster from './assets/texturin-bali-master.png'
import texturinSurabayaMaster from './assets/texturin-surabaya-master.png'
import { buildCommercialDocumentViewModel, type CommercialDocumentViewModel } from './commercialDocumentViewModel'
import {
  documentStatusLabel,
  documentTypeLabel,
  type ProjectDocumentDraft,
  type ProjectDocumentRecord,
  type ProjectRecord,
} from './projectDocuments'

const IDR = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })
const DATE = new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'long', year: 'numeric', timeZone: 'UTC' })

function money(value: number) {
  return IDR.format(value).replace(/\s/g, '')
}

function dateLabel(value: string | null) {
  if (!value) return '—'
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? value : DATE.format(parsed)
}

function Watermark({ status }: { status: string }) {
  return status === 'issued' ? null : <span className={`document-watermark ${status}`}>{status === 'draft' ? 'DRAF' : documentStatusLabel(status as ProjectDocumentRecord['status']).toLocaleUpperCase('id-ID')}</span>
}

function Master({ src, alt }: { src: string; alt: string }) {
  return <img className="commercial-template-master" src={src} alt={alt} draggable={false} />
}

function isReceipt(document: PreviewProps['document']) {
  return document.type === 'receipt'
}

function isInvoice(document: PreviewProps['document']) {
  return document.type === 'invoice'
}

function hasDeposit(document: PreviewProps['document']) {
  return !isReceipt(document) && (!isInvoice(document) || document.invoice_kind === 'DP')
}

function taxLabel(document: PreviewProps['document']) {
  return Number(document.tax_percent || 0) > 0 ? `Pajak ${document.tax_percent}%` : 'Pajak'
}

function DueOrValidity({ document }: { document: PreviewProps['document'] }) {
  const date = isInvoice(document) ? document.due_date : document.valid_until
  if (!date) return null
  return <><b>{isInvoice(document) ? 'Jatuh tempo' : 'Berlaku sampai'}</b><span>{dateLabel(date)}</span></>
}

function ReceiptOverlay({ project, document, vm }: ResolvedPreviewProps) {
  return <section className="live-receipt"><p>Telah diterima dari <strong>{project.client_name}</strong> untuk pembayaran proyek <strong>{project.name}</strong>.</p><b>{money(vm.totals.total)}</b><small>Diterima oleh</small><strong>{document.client_signatory || project.client_name}</strong></section>
}

function HollawallPreview(props: ResolvedPreviewProps) {
  const { project, document, vm } = props
  return <article className="project-document-preview brand-document master-document hollawall-master-document" data-template="hollawall" data-page-size="A5" aria-label={`Pratinjau A5 ${vm.title}`}>
    <Master src={hollawallMaster} alt="Hollawall template" />
    <span className="commercial-template-semantics">{vm.policy.labels.description} · {vm.policy.labels.quantity} · {vm.policy.labels.unit_price} · {vm.policy.labels.line_total}</span>
    <Watermark status={vm.status} />
    <address className="live-issuer"><strong>{project.company || 'Hollawall'}</strong><span>Profil pembayaran: {document.payment_profile_key || project.issuer_key}</span></address>
    <h2 className="live-title">{vm.title}</h2>
    <section className="live-meta live-meta-left"><b>To</b><span>{project.client_name}</span><b>Project</b><span>{project.name}</span></section>
    <section className="live-meta live-meta-right"><b>Tanggal</b><span>{dateLabel(document.issue_date)}</span><b>Letter No.</b><span>{vm.number ?? '—'}</span><DueOrValidity document={document} /></section>
    {isReceipt(document) ? <ReceiptOverlay {...props} /> : <><div className="live-lines">{vm.totals.lines.slice(0, 4).map((line, index) => <div className="live-line" key={line.id}><b>{index + 1}.</b><span>{line.description}</span><span>{line.quantity} {line.unit}</span><span>{money(line.unit_price)}</span><strong>{money(line.total)}</strong></div>)}</div>{document.project_image_url && <figure className="live-project-image"><img src={document.project_image_url} alt={`Proyek ${project.name}`} /></figure>}<dl className="live-totals"><div><dt>Subtotal</dt><dd>{money(vm.totals.subtotal)}</dd></div>{vm.totals.document_discount > 0 && <div className="discount"><dt>Diskon</dt><dd>−{money(vm.totals.document_discount)}</dd></div>}{vm.totals.tax > 0 && <div><dt>{taxLabel(document)}</dt><dd>{money(vm.totals.tax)}</dd></div>}<div className="grand"><dt>Total</dt><dd>{money(vm.totals.total)}</dd></div></dl>{hasDeposit(document) && <div className="live-deposit"><b>{vm.policy.labels.deposit} {vm.policy.default_deposit_percent}%</b><strong>{money(Math.round(vm.totals.total * vm.policy.default_deposit_percent / 100))}</strong></div>}<section className="live-payment"><p>{document.payment_terms || (isInvoice(document) ? 'Pembayaran sesuai tanggal jatuh tempo yang tercantum.' : `Jika penawaran disetujui, pembayaran awal ${vm.policy.default_deposit_percent}% mengurangi saldo proyek. Penawaran berlaku ${vm.policy.default_validity_days} hari sejak diterbitkan.`)}</p><strong>Payment profile: {document.payment_profile_key || project.issuer_key}</strong></section></>}
    <p className="live-closing">Best regards and thank you,<br /><strong>Hollawall</strong></p>
    <footer className="live-disclaimer">*Revisions beyond the agreed scope may be subject to additional charges.</footer>
  </article>
}

function HojjaPreview(props: ResolvedPreviewProps) {
  const { project, document, vm } = props
  return <article className="project-document-preview brand-document master-document hojja-master-document" data-template="hojja" data-page-size="A4" aria-label={`Pratinjau A4 ${vm.title}`}>
    <Master src={hojjaMaster} alt="HOJJA Art House" />
    <span className="commercial-template-semantics">Description · Qty · Total · Down Payment {vm.policy.default_deposit_percent}%</span>
    <Watermark status={vm.status} />
    <h2 className="live-title">{vm.title}</h2>
    <section className="live-meta live-meta-left"><b>To</b><span>{project.client_name}</span><b>Project</b><span>{project.name}</span></section>
    <section className="live-meta live-meta-right"><b>Date</b><span>{dateLabel(document.issue_date)}</span><b>Letter ID</b><span>{vm.number ?? '—'}</span><DueOrValidity document={document} /></section>
    {isReceipt(document) ? <ReceiptOverlay {...props} /> : <><div className="live-lines">{vm.totals.lines.slice(0, 3).map((line) => <div className="live-line" key={line.id}><span>{line.description}<small>{line.width && line.height ? `(${line.width} × ${line.height} ${line.dimension_unit})` : ''}</small>{hasDeposit(document) && <em>{vm.policy.labels.deposit} {vm.policy.default_deposit_percent}%</em>}</span><span>{line.display_quantity ?? line.quantity}</span><span>{line.original_price && line.original_price > line.unit_price && <><small>Harga awal</small><del>{money(line.original_price)}</del></>}<small>Harga sepakat</small><strong>{money(line.total)}</strong></span></div>)}</div>{document.project_image_url && <figure className="live-project-image"><img src={document.project_image_url} alt={`Reference ${project.name}`} /></figure>}<dl className="live-totals"><div><dt>Subtotal</dt><dd>{money(vm.totals.subtotal)}</dd></div>{vm.totals.document_discount > 0 && <div className="discount"><dt>Diskon</dt><dd>−{money(vm.totals.document_discount)}</dd></div>}{vm.totals.tax > 0 && <div><dt>{taxLabel(document)}</dt><dd>{money(vm.totals.tax)}</dd></div>}<div className="grand"><dt>Total</dt><dd>{money(vm.totals.total)}</dd></div></dl>{hasDeposit(document) && <div className="live-deposit"><b>Total DP :</b><strong>{money(Math.round(vm.totals.total * vm.policy.default_deposit_percent / 100))}</strong></div>}<section className="live-payment"><h3>Payment Information:</h3><ul><li>All prices are stated in Indonesian Rupiah (IDR).</li><li>{document.payment_terms || (isInvoice(document) ? 'Pembayaran sesuai tanggal jatuh tempo yang tercantum.' : 'Revisions beyond the agreed scope may be subject to additional charges.')}</li><li>Payment profile: <strong>{document.payment_profile_key || project.issuer_key}</strong></li></ul></section></>}
  </article>
}

function TexturinSurabayaPreview(props: ResolvedPreviewProps) {
  const { project, document, vm } = props
  return <article className="project-document-preview brand-document master-document texturin-master-document texturin-surabaya-master-document" data-template="texturin-surabaya" data-page-size="A4" aria-label={`Pratinjau A4 ${vm.title} Texturin Surabaya`}>
    <Master src={texturinSurabayaMaster} alt="texturin decorative finishes" />
    <span className="commercial-template-semantics">NO. · DESCRIPTION · PPM · QTY/LUAS · TOTAL · {vm.policy.default_deposit_percent}% signature fee</span>
    <Watermark status={vm.status} />
    <h2 className="live-title">{vm.title}</h2>
    <section className="live-meta live-meta-left"><b>TO</b><span>{project.client_name}</span><b>PROJECT</b><span>{project.name}</span></section>
    <section className="live-meta live-meta-right"><b>NO.</b><span>{vm.number ?? '—'}</span><b>DATE</b><span>{dateLabel(document.issue_date)}</span><DueOrValidity document={document} /></section>
    {isReceipt(document) ? <ReceiptOverlay {...props} /> : <><div className="live-lines">{vm.totals.lines.slice(0, 3).map((line, index) => <div className="live-line" key={line.id}><span>{index + 1}</span><span>{line.description}</span><span>{money(line.unit_price)}</span><span>{line.quantity} {line.unit}</span><strong>{money(line.total)}</strong></div>)}</div>{document.project_image_url && <figure className="live-project-image"><img src={document.project_image_url} alt={`Diagram teknis ${project.name}`} /></figure>}<dl className="live-totals"><div><dt>Subtotal</dt><dd>{money(vm.totals.subtotal)}</dd></div><div className="discount"><dt>Diskon</dt><dd>{vm.totals.document_discount > 0 ? `−${money(vm.totals.document_discount)}` : money(0)}</dd></div>{vm.totals.tax > 0 && <div><dt>{taxLabel(document)}</dt><dd>{money(vm.totals.tax)}</dd></div>}<div className="grand"><dt>Total</dt><dd>{money(vm.totals.total)}</dd></div></dl><section className="live-payment live-terms texturin-terms">{!isInvoice(document) && (vm.policy.default_terms ?? []).map((term) => <p key={term}>{term}</p>)}{document.payment_terms && <p>{document.payment_terms}</p>}{document.notes && <p>{document.notes}</p>}</section><section className="live-bank"><b>BANK DETAILS</b><span>Payment profile: {document.payment_profile_key || project.issuer_key}</span></section>{hasDeposit(document) && <div className="live-deposit"><b>{vm.policy.labels.deposit} {vm.policy.default_deposit_percent}%</b><strong>{money(Math.round(vm.totals.total * vm.policy.default_deposit_percent / 100))}</strong></div>}</>}
    <p className="live-closing"><b>THANK YOU</b><strong>Texturin</strong></p>
  </article>
}

function TexturinBaliPreview(props: ResolvedPreviewProps) {
  const { project, document, vm } = props
  return <article className="project-document-preview brand-document master-document texturin-master-document texturin-bali-master-document" data-template="texturin-bali" data-page-size="A4" aria-label={`Pratinjau A4 ${vm.title} Texturin Bali`}>
    <Master src={texturinBaliMaster} alt="texturin decorative finishes" />
    <span className="commercial-template-semantics">NO. · DESCRIPTION · PPM · AREA (M²) · TOTAL</span>
    <Watermark status={vm.status} />
    <h2 className="live-title">{vm.title}</h2>
    <section className="live-meta live-meta-left"><b>TO</b><span>{project.client_name}</span><b>PROJECT</b><span>{project.name}</span></section>
    <section className="live-meta live-meta-right"><b>NO.</b><span>{vm.number ?? '—'}</span><b>DATE</b><span>{dateLabel(document.issue_date)}</span><DueOrValidity document={document} /></section>
    {isReceipt(document) ? <ReceiptOverlay {...props} /> : <><div className="live-lines">{vm.totals.lines.slice(0, 3).map((line, index) => <div className="live-line" key={line.id}><span>{index + 1}</span><span>{line.description}</span><span>{money(line.unit_price)}</span><span>{line.quantity} {line.unit}</span><strong>{money(line.total)}</strong></div>)}</div><dl className="live-totals"><div><dt>Subtotal</dt><dd>{money(vm.totals.subtotal)}</dd></div>{vm.totals.document_discount > 0 && <div className="discount"><dt>Diskon</dt><dd>−{money(vm.totals.document_discount)}</dd></div>}{vm.totals.tax > 0 && <div><dt>{taxLabel(document)}</dt><dd>{money(vm.totals.tax)}</dd></div>}<div className="grand"><dt>Total</dt><dd>{money(vm.totals.total)}</dd></div></dl></>}
    {!isReceipt(document) && <section className="live-bank"><b>BANK DETAILS</b><span>Payment profile: {document.payment_profile_key || project.issuer_key}</span></section>}
    <p className="live-closing"><b>THANK YOU</b><strong>Texturin</strong></p>
  </article>
}

interface PreviewProps { project: ProjectRecord; document: ProjectDocumentDraft | ProjectDocumentRecord; title?: string }
interface ResolvedPreviewProps extends PreviewProps { vm: CommercialDocumentViewModel }

export default function ProjectDocumentPreview(props: PreviewProps) {
  let vm: CommercialDocumentViewModel
  try {
    vm = buildCommercialDocumentViewModel(props.project, props.document, props.title)
  } catch (reason) {
    const number = 'number' in props.document ? props.document.number : null
    const message = reason instanceof Error ? reason.message : 'Data dokumen tidak valid.'
    return <article className="document-preview-invalid" aria-label="Pratinjau tidak tersedia"><span>{documentTypeLabel(props.document.type)}</span>{number && <b>{number}</b>}<strong>Pratinjau tidak dapat dibuat</strong><p>{message}</p></article>
  }
  const resolved = { ...props, vm }
  if (vm.templateKey === 'hojja') return <HojjaPreview {...resolved} />
  if (vm.templateKey === 'texturin-bali') return <TexturinBaliPreview {...resolved} />
  if (vm.templateKey === 'texturin' || vm.templateKey === 'texturin-surabaya') return <TexturinSurabayaPreview {...resolved} />
  return <HollawallPreview {...resolved} />
}
