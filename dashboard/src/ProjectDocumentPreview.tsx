import hollawallLogo from './assets/hollawall-logo.png'
import {
  calculateDocumentTotals,
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

export default function ProjectDocumentPreview({ project, document }: { project: ProjectRecord; document: ProjectDocumentDraft | ProjectDocumentRecord }) {
  let totals
  try {
    totals = isRecord(document) ? document.totals : calculateDocumentTotals(document)
  } catch {
    totals = { lines: document.lines.map((line) => ({ ...line, gross: 0, discount: 0, total: 0 })), subtotal: 0, document_discount: 0, taxable_base: 0, tax: 0, total: 0 }
  }
  const status = isRecord(document) ? document.status : 'draft'
  const number = isRecord(document) ? document.number : null
  const dateCaption = document.type === 'sales_order' ? 'Berlaku sampai' : document.type === 'invoice' ? 'Jatuh tempo' : 'Tanggal kuitansi'
  const dateValue = document.type === 'sales_order' ? document.valid_until : document.type === 'invoice' ? document.due_date : document.issue_date

  return <article className="project-document-preview" aria-label={`Pratinjau A5 ${documentTypeLabel(document.type)}`}>
    {status !== 'issued' && <span className={`document-watermark ${status}`}>{status === 'draft' ? 'DRAF' : documentStatusLabel(status).toLocaleUpperCase('id-ID')}</span>}
    <header className="document-preview-head">
      <img src={hollawallLogo} alt="Hollawall" />
      <div><small>CV HOLLA BERKREASI</small><strong>{documentTypeLabel(document.type)}</strong><span>{number ?? 'Nomor diberikan saat terbit'}</span></div>
    </header>
    <section className="document-preview-meta" aria-label="Identitas dokumen">
      <div><small>PROYEK</small><strong>{project.name}</strong><span>{project.client_name}{project.client_company ? ` · ${project.client_company}` : ''}</span>{project.client_address && <span>{project.client_address}</span>}{project.client_contact && <span>{project.client_contact}</span>}</div>
      <dl>
        <div><dt>Tanggal</dt><dd>{dateLabel(document.issue_date)}</dd></div>
        <div><dt>{dateCaption}</dt><dd>{dateLabel(dateValue)}</dd></div>
        {document.invoice_kind && <div><dt>Tahap</dt><dd>{document.invoice_kind}</dd></div>}
      </dl>
    </section>
    {document.project_image_url && <figure className="document-project-image"><img src={document.project_image_url} alt={`Proyek ${project.name}`} /><figcaption>Dokumentasi proyek</figcaption></figure>}
    {document.type === 'receipt' ? <section className="document-receipt-copy">
      <p>Telah diterima dari <strong>{project.client_name}</strong> untuk pembayaran proyek <strong>{project.name}</strong>.</p>
      <strong>{money(totals.total)}</strong>
    </section> : <div className="document-preview-table-wrap"><table>
      <thead><tr><th>Deskripsi</th><th>Qty</th><th>Harga</th><th>Total</th></tr></thead>
      <tbody>{totals.lines.map((line) => <tr key={line.id}><td>{line.description || 'Item belum diisi'}<small>{line.discount ? `Diskon ${line.discount_percent}%` : ''}</small></td><td>{line.quantity} {line.unit}</td><td>{money(line.unit_price)}</td><td>{money(line.total)}</td></tr>)}</tbody>
    </table></div>}
    <section className="document-preview-totals" aria-label="Total dokumen">
      <dl>
        <div><dt>Subtotal</dt><dd>{money(totals.subtotal)}</dd></div>
        {totals.document_discount > 0 && <div><dt>Diskon</dt><dd>− {money(totals.document_discount)}</dd></div>}
        {totals.tax > 0 && <div><dt>Pajak {document.tax_percent}%</dt><dd>{money(totals.tax)}</dd></div>}
        <div className="grand-total"><dt>Total</dt><dd>{money(totals.total)}</dd></div>
      </dl>
    </section>
    {(document.notes || document.payment_terms) && <section className="document-preview-notes">
      {document.notes && <div><small>CATATAN</small><p>{document.notes}</p></div>}
      {document.payment_terms && <div><small>SYARAT PEMBAYARAN</small><p>{document.payment_terms}</p></div>}
    </section>}
    <section className="document-preview-signatures" aria-label="Tanda tangan">
      <div><small>Disiapkan oleh</small><span /> <strong>{document.prepared_by || 'Hollawall'}</strong></div>
      <div><small>Persetujuan klien</small><span /> <strong>{document.client_signatory || project.client_name}</strong></div>
    </section>
    <footer><span>Hollawall · {project.id}</span><span>Halaman 1</span></footer>
  </article>
}
