import { X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'

import RupiahAmountInput from './RupiahAmountInput'
import type { FinanceDebt, FinanceProject } from './financeWorkspace'
import { jakartaToday } from './transactionApi'
import { CANONICAL_WALLETS } from './transactionMappings'

export interface CanonicalDebtCreateInput {
  lender: string
  borrower: string
  projectId: string | null
  principal: number
  occurredOn: string
  dueOn: string | null
  description: string
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function useModalDialog(onClose: () => void, active = true, dismissible = true) {
  const dialogRef = useRef<HTMLElement>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const wasActiveRef = useRef(false)
  if (active && !wasActiveRef.current && typeof document !== 'undefined') {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
  }
  wasActiveRef.current = active
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const dismissibleRef = useRef(dismissible)
  dismissibleRef.current = dismissible

  useEffect(() => {
    if (!active) return
    const frame = window.requestAnimationFrame(() => {
      const dialog = dialogRef.current
      const target = dialog?.querySelector<HTMLElement>('[autofocus]') ?? dialog?.querySelector<HTMLElement>(FOCUSABLE)
      target?.focus()
    })
    return () => {
      window.cancelAnimationFrame(frame)
      const opener = openerRef.current
      window.queueMicrotask(() => { if (opener?.isConnected) opener.focus() })
    }
  }, [active])

  const onKeyDown = useCallback((event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      if (dismissibleRef.current) closeRef.current()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])]
      .filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true')
    if (!focusable.length) { event.preventDefault(); dialogRef.current?.focus(); return }
    const first = focusable[0]
    const last = focusable.at(-1)!
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }, [])

  return { dialogRef, onKeyDown }
}

function Modal({ title, children, onClose, busy = false }: { title: string; children: React.ReactNode; onClose: () => void; busy?: boolean }) {
  const dialog = useModalDialog(onClose, true, !busy)
  return <div className="modal-backdrop" role="presentation"><section ref={dialog.dialogRef} onKeyDown={dialog.onKeyDown} className="modal-card" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
    <header><div><p className="eyebrow">HUTANG INTERNAL</p><h2>{title}</h2></div><button type="button" className="icon-button" aria-label="Tutup formulir hutang" disabled={busy} onClick={onClose}><X size={19} /></button></header>
    {children}
  </section></div>
}

export function CanonicalDebtCreateForm({ projects, saving, initialProjectId = null, initialBorrower = CANONICAL_WALLETS[1], onSave, onClose }: {
  projects: FinanceProject[]
  saving: boolean
  initialProjectId?: string | null
  initialBorrower?: string
  onSave: (input: CanonicalDebtCreateInput) => Promise<void>
  onClose: () => void
}) {
  const [lender, setLender] = useState<string>(CANONICAL_WALLETS[0])
  const [borrower, setBorrower] = useState<string>(initialBorrower)
  const [projectId, setProjectId] = useState(initialProjectId ?? '')
  const [principal, setPrincipal] = useState<number | null>(null)
  const [occurredOn, setOccurredOn] = useState(jakartaToday())
  const [dueOn, setDueOn] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const submitting = useRef(false)
  const [pending, setPending] = useState(false)
  const busy = saving || pending
  const close = () => { if (!saving && !submitting.current) onClose() }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (saving || submitting.current) return
    submitting.current = true
    setPending(true)
    try {
      setError('')
      const amount = principal ?? 0
      if (lender === borrower) throw new Error('Dompet peminjam dan pemberi dana harus berbeda.')
      if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error('Jumlah wajib berupa rupiah bulat lebih dari nol.')
      if (!description.trim()) throw new Error('Keterangan wajib diisi.')
      if (dueOn && dueOn < occurredOn) throw new Error('Jatuh tempo tidak boleh sebelum tanggal pencairan.')
      await onSave({ lender, borrower, projectId: projectId || null, principal: amount, occurredOn, dueOn: dueOn || null, description: description.trim().replace(/\s+/g, ' ') })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Hutang belum dapat disimpan.')
    } finally { submitting.current = false; setPending(false) }
  }
  return <Modal title="Tambah hutang antar-dompet" busy={busy} onClose={close}><form onSubmit={submit} noValidate>
    {error && <p className="form-error" role="alert">{error}</p>}
    <fieldset disabled={busy} style={{ border: 0, margin: 0, padding: 0 }}>
    <div className="form-grid">
      <label>Dompet pemberi dana<select value={lender} onChange={(event) => setLender(event.target.value)}>{CANONICAL_WALLETS.map((wallet) => <option key={wallet}>{wallet}</option>)}</select></label>
      <label>Dompet peminjam<select value={borrower} onChange={(event) => setBorrower(event.target.value)}>{CANONICAL_WALLETS.map((wallet) => <option key={wallet}>{wallet}</option>)}</select></label>
      <label>Project terkait<select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Tanpa Project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      <RupiahAmountInput label="Jumlah" value={principal} onChange={setPrincipal} />
      <label>Tanggal pencairan<input type="date" value={occurredOn} onChange={(event) => setOccurredOn(event.target.value)} /></label>
      <label>Jatuh tempo<input type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} /></label>
    </div>
    <label>Keterangan<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    </fieldset>
    <div className="modal-actions"><button type="button" className="secondary-button" disabled={busy} onClick={close}>Batal</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Menyimpan…' : 'Simpan hutang'}</button></div>
  </form></Modal>
}

export function CanonicalDebtRepaymentForm({ debt, saving, onSave, onClose }: {
  debt: FinanceDebt
  saving: boolean
  onSave: (amount: number, occurredOn: string, description: string) => Promise<void>
  onClose: () => void
}) {
  const outstanding = debt.amount - debt.repaid
  const [amount, setAmount] = useState<number | null>(outstanding)
  const [occurredOn, setOccurredOn] = useState(jakartaToday())
  const [description, setDescription] = useState(`Pembayaran ${debt.notes}`)
  const [error, setError] = useState('')
  const submitting = useRef(false)
  const [pending, setPending] = useState(false)
  const busy = saving || pending
  const close = () => { if (!saving && !submitting.current) onClose() }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (saving || submitting.current) return
    submitting.current = true
    setPending(true)
    try {
      setError('')
      const value = amount ?? 0
      if (!Number.isSafeInteger(value) || value <= 0 || value > outstanding) throw new Error('Pembayaran harus lebih dari nol dan tidak melebihi saldo terbuka.')
      await onSave(value, occurredOn, description.trim().replace(/\s+/g, ' '))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Pembayaran belum dapat disimpan.')
    } finally { submitting.current = false; setPending(false) }
  }
  return <Modal title="Catat pembayaran hutang" busy={busy} onClose={close}><form onSubmit={submit} noValidate>
    {error && <p className="form-error" role="alert">{error}</p>}
    <p>Saldo terbuka: <strong>{new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(outstanding)}</strong></p>
    <fieldset disabled={busy} style={{ border: 0, margin: 0, padding: 0 }}>
    <div className="form-grid"><RupiahAmountInput label="Jumlah pembayaran" value={amount} onChange={setAmount} /><label>Tanggal pembayaran<input type="date" value={occurredOn} onChange={(event) => setOccurredOn(event.target.value)} /></label></div>
    <label>Keterangan<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    </fieldset>
    <div className="modal-actions"><button type="button" className="secondary-button" disabled={busy} onClick={close}>Batal</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Menyimpan…' : 'Simpan pembayaran'}</button></div>
  </form></Modal>
}
