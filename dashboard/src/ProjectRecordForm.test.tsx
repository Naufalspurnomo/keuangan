import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectRecordForm from './ProjectRecordForm'
import { createEmptyProjectDraft, type ProjectRecord } from './projectDocuments'

afterEach(cleanup)

describe('ProjectRecordForm', () => {
  it('submits the canonical production issuer and an explicit wallet/company pair', async () => {
    const onSave = vi.fn(async () => undefined)
    render(<ProjectRecordForm onSave={onSave} onClose={vi.fn()} />)

    expect(screen.getByLabelText('Profil penerbit')).toHaveValue('hollawall')
    expect(screen.getByLabelText('Dompet pencatatan')).toHaveValue('CV HB(101)')
    expect(screen.getByLabelText('Unit usaha')).toHaveValue('HOLLA')
    expect(screen.getByText('Sheet/dompet tempat transaksi proyek dicatat.')).toBeTruthy()
    expect(screen.getByText('Perusahaan atau brand pemilik transaksi di dompet tersebut.')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Nama proyek'), { target: { value: 'Proyek produksi' } })
    fireEvent.change(screen.getByLabelText('Nama klien'), { target: { value: 'Klien produksi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan proyek' }))

    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      issuer_key: 'hollawall',
      wallet: 'CV HB(101)',
      company: 'HOLLA',
    })))
  })

  it('reuses a historical client without changing project wallet or issuer', () => {
    const client = {
      ...createEmptyProjectDraft('2026-10-01'), id: '11111111-1111-4111-8111-111111111111',
      name: 'Proyek lama', client_name: 'Ibu Naufal', client_company: 'PT Klien',
      client_contact: '0812000000', client_address: 'Surabaya', issuer_key: 'hollawall',
      wallet: 'CV HB(101)', company: 'HOLLA', status: 'completed', lock_version: 2,
      archived_at: null, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
    } as ProjectRecord
    render(<ProjectRecordForm clients={[client]} onSave={vi.fn()} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Gunakan klien tersimpan'), { target: { value: client.id } })
    expect(screen.getByLabelText('Nama klien')).toHaveValue('Ibu Naufal')
    expect(screen.getByLabelText('Perusahaan klien')).toHaveValue('PT Klien')
    expect(screen.getByLabelText('Kontak klien')).toHaveValue('0812000000')
    expect(screen.getByLabelText('Dompet pencatatan')).toHaveValue('CV HB(101)')
  })

  it('keeps unit choices constrained to the selected wallet', () => {
    render(<ProjectRecordForm onSave={vi.fn()} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Dompet pencatatan'), { target: { value: 'TX SBY(216)' } })
    expect(screen.getByLabelText('Unit usaha')).toHaveValue('TEXTURIN-Surabaya')
    expect(screen.getByRole('option', { name: 'TEXTURIN-Surabaya' })).toBeTruthy()
    expect(screen.queryByRole('option', { name: 'HOLLA' })).toBeNull()
  })
})
