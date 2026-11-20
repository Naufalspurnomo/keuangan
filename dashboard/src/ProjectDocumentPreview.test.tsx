import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import ProjectDocumentPreview from './ProjectDocumentPreview'
import { createEmptyDocumentDraft, createEmptyProjectDraft, type ProjectDocumentDraft, type ProjectRecord } from './projectDocuments'

const baseProject: ProjectRecord = {
  ...createEmptyProjectDraft('2026-11-03'),
  id: '018f9ca2-355a-4d66-b1d5-4d4be6e2f321',
  name: 'Feature Wall',
  client_name: 'PT Marvell',
  issuer_key: 'hollawall',
  wallet: 'CV HB(101)',
  company: 'HOLLA',
  status: 'active',
  lock_version: 1,
  archived_at: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

function documentFor(project: ProjectRecord, template: 'hollawall' | 'hojja' | 'texturin' | 'texturin-surabaya' | 'texturin-bali', line: ProjectDocumentDraft['lines'][number]) {
  return {
    ...createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03'),
    template_key: template,
    template_version: 'commercial-v3',
    payment_profile_key: project.issuer_key,
    lines: [line],
  }
}

afterEach(cleanup)

describe('ProjectDocumentPreview brand renderers', () => {
  it('renders Hollawall on A5 with area × price/m² and 30% down payment', () => {
    const document = documentFor(baseProject, 'hollawall', {
      id: 'line-hw', description: 'Mural lobby', quantity: '', unit: 'm²', unit_price: 200_000, discount_percent: '0',
      pricing_mode: 'area_rate', width: '3', height: '2', dimension_unit: 'm', area_rounding: 'exact',
    })
    render(<ProjectDocumentPreview project={baseProject} document={document} title="Quotation" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A5 Quotation' })
    expect(page).toHaveAttribute('data-template', 'hollawall')
    expect(page).toHaveTextContent('HARGA/M²')
    expect(page).toHaveTextContent('6 m²')
    expect(page).toHaveTextContent('Rp1.200.000')
    expect(page).toHaveTextContent('Down Payment 30%')
    expect(page).not.toHaveTextContent('Persetujuan klien')
  })

  it('renders Hojja on A4 with artwork quantity, descriptive dimensions, original/agreed pricing, and 50% DP', () => {
    const project = { ...baseProject, issuer_key: 'hojja', company: 'HOJJA' }
    const document = documentFor(project, 'hojja', {
      id: 'line-hojja', description: 'Custom painting', quantity: '1', unit: 'artwork', unit_price: 3_100_000, discount_percent: '0',
      pricing_mode: 'fixed_artwork', display_quantity: '1', width: '2.2', height: '1.4', dimension_unit: 'm', original_price: 3_500_000,
    })
    render(<ProjectDocumentPreview project={project} document={document} title="Quotation" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A4 Quotation' })
    expect(page).toHaveAttribute('data-template', 'hojja')
    expect(within(page).getByAltText('HOJJA Art House')).toBeTruthy()
    expect(page).toHaveTextContent('2.2 × 1.4 m')
    expect(page).toHaveTextContent('Rp3.500.000')
    expect(page).toHaveTextContent('Rp3.100.000')
    expect(page).toHaveTextContent('Total DP')
    expect(page).toHaveTextContent('Rp1.550.000')
  })

  it('fails visibly for invalid legacy data without inventing Rp0', () => {
    const document = documentFor(baseProject, 'hollawall', {
      id: 'invalid', description: '', quantity: '1', unit: 'unit', unit_price: 0, discount_percent: '0', pricing_mode: 'legacy_generic',
    })
    render(<ProjectDocumentPreview project={baseProject} document={document} />)
    const invalid = screen.getByRole('article', { name: 'Pratinjau tidak tersedia' })
    expect(invalid).toHaveTextContent('Pratinjau tidak dapat dibuat')
    expect(invalid).toHaveTextContent('Deskripsi item wajib diisi')
    expect(invalid).not.toHaveTextContent('Rp0')
  })

  it('renders Texturin Surabaya on A4 with PPM, explicit billed area, terms, and signature fee', () => {
    const project = { ...baseProject, issuer_key: 'texturin-surabaya', wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya' }
    const document = documentFor(project, 'texturin-surabaya', {
      id: 'line-texturin', description: 'Lime wash paint', quantity: '', unit: 'm²', unit_price: 250_000, discount_percent: '0',
      pricing_mode: 'ppm_area', width: '5', height: '2.695', dimension_unit: 'm', area_rounding: 'truncate',
    })
    render(<ProjectDocumentPreview project={project} document={document} title="Quotation" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A4 Quotation Texturin Surabaya' })
    expect(page).toHaveAttribute('data-template', 'texturin-surabaya')
    expect(within(page).getByAltText('texturin decorative finishes')).toBeTruthy()
    expect(page).toHaveTextContent('PPM')
    expect(page).toHaveTextContent('13.47 m²')
    expect(page).toHaveTextContent('Rp3.367.500')
    expect(page).toHaveTextContent('30% signature fee')
    expect(page.querySelector('.texturin-terms')).toBeTruthy()
    expect(within(page).getByAltText('Texturin sign-off Evanvun')).toBeTruthy()
  })

  it('keeps a two-item Texturin paper proof complete, aligned, and signed', () => {
    const project = {
      ...baseProject,
      name: 'Gatau',
      client_name: 'GGWP',
      issuer_key: 'texturin-surabaya',
      wallet: 'TX SBY(216)',
      company: 'TEXTURIN-Surabaya',
    }
    const document = documentFor(project, 'texturin-surabaya', {
      id: 'line-land', description: 'Tanah', quantity: '300', unit: 'm²', unit_price: 10_000,
      discount_percent: '0', pricing_mode: 'ppm_area', billed_area_m2: '300',
    })
    document.issue_date = '2026-11-20'
    document.lines.push({
      ...document.lines[0], id: 'line-water', description: 'Air', quantity: '200',
      billed_area_m2: '200', unit_price: 40_000,
    })

    render(<ProjectDocumentPreview project={project} document={document} title="Quotation" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A4 Quotation Texturin Surabaya' })
    expect(page).toHaveTextContent('20 November 2026')
    expect(page).toHaveTextContent('Tanah')
    expect(page).toHaveTextContent('Rp3.000.000')
    expect(page).toHaveTextContent('Air')
    expect(page).toHaveTextContent('Rp8.000.000')
    expect(page).toHaveTextContent('Rp11.000.000')
    const signoff = within(page).getByAltText('Texturin sign-off Evanvun')
    expect(signoff).toHaveClass('texturin-signoff-art')
    expect(page.querySelector('.live-closing')).toContainElement(signoff)
  })

  it('renders Texturin Bali as the reduced invoice-like variant without Surabaya terms or signature-fee band', () => {
    const project = { ...baseProject, issuer_key: 'texturin-bali', wallet: 'TX BALI(087)', company: 'TEXTURIN-Bali' }
    const document = documentFor(project, 'texturin-bali', {
      id: 'line-texturin-bali', description: 'Washpaint', quantity: '', unit: 'm²', unit_price: 200_000, discount_percent: '0',
      pricing_mode: 'ppm_area', width: '3', height: '2', dimension_unit: 'm', area_rounding: 'exact',
    })
    render(<ProjectDocumentPreview project={project} document={document} title="Invoice" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A4 Invoice Texturin Bali' })
    expect(page).toHaveAttribute('data-template', 'texturin-bali')
    expect(page).toHaveTextContent('AREA (M²)')
    expect(page).toHaveTextContent('Rp1.200.000')
    expect(page).toHaveTextContent('BANK DETAILS')
    expect(page.querySelector('.texturin-terms')).toBeNull()
    expect(page.querySelector('.texturin-deposit')).toBeNull()
    expect(within(page).getByAltText('Texturin sign-off Evanvun')).toBeTruthy()
  })

  it('shows every Hojja billed artwork when a document has three lines', () => {
    const project = { ...baseProject, issuer_key: 'hojja', company: 'HOJJA' }
    const document = documentFor(project, 'hojja', {
      id: 'line-1', description: 'Artwork one', quantity: '1', unit: 'artwork', unit_price: 1_000_000, discount_percent: '0', pricing_mode: 'fixed_artwork',
    })
    document.lines = [
      document.lines[0],
      { ...document.lines[0], id: 'line-2', description: 'Artwork two' },
      { ...document.lines[0], id: 'line-3', description: 'Artwork three' },
    ]

    render(<ProjectDocumentPreview project={project} document={document} title="Quotation" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A4 Quotation' })
    expect(page).toHaveTextContent('Artwork one')
    expect(page).toHaveTextContent('Artwork two')
    expect(page).toHaveTextContent('Artwork three')
  })

  it('shows invoice tax and due date without quotation-validity language', () => {
    const document = documentFor(baseProject, 'hollawall', {
      id: 'line-tax', description: 'Mural', quantity: '', unit: 'm²', unit_price: 100_000, discount_percent: '0',
      pricing_mode: 'area_rate', width: '2', height: '1', dimension_unit: 'm', area_rounding: 'exact',
    })
    document.tax_percent = '11'
    document.due_date = '2026-11-10'

    render(<ProjectDocumentPreview project={baseProject} document={document} title="Invoice" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A5 Invoice' })
    expect(page).toHaveTextContent('Jatuh tempo')
    expect(page).toHaveTextContent('10 November 2026')
    expect(page).toHaveTextContent('Pajak 11%')
    expect(page).toHaveTextContent('Rp22.000')
    expect(page).not.toHaveTextContent('Penawaran berlaku')
  })

  it('renders a receipt as acknowledgement without line items, totals breakdown, or deposit request', () => {
    const document = documentFor(baseProject, 'hollawall', {
      id: 'line-receipt', description: 'Pembayaran proyek', quantity: '1', unit: 'unit', unit_price: 200_000, discount_percent: '0', pricing_mode: 'legacy_generic',
    })
    document.type = 'receipt'

    render(<ProjectDocumentPreview project={baseProject} document={document} title="Receipt" />)

    const page = screen.getByRole('article', { name: 'Pratinjau A5 Receipt' })
    expect(page).toHaveTextContent('Telah diterima dari')
    expect(page).not.toHaveTextContent('Pembayaran proyek')
    expect(page.querySelector('.live-totals')).toBeNull()
    expect(page.querySelector('.live-deposit')).toBeNull()
  })
})
