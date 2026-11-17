import hollawallFooterArt from './assets/hollawall-footer-art.png'
import hollawallLogo from './assets/hollawall-logo-reference.png'
import hojjaLogo from './assets/hojja-logo.png'
import texturinLogo from './assets/texturin-logo.png'
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

function isRecord(document: ProjectDocumentDraft): document is ProjectDocumentRecord {
  return typeof document.id === 'string' && 'status' in document
}

function Watermark({ status }: { status: string }) {
  return status === 'issued' ? null : <span className={`document-watermark ${status}`}>{status === 'draft' ? 'DRAF' : documentStatusLabel(status as ProjectDocumentRecord['status']).toLocaleUpperCase('id-ID')}</span>
}

function Totals({ subtotal, discount, tax, total, discountLabel = 'Diskon' }: { subtotal: number; discount: number; tax: number; total: number; discountLabel?: string }) {
  return <dl className="brand-document-totals">
    <div><dt>Subtotal</dt><dd>{money(subtotal)}</dd></div>
    {discount > 0 && <div className="discount"><dt>{discountLabel}</dt><dd>− {money(discount)}</dd></div>}
    {tax > 0 && <div><dt>Pajak</dt><dd>{money(tax)}</dd></div>}
    <div className="grand-total"><dt>Total</dt><dd>{money(total)}</dd></div>
  </dl>
}

function ReceiptStatement({ project, total, receiver }: { project: ProjectRecord; total: number; receiver: string }) {
  return <section className="brand-receipt-statement"><p>Telah diterima dari <strong>{project.client_name}</strong> untuk pembayaran proyek <strong>{project.name}</strong>.</p><b>{money(total)}</b><small>Diterima oleh</small><strong>{receiver || project.client_name}</strong></section>
}

function HollawallPreview({ project, document, vm }: ResolvedPreviewProps) {
  const status = vm.status
  const dateValue = document.type === 'invoice' ? document.due_date : document.valid_until
  return <article className="project-document-preview brand-document hollawall-document" data-template="hollawall" data-page-size="A5" aria-label={`Pratinjau A5 ${vm.title}`}>
    <Watermark status={status} />
    <div className="hollawall-frame" aria-hidden="true" />
    <header className="hollawall-head"><img src={hollawallLogo} alt="Hollawall" /><p>Making vertical identity, and<br />transform your space ambience<br /><strong>Original visuals<br />Experienced Execution</strong></p><address><strong>CV HOLLA BERKREASI</strong><span>Payment profile: {document.payment_profile_key || project.issuer_key}</span></address></header>
    <h2>{vm.title}</h2>
    <section className="brand-document-meta"><div><b>To</b><span>{project.client_name}</span><b>Project</b><span>{project.name}</span></div><div><b>Tanggal</b><span>{dateLabel(document.issue_date)}</span><b>{document.type === 'invoice' ? 'Jatuh tempo' : 'Berlaku sampai'}</b><span>{dateLabel(dateValue)}</span></div></section>
    {document.type === 'receipt' ? <ReceiptStatement project={project} total={vm.totals.total} receiver={document.client_signatory} /> : <div className="hollawall-table"><div className="table-head"><span /><b>{vm.policy.labels.description}</b><b>{vm.policy.labels.quantity}</b><b>{vm.policy.labels.unit_price}</b><b>{vm.policy.labels.line_total}</b></div>{vm.totals.lines.map((line, index) => <div className="table-row" key={line.id}><b>{index + 1}</b><span>{line.description}</span><span>{line.quantity} {line.unit}</span><span>{money(line.unit_price)}</span><strong>{money(line.total)}</strong></div>)}</div>}
    {document.project_image_url && <figure className="brand-project-media"><img src={document.project_image_url} alt={`Proyek ${project.name}`} /></figure>}
    <section className="hollawall-summary"><Totals subtotal={vm.totals.subtotal} discount={vm.totals.document_discount} tax={vm.totals.tax} total={vm.totals.total} /><div className="deposit-band">{vm.policy.labels.deposit} {vm.policy.default_deposit_percent}% <strong>{money(Math.round(vm.totals.total * vm.policy.default_deposit_percent / 100))}</strong></div></section>
    <section className="hollawall-payment"><i aria-hidden="true" /><div><h3>Payment Information</h3><p>{document.payment_terms || `Pembayaran awal ${vm.policy.default_deposit_percent}% mengurangi saldo proyek. Quotation berlaku ${vm.policy.default_validity_days} hari sejak dikirim.`}</p><strong>Gunakan profil pembayaran terverifikasi: {document.payment_profile_key || project.issuer_key}</strong></div></section>
    <img className="hollawall-footer-art" src={hollawallFooterArt} alt="" />
    <footer>*Revisions beyond the agreed scope may be subject to additional charges.</footer>
  </article>
}

function HojjaPreview({ project, document, vm }: ResolvedPreviewProps) {
  return <article className="project-document-preview brand-document hojja-document" data-template="hojja" data-page-size="A4" aria-label={`Pratinjau A4 ${vm.title}`}>
    <Watermark status={vm.status} /><i className="hojja-left-rule" aria-hidden="true" />
    <header className="hojja-head"><h2>{vm.title}</h2><img src={hojjaLogo} alt="HOJJA Art House" /></header>
    <section className="hojja-meta"><div><b>To:</b><span>{project.client_name}</span><b>Project:</b><span>{project.name}</span></div><div><b>Date:</b><span>{dateLabel(document.issue_date)}</span><b>Letter ID:</b><span>{vm.number ?? 'Diberikan saat dikirim'}</span></div></section>
    {document.type === 'receipt' ? <ReceiptStatement project={project} total={vm.totals.total} receiver={document.client_signatory} /> : <div className="hojja-table"><div className="table-head"><b>{vm.policy.labels.description}</b><b>{vm.policy.labels.quantity}</b><b>{vm.policy.labels.line_total}</b></div>{vm.totals.lines.map((line) => <div className="table-row" key={line.id}><span>{line.description}{line.width && line.height ? <small>({line.width} × {line.height} {line.dimension_unit})</small> : null}</span><span>{line.display_quantity ?? line.quantity}</span><span>{line.original_price && line.original_price > line.unit_price ? <><small>Harga awal</small><del>{money(line.original_price)}</del><small>Harga sepakat</small></> : null}<strong>{money(line.total)}</strong></span></div>)}</div>}
    {document.project_image_url && <figure className="hojja-project-media"><img src={document.project_image_url} alt={`Reference ${project.name}`} /></figure>}
    <section className="hojja-total"><span>{vm.policy.labels.deposit} {vm.policy.default_deposit_percent}% :</span><strong>{money(Math.round(vm.totals.total * vm.policy.default_deposit_percent / 100))}</strong></section>
    <section className="hojja-payment"><h3>Payment Information :</h3><ul><li>All prices are stated in Indonesian Rupiah (IDR).</li><li>{document.payment_terms || 'Revisions beyond the agreed scope may be subject to additional charges.'}</li><li>Payment profile: <strong>{document.payment_profile_key || project.issuer_key}</strong></li></ul></section>
    <footer><strong>HOJJA Arthouse</strong><span>Commercial artwork studio</span></footer>
  </article>
}

function TexturinPreview({ project, document, vm }: ResolvedPreviewProps) {
  return <article className="project-document-preview brand-document texturin-document texturin-surabaya-document" data-template="texturin-surabaya" data-page-size="A4" aria-label={`Pratinjau A4 ${vm.title} Texturin Surabaya`}>
    <Watermark status={vm.status} />
    <header className="texturin-head"><img src={texturinLogo} alt="texturin decorative finishes" /></header>
    <h2>{vm.title}</h2>
    <section className="texturin-meta"><div><b>TO</b><span>{project.client_name}</span><b>PROJECT</b><span>{project.name}</span></div><div><b>NO.</b><span>{vm.number ?? 'Diberikan saat dikirim'}</span><b>DATE</b><span>{dateLabel(document.issue_date)}</span></div></section>
    {document.type === 'receipt' ? <ReceiptStatement project={project} total={vm.totals.total} receiver={document.client_signatory} /> : <div className="texturin-table"><div className="table-head"><b>NO.</b><b>{vm.policy.labels.description}</b><b>{vm.policy.labels.unit_price}</b><b>{vm.policy.labels.quantity}</b><b>{vm.policy.labels.line_total}</b></div>{vm.totals.lines.map((line, index) => <div className="table-row" key={line.id}><span>{index + 1}</span><span>{line.description}</span><span>{money(line.unit_price)}</span><span>{line.quantity} {line.unit}</span><strong>{money(line.total)}</strong></div>)}</div>}
    {document.project_image_url && <figure className="texturin-diagram"><img src={document.project_image_url} alt={`Diagram teknis ${project.name}`} /></figure>}
    <section className="texturin-summary"><Totals subtotal={vm.totals.subtotal} discount={vm.totals.document_discount} tax={vm.totals.tax} total={vm.totals.total} /><div className="texturin-deposit"><span>{vm.policy.labels.deposit} {vm.policy.default_deposit_percent}%</span><strong>{money(Math.round(vm.totals.total * vm.policy.default_deposit_percent / 100))}</strong></div></section>
    <section className="texturin-terms"><p>{document.payment_terms || `Approval requires a ${vm.policy.default_deposit_percent}% ${vm.policy.labels.deposit.toLowerCase()}. Quotation valid ${vm.policy.default_validity_days} days after release.`}</p>{document.notes && <p>{document.notes}</p>}</section>
    <section className="texturin-footer"><div><b>BANK DETAILS</b><span>Payment profile: {document.payment_profile_key || project.issuer_key}</span></div><div><b>THANK YOU</b><strong>Texturin</strong></div></section>
  </article>
}

function TexturinBaliPreview({ project, document, vm }: ResolvedPreviewProps) {
  return <article className="project-document-preview brand-document texturin-document texturin-bali-document" data-template="texturin-bali" data-page-size="A4" aria-label={`Pratinjau A4 ${vm.title} Texturin Bali`}>
    <Watermark status={vm.status} />
    <header className="texturin-head"><img src={texturinLogo} alt="texturin decorative finishes" /></header>
    <h2>{vm.title}</h2>
    <section className="texturin-meta"><div><b>TO</b><span>{project.client_name}</span><b>PROJECT</b><span>{project.name}</span></div><div><b>NO.</b><span>{vm.number ?? 'Diberikan saat dikirim'}</span><b>DATE</b><span>{dateLabel(document.issue_date)}</span></div></section>
    {document.type === 'receipt' ? <ReceiptStatement project={project} total={vm.totals.total} receiver={document.client_signatory} /> : <div className="texturin-table"><div className="table-head"><b>NO.</b><b>{vm.policy.labels.description}</b><b>{vm.policy.labels.unit_price}</b><b>{vm.policy.labels.quantity}</b><b>{vm.policy.labels.line_total}</b></div>{vm.totals.lines.map((line, index) => <div className="table-row" key={line.id}><span>{index + 1}</span><span>{line.description}</span><span>{money(line.unit_price)}</span><span>{line.quantity} {line.unit}</span><strong>{money(line.total)}</strong></div>)}</div>}
    <section className="texturin-bali-total"><span>Total</span><strong>{money(vm.totals.total)}</strong></section>
    <section className="texturin-bali-bank"><b>BANK DETAILS</b><span>Payment profile: {document.payment_profile_key || project.issuer_key}</span></section>
    <section className="texturin-footer"><div /><div><b>THANK YOU</b><strong>Texturin</strong></div></section>
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
    return <article className="document-preview-invalid" aria-label="Pratinjau tidak tersedia">
      <span>{documentTypeLabel(props.document.type)}</span>
      {number && <b>{number}</b>}
      <strong>Pratinjau tidak dapat dibuat</strong>
      <p>{message}</p>
    </article>
  }
  const resolved = { ...props, vm }
  if (vm.templateKey === 'hojja') return <HojjaPreview {...resolved} />
  if (vm.templateKey === 'texturin-bali') return <TexturinBaliPreview {...resolved} />
  if (vm.templateKey === 'texturin' || vm.templateKey === 'texturin-surabaya') return <TexturinPreview {...resolved} />
  return <HollawallPreview {...resolved} />
}
