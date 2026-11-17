import React from 'react'
import ReactDOM from 'react-dom/client'
import ProjectDocumentPreview from '../../src/ProjectDocumentPreview'
import { createEmptyDocumentDraft, createEmptyProjectDraft, type ProjectDocumentDraft, type ProjectRecord } from '../../src/projectDocuments'
import '../../src/styles.css'
import '../../src/style.css'
import '../../src/finance-workspace-v2.css'

function project(issuer_key: string, company: string): ProjectRecord {
  return {
    ...createEmptyProjectDraft('2026-11-17'), id: `${issuer_key}-visual-project`, name: company.includes('Bali') ? 'Feature Wall Bali' : 'Feature Wall Surabaya',
    client_name: 'PT Marvell Indonesia', client_company: 'PT Marvell Indonesia', client_address: 'Surabaya', client_contact: '+62 812 0000 0000',
    issuer_key, company, wallet: 'Test wallet', status: 'active', lock_version: 1, archived_at: null,
    created_at: '2026-11-17T00:00:00Z', updated_at: '2026-11-17T00:00:00Z',
  }
}

function doc(p: ProjectRecord, template: 'hollawall' | 'hojja' | 'texturin-surabaya' | 'texturin-bali', line: ProjectDocumentDraft['lines'][number]) {
  return {
    ...createEmptyDocumentDraft(p.id, 'invoice', '2026-11-17'), template_key: template, template_version: 'commercial-v3', payment_profile_key: p.issuer_key,
    due_date: '2026-11-24', payment_terms: 'Pembayaran menggunakan profil rekening terverifikasi.', notes: 'Harga termasuk instalasi sesuai scope.', lines: [line],
  }
}

const cases = [
  { label: 'Hollawall A5', title: 'Quotation', p: project('hollawall', 'HOLLA'), d: doc(project('hollawall', 'HOLLA'), 'hollawall', { id: 'hw', description: 'Mural lobby premium', quantity: '', unit: 'm²', unit_price: 200_000, discount_percent: '0', pricing_mode: 'area_rate', width: '3', height: '2', dimension_unit: 'm', area_rounding: 'exact' }) },
  { label: 'HOJJA A4', title: 'Quotation', p: project('hojja', 'HOJJA'), d: doc(project('hojja', 'HOJJA'), 'hojja', { id: 'hj', description: 'Custom botanical painting', quantity: '1', unit: 'artwork', unit_price: 3_100_000, discount_percent: '0', pricing_mode: 'fixed_artwork', display_quantity: '1', width: '2.2', height: '1.4', dimension_unit: 'm', original_price: 3_500_000 }) },
  { label: 'Texturin Surabaya A4', title: 'Quotation', p: project('texturin-surabaya', 'TEXTURIN-Surabaya'), d: doc(project('texturin-surabaya', 'TEXTURIN-Surabaya'), 'texturin-surabaya', { id: 'tx-sby', description: 'Lime wash decorative finish', quantity: '', unit: 'm²', unit_price: 250_000, discount_percent: '0', pricing_mode: 'ppm_area', width: '5', height: '2.695', dimension_unit: 'm', area_rounding: 'truncate' }) },
  { label: 'Texturin Bali A4', title: 'Invoice', p: project('texturin-bali', 'TEXTURIN-Bali'), d: doc(project('texturin-bali', 'TEXTURIN-Bali'), 'texturin-bali', { id: 'tx-bali', description: 'Washpaint', quantity: '', unit: 'm²', unit_price: 200_000, discount_percent: '0', pricing_mode: 'ppm_area', width: '3', height: '2', dimension_unit: 'm', area_rounding: 'exact' }) },
]

ReactDOM.createRoot(document.getElementById('root')!).render(<main className="visual-grid">{cases.map(({ label, title, p, d }) => <section className="visual-case" key={label}><h1>{label}</h1><div className="visual-page"><ProjectDocumentPreview project={p} document={d} title={title} /></div></section>)}</main>)
