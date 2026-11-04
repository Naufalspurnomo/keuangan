import { X } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { createEmptyProjectDraft, validateProjectDraft, type ProjectDraft, type ProjectRecord } from './projectDocuments'

interface ProjectRecordFormProps {
  project?: ProjectRecord
  saving?: boolean
  onSave: (project: ProjectDraft) => void | Promise<void>
  onClose: () => void
}

export default function ProjectRecordForm({ project, saving = false, onSave, onClose }: ProjectRecordFormProps) {
  const [draft, setDraft] = useState<ProjectDraft>(() => project ? { ...project } : { ...createEmptyProjectDraft(new Date().toISOString().slice(0, 10)), issuer_key: 'cv-holla-berkreasi' })
  const [error, setError] = useState('')
  const change = <K extends keyof ProjectDraft>(key: K, value: ProjectDraft[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setError('')
      await onSave(validateProjectDraft(draft))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Proyek belum dapat disimpan.')
    }
  }
  return <div className="modal-backdrop" role="presentation"><section className="modal-card project-record-form" role="dialog" aria-modal="true" aria-label={project ? 'Ubah proyek' : 'Buat proyek'}>
    <header><div><p className="eyebrow">PROYEK</p><h2>{project ? 'Ubah proyek' : 'Buat proyek baru'}</h2></div><button type="button" className="icon-button" aria-label="Tutup formulir proyek" onClick={onClose}><X size={19} /></button></header>
    <form onSubmit={submit} noValidate>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="document-field-grid">
        <label>Nama proyek<input autoFocus value={draft.name} onChange={(event) => change('name', event.target.value)} /></label>
        <label>Nama klien<input value={draft.client_name} onChange={(event) => change('client_name', event.target.value)} /></label>
        <label>Perusahaan klien<input value={draft.client_company} onChange={(event) => change('client_company', event.target.value)} /></label>
        <label>Kontak klien<input value={draft.client_contact} onChange={(event) => change('client_contact', event.target.value)} /></label>
        {project
          ? <label>Profil penerbit<input value="CV Holla Berkreasi" readOnly aria-readonly="true" /></label>
          : <label>Profil penerbit<select value={draft.issuer_key} onChange={(event) => change('issuer_key', event.target.value)}><option value="cv-holla-berkreasi">CV Holla Berkreasi</option></select></label>}
        <label>Dompet transaksi<input value={draft.wallet} onChange={(event) => change('wallet', event.target.value)} /></label>
        <label>Perusahaan transaksi<input value={draft.company} onChange={(event) => change('company', event.target.value)} /></label>
        <label>Status<select value={draft.status} onChange={(event) => change('status', event.target.value as ProjectDraft['status'])}><option value="planned">Direncanakan</option><option value="active">Aktif</option><option value="completed">Selesai</option><option value="cancelled">Dibatalkan</option></select></label>
        <label>Tanggal mulai<input type="date" value={draft.started_on} onChange={(event) => change('started_on', event.target.value)} /></label>
        {(draft.status === 'completed' || draft.completed_on) && <label>Tanggal selesai<input type="date" value={draft.completed_on ?? ''} onChange={(event) => change('completed_on', event.target.value || null)} /></label>}
      </div>
      <label>Alamat klien<textarea value={draft.client_address} onChange={(event) => change('client_address', event.target.value)} /></label>
      <label>Catatan kontrak<textarea value={draft.contract_notes} onChange={(event) => change('contract_notes', event.target.value)} /></label>
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button type="submit" className="primary-button" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan proyek'}</button></div>
    </form>
  </section></div>
}

export type { ProjectRecordFormProps }
