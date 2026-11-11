import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { X } from 'lucide-react'

import {
  OFFICE_CATEGORIES,
  WALLET_COMPANIES,
  WALLETS,
  type CompanyId,
  type DebtInput,
  type FinanceDebt,
  type FinanceProject,
  type FinanceTransaction,
  type OfficeCategory,
  type ProjectInput,
  type TransactionDirection,
  type TransactionFormInput,
  type TransactionScope,
  type WalletId,
} from './financeWorkspace'
import { projectStatusLabel } from './financeView'
import { CANONICAL_WALLETS, OFFICE_WRITE_CATEGORIES, PROJECT_WRITE_CATEGORIES, canonicalCompaniesForWallet, canonicalPair } from './transactionMappings'

const today = () => new Date().toISOString().slice(0, 10)

export function Modal({ title, copy, onClose, children, live = false }: { title: string; copy: string; onClose: () => void; children: ReactNode; live?: boolean }) {
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
      <header><div>{!live && <p className="eyebrow">DATA DEMO</p>}<h2 id="finance-modal-title">{title}</h2><p>{copy}</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Tutup"><X size={20} /></button></header>
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
  const [wallet, setWallet] = useState<WalletId>(project?.wallet ?? 'CV HB')
  const [started, setStarted] = useState(project?.started_on ?? today())
  const [client, setClient] = useState(project?.client ?? '')
  const [value, setValue] = useState<number | null>(project?.contract_value ?? null)
  const [notes, setNotes] = useState(project?.notes ?? '')
  const [error, setError] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    try { onSave({ name, company, status: project?.status ?? 'active', started_on: started, completed_on: project?.completed_on ?? null, client, contract_value: value, notes }); onClose() } catch (reason) { submitting.current = false; setError(reason instanceof Error ? reason.message : 'Data belum dapat disimpan.') }
  }
  const changeWallet = (nextWallet: WalletId) => {
    setWallet(nextWallet)
    setCompany(WALLET_COMPANIES[nextWallet][0])
  }
  return <Modal title={project ? 'Ubah proyek' : 'Tambah proyek'} copy="Pilih dompet, lalu unit usaha yang memang berada di dalamnya. Proyek baru langsung aktif." onClose={onClose}>
    <form className="finance-form" onSubmit={submit}>
      <div className="form-grid"><label className="wide"><span>Nama proyek *</span><input autoFocus required value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label><span>Dompet pencatatan *</span><select value={wallet} onChange={(event) => changeWallet(event.target.value as WalletId)}>{WALLETS.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span>Unit usaha *</span><select value={company} onChange={(event) => setCompany(event.target.value as CompanyId)}>{WALLET_COMPANIES[wallet].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span>Status proyek</span><input value={project ? projectStatusLabel(project.status) : 'Aktif setelah dibuat'} readOnly aria-readonly="true" /></label>
        <label><span>Tanggal mulai *</span><input type="date" required value={started} onChange={(event) => setStarted(event.target.value)} /></label>
        <label><span>Klien</span><input value={client} onChange={(event) => setClient(event.target.value)} /></label>
        <AmountInput label="Nilai kontrak" required={false} value={value} onChange={setValue} />
        <label className="wide"><span>Catatan</span><textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label></div>
      <ErrorNote error={error} /><footer><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button className="primary-button">{project ? 'Simpan perubahan' : 'Tambah proyek'}</button></footer>
    </form>
  </Modal>
}

export function TransactionForm({ projects, transaction, initialScope = 'project', lockedProjectId, onSave, onClose, liveWrite = false, currentDate }: { projects: FinanceProject[]; transaction?: FinanceTransaction; initialScope?: TransactionScope; lockedProjectId?: string; onSave: (input: TransactionFormInput) => void | Promise<void>; onClose: () => void; liveWrite?: boolean; currentDate?: string }) {
  const submitting = useRef(false)
  const selectable = projects.filter((project) => liveWrite ? project.status === 'active' : project.status !== 'planned')
  const firstProject = selectable[0]
  const lockedProject = projects.find((project) => project.id === lockedProjectId)
  const locked = Boolean(lockedProjectId)
  const projectCreationUnavailable = liveWrite && initialScope === 'project' && !locked && !transaction && !firstProject
  const [date, setDate] = useState(transaction?.date ?? currentDate ?? today())
  const [scope] = useState<TransactionScope>(locked ? 'project' : transaction?.scope ?? initialScope)
  const [direction, setDirection] = useState<TransactionDirection>(transaction?.direction ?? 'expense')
  const [projectId, setProjectId] = useState(lockedProjectId ?? transaction?.project_id ?? firstProject?.id ?? '')
  const [wallet, setWallet] = useState<WalletId>(transaction?.wallet ?? 'CV HB')
  const [writeWallet, setWriteWallet] = useState<string>(CANONICAL_WALLETS[0])
  const [category, setCategory] = useState<OfficeCategory>(transaction?.office_category ?? 'Listrik & utilitas')
  const [writeCategory, setWriteCategory] = useState<string>(initialScope === 'office' ? OFFICE_WRITE_CATEGORIES[0] : PROJECT_WRITE_CATEGORIES[0])
  const [amount, setAmount] = useState<number | null>(transaction?.amount ?? null)
  const [notes, setNotes] = useState(transaction?.notes ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [retryOnly, setRetryOnly] = useState(false)
  useEffect(() => { if (scope === 'office') setDirection('expense') }, [scope])
  const selected = lockedProject ?? projects.find((project) => project.id === projectId)
  useEffect(() => {
    if (locked || selected || !firstProject) return
    setProjectId(firstProject.id)
  }, [firstProject?.id, locked, selected])
  const projectScoped = locked || scope === 'project'
  const projectWritePair = selected?.write_mapping
    ? canonicalPair(selected.write_mapping.wallet, selected.write_mapping.company)
    : undefined
  const officeWritePair = canonicalCompaniesForWallet(writeWallet)[0]
  const writeMappingAvailable = !liveWrite || Boolean(projectScoped ? projectWritePair : officeWritePair)
  const fail = (reason: unknown) => {
    submitting.current = false
    setBusy(false)
    setRetryOnly(Boolean(reason && typeof reason === 'object' && 'uncertain' in reason && reason.uncertain))
    setError(reason instanceof Error ? reason.message : 'Data belum dapat disimpan.')
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    setBusy(true)
    setError('')
    try {
      if (locked && (!lockedProject || (liveWrite ? lockedProject.status !== 'active' : lockedProject.status === 'planned'))) throw new Error('Proyek terkunci tidak tersedia untuk transaksi.')
      if (liveWrite && date !== currentDate) throw new Error('Tanggal transaksi harus tanggal Jakarta hari ini.')
      if (!writeMappingAvailable) throw new Error('Pilihan dompet, perusahaan, dan proyek belum tersedia.')
      const pair = projectScoped ? projectWritePair : officeWritePair
      const result = onSave({
        date,
        direction,
        amount: amount ?? 0,
        scope: projectScoped ? 'project' : 'office',
        wallet: liveWrite ? pair!.wallet : (projectScoped ? selected?.wallet ?? wallet : wallet),
        company: liveWrite ? pair!.company : (projectScoped ? selected?.company ?? null : null),
        project_id: projectScoped ? selected?.id ?? projectId : null,
        office_category: projectScoped ? null : category,
        category: liveWrite ? writeCategory : undefined,
        notes,
      })
      if (result instanceof Promise) result.then(onClose).catch(fail)
      else onClose()
    } catch (reason) { fail(reason) }
  }
  const title = transaction ? `Ubah transaksi${lockedProject ? ` · ${lockedProject.name}` : ''}` : lockedProject ? `Tambah transaksi · ${lockedProject.name}` : scope === 'office' ? 'Catat biaya kantor' : 'Tambah transaksi'
  return <Modal title={title} copy={liveWrite ? 'Periksa kembali rincian transaksi sebelum menyimpan.' : 'Transaksi demo langsung memperbarui seluruh ringkasan dan laporan.'} onClose={onClose} live={liveWrite}>
    <form className="finance-form" onSubmit={submit}>
      <fieldset disabled={busy || retryOnly} style={{ border: 0, margin: 0, padding: 0 }}>
      <div className="form-grid"><label><span>Tanggal *</span><input type="date" required value={date} min={liveWrite ? currentDate : lockedProject?.started_on} max={liveWrite ? currentDate : lockedProject?.completed_on ?? undefined} onChange={(event) => setDate(event.target.value)} />{liveWrite && <small>Wajib tanggal Jakarta hari ini: {currentDate}</small>}</label>
        <label><span>Jenis *</span><select value={direction} disabled={!locked && scope === 'office'} onChange={(event) => setDirection(event.target.value as TransactionDirection)}><option value="income">Pemasukan</option><option value="expense">Pengeluaran</option></select></label>
        {projectScoped ? <>{lockedProject ? <div className="wide locked-project-context" aria-label="Proyek terkunci"><small>Proyek</small><strong>{lockedProject.name}</strong><span>Transaksi mengikuti dompet dan unit usaha proyek.</span></div> : <label className="wide"><span>Proyek *</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{selectable.map((project) => <option value={project.id} key={project.id}>{project.name} · {project.company}</option>)}</select></label>}{liveWrite ? <><label><span>Dompet proyek</span><input aria-label="Dompet proyek" readOnly value={projectWritePair?.wallet ?? ''} /></label><label><span>Unit usaha proyek</span><input aria-label="Unit usaha proyek" readOnly value={projectWritePair?.company ?? ''} /></label></> : <><label><span>Perusahaan</span><input readOnly value={selected?.company ?? ''} /></label><label><span>Dompet</span><input readOnly value={selected?.wallet ?? ''} /></label></>}</> : liveWrite ? <label className="wide"><span>Dompet sumber *</span><select aria-label="Dompet sumber *" value={writeWallet} onChange={(event) => setWriteWallet(event.target.value)}>{CANONICAL_WALLETS.map((item) => <option key={item}>{item}</option>)}</select><small>Biaya kantor terpisah dari proyek; pilih dompet yang membayar.</small></label> : <><label><span>Dompet *</span><select value={wallet} onChange={(event) => setWallet(event.target.value as WalletId)}>{WALLETS.map((item) => <option key={item}>{item}</option>)}</select></label><label><span>Kategori *</span><select value={category} onChange={(event) => setCategory(event.target.value as OfficeCategory)}>{OFFICE_CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label></>}
        {liveWrite && <label><span>Kategori *</span><select value={writeCategory} onChange={(event) => setWriteCategory(event.target.value)}>{((locked || scope === 'project') ? PROJECT_WRITE_CATEGORIES : OFFICE_WRITE_CATEGORIES).map((item) => <option key={item}>{item}</option>)}</select></label>}
        <AmountInput label="Jumlah" value={amount} onChange={setAmount} />
        <label className="wide"><span>Keterangan *</span><textarea autoFocus rows={3} required maxLength={liveWrite ? ((locked || scope === 'project') ? 200 : 150) : undefined} value={notes} onChange={(event) => setNotes(event.target.value)} /></label></div>
      </fieldset>
      {projectCreationUnavailable && <p className="form-guidance" role="status">Belum ada proyek aktif. Buat atau aktifkan proyek sebelum mencatat transaksi proyek.</p>}
      {!writeMappingAvailable && <p className="form-error" role="status">Pencatatan belum tersedia untuk pilihan ini.</p>}
      <ErrorNote error={error} /><footer><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>Batal</button><button className="primary-button" disabled={busy || !writeMappingAvailable}>{busy ? 'Memverifikasi pencatatan…' : retryOnly ? 'Coba lagi permintaan yang sama' : transaction ? 'Simpan perubahan' : 'Simpan transaksi'}</button></footer>
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
