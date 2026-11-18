import policiesFixture from '../../config/commercial_document_policies.json'
import { ProjectDocumentValidationError } from './projectDocuments'

export type TemplateKey = 'hollawall' | 'hojja' | 'texturin' | 'texturin-surabaya' | 'texturin-bali'
export type PricingMode = 'area_rate' | 'ppm_area' | 'fixed_artwork' | 'fixed_fee' | 'legacy_generic'
export type DimensionUnit = 'mm' | 'cm' | 'm'
export type AreaRounding = 'exact' | 'half_up' | 'truncate' | 'manual_override'

export const COMMERCIAL_META_FIELDS = [
  'pricing_mode', 'width', 'height', 'dimension_unit', 'raw_area_m2',
  'billed_area_m2', 'area_rounding', 'area_override_reason',
  'display_quantity', 'original_price', 'asset_ref',
] as const

export interface CommercialPolicy {
  template_key: TemplateKey
  template_version: string
  pricing_mode: Exclude<PricingMode, 'fixed_fee' | 'legacy_generic'>
  page_size: 'A4' | 'A5'
  default_deposit_percent: number
  default_validity_days: number
  default_terms?: string[]
  labels: { description: string; quantity: string; unit_price: string; line_total: string; deposit: string }
}

export interface CommercialLineInput {
  description: string
  pricing_mode?: PricingMode
  quantity?: string
  unit?: string
  unit_price: number
  width?: string | null
  height?: string | null
  dimension_unit?: DimensionUnit | null
  raw_area_m2?: string | null
  billed_area_m2?: string | null
  area_rounding?: AreaRounding | null
  area_override_reason?: string | null
  display_quantity?: string | null
  original_price?: number | null
  discount_percent?: string | number | null
  line_discount_percent?: string | number | null
}

export interface NormalizedCommercialLine extends CommercialLineInput {
  pricing_mode: PricingMode
  quantity: string
  unit: string
  line_total: number
}

export const commercialPolicies = policiesFixture as Record<TemplateKey, CommercialPolicy>

function canonicalTemplateKey(value: string): TemplateKey {
  const text = value.trim().toLowerCase()
  if (text.includes('hojja')) return 'hojja'
  if (text.includes('bali') || text.includes('tx bali')) return 'texturin-bali'
  if (text.includes('surabaya') || text.includes('tx sby')) return 'texturin-surabaya'
  if (text.includes('texturin') || text.startsWith('tx ')) return 'texturin'
  return 'hollawall'
}

export function commercialPolicy(templateKey: string): CommercialPolicy {
  return commercialPolicies[canonicalTemplateKey(templateKey)]
}

interface Rational { numerator: bigint; scale: bigint; digits: number }

function rational(value: unknown, field: string, maxFractionalDigits: number): Rational {
  const text = String(value ?? '').trim().replace(',', '.')
  if (!/^\d+(?:\.\d+)?$/.test(text)) throw new ProjectDocumentValidationError(`${field} tidak valid.`)
  const [whole, fraction = ''] = text.split('.')
  if (fraction.length > maxFractionalDigits) {
    const limit = maxFractionalDigits === 4 ? 'four' : 'eight'
    throw new ProjectDocumentValidationError(`${field} supports at most ${limit} fractional digits.`)
  }
  const numerator = BigInt(`${whole}${fraction}`)
  if (numerator <= 0n) throw new ProjectDocumentValidationError(`${field} harus lebih dari nol.`)
  return { numerator, scale: 10n ** BigInt(fraction.length), digits: fraction.length }
}

function gcd(left: bigint, right: bigint): bigint {
  let a = left < 0n ? -left : left
  let b = right < 0n ? -right : right
  while (b) [a, b] = [b, a % b]
  return a
}

function multiply(left: Rational, right: Rational): Rational {
  const numerator = left.numerator * right.numerator
  const scale = left.scale * right.scale
  const divisor = gcd(numerator, scale)
  return { numerator: numerator / divisor, scale: scale / divisor, digits: left.digits + right.digits }
}

function unitFactor(unit: DimensionUnit): Rational {
  if (unit === 'm') return { numerator: 1n, scale: 1n, digits: 0 }
  if (unit === 'cm') return { numerator: 1n, scale: 100n, digits: 2 }
  return { numerator: 1n, scale: 1000n, digits: 3 }
}

function area(width: unknown, height: unknown, unit: DimensionUnit): Rational {
  return multiply(multiply(rational(width, 'width', 8), unitFactor(unit)), multiply(rational(height, 'height', 8), unitFactor(unit)))
}

function decimalText(value: Rational, maxDigits = 8): string {
  const whole = value.numerator / value.scale
  let remainder = value.numerator % value.scale
  if (!remainder) return whole.toString()
  let fraction = ''
  for (let index = 0; index < maxDigits && remainder; index += 1) {
    remainder *= 10n
    fraction += (remainder / value.scale).toString()
    remainder %= value.scale
  }
  return `${whole}.${fraction}`.replace(/0+$/, '')
}

function roundTo(value: Rational, digits: number, mode: 'half_up' | 'truncate'): Rational {
  const targetScale = 10n ** BigInt(digits)
  const scaled = value.numerator * targetScale
  let result = scaled / value.scale
  const remainder = scaled % value.scale
  if (mode === 'half_up' && remainder * 2n >= value.scale) result += 1n
  return { numerator: result, scale: targetScale, digits }
}

function integerMoney(value: number, field: string) {
  if (!Number.isSafeInteger(value) || value < 0) throw new ProjectDocumentValidationError(`${field} harus berupa rupiah bulat positif.`)
  return value
}

function lineTotal(quantity: Rational, unitPrice: number) {
  const numerator = quantity.numerator * BigInt(unitPrice)
  const rounded = (numerator * 2n + quantity.scale) / (quantity.scale * 2n)
  if (rounded > BigInt(Number.MAX_SAFE_INTEGER)) throw new ProjectDocumentValidationError('Total item melebihi batas aman.')
  return Number(rounded)
}

export function normalizeCommercialLine<T extends CommercialLineInput>(raw: T, policy: CommercialPolicy): NormalizedCommercialLine & T {
  const description = raw.description.trim()
  if (!description) throw new ProjectDocumentValidationError('Deskripsi item wajib diisi.')
  const pricingMode = raw.pricing_mode ?? 'legacy_generic'
  if (pricingMode !== 'legacy_generic' && pricingMode !== policy.pricing_mode) {
    throw new ProjectDocumentValidationError('pricing_mode conflicts with template policy.')
  }
  const unitPrice = integerMoney(raw.unit_price, 'Harga')
  const normalized = {
    ...raw, description, pricing_mode: pricingMode, quantity: '', unit: '', unit_price: unitPrice, line_total: 0,
  } as NormalizedCommercialLine & T
  let rawArea: Rational | null = null
  if (raw.width || raw.height) {
    if (!raw.width || !raw.height) throw new ProjectDocumentValidationError('width and height must be supplied together.')
    rawArea = area(raw.width, raw.height, raw.dimension_unit ?? 'm')
    normalized.raw_area_m2 = decimalText(rawArea)
  }
  let moneyQuantity: Rational
  if (pricingMode === 'area_rate' || pricingMode === 'ppm_area') {
    if (!rawArea && !raw.billed_area_m2) throw new ProjectDocumentValidationError('area dimensions or billed_area_m2 are required.')
    const rounding = raw.area_rounding ?? 'half_up'
    let billed: Rational
    if (rounding === 'manual_override') {
      if (!raw.area_override_reason?.trim()) throw new ProjectDocumentValidationError('manual area override reason is required.')
      billed = rational(raw.billed_area_m2, 'billed_area_m2', 4)
      normalized.area_override_reason = raw.area_override_reason.trim()
    } else if (raw.billed_area_m2) {
      billed = rational(raw.billed_area_m2, 'billed_area_m2', 4)
      if (rawArea) {
        const target = roundTo(rawArea, rounding === 'exact' ? 4 : 2, rounding === 'truncate' ? 'truncate' : 'half_up')
        if (billed.numerator * target.scale !== target.numerator * billed.scale) throw new ProjectDocumentValidationError('billed_area_m2 disagrees with dimensions and rounding policy.')
      }
    } else {
      billed = roundTo(rawArea!, rounding === 'exact' ? 4 : 2, rounding === 'truncate' ? 'truncate' : 'half_up')
    }
    normalized.area_rounding = rounding
    normalized.billed_area_m2 = decimalText(billed, 4)
    normalized.quantity = decimalText(billed, 4)
    normalized.unit = 'm²'
    moneyQuantity = billed
  } else if (pricingMode === 'fixed_artwork') {
    const lineDiscount = Number(raw.line_discount_percent ?? raw.discount_percent ?? 0)
    if (!Number.isFinite(lineDiscount) || lineDiscount !== 0) {
      throw new ProjectDocumentValidationError('An agreed artwork price cannot receive a second line discount.')
    }
    moneyQuantity = rational(raw.display_quantity ?? raw.quantity ?? '1', 'display_quantity', 4)
    if (moneyQuantity.numerator % moneyQuantity.scale) throw new ProjectDocumentValidationError('display_quantity must be a whole artwork count.')
    if (raw.original_price != null) {
      normalized.original_price = integerMoney(raw.original_price, 'original_price')
      if (normalized.original_price < unitPrice) throw new ProjectDocumentValidationError('original_price must not be below agreed price.')
    }
    normalized.display_quantity = decimalText(moneyQuantity, 4)
    normalized.quantity = normalized.display_quantity
    normalized.unit = 'artwork'
  } else {
    moneyQuantity = rational(raw.quantity ?? '1', 'quantity', 4)
    normalized.quantity = decimalText(moneyQuantity, 4)
    normalized.unit = raw.unit?.trim() || 'unit'
  }
  normalized.line_total = lineTotal(moneyQuantity, unitPrice)
  return normalized
}
