import { X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'

import type { FinanceDebt, FinanceProject } from './financeWorkspace'
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

export function useModalDialog(onClose: () => void, active = true) {
  const dialogRef = useRef<HTMLElement>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const wasActiveRef = useRef(false)
  if (active && !wasActiveRef.current && typeof document !== 'undefined') {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
  }
  wasActiveRef.current = active
  const closeRef = useRef(onClose)
  closeRef.current = onClose

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
      closeRef.current()
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

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  const dialog = useModalDialog(onClose)
  return <div className="modal-backdrop" role="presentation"><section ref={dialog.dialogRef} onKeyDown={dialog.onKeyDown} className="modal-card" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
    <header><div><p className="eyebrow">HUTANG INTERNAL</p><h2>{title}</h2></div><button type="button" className="icon-button" aria-label="Tutup formulir hutang" onClick={onClose}><X size={19} /></button></header>
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
  const [principal, setPrincipal] = useState('')
  const [occurredOn, setOccurredOn] = useState(new Date().toISOString().slice(0, 10))
  const [dueOn, setDueOn] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setError('')
      const amount = Number(principal)
      if (lender === borrower) throw new Error('Dompet peminjam dan pemberi dana harus berbeda.')
      if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error('Jumlah wajib berupa rupiah bulat lebih dari nol.')
      if (!description.trim()) throw new Error('Keterangan wajib diisi.')
      if (dueOn && dueOn < occurredOn) throw new Error('Jatuh tempo tidak boleh sebelum tanggal pencairan.')
      await onSave({ lender, borrower, projectId: projectId || null, principal: amount, occurredOn, dueOn: dueOn || null, description: description.trim().replace(/\s+/g, ' ') })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Hutang belum dapat disimpan.')
    }
  }
  return <Modal title="Tambah hutang antar-dompet" onClose={onClose}><form onSubmit={submit} noValidate>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="form-grid">
      <label>Dompet pemberi dana<select value={lender} onChange={(event) => setLender(event.target.value)}>{CANONICAL_WALLETS.map((wallet) => <option key={wallet}>{wallet}</option>)}</select></label>
      <label>Dompet peminjam<select value={borrower} onChange={(event) => setBorrower(event.target.value)}>{CANONICAL_WALLETS.map((wallet) => <option key={wallet}>{wallet}</option>)}</select></label>
      <label>Proyek terkait<select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Tanpa proyek</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      <label>Jumlah<input inputMode="numeric" value={principal} onChange={(event) => setPrincipal(event.target.value.replace(/\D/g, ''))} /></label>
      <label>Tanggal pencairan<input type="date" value={occurredOn} onChange={(event) => setOccurredOn(event.target.value)} /></label>
      <label>Jatuh tempo<input type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} /></label>
    </div>
    <label>Keterangan<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button type="submit" className="primary-button" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan hutang'}</button></div>
  </form></Modal>
}

export function CanonicalDebtRepaymentForm({ debt, saving, onSave, onClose }: {
  debt: FinanceDebt
  saving: boolean
  onSave: (amount: number, occurredOn: string, description: string) => Promise<void>
  onClose: () => void
}) {
  const outstanding = debt.amount - debt.repaid
  const [amount, setAmount] = useState(String(outstanding))
  const [occurredOn, setOccurredOn] = useState(new Date().toISOString().slice(0, 10))
  const [description, setDescription] = useState(`Pembayaran ${debt.notes}`)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setError('')
      const value = Number(amount)
      if (!Number.isSafeInteger(value) || value <= 0 || value > outstanding) throw new Error('Pembayaran harus lebih dari nol dan tidak melebihi saldo terbuka.')
      await onSave(value, occurredOn, description.trim().replace(/\s+/g, ' '))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Pembayaran belum dapat disimpan.')
    }
  }
  return <Modal title="Catat pembayaran hutang" onClose={onClose}><form onSubmit={submit} noValidate>
    {error && <p className="form-error" role="alert">{error}</p>}
    <p>Saldo terbuka: <strong>{new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(outstanding)}</strong></p>
    <div className="form-grid"><label>Jumlah pembayaran<input inputMode="numeric" value={amount} onChange={(event) => setAmount(event.target.value.replace(/\D/g, ''))} /></label><label>Tanggal pembayaran<input type="date" value={occurredOn} onChange={(event) => setOccurredOn(event.target.value)} /></label></div>
    <label>Keterangan<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Batal</button><button type="submit" className="primary-button" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan pembayaran'}</button></div>
  </form></Modal>
}
