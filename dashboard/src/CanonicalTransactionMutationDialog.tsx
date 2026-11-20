import { useState, type FormEvent } from 'react'

import { Modal } from './FinanceForms'
import type { FinanceTransaction } from './financeWorkspace'
import RupiahAmountInput from './RupiahAmountInput'
import { OFFICE_WRITE_CATEGORIES, PROJECT_EXPENSE_WRITE_CATEGORIES, PROJECT_INCOME_WRITE_CATEGORIES } from './transactionMappings'

export interface TransactionMutationDraft {
  reason: string
  amount?: number
  occurredAt?: string
  description?: string
  category?: string
}

export default function CanonicalTransactionMutationDialog({ row, action, saving, onSubmit, onClose }: {
  row: FinanceTransaction
  action: 'correction' | 'reversal'

  saving: boolean
  onSubmit: (draft: TransactionMutationDraft) => Promise<void>
  onClose: () => void
}) {
  const initialCategory = row.category ?? row.office_category ?? ''
  const categoryOptions: string[] = row.scope === 'office'
    ? [...OFFICE_WRITE_CATEGORIES]
    : row.direction === 'income' ? [...PROJECT_INCOME_WRITE_CATEGORIES] : [...PROJECT_EXPENSE_WRITE_CATEGORIES]
  if (initialCategory && !categoryOptions.includes(initialCategory)) categoryOptions.unshift(initialCategory)
  const [amount, setAmount] = useState<number | null>(row.amount)
  const [date, setDate] = useState(row.date)
  const [description, setDescription] = useState(row.notes)
  const [category, setCategory] = useState(initialCategory || categoryOptions[0] || '')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (saving) return
    const cleanReason = reason.trim()
    if (!cleanReason) { setError('Alasan wajib diisi.'); return }
    if (action === 'reversal') {
      try { setError(''); await onSubmit({ reason: cleanReason }) }
      catch (problem) { setError(problem instanceof Error ? problem.message : 'Pembalikan belum dapat dipastikan.') }
      return
    }
    if (amount === null || !description.trim() || !category) { setError('Nominal, keterangan, dan kategori wajib diisi.'); return }

    if (amount === row.amount && date === row.date && description.trim() === row.notes && category === initialCategory) {
      setError('Ubah setidaknya satu nilai sebelum menyimpan koreksi.')
      return
    }
    const occurredAt = date === row.date ? undefined : `${date}T00:00:00+07:00`
    try {
      setError('')
      await onSubmit({
        reason: cleanReason,
        ...(amount === row.amount ? {} : { amount }),
        ...(occurredAt ? { date, occurredAt } : {}),
        ...(description.trim() === row.notes ? {} : { description: description.trim() }),
        ...(category === initialCategory ? {} : { category }),
      })
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Koreksi belum dapat dipastikan.') }
  }

  return <Modal
    live
    title={action === 'correction' ? 'Koreksi transaksi' : 'Balik transaksi'}
      copy={action === 'correction' ? `Lingkup ${row.scope === 'project' ? 'Project' : 'Operasional kantor'} · ${row.notes}` : `Efek kas transaksi ${row.notes} akan dinetralkan. Riwayat tetap tersimpan.`}
    onClose={onClose}
  >
    <form className="finance-form" onSubmit={submit} aria-busy={saving}>
      {action === 'correction' && <fieldset disabled={saving} className="transaction-correction-fields"><div className="form-grid">
        <label><span>Tanggal transaksi *</span><input type="date" required value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <RupiahAmountInput label="Jumlah" value={amount} onChange={setAmount} disabled={saving} />
        <label><span>Kategori *</span><select required value={category} onChange={(event) => setCategory(event.target.value)}>{categoryOptions.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
        <label className="wide"><span>Keterangan *</span><textarea required maxLength={200} rows={3} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      </div></fieldset>}
      {action === 'reversal' && <p className="form-guidance">Pembalikan membuat event penyeimbang dan mempertahankan catatan transaksi asli.</p>}
      <label className="mutation-reason"><span>Alasan {action === 'correction' ? 'koreksi' : 'pembalikan'} *</span><textarea required maxLength={300} rows={3} value={reason} disabled={saving} onChange={(event) => setReason(event.target.value)} /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <footer><button type="button" className="secondary-button" onClick={onClose} disabled={saving}>Batal</button><button type="submit" className={action === 'correction' ? 'primary-button' : 'primary-button danger'} disabled={saving}>{saving ? 'Menyimpan perubahan…' : action === 'correction' ? 'Simpan koreksi' : 'Konfirmasi pembalikan'}</button></footer>
    </form>
  </Modal>
}
