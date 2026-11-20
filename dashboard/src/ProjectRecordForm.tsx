import { X } from 'lucide-react'
import { useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'

import { useModalDialog } from './CanonicalDebtForms'
import { createEmptyProjectDraft, validateProjectDraft, type ProjectDraft, type ProjectRecord } from './projectDocuments'
import { jakartaToday } from './transactionApi'
import { CANONICAL_WALLETS, CANONICAL_WALLET_COMPANY_PAIRS, canonicalCompaniesForWallet, canonicalIssuerKey } from './transactionMappings'
import { visibleProjectStatus } from './projectStatus'

const DEFAULT_PAIR = CANONICAL_WALLET_COMPANY_PAIRS[0]

interface ProjectRecordFormProps {
  project?: ProjectRecord
  clients?: ProjectRecord[]
  saving?: boolean
  onSave: (project: ProjectDraft) => void | Promise<void>
  onClose: () => void
}

export default function ProjectRecordForm({ project, clients = [], saving = false, onSave, onClose }: ProjectRecordFormProps) {
  const submitting = useRef(false)
  const [pending, setPending] = useState(false)
  const busy = saving || pending
  const close = () => { if (!saving && !submitting.current) onClose() }
  const dialog = useModalDialog(close, true, !busy)
  const [draft, setDraft] = useState<ProjectDraft>(() => project ? { ...project, status: visibleProjectStatus(project.status) } : {
    ...createEmptyProjectDraft(jakartaToday()),
    issuer_key: canonicalIssuerKey(DEFAULT_PAIR.wallet, DEFAULT_PAIR.company),
    wallet: DEFAULT_PAIR.wallet,
    company: DEFAULT_PAIR.company,
  })
  const [error, setError] = useState('')
  const [clientQuery, setClientQuery] = useState(draft.client_name)
  const [clientMenuOpen, setClientMenuOpen] = useState(false)
  const [activeClient, setActiveClient] = useState(0)
  const change = <K extends keyof ProjectDraft>(key: K, value: ProjectDraft[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const companyOptions = canonicalCompaniesForWallet(draft.wallet)
  const changeWallet = (wallet: string) => {
    const company = CANONICAL_WALLET_COMPANY_PAIRS.find((pair) => pair.wallet === wallet)?.company ?? ''
    setDraft((current) => ({ ...current, wallet, company, issuer_key: canonicalIssuerKey(wallet, company) }))
  }
  const changeCompany = (company: string) => setDraft((current) => ({
    ...current,
    company,
    issuer_key: canonicalIssuerKey(current.wallet, company),
  }))
  const clientOptions = [...new Map(clients.filter((item) => item.client_name.trim()).map((item) => [
    [item.client_name, item.client_company, item.client_contact, item.client_address].join('\u0000'), item,
  ])).values()]
  const filteredClients = useMemo(() => {
    const query = clientQuery.trim().toLocaleLowerCase('id-ID')
    if (!query) return []
    return clientOptions.filter((item) => [item.client_name, item.client_company, item.client_contact, item.client_address]
      .some((value) => value.toLocaleLowerCase('id-ID').includes(query))).slice(0, 8)
  }, [clientOptions, clientQuery])
  const reuseClient = (source: ProjectRecord) => {
    if (!source) return
    setClientQuery(source.client_name)
    setClientMenuOpen(false)
    setDraft((current) => ({
      ...current,
      client_name: source.client_name,
      client_company: source.client_company,
      client_contact: source.client_contact,
      client_address: source.client_address,
    }))
  }
  const handleClientKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape' && clientMenuOpen) { event.preventDefault(); event.stopPropagation(); setClientMenuOpen(false); return }
    if (!clientMenuOpen || !filteredClients.length) return
    if (event.key === 'ArrowDown') { event.preventDefault(); setActiveClient((index) => (index + 1) % filteredClients.length) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActiveClient((index) => (index - 1 + filteredClients.length) % filteredClients.length) }
    else if (event.key === 'Enter' && filteredClients[activeClient]) { event.preventDefault(); reuseClient(filteredClients[activeClient]) }
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (saving || submitting.current) return
    submitting.current = true
    setPending(true)
    try {
      setError('')
      await onSave(validateProjectDraft(draft))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Project belum dapat disimpan.')
    } finally { submitting.current = false; setPending(false) }
  }
  return <div className="modal-backdrop" role="presentation"><section ref={dialog.dialogRef} onKeyDown={dialog.onKeyDown} className="modal-card project-record-form" role="dialog" aria-modal="true" aria-label={project ? 'Ubah Project' : 'Buat Project'} tabIndex={-1}>
    <header><div><p className="eyebrow">Project</p><h2>{project ? 'Ubah Project' : 'Buat Project baru'}</h2></div><button type="button" className="icon-button" aria-label="Tutup formulir Project" disabled={busy} onClick={close}><X size={19} /></button></header>
    <form onSubmit={submit} noValidate>
      {error && <p className="form-error" role="alert">{error}</p>}
      <fieldset disabled={busy} style={{ border: 0, margin: 0, padding: 0 }}>
      <div className="document-field-grid">
        <label>Nama Project<input autoFocus value={draft.name} onChange={(event) => change('name', event.target.value)} /></label>
        <label className="client-autocomplete-label">Nama klien<div className="client-autocomplete"><input role="combobox" aria-autocomplete="list" aria-expanded={clientMenuOpen && filteredClients.length > 0} aria-controls="project-client-options" aria-activedescendant={clientMenuOpen && filteredClients[activeClient] ? `project-client-option-${activeClient}` : undefined} autoComplete="off" value={clientQuery} onFocus={() => setClientMenuOpen(true)} onBlur={(event) => { if (!event.currentTarget.parentElement?.contains(event.relatedTarget as Node | null)) setClientMenuOpen(false) }} onKeyDown={handleClientKeyDown} onChange={(event) => { const value = event.target.value; setClientQuery(value); setClientMenuOpen(true); setActiveClient(0); setDraft((current) => ({ ...current, client_name: value, ...(value === current.client_name ? {} : { client_company: '', client_contact: '', client_address: '' }) })) }} />{clientMenuOpen && filteredClients.length > 0 && <ul id="project-client-options" role="listbox">{filteredClients.map((item, index) => <li key={`${item.id}-${index}`}><button id={`project-client-option-${index}`} type="button" role="option" aria-selected={activeClient === index} onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActiveClient(index)} onClick={() => reuseClient(item)}><strong>{item.client_name}</strong><span>{[item.client_company, item.client_contact, item.client_address].filter(Boolean).join(' · ')}</span></button></li>)}</ul>}</div><small className="field-help">Cari klien lama atau masukkan nama baru.</small></label>
        <label>Perusahaan klien<input value={draft.client_company} onChange={(event) => change('client_company', event.target.value)} /></label>
        <label>Kontak klien<input value={draft.client_contact} onChange={(event) => change('client_contact', event.target.value)} /></label>
        <label>Dompet pencatatan<select aria-label="Dompet pencatatan" value={draft.wallet} onChange={(event) => changeWallet(event.target.value)}>{CANONICAL_WALLETS.map((wallet) => <option key={wallet} value={wallet}>{wallet}</option>)}</select><small className="field-help">Dompet sumber seluruh transaksi Project ini.</small></label>
        <label>Unit usaha<select aria-label="Unit usaha" value={draft.company} onChange={(event) => changeCompany(event.target.value)}>{companyOptions.map(({ company }) => <option key={company} value={company}>{company}</option>)}</select><small className="field-help">Hanya unit usaha yang berada di dompet terpilih.</small></label>
        <label>Tanggal mulai<input type="date" value={draft.started_on} onChange={(event) => change('started_on', event.target.value)} /></label>
        {(draft.status === 'completed' || draft.completed_on) && <label>Tanggal selesai<input type="date" value={draft.completed_on ?? ''} onChange={(event) => change('completed_on', event.target.value || null)} /></label>}
      </div>
      <label>Alamat klien<textarea value={draft.client_address} onChange={(event) => change('client_address', event.target.value)} /></label>
      <label>Catatan kontrak<textarea value={draft.contract_notes} onChange={(event) => change('contract_notes', event.target.value)} /></label>
      </fieldset>
      <div className="modal-actions"><button type="button" className="secondary-button" disabled={busy} onClick={close}>Batal</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Menyimpan…' : 'Simpan Project'}</button></div>
    </form>
  </section></div>
}

export type { ProjectRecordFormProps }
