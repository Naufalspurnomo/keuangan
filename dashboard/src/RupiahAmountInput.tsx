import { useRef, useState } from 'react'

const IDR_FORMAT = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 0 })

export function formatIDRAmount(value: number | null) {
  return value === null ? '' : `Rp ${IDR_FORMAT.format(value)}`
}

export function parseIDRAmount(value: string) {
  const digits = value.replace(/\D/g, '')
  if (!digits) return null
  const amount = Number(digits)
  return Number.isSafeInteger(amount) ? amount : undefined
}

export default function RupiahAmountInput({ value, onChange, label, required = true, disabled = false }: {
  value: number | null
  onChange: (value: number | null) => void
  label: string
  required?: boolean
  disabled?: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [unsafeAmount, setUnsafeAmount] = useState(false)
  const handleChange = (raw: string, caret: number | null) => {
    const digitsBeforeCaret = raw.slice(0, caret ?? raw.length).replace(/\D/g, '').length
    const digits = raw.replace(/\D/g, '')
    if (!digits) { setUnsafeAmount(false); onChange(null); return }
    const parsed = parseIDRAmount(digits)
    if (parsed === undefined) { setUnsafeAmount(true); return }
    setUnsafeAmount(false)
    onChange(parsed)
    const formatted = formatIDRAmount(parsed)
    const leadingZeroCount = digits.length - String(parsed).length
    const targetDigitCount = Math.max(0, digitsBeforeCaret - leadingZeroCount)
    let nextCaret = 0
    let seenDigits = 0
    while (nextCaret < formatted.length && seenDigits < targetDigitCount) {
      if (/\d/.test(formatted[nextCaret])) seenDigits += 1
      nextCaret += 1
    }
    if (targetDigitCount === 0) nextCaret = formatted.indexOf('Rp ') + 3
    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(() => inputRef.current?.setSelectionRange(nextCaret, nextCaret))
    }
  }

  return <label><span>{label}{required && ' *'}</span><input
    ref={inputRef}
    aria-label={`${label}${required ? ' *' : ''}`}
    type="text"
    inputMode="numeric"
    autoComplete="off"
    required={required}
    disabled={disabled}
    aria-invalid={unsafeAmount || undefined}
    value={formatIDRAmount(value)}
    placeholder="Rp 0"
    onChange={(event) => handleChange(event.target.value, event.currentTarget.selectionStart)}
  />{unsafeAmount && <small className="form-error" role="alert">Nominal melewati batas Rupiah yang aman untuk disimpan.</small>}</label>
}
