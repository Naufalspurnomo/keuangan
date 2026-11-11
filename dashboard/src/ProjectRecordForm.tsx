import { X } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { createEmptyProjectDraft, validateProjectDraft, type ProjectDraft, type ProjectRecord } from './projectDocuments'
import { CANONICAL_WALLETS, CANONICAL_WALLET_COMPANY_PAIRS, canonicalCompaniesForWallet } from './transactionMappings'

const PROJECT_ISSUER_KEY = 'hollawall'
const DEFAULT_PAIR = CANONICAL_WALLET_COMPANY_PAIRS[0]

interface ProjectRecordFormProps {
  project?: ProjectRecord
  clients?: ProjectRecord[]
  saving?: boolean
  onSave: (project: ProjectDraft) => void | Promise<void>
  onClose: () => void
}

export default function ProjectRecordForm({ project, clients = [], saving = false, onSave, onClose }: ProjectRecordFormProps) {
  const [draft, setDraft] = useState<ProjectDraft>(() => project ? { ...project } : {
    ...createEmptyProjectDraft(new Date().toISOString().slice(0, 10)),
    issuer_key: PROJECT_ISSUER_KEY,
    wallet: DEFAULT_PAIR.wallet,
    company: DEFAULT_PAIR.company,
  })
  const [error, setError] = useState('')
  const change = <K extends keyof ProjectDraft>(key: K, value: ProjectDraft[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const companyOptions = canonicalCompaniesForWallet(draft.wallet)
  const changeWallet = (wallet: string) => {
    const company = CANONICAL_WALLET_COMPANY_PAIRS.find((pair) => pair.wallet === wallet)?.company ?? ''
    setDraft((current) => ({ ...current, wallet, company }))
  }
  const clientOptions = [...new Map(clients.map((item) => [
    [item.client_name, item.client_company, item.client_contact, item.client_address].join('\u0000'), item,
  ])).values()]
  const reuseClient = (id: string) => {
    const source = clientOptions.find((item) => item.id === id)
    if (!source) return
    setDraft((current) => ({
      ...current,
      client_name: source.client_name,
      client_company: source.client_company,
      client_contact: source.client_contact,
      client_address: source.client_address,
    }))
  }
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
        {!project && clientOptions.length > 0 && <label>Gunakan klien tersimpan<select aria-label="Gunakan klien tersimpan" defaultValue="" onChange={(event) => reuseClient(event.target.value)}><option value="">Pilih dari proyek sebelumnya</option>{clientOptions.map((item) => <option key={item.id} value={item.id}>{item.client_name}{item.client_company ? ` · ${item.client_company}` : ''}</option>)}</select></label>}
        <label>Nama proyek<input autoFocus value={draft.name} onChange={(event) => change('name', event.target.value)} /></label>
        <label>Nama klien<input value={draft.client_name} onChange={(event) => change('client_name', event.target.value)} /></label>
        <label>Perusahaan klien<input value={draft.client_company} onChange={(event) => change('client_company', event.target.value)} /></label>
        <label>Kontak klien<input value={draft.client_contact} onChange={(event) => change('client_contact', event.target.value)} /></label>
        {project
          ? <label>Profil penerbit<input value="CV Holla Berkreasi" readOnly aria-readonly="true" /></label>
          : <label>Profil penerbit<select aria-label="Profil penerbit" value={draft.issuer_key} onChange={(event) => change('issuer_key', event.target.value)}><option value={PROJECT_ISSUER_KEY}>CV Holla Berkreasi</option></select></label>}
        <label>Dompet pencatatan<select aria-label="Dompet pencatatan" value={draft.wallet} onChange={(event) => changeWallet(event.target.value)}>{CANONICAL_WALLETS.map((wallet) => <option key={wallet} value={wallet}>{wallet}</option>)}</select><small className="field-help">Dompet sumber seluruh transaksi proyek ini.</small></label>
        <label>Unit usaha<select aria-label="Unit usaha" value={draft.company} onChange={(event) => change('company', event.target.value)}>{companyOptions.map(({ company }) => <option key={company} value={company}>{company}</option>)}</select><small className="field-help">Hanya unit usaha yang berada di dompet terpilih.</small></label>
        <label>Status proyek<input aria-label="Status proyek" value={project ? (draft.status === 'active' ? 'Aktif' : draft.status === 'completed' ? 'Selesai' : draft.status === 'cancelled' ? 'Dibatalkan' : 'Direncanakan') : 'Aktif setelah dibuat'} readOnly aria-readonly="true" /><small className="field-help">Status diubah dari halaman proyek, bukan saat mengisi identitas.</small></label>
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
