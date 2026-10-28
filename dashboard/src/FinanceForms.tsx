import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { X } from 'lucide-react'

import {
  COMPANIES,
  COMPANY_WALLET,
  OFFICE_CATEGORIES,
  PROJECT_STATUSES,
  WALLETS,
  type CompanyId,
  type DebtInput,
  type FinanceDebt,
  type FinanceProject,
  type FinanceTransaction,
  type OfficeCategory,
  type ProjectInput,
  type ProjectStatus,
  type TransactionDirection,
  type TransactionInput,
  type TransactionScope,
  type WalletId,
} from './financeWorkspace'
import { projectStatusLabel } from './financeView'

const today = () => new Date().toISOString().slice(0, 10)

function Modal({ title, copy, onClose, children }: { title: string; copy: string; onClose: () => void; children: ReactNode }) {
  const modalRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const modal = modalRef.current
    const focusable = () => [...(modal?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? [])]
    window.requestAnimationFrame(() => { if (!modal?.contains(document.activeElement)) focusable()[0]?.focus() })
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0]
      const last = items.at(-1)!
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); previous?.focus() }
  }, [onClose])
  return <div className="finance-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose() }}>
    <section ref={modalRef} className="finance-modal" role="dialog" aria-modal="true" aria-labelledby="finance-modal-title">
      <header><div><p className="eyebrow">DATA DEMO</p><h2 id="finance-modal-title">{title}</h2><p>{copy}</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Tutup"><X size={20} /></button></header>
      {children}
    </section>
  </div>
}

function ErrorNote({ error }: { error: string }) {
  return error ? <p className="form-error" role="alert">{error}</p> : null
}

function AmountInput({ value, onChange, label, required = true }: { value: number | null; onChange: (value: number | null) => void; label: string; required?: boolean }) {
  return <label><span>{label}{required && ' *'}</span><input type="number" inputMode="numeric" min="0" step="1" required={required} value={value ?? ''} onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))} /></label>
}

export function ProjectForm({ project, onSave, onClose }: { project?: FinanceProject; onSave: (input: ProjectInput) => void; onClose: () => void }) {
  const submitting = useRef(false)
  const [name, setName] = useState(project?.name ?? '')
  const [company, setCompany] = useState<CompanyId>(project?.company ?? 'Holla')
  const [status, setStatus] = useState<ProjectStatus>(project?.status ?? 'active')
  const [started, setStarted] = useState(project?.started_on ?? today())
  const [completed, setCompleted] = useState(project?.completed_on ?? '')
  const [client, setClient] = useState(project?.client ?? '')
  const [value, setValue] = useState<number | null>(project?.contract_value ?? null)
  const [notes, setNotes] = useState(project?.notes ?? '')
  const [error, setError] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    try { onSave({ name, company, status, started_on: started, completed_on: status === 'completed' ? completed : null, client, contract_value: value, notes }); onClose() } catch (reason) { submitting.current = false; setError(reason instanceof Error ? reason.message : 'Data belum dapat disimpan.') }
  }
  return <Modal title={project ? 'Ubah proyek' : 'Tambah proyek'} copy="Dompet mengikuti perusahaan agar pencatatan tetap konsisten." onClose={onClose}>
    <form className="finance-form" onSubmit={submit}>
      <div className="form-grid"><label className="wide"><span>Nama proyek *</span><input autoFocus required value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label><span>Perusahaan *</span><select value={company} onChange={(event) => setCompany(event.target.value as CompanyId)}>{COMPANIES.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span>Dompet</span><input value={COMPANY_WALLET[company]} readOnly aria-readonly="true" /></label>
        <label><span>Status *</span><select value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>{PROJECT_STATUSES.map((item) => <option value={item} key={item}>{projectStatusLabel(item)}</option>)}</select></label>
        <label><span>Tanggal mulai *</span><input type="date" required value={started} onChange={(event) => setStarted(event.target.value)} /></label>
        {status === 'completed' && <label><span>Tanggal selesai *</span><input type="date" required value={completed} min={started} onChange={(event) => setCompleted(event.target.value)} /></label>}
        <label><span>Klien</span><input value={client} onChange={(event) => setClient(event.target.value)} /></label>
        <AmountInput label="Nilai kontrak" required={false} value={value} onChange={setValue} />
        <label className="wide"><span>Catatan</span><textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label></div>
      <ErrorNote error={error} /><footer><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button className="primary-button">{project ? 'Simpan perubahan' : 'Tambah proyek'}</button></footer>
    </form>
  </Modal>
}

export function TransactionForm({ projects, transaction, initialScope = 'project', onSave, onClose }: { projects: FinanceProject[]; transaction?: FinanceTransaction; initialScope?: TransactionScope; onSave: (input: TransactionInput) => void; onClose: () => void }) {
  const submitting = useRef(false)
  const selectable = projects.filter((project) => project.status !== 'planned')
  const [date, setDate] = useState(transaction?.date ?? today())
  const [scope, setScope] = useState<TransactionScope>(transaction?.scope ?? initialScope)
  const [direction, setDirection] = useState<TransactionDirection>(transaction?.direction ?? 'expense')
  const [projectId, setProjectId] = useState(transaction?.project_id ?? selectable[0]?.id ?? '')
  const [wallet, setWallet] = useState<WalletId>(transaction?.wallet ?? 'CV HB')
  const [category, setCategory] = useState<OfficeCategory>(transaction?.office_category ?? 'Listrik & utilitas')
  const [amount, setAmount] = useState<number | null>(transaction?.amount ?? null)
  const [notes, setNotes] = useState(transaction?.notes ?? '')
  const [error, setError] = useState('')
  useEffect(() => { if (scope === 'office') setDirection('expense') }, [scope])
  const selected = projects.find((project) => project.id === projectId)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    try { onSave({ date, direction, amount: amount ?? 0, scope, wallet, company: null, project_id: scope === 'project' ? projectId : null, office_category: scope === 'office' ? category : null, notes }); onClose() } catch (reason) { submitting.current = false; setError(reason instanceof Error ? reason.message : 'Data belum dapat disimpan.') }
  }
  return <Modal title={transaction ? 'Ubah transaksi' : scope === 'office' ? 'Catat biaya kantor' : 'Tambah transaksi'} copy="Transaksi demo langsung memperbarui seluruh ringkasan dan laporan." onClose={onClose}>
    <form className="finance-form" onSubmit={submit}>
      <div className="scope-selector" role="group" aria-label="Pilih aktivitas"><button type="button" className={scope === 'project' ? 'active' : ''} aria-pressed={scope === 'project'} onClick={() => setScope('project')}>Proyek</button><button type="button" className={scope === 'office' ? 'active' : ''} aria-pressed={scope === 'office'} onClick={() => setScope('office')}>Operasional Kantor</button></div>
      <div className="form-grid"><label><span>Tanggal *</span><input type="date" required value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <label><span>Jenis *</span><select value={direction} disabled={scope === 'office'} onChange={(event) => setDirection(event.target.value as TransactionDirection)}><option value="income">Pemasukan</option><option value="expense">Pengeluaran</option></select></label>
        {scope === 'project' ? <><label className="wide"><span>Proyek *</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{selectable.map((project) => <option value={project.id} key={project.id}>{project.name} · {project.company}</option>)}</select></label><label><span>Perusahaan</span><input readOnly value={selected?.company ?? ''} /></label><label><span>Dompet</span><input readOnly value={selected?.wallet ?? ''} /></label></> : <><label><span>Dompet *</span><select value={wallet} onChange={(event) => setWallet(event.target.value as WalletId)}>{WALLETS.map((item) => <option key={item}>{item}</option>)}</select></label><label><span>Kategori *</span><select value={category} onChange={(event) => setCategory(event.target.value as OfficeCategory)}>{OFFICE_CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label></>}
        <AmountInput label="Jumlah" value={amount} onChange={setAmount} />
        <label className="wide"><span>Keterangan *</span><textarea autoFocus rows={3} required value={notes} onChange={(event) => setNotes(event.target.value)} /></label></div>
      <ErrorNote error={error} /><footer><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button className="primary-button">{transaction ? 'Simpan perubahan' : 'Simpan transaksi'}</button></footer>
    </form>
  </Modal>
}

export function DebtForm({ debt, onSave, onClose }: { debt?: FinanceDebt; onSave: (input: DebtInput) => void; onClose: () => void }) {
  const submitting = useRef(false)
  const [date, setDate] = useState(debt?.date ?? today())
  const [borrower, setBorrower] = useState<WalletId>(debt?.borrower ?? 'TX Bali')
  const [lender, setLender] = useState<WalletId>(debt?.lender ?? 'CV HB')
  const [amount, setAmount] = useState<number | null>(debt?.amount ?? null)
  const [repaid, setRepaid] = useState<number | null>(debt?.repaid ?? 0)
  const [notes, setNotes] = useState(debt?.notes ?? '')
  const [error, setError] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    try { onSave({ date, borrower, lender, amount: amount ?? 0, repaid: repaid ?? 0, notes }); onClose() } catch (reason) { submitting.current = false; setError(reason instanceof Error ? reason.message : 'Data belum dapat disimpan.') }
  }
  return <Modal title={debt ? 'Ubah hutang internal' : 'Tambah hutang internal'} copy="Hutang antar-dompet tidak mengubah kas konsolidasi." onClose={onClose}>
    <form className="finance-form" onSubmit={submit}><div className="form-grid"><label><span>Tanggal *</span><input type="date" required value={date} onChange={(event) => setDate(event.target.value)} /></label><label><span>Dompet peminjam *</span><select value={borrower} onChange={(event) => setBorrower(event.target.value as WalletId)}>{WALLETS.map((item) => <option key={item}>{item}</option>)}</select></label><label><span>Pemberi dana *</span><select value={lender} onChange={(event) => setLender(event.target.value as WalletId)}>{WALLETS.map((item) => <option key={item}>{item}</option>)}</select></label><AmountInput label="Jumlah hutang" value={amount} onChange={setAmount} /><AmountInput label="Sudah dibayar" value={repaid} onChange={setRepaid} /><label className="wide"><span>Keterangan *</span><textarea required rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label></div><ErrorNote error={error} /><footer><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button className="primary-button">Simpan hutang</button></footer></form>
  </Modal>
}
