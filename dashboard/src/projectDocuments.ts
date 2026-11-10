export const PROJECT_STATUSES = ['planned', 'active', 'completed', 'cancelled'] as const
export const DOCUMENT_TYPES = ['sales_order', 'invoice', 'receipt'] as const
export const DOCUMENT_STATUSES = ['draft', 'issued', 'void', 'superseded'] as const
export const INVOICE_KINDS = ['DP', 'PROGRESS', 'FINAL'] as const

export type ProductionProjectStatus = typeof PROJECT_STATUSES[number]
export type ProjectDocumentType = typeof DOCUMENT_TYPES[number]
export type ProjectDocumentStatus = typeof DOCUMENT_STATUSES[number]
export type InvoiceKind = typeof INVOICE_KINDS[number]
export type ProjectDetailTab = 'transactions' | 'presensi' | 'documents'
export type DocumentDiscountMode = 'none' | 'fixed' | 'percent'

export interface ProjectDocumentCapabilities {
  projectWrites: boolean
  documentWrites: boolean
  transactionCorrections: boolean
  transactionReversals: boolean
}

export const NO_PROJECT_DOCUMENT_WRITES: ProjectDocumentCapabilities = Object.freeze({
  projectWrites: false,
  documentWrites: false,
  transactionCorrections: false,
  transactionReversals: false,
})

export interface ProjectDraft {
  id: string | null
  name: string
  client_name: string
  client_company: string
  client_address: string
  client_contact: string
  issuer_key: string
  wallet: string
  company: string
  status: ProductionProjectStatus
  started_on: string
  completed_on: string | null
  contract_notes: string
}

export interface ProjectRecord extends ProjectDraft {
  id: string
  lock_version: number
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface DocumentLineInput {
  id: string
  description: string
  quantity: string
  unit: string
  unit_price: number
  discount_percent: string
}

export interface ReceiptAllocation {
  transaction_id: string
  source_key: string
  amount: number
  available_amount?: number
  description?: string
  transaction_date?: string
}

export type PaymentStatus = 'UNPAID' | 'PARTIALLY_PAID' | 'PAID'
export type ProjectPaymentStatus = PaymentStatus | 'NOT_CONTRACTED'

export interface InvoicePaymentSummary {
  invoice_id: string
  invoice_kind: InvoiceKind
  official_number: string
  due_date: string | null
  invoice_total: number
  paid_total: number
  outstanding: number
  payment_status: PaymentStatus
}

export interface ProjectQuotation {
  id: string
  project_id: string
  version: number
  canva_url: string
  amount: number
  status: 'draft' | 'sent' | 'revised' | 'accepted' | 'rejected'
  channel: 'whatsapp' | 'phone' | 'email' | 'meeting' | 'other'
  negotiation_notes: string | null
  sent_at: string | null
  decided_at: string | null
  sales_order_id: string | null
  created_at: string
  updated_at: string
  lock_version: number
}

export interface ProjectPaymentSummary {
  project_id: string
  contract_total: number | null
  invoiced_total: number
  unbilled_total: number | null
  paid_total: number
  contract_outstanding: number | null
  overpaid_total: number
  unapplied_total: number
  payment_status: ProjectPaymentStatus
  invoices: InvoicePaymentSummary[]
}

export interface ReceiptOptions {
  invoices: InvoicePaymentSummary[]
  transactions: ReceiptAllocation[]
}

export interface ProjectDocumentDraft {
  id: string | null
  project_id: string
  type: ProjectDocumentType
  invoice_kind: InvoiceKind | null
  applies_to_invoice_id: string | null
  issue_date: string
  due_date: string | null
  valid_until: string | null
  notes: string
  payment_terms: string
  prepared_by: string
  client_signatory: string
  project_image_url: string | null
  lines: DocumentLineInput[]
  discount_mode: DocumentDiscountMode
  discount_value: string
  tax_percent: string
  allocations: ReceiptAllocation[]
}

export interface ProjectDocumentRecord extends ProjectDocumentDraft {
  id: string
  status: ProjectDocumentStatus
  number: string | null
  currency: 'IDR'
  totals: DocumentTotals
  lock_version: number
  revised_from_id: string | null
  superseded_by_id: string | null
  void_reason: string | null
  issued_at: string | null
  created_at: string
  updated_at: string
}

export interface CalculatedDocumentLine extends DocumentLineInput {
  gross: number
  discount: number
  total: number
}

export interface DocumentTotals {
  lines: CalculatedDocumentLine[]
  subtotal: number
  document_discount: number
  taxable_base: number
  tax: number
  total: number
}

export interface ProjectDocumentRoute {
  projectId?: string
  tab: ProjectDetailTab
  document?: string
  type?: ProjectDocumentType
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

export class ProjectDocumentValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ProjectDocumentValidationError'
  }
}

export function createEmptyProjectDraft(today: string): ProjectDraft {
  return {
    id: null,
    name: '',
    client_name: '',
    client_company: '',
    client_address: '',
    client_contact: '',
    issuer_key: '',
    wallet: '',
    company: '',
    status: 'planned',
    started_on: today,
    completed_on: null,
    contract_notes: '',
  }
}

function addUtcDays(date: string, days: number) {
  const parsed = new Date(`${date}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return date
  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}

function lineId() {
  return typeof crypto?.randomUUID === 'function'
    ? crypto.randomUUID()
    : `line-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

export function createEmptyDocumentLine(): DocumentLineInput {
  return { id: lineId(), description: '', quantity: '1', unit: 'unit', unit_price: 0, discount_percent: '0' }
}

export function createEmptyDocumentDraft(projectId: string, type: ProjectDocumentType, today: string): ProjectDocumentDraft {
  return {
    id: null,
    project_id: projectId,
    type,
    invoice_kind: type === 'invoice' ? 'DP' : null,
    applies_to_invoice_id: null,
    issue_date: today,
    due_date: type === 'invoice' ? addUtcDays(today, 7) : null,
    valid_until: type === 'sales_order' ? addUtcDays(today, 14) : null,
    notes: '',
    payment_terms: '',
    prepared_by: '',
    client_signatory: '',
    project_image_url: null,
    lines: type === 'receipt' ? [] : [createEmptyDocumentLine()],
    discount_mode: 'none',
    discount_value: '0',
    tax_percent: '0',
    allocations: [],
  }
}

function cleanText(value: string) {
  return value.trim().replace(/\s+/g, ' ')
}

function validDate(value: string, label: string, optional = false) {
  if (optional && !value) return null
  if (!ISO_DATE.test(value)) throw new ProjectDocumentValidationError(`${label} tidak valid.`)
  const parsed = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new ProjectDocumentValidationError(`${label} tidak valid.`)
  }
  return value
}

export function validateProjectDraft(input: ProjectDraft): ProjectDraft {
  const name = cleanText(input.name)
  const clientName = cleanText(input.client_name)
  const issuerKey = cleanText(input.issuer_key)
  const wallet = cleanText(input.wallet)
  const company = cleanText(input.company)
  if (!name) throw new ProjectDocumentValidationError('Nama proyek wajib diisi.')
  if (!clientName) throw new ProjectDocumentValidationError('Nama klien wajib diisi.')
  if (!issuerKey) throw new ProjectDocumentValidationError('Profil penerbit wajib dipilih.')
  if (!wallet) throw new ProjectDocumentValidationError('Dompet transaksi wajib dipilih.')
  if (!company) throw new ProjectDocumentValidationError('Perusahaan transaksi wajib dipilih.')
  if (!PROJECT_STATUSES.includes(input.status)) throw new ProjectDocumentValidationError('Status proyek tidak valid.')
  const startedOn = validDate(input.started_on, 'Tanggal mulai')!
  const completedOn = validDate(input.completed_on ?? '', 'Tanggal selesai', true)
  if (completedOn && completedOn < startedOn) throw new ProjectDocumentValidationError('Tanggal selesai tidak boleh sebelum tanggal mulai.')
  if (input.status === 'completed' && !completedOn) throw new ProjectDocumentValidationError('Tanggal selesai wajib diisi untuk proyek selesai.')
  return {
    ...input,
    name,
    client_name: clientName,
    client_company: cleanText(input.client_company),
    client_address: input.client_address.trim(),
    client_contact: cleanText(input.client_contact),
    issuer_key: issuerKey,
    wallet,
    company,
    started_on: startedOn,
    completed_on: completedOn,
    contract_notes: input.contract_notes.trim(),
  }
}

interface Decimal {
  numerator: bigint
  scale: bigint
}

function decimal(value: string, label: string): Decimal {
  const normalized = value.trim().replace(',', '.')
  if (!/^\d+(?:\.\d{1,6})?$/.test(normalized)) throw new ProjectDocumentValidationError(`${label} tidak valid.`)
  const [whole, fraction = ''] = normalized.split('.')
  const scale = 10n ** BigInt(fraction.length)
  return { numerator: BigInt(`${whole}${fraction}`), scale }
}

function halfUp(numerator: bigint, denominator: bigint) {
  if (denominator <= 0n || numerator < 0n) throw new ProjectDocumentValidationError('Perhitungan dokumen tidak valid.')
  const rounded = (numerator * 2n + denominator) / (denominator * 2n)
  if (rounded > BigInt(Number.MAX_SAFE_INTEGER)) throw new ProjectDocumentValidationError('Total dokumen melebihi batas aman.')
  return Number(rounded)
}

function percent(value: string, label: string) {
  const parsed = decimal(value, label)
  if (parsed.numerator > 100n * parsed.scale) throw new ProjectDocumentValidationError(`${label} harus antara 0 dan 100.`)
  return parsed
}

function safeMoney(value: number, label: string) {
  if (!Number.isSafeInteger(value) || value < 0) throw new ProjectDocumentValidationError(`${label} harus berupa rupiah bulat positif.`)
  return value
}

function sumMoney(values: number[]) {
  return values.reduce((total, value) => {
    const next = total + value
    if (!Number.isSafeInteger(next)) throw new ProjectDocumentValidationError('Total dokumen melebihi batas aman.')
    return next
  }, 0)
}

export function calculateDocumentTotals(input: ProjectDocumentDraft): DocumentTotals {
  if (input.type === 'receipt') {
    const subtotal = sumMoney(input.allocations.map((allocation) => safeMoney(allocation.amount, 'Alokasi kuitansi')))
    return { lines: [], subtotal, document_discount: 0, taxable_base: subtotal, tax: 0, total: subtotal }
  }
  const lines = input.lines.map((line) => {
    const quantity = decimal(line.quantity, 'Kuantitas')
    const unitPrice = safeMoney(line.unit_price, 'Harga satuan')
    const linePercent = percent(line.discount_percent, 'Diskon item')
    const gross = halfUp(quantity.numerator * BigInt(unitPrice), quantity.scale)
    const discount = halfUp(BigInt(gross) * linePercent.numerator, linePercent.scale * 100n)
    return { ...line, gross, discount, total: gross - discount }
  })
  const subtotal = sumMoney(lines.map((line) => line.total))
  let documentDiscount = 0
  if (input.discount_mode === 'fixed') documentDiscount = safeMoney(Number(input.discount_value), 'Diskon dokumen')
  if (input.discount_mode === 'percent') {
    const discountPercent = percent(input.discount_value, 'Diskon dokumen')
    documentDiscount = halfUp(BigInt(subtotal) * discountPercent.numerator, discountPercent.scale * 100n)
  }
  if (documentDiscount > subtotal) throw new ProjectDocumentValidationError('Diskon dokumen tidak boleh melebihi subtotal.')
  const taxableBase = subtotal - documentDiscount
  const taxPercent = percent(input.tax_percent, 'Pajak')
  const tax = halfUp(BigInt(taxableBase) * taxPercent.numerator, taxPercent.scale * 100n)
  const total = sumMoney([taxableBase, tax])
  return { lines, subtotal, document_discount: documentDiscount, taxable_base: taxableBase, tax, total }
}

export function validateDocumentDraft(input: ProjectDocumentDraft): ProjectDocumentDraft {
  if (!input.project_id) throw new ProjectDocumentValidationError('Identitas proyek wajib tersedia.')
  if (!DOCUMENT_TYPES.includes(input.type)) throw new ProjectDocumentValidationError('Jenis dokumen tidak valid.')
  validDate(input.issue_date, 'Tanggal dokumen')
  if (input.due_date) validDate(input.due_date, 'Jatuh tempo')
  if (input.valid_until) validDate(input.valid_until, 'Berlaku sampai')
  if (input.type === 'invoice' && (!input.invoice_kind || !INVOICE_KINDS.includes(input.invoice_kind))) {
    throw new ProjectDocumentValidationError('Tahap invoice wajib dipilih.')
  }
  if (input.type === 'receipt') {
    if (!input.allocations.length) throw new ProjectDocumentValidationError('Pilih minimal satu transaksi pemasukan terverifikasi.')
    for (const allocation of input.allocations) {
      if (!Number.isSafeInteger(allocation.amount)) throw new ProjectDocumentValidationError('Alokasi kuitansi tidak valid.')
      if (allocation.amount <= 0) throw new ProjectDocumentValidationError('Alokasi kuitansi harus lebih dari nol.')
      if (allocation.available_amount !== undefined) {
        if (!Number.isSafeInteger(allocation.available_amount) || allocation.available_amount < 0) {
          throw new ProjectDocumentValidationError('Nilai transaksi tersedia tidak valid.')
        }
        if (allocation.amount > allocation.available_amount) {
          throw new ProjectDocumentValidationError('Alokasi kuitansi melebihi nilai transaksi tersedia.')
        }
      }
    }
  } else {
    if (!input.lines.length) throw new ProjectDocumentValidationError('Tambahkan minimal satu item.')
    for (const line of input.lines) {
      if (!cleanText(line.description)) throw new ProjectDocumentValidationError('Deskripsi item wajib diisi.')
      if (!cleanText(line.unit)) throw new ProjectDocumentValidationError('Satuan item wajib diisi.')
    }
  }
  const projectImage = input.project_image_url?.trim() || null
  if (projectImage) {
    if (projectImage.length > 196_608) throw new ProjectDocumentValidationError('Gambar proyek terlalu besar.')
    if (!/^data:image\/(?:png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(projectImage)) {
      throw new ProjectDocumentValidationError('Gambar proyek harus berupa data PNG atau JPEG.')
    }
  }
  calculateDocumentTotals(input)
  return {
    ...input,
    notes: input.notes.trim(),
    payment_terms: input.payment_terms.trim(),
    prepared_by: cleanText(input.prepared_by),
    client_signatory: cleanText(input.client_signatory),
    project_image_url: projectImage,
    lines: input.lines.map((line) => ({ ...line, description: cleanText(line.description), unit: cleanText(line.unit) })),
  }
}

function routeType(type?: ProjectDocumentType) {
  return type === 'sales_order' ? 'sales-order' : type
}

function parseRouteType(value: string | null): ProjectDocumentType | undefined {
  const type = value === 'sales-order' ? 'sales_order' : value
  return DOCUMENT_TYPES.includes(type as ProjectDocumentType) ? type as ProjectDocumentType : undefined
}

export function projectDocumentRoute(route: ProjectDocumentRoute) {
  const params = new URLSearchParams()
  if (route.projectId) params.set('project', route.projectId)
  if (route.projectId || route.tab !== 'transactions') params.set('tab', route.tab)
  if (route.document) params.set('document', route.document)
  if (route.type) params.set('type', routeType(route.type)!)
  const query = params.toString()
  return `#projects${query ? `?${query}` : ''}`
}

export function readProjectDocumentRoute(hash = window.location.hash): ProjectDocumentRoute {
  const [page, query = ''] = hash.replace(/^#/, '').split('?')
  if (page !== 'projects') return { tab: 'transactions' }
  const params = new URLSearchParams(query)
  const requestedTab = params.get('tab')
  const tab: ProjectDetailTab = requestedTab === 'presensi' || requestedTab === 'documents' ? requestedTab : 'transactions'
  return {
    projectId: params.get('project') || undefined,
    tab,
    document: params.get('document') || undefined,
    type: parseRouteType(params.get('type')),
  }
}

export function projectStatusLabel(status: ProductionProjectStatus) {
  return status === 'planned' ? 'Direncanakan'
    : status === 'active' ? 'Aktif'
      : status === 'completed' ? 'Selesai'
        : 'Dibatalkan'
}

export function documentTypeLabel(type: ProjectDocumentType) {
  return type === 'sales_order' ? 'Sales Order' : type === 'invoice' ? 'Invoice' : 'Kuitansi'
}

export function documentStatusLabel(status: ProjectDocumentStatus) {
  return status === 'draft' ? 'Draf' : status === 'issued' ? 'Terbit' : status === 'void' ? 'Batal' : 'Digantikan'
}
