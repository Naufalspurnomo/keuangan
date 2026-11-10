import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectRecordForm from './ProjectRecordForm'

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

  it('keeps unit choices constrained to the selected wallet', () => {
    render(<ProjectRecordForm onSave={vi.fn()} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Dompet pencatatan'), { target: { value: 'TX SBY(216)' } })
    expect(screen.getByLabelText('Unit usaha')).toHaveValue('TEXTURIN-Surabaya')
    expect(screen.getByRole('option', { name: 'TEXTURIN-Surabaya' })).toBeTruthy()
    expect(screen.queryByRole('option', { name: 'HOLLA' })).toBeNull()
  })
})
