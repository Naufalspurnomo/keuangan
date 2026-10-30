import { useRef, useState, type FormEvent } from 'react'

import { Modal } from './FinanceForms'
import type { FinanceProject, ProjectInput } from './financeWorkspace'

const today = () => {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export default function ProjectCompleteDialog({ project, onSave, onClose }: {
  project: FinanceProject
  onSave: (input: ProjectInput) => void
  onClose: () => void
}) {
  const submitting = useRef(false)
  const [completedOn, setCompletedOn] = useState(today)
  const [error, setError] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current) return
    if (!completedOn || completedOn < project.started_on) {
      setError('Tanggal selesai tidak boleh sebelum tanggal mulai proyek.')
      return
    }
    submitting.current = true
    try {
      onSave({
        name: project.name,
        company: project.company,
        status: 'completed',
        started_on: project.started_on,
        completed_on: completedOn,
        client: project.client,
        contract_value: project.contract_value,
        notes: project.notes,
      })
      onClose()
    } catch (reason) {
      submitting.current = false
      setError(reason instanceof Error ? reason.message : 'Proyek belum dapat diselesaikan.')
    }
  }

  return <Modal title={`Selesaikan ${project.name}`} copy="Tetapkan tanggal penyelesaian proyek. Data transaksi tetap tersimpan." onClose={onClose}>
    <form className="finance-form project-complete-form" onSubmit={submit} noValidate>
      <label><span>Tanggal selesai *</span><input autoFocus type="date" required min={project.started_on} value={completedOn} onChange={(event) => { setCompletedOn(event.target.value); setError('') }} /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <footer><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button className="primary-button">Selesaikan proyek</button></footer>
    </form>
  </Modal>
}
