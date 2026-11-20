import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectRecordForm from './ProjectRecordForm'
import { CanonicalDebtCreateForm, CanonicalDebtRepaymentForm } from './CanonicalDebtForms'
import { TransactionForm } from './FinanceForms'
import { seedFinanceWorkspace } from './financeWorkspace'
import { createEmptyProjectDraft, type ProjectRecord } from './projectDocuments'

afterEach(cleanup)

it('locks project dismissal and fields until the single pending submission settles', async () => {
  let reject!: (error: Error) => void
  const save = vi.fn(() => new Promise<void>((_, fail) => { reject = fail }))
  const close = vi.fn()
  render(<ProjectRecordForm onSave={save} onClose={close} />)
  fireEvent.change(screen.getByLabelText('Nama Project'), { target: { value: 'Reliable' } })
  fireEvent.change(screen.getByRole('combobox', { name: /Nama klien/ }), { target: { value: 'Client' } })
  const form = screen.getByRole('button', { name: 'Simpan Project' }).closest('form')!
  fireEvent.submit(form); fireEvent.submit(form)
  expect(save).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText('Nama Project')).toBeDisabled()
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  fireEvent.click(screen.getByRole('button', { name: 'Tutup formulir Project' }))
  fireEvent.mouseDown(screen.getByRole('dialog').parentElement!)
  expect(close).not.toHaveBeenCalled()
  reject(new Error('Try again'))
  await waitFor(() => expect(screen.getByLabelText('Nama Project')).not.toBeDisabled())
})

it('closes suggestions on blur and consumes Escape before closing the project dialog', () => {
  const close = vi.fn()
  const client = { ...createEmptyProjectDraft('2026-01-01'), id: 'client', client_name: 'Client' } as ProjectRecord
  render(<ProjectRecordForm clients={[client]} onSave={vi.fn()} onClose={close} />)
  const input = screen.getByRole('combobox', { name: /Nama klien/ })
  fireEvent.change(input, { target: { value: 'Cli' } })
  expect(screen.getByRole('listbox')).toBeTruthy()
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(close).not.toHaveBeenCalled()
  expect(screen.queryByRole('listbox')).toBeNull()
  fireEvent.focus(input); fireEvent.blur(input)
  expect(screen.queryByRole('listbox')).toBeNull()
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(close).toHaveBeenCalledTimes(1)
})

it.each(['create', 'repay'])('locks %s debt submission, dismissal and formatted amounts', (kind) => {
  const close = vi.fn()
  const save = vi.fn(() => new Promise<void>(() => {}))
  if (kind === 'create') render(<CanonicalDebtCreateForm projects={[]} saving={false} onSave={save} onClose={close} />)
  else render(<CanonicalDebtRepaymentForm debt={seedFinanceWorkspace().debts[0]} saving={false} onSave={save} onClose={close} />)
  const amount = screen.getByLabelText(kind === 'create' ? 'Jumlah *' : 'Jumlah pembayaran *')
  fireEvent.change(amount, { target: { value: '1000' } })
  expect(amount).toHaveValue('Rp 1.000')
  fireEvent.change(screen.getByLabelText('Keterangan'), { target: { value: 'Debt test' } })
  const form = amount.closest('form')!
  fireEvent.submit(form); fireEvent.submit(form)
  expect(save).toHaveBeenCalledTimes(1)
  expect(amount).toBeDisabled()
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  fireEvent.click(screen.getByRole('button', { name: 'Tutup formulir hutang' }))
  expect(close).not.toHaveBeenCalled()
})

it('blocks all transaction dismissal paths while saving', () => {
  const close = vi.fn()
  const save = vi.fn(() => new Promise<void>(() => {}))
  render(<TransactionForm projects={seedFinanceWorkspace().projects} onSave={save} onClose={close} />)
  fireEvent.submit(screen.getByRole('button', { name: 'Simpan transaksi' }).closest('form')!)
  fireEvent.keyDown(document, { key: 'Escape' })
  fireEvent.click(screen.getByRole('button', { name: 'Tutup' }))
  fireEvent.mouseDown(screen.getByRole('dialog').parentElement!)
  expect(close).not.toHaveBeenCalled()
})
