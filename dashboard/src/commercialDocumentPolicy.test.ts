import { describe, expect, it } from 'vitest'

import fixture from '../../config/commercial_document_policies.json'
import { commercialPolicies, commercialPolicy, normalizeCommercialLine } from './commercialDocumentPolicy'

describe('commercial document policy', () => {
  it('matches the cross-runtime canonical policy fixture', () => {
    expect(commercialPolicies).toEqual(fixture)
    expect(commercialPolicy('HOJJA')).toEqual(fixture.hojja)
    expect(commercialPolicy('unknown')).toEqual(fixture.hollawall)
  })

  it('derives Hollawall billed area and canonical money quantity', () => {
    expect(normalizeCommercialLine({
      description: 'Mural indoor kiri', pricing_mode: 'area_rate',
      width: '3.1', height: '2.71', dimension_unit: 'm', unit_price: 650_000,
    }, commercialPolicy('hollawall'))).toMatchObject({
      pricing_mode: 'area_rate', raw_area_m2: '8.401', billed_area_m2: '8.4',
      quantity: '8.4', unit: 'm²', unit_price: 650_000, line_total: 5_460_000,
    })
  })

  it('treats Hojja dimensions as descriptive and agreed price as monetary basis', () => {
    expect(normalizeCommercialLine({
      description: 'Custom painting', pricing_mode: 'fixed_artwork',
      width: '2.2', height: '1.4', dimension_unit: 'm', display_quantity: '2',
      original_price: 3_500_000, unit_price: 3_100_000,
    }, commercialPolicy('hojja'))).toMatchObject({
      pricing_mode: 'fixed_artwork', raw_area_m2: '3.08', display_quantity: '2',
      quantity: '2', unit: 'artwork', original_price: 3_500_000, line_total: 6_200_000,
    })
    expect(() => normalizeCommercialLine({
      description: 'Custom painting', pricing_mode: 'fixed_artwork', quantity: '1',
      original_price: 3_500_000, unit_price: 3_100_000, discount_percent: '10',
    } as Parameters<typeof normalizeCommercialLine>[0], commercialPolicy('hojja'))).toThrow('agreed artwork price')
  })

  it('uses Texturin PPM times half-up billed area, never the erroneous sample total', () => {
    const line = normalizeCommercialLine({
      description: 'Lime Wash Paint', pricing_mode: 'ppm_area',
      width: '5000', height: '2695', dimension_unit: 'mm', unit_price: 250_000,
    }, commercialPolicy('texturin'))
    expect(line).toMatchObject({ raw_area_m2: '13.475', billed_area_m2: '13.48', quantity: '13.48', unit: 'm²', line_total: 3_370_000 })
  })

  it('requires a reason for a billed-area override and rejects precision beyond the contract', () => {
    const base = { description: 'Wall', pricing_mode: 'area_rate' as const, width: '3', height: '2', dimension_unit: 'm' as const, unit_price: 100_000 }
    expect(() => normalizeCommercialLine({ ...base, billed_area_m2: '5.5', area_rounding: 'manual_override' }, commercialPolicy('hollawall'))).toThrow('override reason')
    expect(() => normalizeCommercialLine({ ...base, billed_area_m2: '5.12345', area_rounding: 'manual_override', area_override_reason: 'Site measurement' }, commercialPolicy('hollawall'))).toThrow('four fractional digits')
  })

  it('preserves legacy generic quantity and pricing', () => {
    expect(normalizeCommercialLine({ description: 'Installation', quantity: '2.5', unit: 'ls', unit_price: 1000 }, commercialPolicy('hollawall'))).toMatchObject({
      pricing_mode: 'legacy_generic', quantity: '2.5', unit: 'ls', line_total: 2500,
    })
  })
})
