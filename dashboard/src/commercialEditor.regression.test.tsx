import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectDocumentComposer from './ProjectDocumentComposer'
import { createEmptyDocumentDraft, createEmptyProjectDraft, type ProjectRecord } from './projectDocuments'

const project = { ...createEmptyProjectDraft('2026-11-03'), id: '11111111-1111-4111-8111-111111111111', name: 'Lobby', client_name: 'Client', company: 'HOLLA', issuer_key: 'hollawall', status: 'active', lock_version: 1, archived_at: null, created_at: '', updated_at: '' } as ProjectRecord
afterEach(cleanup)
it('saves direct billed area without dimensions or an invented override reason', async () => {
  const save = vi.fn()
  render(<ProjectDocumentComposer project={project} document={createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')} writesEnabled onSave={save} onClose={vi.fn()} />)
  expect(screen.queryByLabelText('Lebar item 1')).toBeNull()
  fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Wall' } })
  fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '2.5' } })
  fireEvent.change(screen.getByLabelText('HARGA/M² item 1'), { target: { value: '100000' } })
  fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
  await waitFor(() => expect(save).toHaveBeenCalled())
  expect(save.mock.calls[0][0].lines[0]).toMatchObject({ billed_area_m2: '2.5', quantity: '2.5', line_total: 250000, width: null, height: null, area_override_reason: null })
})
it('replaces historical dimensions when directly editing billed area', async () => {
  const save = vi.fn()
  const draft = createEmptyDocumentDraft(project.id, 'invoice', '2026-11-03')
  draft.lines[0] = { ...draft.lines[0], description: 'Wall', pricing_mode: 'area_rate', width: '3', height: '2', quantity: '6', billed_area_m2: '6', unit_price: 100000 }
  render(<ProjectDocumentComposer project={project} document={draft} writesEnabled onSave={save} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Luas tagihan item 1 (m²)'), { target: { value: '5.5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1))
  expect(save.mock.calls[0][0].lines[0]).toMatchObject({ quantity: '5.5', billed_area_m2: '5.5', width: null, height: null, line_total: 550000 })
})
it('updates artwork display and billed quantity atomically', async () => {
  const save = vi.fn()
  const p = { ...project, company: 'HOJJA', issuer_key: 'hojja' }
  render(<ProjectDocumentComposer project={p} document={createEmptyDocumentDraft(p.id, 'invoice', '2026-11-03')} writesEnabled onSave={save} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Deskripsi item 1'), { target: { value: 'Artwork' } })
  fireEvent.change(screen.getByLabelText('Jumlah artwork item 1'), { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: 'Simpan draf' }))
  await waitFor(() => expect(save).toHaveBeenCalled())
  expect(save.mock.calls[0][0].lines[0]).toMatchObject({ display_quantity: '3', quantity: '3' })
})
