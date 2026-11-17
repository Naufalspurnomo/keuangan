import { commercialPolicy, normalizeCommercialLine, type CommercialPolicy, type TemplateKey } from './commercialDocumentPolicy'
import {
  calculateDocumentTotals,
  documentTypeLabel,
  type DocumentTotals,
  type ProjectDocumentDraft,
  type ProjectDocumentRecord,
  type ProjectQuotationLine,
  type ProjectRecord,
} from './projectDocuments'

export interface CommercialDocumentViewModel {
  templateKey: TemplateKey
  policy: CommercialPolicy
  pageSize: 'A4' | 'A5'
  brandName: string
  legalName: string
  title: string
  number: string | null
  status: string
  lines: ProjectQuotationLine[]
  totals: DocumentTotals
}

const BRAND_NAMES: Record<TemplateKey, string> = {
  hollawall: 'Hollawall',
  hojja: 'HOJJA Arthouse',
  texturin: 'texturin',
  'texturin-surabaya': 'texturin Surabaya',
  'texturin-bali': 'texturin Bali',
}

const LEGAL_NAMES: Record<TemplateKey, string> = {
  hollawall: 'CV Holla Berkreasi',
  hojja: 'CV Holla Berkreasi',
  texturin: 'Texturin Decorative Finishes',
  'texturin-surabaya': 'Texturin Decorative Finishes Surabaya',
  'texturin-bali': 'Texturin Decorative Finishes Bali',
}

export function projectTemplateKey(project: ProjectRecord, explicit = ''): TemplateKey {
  return commercialPolicy(explicit || project.company || project.wallet || project.issuer_key).template_key
}

export function normalizeCommercialLines(project: ProjectRecord, lines: ProjectQuotationLine[], explicit = '') {
  const policy = commercialPolicy(projectTemplateKey(project, explicit))
  return lines.map((line) => normalizeCommercialLine(line, policy))
}

export function buildCommercialDocumentViewModel(
  project: ProjectRecord,
  document: ProjectDocumentDraft | ProjectDocumentRecord,
  title?: string,
): CommercialDocumentViewModel {
  const templateKey = projectTemplateKey(project, document.template_key)
  const policy = commercialPolicy(templateKey)
  const normalized = document.type === 'receipt'
    ? document.lines.map((line) => ({ ...line }))
    : document.lines.map((line) => normalizeCommercialLine(line, policy))
  const normalizedDocument = { ...document, lines: normalized }
  const totals = 'totals' in document ? document.totals : calculateDocumentTotals(normalizedDocument)
  return {
    templateKey,
    policy,
    pageSize: policy.page_size,
    brandName: BRAND_NAMES[templateKey],
    legalName: LEGAL_NAMES[templateKey],
    title: title ?? documentTypeLabel(document.type),
    number: 'number' in document ? document.number : null,
    status: 'status' in document ? document.status : 'draft',
    lines: normalized,
    totals,
  }
}
