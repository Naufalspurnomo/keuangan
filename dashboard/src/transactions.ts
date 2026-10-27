import type { Transaction } from './types'

export type TransactionTypeFilter = 'all' | 'Pemasukan' | 'Pengeluaran' | 'external-income' | 'external-expense' | 'external' | 'projects'
export interface ProjectTransactionTarget { name: string; portfolio?: string }

const isInternal = (row: Transaction) => (row.transfer_scope ?? (row.internal_movement ? 'internal' : 'external')) === 'internal'

function transactionPortfolio(row: Transaction) {
  const company = row.company.trim().toLocaleLowerCase('id-ID')
  const wallet = row.wallet.trim().toLocaleLowerCase('id-ID')
  if (company.startsWith('texturin') || company.startsWith('tx ')) return 'Texturin'
  if (company === 'holla' || company === 'hojja' || company.startsWith('cv hb')) return 'Hollawall'
  return wallet.startsWith('tx ') ? 'Texturin' : 'Hollawall'
}

export function filterTransactions(rows: Transaction[], query: string, type: TransactionTypeFilter, projectTarget?: ProjectTransactionTarget | null): Transaction[] {
  const needle = query.trim().toLocaleLowerCase('id-ID')
  return rows.filter((row) => {
    if (type === 'external-income' && (isInternal(row) || row.transaction_type !== 'Pemasukan')) return false
    if (type === 'external-expense' && (isInternal(row) || row.transaction_type !== 'Pengeluaran')) return false
    if (type === 'external' && isInternal(row)) return false
    if (type === 'projects' && (isInternal(row) || !row.project || ['saldo umum', 'umum'].includes(row.project.trim().toLocaleLowerCase('id-ID')))) return false
    if ((type === 'Pemasukan' || type === 'Pengeluaran') && row.transaction_type !== type) return false
    if (projectTarget) {
      const exactName = row.project.trim().toLocaleLowerCase('id-ID') === projectTarget.name.trim().toLocaleLowerCase('id-ID')
      const exactPortfolio = !projectTarget.portfolio || transactionPortfolio(row) === projectTarget.portfolio
      return exactName && exactPortfolio
    }
    if (!needle) return true
    return [row.notes, row.project, row.wallet, row.company, row.source_key]
      .some((value) => String(value ?? '').toLocaleLowerCase('id-ID').includes(needle))
  })
}

function safeCsvCell(value: unknown): string {
  let text = String(value ?? '')
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`
  if (/[;"\n\r]/.test(text)) text = `"${text.replaceAll('"', '""')}"`
  return text
}

export function transactionsToCsv(rows: Transaction[]): string {
  const header = ['Tanggal', 'Jenis', 'Jumlah', 'Dompet', 'Perusahaan', 'Proyek', 'Keterangan', 'Source Key']
  const body = rows.map((row) => [
    row.transaction_date,
    row.transaction_type,
    row.amount,
    row.wallet,
    row.company,
    row.project,
    row.notes,
    row.source_key,
  ].map(safeCsvCell).join(';'))
  return `\uFEFF${[header.join(';'), ...body].join('\r\n')}\r\n`
}

export function downloadTransactionsCsv(rows: Transaction[]): void {
  const blob = new Blob([transactionsToCsv(rows)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `hollawall-transaksi-${new Date().toISOString().slice(0, 10)}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
