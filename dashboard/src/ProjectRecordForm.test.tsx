import React from 'react'
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
    expect(screen.getByLabelText('Status proyek')).toHaveValue('Aktif setelah dibuat')
    expect(screen.getByText('Dompet sumber seluruh transaksi proyek ini.')).toBeTruthy()
    expect(screen.getByText('Hanya unit usaha yang berada di dompet terpilih.')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Nama proyek'), { target: { value: 'Proyek produksi' } })
    fireEvent.change(screen.getByLabelText('Nama klien'), { target: { value: 'Klien produksi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan proyek' }))

    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      issuer_key: 'hollawall',
      wallet: 'CV HB(101)',
      company: 'HOLLA',
      status: 'active',
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
    expect(screen.queryByRole('option', { name: 'TX SBY' })).toBeNull()
    expect(screen.getByLabelText('Unit usaha').querySelectorAll('option')).toHaveLength(1)
    expect(screen.getByLabelText('Profil penerbit')).toHaveValue('texturin-surabaya')
  })

  it('binds Texturin Bali to its own payment profile', () => {
    render(<ProjectRecordForm onSave={vi.fn()} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Dompet pencatatan'), { target: { value: 'TX BALI(087)' } })
    expect(screen.getByLabelText('Unit usaha')).toHaveValue('TEXTURIN-Bali')
    expect(screen.getByLabelText('Profil penerbit')).toHaveValue('texturin-bali')
  })

  it('offers exactly HOLLA and HOJJA for wallet 101', () => {
    render(<ProjectRecordForm onSave={vi.fn()} onClose={vi.fn()} />)
    const units = screen.getByLabelText('Unit usaha')
    expect([...units.querySelectorAll('option')].map((option) => option.textContent)).toEqual(['HOLLA', 'HOJJA'])
    expect(screen.queryByRole('option', { name: 'CV HB' })).toBeNull()
  })

  it('traps focus, closes on Escape, and returns focus to the opener', async () => {
    function Harness() {
      const [open, setOpen] = React.useState(false)
      return <><button type="button" onClick={() => setOpen(true)}>Buka formulir</button>{open && <ProjectRecordForm onSave={vi.fn()} onClose={() => setOpen(false)} />}</>
    }
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Buka formulir' })
    opener.focus()
    fireEvent.click(opener)

    const dialog = screen.getByRole('dialog', { name: 'Buat proyek' })
    const close = screen.getByRole('button', { name: 'Tutup formulir proyek' })
    const save = screen.getByRole('button', { name: 'Simpan proyek' })
    save.focus()
    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(close).toHaveFocus()

    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(opener).toHaveFocus()
  })
})
