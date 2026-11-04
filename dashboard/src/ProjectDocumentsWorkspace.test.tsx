import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectDocumentsWorkspace from './ProjectDocumentsWorkspace'
import { createEmptyDocumentDraft, createEmptyProjectDraft, type ProjectDocumentRecord, type ProjectRecord } from './projectDocuments'
import type { ProjectDocumentApi, ProjectDocumentSession } from './projectDocumentApi'

const project: ProjectRecord = {
  ...createEmptyProjectDraft('2026-11-03'),
  id: '018f9ca2-355a-4d66-b1d5-4d4be6e2f321',
  name: 'Lobby Marvell',
  client_name: 'PT Marvell',
  issuer_key: 'cv-holla-berkreasi',
  status: 'active',
  wallet: 'CV HB(101)',
  company: 'HOLLA',
  lock_version: 1,
  archived_at: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

const baseDraft = createEmptyDocumentDraft(project.id, 'sales_order', '2026-11-03')
const draft: ProjectDocumentRecord = {
  ...baseDraft,
  id: '22222222-2222-4222-8222-222222222222',
  status: 'draft',
  number: null,
  currency: 'IDR',
  totals: { lines: [], subtotal: 0, document_discount: 0, taxable_base: 0, tax: 0, total: 0 },
  lock_version: 1,
  revised_from_id: null,
  superseded_by_id: null,
  void_reason: null,
  issued_at: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

const issued: ProjectDocumentRecord = {
  ...draft,
  id: '33333333-3333-4333-8333-333333333333',
  type: 'invoice',
  invoice_kind: 'DP',
  status: 'issued',
  number: 'INV/HW/2026/000001',
  lock_version: 2,
  issued_at: '2026-11-03T11:00:00Z',
}

const session: ProjectDocumentSession = {
  csrfToken: 'csrf-token-with-16-chars',
  capabilities: { projectWrites: true, documentWrites: true, transactionCorrections: false, transactionReversals: false },
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function api(overrides: Partial<ProjectDocumentApi> = {}): ProjectDocumentApi {
  const command = (result: ProjectDocumentRecord) => ({ idempotencyKey: 'idem-key-1234567890', payload: {}, submit: vi.fn(async () => result) })
  return {
    listProjects: vi.fn(),
    getProject: vi.fn(),
    createProject: vi.fn(),
    updateProject: vi.fn(),
    setProjectStatus: vi.fn(),
    archiveProject: vi.fn(),
    listDocuments: vi.fn(async () => ({ documents: [draft, issued], capabilities: session.capabilities })),
    getDocument: vi.fn(async () => draft),
    createDocument: vi.fn(() => command(draft)),
    updateDocument: vi.fn(() => command(draft)),
    issueDocument: vi.fn(() => command({ ...draft, status: 'issued', number: 'SO/HW/2026/000001' })),
    voidDocument: vi.fn(() => command({ ...issued, status: 'void', void_reason: 'Nilai keliru' })),
    reviseDocument: vi.fn(() => command({ ...issued, id: '44444444-4444-4444-8444-444444444444', status: 'draft', number: null })),
    downloadDocument: vi.fn(async () => new Blob(['%PDF-'], { type: 'application/pdf' })),
    ...overrides,
  } as ProjectDocumentApi
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ProjectDocumentsWorkspace', () => {
  it('renders loading, empty, error, and retry states', async () => {
    const loading = deferred<Awaited<ReturnType<ProjectDocumentApi['listDocuments']>>>()
    const subject = api({ listDocuments: vi.fn(() => loading.promise) })
    const { rerender } = render(<ProjectDocumentsWorkspace project={project} api={subject} session={session} route={{ tab: 'documents' }} onRouteChange={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent('Memuat dokumen')
    loading.resolve({ documents: [], capabilities: session.capabilities })
    expect(await screen.findByText('Belum ada dokumen tambahan.')).toBeTruthy()
    expect(screen.getByText(/Sales Order dibuat otomatis/)).toBeTruthy()

    const broken = api({ listDocuments: vi.fn(async () => { throw new Error('offline') }) })
    rerender(<ProjectDocumentsWorkspace project={project} api={broken} session={session} route={{ tab: 'documents' }} onRouteChange={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Dokumen belum dapat dimuat')
    fireEvent.click(screen.getByRole('button', { name: 'Coba lagi' }))
    expect(broken.listDocuments).toHaveBeenCalledTimes(2)
  })

  it('lists totals, opens documents, and advertises only real create actions', async () => {
    const onRouteChange = vi.fn()
    render(<ProjectDocumentsWorkspace project={project} api={api()} session={session} route={{ tab: 'documents' }} onRouteChange={onRouteChange} />)
    expect(await screen.findByText('INV/HW/2026/000001')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Buat invoice' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Buat kuitansi' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Sales Order baru/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Buka Sales Order draf' }))
    expect(onRouteChange).toHaveBeenCalledWith(expect.objectContaining({ document: draft.id }))
  })

  it('issues after confirmation, then performs authoritative readback', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const subject = api()
    render(<ProjectDocumentsWorkspace project={project} api={subject} session={session} route={{ tab: 'documents', document: draft.id }} onRouteChange={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'Terbitkan dokumen' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Terbitkan dokumen' }))
    await waitFor(() => expect(subject.issueDocument).toHaveBeenCalledWith(draft.id, 1))
    await waitFor(() => expect(subject.getDocument).toHaveBeenCalledWith(draft.id))
    expect(screen.getByRole('status')).toHaveTextContent('dibaca kembali')
  })

  it('handles issued download, void with reason, and revision', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const createObjectURL = vi.fn(() => 'blob:pdf')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    const subject = api({ getDocument: vi.fn(async () => issued) })
    render(<ProjectDocumentsWorkspace project={project} api={subject} session={session} route={{ tab: 'documents', document: issued.id }} onRouteChange={vi.fn()} />)
    expect(await screen.findByText('INV/HW/2026/000001')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Unduh PDF' }))
    await waitFor(() => expect(subject.downloadDocument).toHaveBeenCalledWith(issued.id))
    fireEvent.click(screen.getByRole('button', { name: 'Buat revisi' }))
    await waitFor(() => expect(subject.reviseDocument).toHaveBeenCalledWith(issued.id, 2))

    fireEvent.click(screen.getByRole('button', { name: 'Batalkan dokumen' }))
    const dialog = screen.getByRole('dialog', { name: 'Batalkan dokumen' })
    fireEvent.change(within(dialog).getByLabelText('Alasan pembatalan'), { target: { value: 'Nilai tagihan keliru' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Konfirmasi pembatalan' }))
    await waitFor(() => expect(subject.voidDocument).toHaveBeenCalledWith(issued.id, 'Nilai tagihan keliru', 2))
  })

  it('shows write-disabled, stale conflict, and uncertain retry states without inventing success', async () => {
    const disabled = { ...session, capabilities: { ...session.capabilities, documentWrites: false } }
    const subject = api()
    const { rerender } = render(<ProjectDocumentsWorkspace project={project} api={subject} session={disabled} route={{ tab: 'documents', document: draft.id }} onRouteChange={vi.fn()} />)
    expect(await screen.findByText('Perubahan dokumen belum diaktifkan.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Terbitkan dokumen' })).toBeDisabled()

    const staleCommand = { idempotencyKey: 'idem-key-1234567890', payload: {}, submit: vi.fn(async () => { throw Object.assign(new Error('versi berubah'), { stale: true }) }) }
    const staleApi = api({ issueDocument: vi.fn(() => staleCommand) })
    rerender(<ProjectDocumentsWorkspace project={project} api={staleApi} session={session} route={{ tab: 'documents', document: draft.id }} onRouteChange={vi.fn()} />)
    await screen.findByRole('button', { name: 'Terbitkan dokumen' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Terbitkan dokumen' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Data berubah di server')
    expect(staleApi.getDocument).toHaveBeenCalledWith(draft.id)

    const uncertainCommand = { idempotencyKey: 'idem-key-1234567890', payload: {}, submit: vi.fn(async () => { throw Object.assign(new Error('belum pasti'), { uncertain: true, retryable: true }) }) }
    const uncertainApi = api({ issueDocument: vi.fn(() => uncertainCommand) })
    rerender(<ProjectDocumentsWorkspace project={project} api={uncertainApi} session={session} route={{ tab: 'documents', document: draft.id }} onRouteChange={vi.fn()} />)
    await screen.findByRole('button', { name: 'Terbitkan dokumen' })
    fireEvent.click(screen.getByRole('button', { name: 'Terbitkan dokumen' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('belum pasti')
    fireEvent.click(screen.getByRole('button', { name: 'Ulangi permintaan yang sama' }))
    await waitFor(() => expect(uncertainCommand.submit).toHaveBeenCalledTimes(2))
  })
})
