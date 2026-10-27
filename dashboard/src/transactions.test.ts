import { describe, expect, it } from 'vitest'
import { filterTransactions, transactionsToCsv } from './transactions'
import type { Transaction } from './types'

const rows: Transaction[] = [
  { id: 1, source_key: 'WA-001|1', transaction_date: '2026-09-02', transaction_type: 'Pemasukan', amount: 5_000_000, wallet: 'CV HB(101)', company: 'Hollawall', project: 'Mural Hotel', notes: 'Termin kedua' },
  { id: 2, source_key: 'TG-002|1', transaction_date: '2026-09-01', transaction_type: 'Pengeluaran', amount: 750_000, wallet: 'TX SBY(216)', company: 'Texturin Surabaya', project: 'Kafe Juanda', notes: 'Beli cat biru' },
]

describe('transaction tools', () => {
  it('searches across notes, project, wallet, company, and source key', () => {
    expect(filterTransactions(rows, 'cat biru', 'all').map((row) => row.id)).toEqual([2])
    expect(filterTransactions(rows, 'mural hotel', 'all').map((row) => row.id)).toEqual([1])
    expect(filterTransactions(rows, 'TX SBY', 'all').map((row) => row.id)).toEqual([2])
    expect(filterTransactions(rows, 'Hollawall', 'all').map((row) => row.id)).toEqual([1])
    expect(filterTransactions(rows, 'WA-001', 'all').map((row) => row.id)).toEqual([1])
  })

  it('filters transaction type without mutating source rows', () => {
    const original = structuredClone(rows)
    expect(filterTransactions(rows, '', 'Pemasukan').map((row) => row.id)).toEqual([1])
    expect(filterTransactions(rows, '', 'Pengeluaran').map((row) => row.id)).toEqual([2])
    expect(rows).toEqual(original)
  })

  it('opens one exact project identity instead of substring matches', () => {
    const ambiguous: Transaction[] = [
      { ...rows[0], id: 10, project: 'Villa A', company: 'HOLLA', notes: 'exact Hollawall' },
      { ...rows[0], id: 11, project: 'Villa AB', company: 'HOLLA', notes: 'prefix collision' },
      { ...rows[0], id: 12, project: 'Villa A', company: 'TEXTURIN-Surabaya', wallet: 'TX SBY(216)', notes: 'same name other portfolio' },
      { ...rows[0], id: 13, project: 'Lainnya', company: 'HOLLA', notes: 'mentions Villa A' },
    ]

    expect(filterTransactions(ambiguous, 'Villa A', 'projects', { name: 'Villa A', portfolio: 'Hollawall' }).map((row) => row.id)).toEqual([10])
    expect(filterTransactions(ambiguous, 'Villa A', 'projects', { name: 'Villa A', portfolio: 'Texturin' }).map((row) => row.id)).toEqual([12])
  })

  it('exports traceable semicolon CSV with spreadsheet-injection protection', () => {
    const malicious = [{ ...rows[0], notes: '=HYPERLINK("https://evil.invalid")' }]
    const csv = transactionsToCsv(malicious)
    expect(csv).toContain('Tanggal;Jenis;Jumlah;Dompet;Perusahaan;Proyek;Keterangan;Source Key')
    expect(csv).toContain("'=HYPERLINK")
    expect(csv).toContain('WA-001|1')
    expect(csv.startsWith('\uFEFF')).toBe(true)
  })
})
