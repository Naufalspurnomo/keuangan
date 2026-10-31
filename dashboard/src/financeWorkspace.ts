import { seedDemoFinanceWorkspace } from './demoFinanceFixtures'

export const WALLETS = ['CV HB', 'TX SBY', 'TX Bali'] as const
export type WalletId = typeof WALLETS[number]

export const COMPANIES = ['Holla', 'Hojja', 'Texturin Surabaya', 'Texturin Bali'] as const
export type CompanyId = typeof COMPANIES[number]

export const PROJECT_STATUSES = ['planned', 'active', 'completed'] as const
export type ProjectStatus = typeof PROJECT_STATUSES[number]
export type TransactionDirection = 'income' | 'expense'
export type TransactionScope = 'project' | 'office'

export const OFFICE_CATEGORIES = ['Listrik & utilitas', 'Sewa & fasilitas', 'Gaji & honor', 'Peralatan kantor', 'Transportasi', 'Administrasi', 'Lainnya'] as const
export type OfficeCategory = typeof OFFICE_CATEGORIES[number]

export const COMPANY_WALLET: Record<CompanyId, WalletId> = {
  Holla: 'CV HB',
  Hojja: 'CV HB',
  'Texturin Surabaya': 'TX SBY',
  'Texturin Bali': 'TX Bali',
}

export interface FinanceProject {
  id: string
  name: string
  company: CompanyId
  wallet: WalletId
  status: ProjectStatus
  started_on: string
  completed_on: string | null
  client: string
  contract_value: number | null
  notes: string
  created_at: string
  updated_at: string
}

export interface FinanceTransaction {
  id: string
  date: string
  direction: TransactionDirection
  amount: number
  scope: TransactionScope
  wallet: WalletId
  company: CompanyId | null
  project_id: string | null
  office_category: OfficeCategory | null
  notes: string
  created_at: string
  updated_at: string
}

export interface FinanceAuditEvent {
  id: string
  action: 'create' | 'update' | 'delete' | 'reset'
  entity: 'project' | 'transaction' | 'debt' | 'workspace'
  entity_id: string
  at: string
  summary: string
}

export interface FinanceDebt {
  id: string
  date: string
  borrower: WalletId
  lender: WalletId
  amount: number
  repaid: number
  notes: string
  created_at: string
  updated_at: string
}

export interface FinanceWorkspace {
  version: 3
  mode: 'demo'
  projects: FinanceProject[]
  transactions: FinanceTransaction[]
  debts: FinanceDebt[]
  audit: FinanceAuditEvent[]
  updated_at: string
}

export type ProjectInput = Omit<FinanceProject, 'id' | 'wallet' | 'created_at' | 'updated_at'>
export type TransactionInput = Omit<FinanceTransaction, 'id' | 'wallet' | 'company' | 'created_at' | 'updated_at'> & { wallet?: WalletId; company?: CompanyId | null }
export type DebtInput = Omit<FinanceDebt, 'id' | 'created_at' | 'updated_at'>

export class FinanceValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'FinanceValidationError'
  }
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
const nowIso = () => new Date().toISOString()
const uid = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

function requiredText(value: string, label: string) {
  const clean = value.trim()
  if (!clean) throw new FinanceValidationError(`${label} wajib diisi.`)
  return clean
}

function isRealIsoDate(value: string) {
  if (!ISO_DATE.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

function validDate(value: string, label: string) {
  if (!value) throw new FinanceValidationError(`${label} wajib diisi.`)
  if (!isRealIsoDate(value)) throw new FinanceValidationError(`${label} tidak valid.`)
  return value
}

function validAmount(value: number, label: string, nullable = false) {
  if (nullable && value === null) return null
  if (!Number.isSafeInteger(value) || value < 0) throw new FinanceValidationError(`${label} harus berupa rupiah bulat positif.`)
  return value
}

export function sumMoney(values: Iterable<number>, label = 'rupiah') {
  let total = 0
  for (const value of values) {
    if (!Number.isSafeInteger(value)) throw new FinanceValidationError(`${label} berisi nilai di luar batas aman.`)
    const next = total + value
    if (!Number.isSafeInteger(next)) throw new FinanceValidationError(`Total ${label} melebihi batas aman.`)
    total = next
  }
  return total
}

function projectNameTaken(projects: FinanceProject[], input: Pick<FinanceProject, 'name' | 'company'>, exceptId?: string) {
  const name = input.name.trim().toLocaleLowerCase('id-ID')
  return projects.some((project) => project.id !== exceptId && project.company === input.company && project.name.trim().toLocaleLowerCase('id-ID') === name)
}

export function validateProjectInput(input: ProjectInput, projects: FinanceProject[], exceptId?: string): ProjectInput {
  const name = requiredText(input.name, 'Nama proyek')
  const client = input.client.trim()
  const notes = input.notes.trim()
  const started_on = validDate(input.started_on, 'Tanggal mulai')
  if (!COMPANIES.includes(input.company)) throw new FinanceValidationError('Perusahaan tidak valid.')
  if (!PROJECT_STATUSES.includes(input.status)) throw new FinanceValidationError('Status proyek tidak valid.')
  if (projectNameTaken(projects, { name, company: input.company }, exceptId)) throw new FinanceValidationError('Nama proyek sudah dipakai pada perusahaan ini.')
  const completed_on = input.status === 'completed' ? validDate(input.completed_on ?? '', 'Tanggal selesai') : null
  if (completed_on && completed_on < started_on) throw new FinanceValidationError('Tanggal selesai tidak boleh sebelum tanggal mulai.')
  const contract_value = input.contract_value === null ? null : validAmount(input.contract_value, 'Nilai kontrak', true)
  return { name, company: input.company, status: input.status, started_on, completed_on, client, contract_value, notes }
}

export function createProject(workspace: FinanceWorkspace, input: ProjectInput): FinanceWorkspace {
  const clean = validateProjectInput(input, workspace.projects)
  const at = nowIso()
  const project: FinanceProject = { ...clean, id: uid('prj'), wallet: COMPANY_WALLET[clean.company], created_at: at, updated_at: at }
  return commit(workspace, { projects: [...workspace.projects, project] }, audit('create', 'project', project.id, `Menambah proyek ${project.name}`))
}

export function updateProject(workspace: FinanceWorkspace, id: string, input: ProjectInput): FinanceWorkspace {
  const current = workspace.projects.find((project) => project.id === id)
  if (!current) throw new FinanceValidationError('Proyek tidak ditemukan.')
  const clean = validateProjectInput(input, workspace.projects, id)
  const linkedTransactions = workspace.transactions.filter((row) => row.project_id === id)
  if (clean.status === 'planned' && linkedTransactions.length) throw new FinanceValidationError('Proyek yang sudah memiliki transaksi tidak dapat berstatus Direncanakan.')
  if (linkedTransactions.some((row) => row.date < clean.started_on)) throw new FinanceValidationError('Tanggal mulai proyek tidak boleh setelah transaksi pertamanya.')
  if (clean.completed_on && linkedTransactions.some((row) => row.date > clean.completed_on!)) throw new FinanceValidationError('Tanggal selesai tidak boleh sebelum transaksi terakhir.')
  const nextProject = { ...current, ...clean, wallet: COMPANY_WALLET[clean.company], updated_at: nowIso() }
  const transactions = workspace.transactions.map((transaction) => transaction.project_id === id
    ? { ...transaction, wallet: nextProject.wallet, company: nextProject.company, updated_at: nowIso() }
    : transaction)
  return commit(workspace, { projects: workspace.projects.map((project) => project.id === id ? nextProject : project), transactions }, audit('update', 'project', id, `Memperbarui proyek ${nextProject.name}`))
}

export function deleteProject(workspace: FinanceWorkspace, id: string): FinanceWorkspace {
  const project = workspace.projects.find((item) => item.id === id)
  if (!project) throw new FinanceValidationError('Proyek tidak ditemukan.')
  if (workspace.transactions.some((transaction) => transaction.project_id === id)) throw new FinanceValidationError('Proyek masih memiliki transaksi. Hapus atau pindahkan transaksinya lebih dulu.')
  return commit(workspace, { projects: workspace.projects.filter((item) => item.id !== id) }, audit('delete', 'project', id, `Menghapus proyek ${project.name}`))
}

export function validateTransactionInput(input: TransactionInput, workspace: FinanceWorkspace): TransactionInput & { wallet: WalletId; company: CompanyId | null } {
  const date = validDate(input.date, 'Tanggal transaksi')
  if (!['income', 'expense'].includes(input.direction)) throw new FinanceValidationError('Jenis transaksi tidak valid.')
  const amount = validAmount(input.amount, 'Jumlah') as number
  if (amount === 0) throw new FinanceValidationError('Jumlah harus lebih dari nol.')
  const notes = requiredText(input.notes, 'Keterangan')
  if (input.scope === 'project') {
    const project = workspace.projects.find((item) => item.id === input.project_id)
    if (!project) throw new FinanceValidationError('Proyek wajib dipilih.')
    if (project.status === 'planned') throw new FinanceValidationError('Proyek Direncanakan belum dapat memiliki transaksi.')
    if (date < project.started_on) throw new FinanceValidationError('Tanggal transaksi tidak boleh sebelum proyek dimulai.')
    if (project.completed_on && date > project.completed_on) throw new FinanceValidationError('Tanggal transaksi tidak boleh setelah proyek selesai.')
    return { ...input, date, amount, notes, wallet: project.wallet, company: project.company, project_id: project.id, office_category: null }
  }
  if (input.scope !== 'office') throw new FinanceValidationError('Aktivitas transaksi tidak valid.')
  if (!input.wallet || !WALLETS.includes(input.wallet)) throw new FinanceValidationError('Dompet wajib dipilih.')
  if (!input.office_category || !OFFICE_CATEGORIES.includes(input.office_category)) throw new FinanceValidationError('Kategori biaya kantor wajib dipilih.')
  if (input.direction !== 'expense') throw new FinanceValidationError('Operasional Kantor hanya mencatat pengeluaran.')
  return { ...input, date, amount, notes, wallet: input.wallet, company: null, project_id: null, office_category: input.office_category }
}

export function createTransaction(workspace: FinanceWorkspace, input: TransactionInput): FinanceWorkspace {
  const clean = validateTransactionInput(input, workspace)
  const at = nowIso()
  const transaction: FinanceTransaction = { ...clean, id: uid('trx'), created_at: at, updated_at: at }
  return commit(workspace, { transactions: [...workspace.transactions, transaction] }, audit('create', 'transaction', transaction.id, `Menambah transaksi ${transaction.notes}`))
}

export function updateTransaction(workspace: FinanceWorkspace, id: string, input: TransactionInput): FinanceWorkspace {
  const current = workspace.transactions.find((transaction) => transaction.id === id)
  if (!current) throw new FinanceValidationError('Transaksi tidak ditemukan.')
  const clean = validateTransactionInput(input, workspace)
  const next = { ...current, ...clean, updated_at: nowIso() }
  return commit(workspace, { transactions: workspace.transactions.map((transaction) => transaction.id === id ? next : transaction) }, audit('update', 'transaction', id, `Memperbarui transaksi ${next.notes}`))
}

export function deleteTransaction(workspace: FinanceWorkspace, id: string): FinanceWorkspace {
  const transaction = workspace.transactions.find((item) => item.id === id)
  if (!transaction) throw new FinanceValidationError('Transaksi tidak ditemukan.')
  return commit(workspace, { transactions: workspace.transactions.filter((item) => item.id !== id) }, audit('delete', 'transaction', id, `Menghapus transaksi ${transaction.notes}`))
}

export function validateDebtInput(input: DebtInput): DebtInput {
  const date = validDate(input.date, 'Tanggal hutang')
  if (!WALLETS.includes(input.borrower) || !WALLETS.includes(input.lender)) throw new FinanceValidationError('Dompet hutang tidak valid.')
  if (input.borrower === input.lender) throw new FinanceValidationError('Dompet peminjam dan pemberi dana harus berbeda.')
  const amount = validAmount(input.amount, 'Jumlah hutang') as number
  const repaid = validAmount(input.repaid, 'Jumlah terbayar') as number
  if (amount === 0) throw new FinanceValidationError('Jumlah hutang harus lebih dari nol.')
  if (repaid > amount) throw new FinanceValidationError('Jumlah terbayar tidak boleh melebihi hutang.')
  return { ...input, date, amount, repaid, notes: requiredText(input.notes, 'Keterangan') }
}

export function createDebt(workspace: FinanceWorkspace, input: DebtInput): FinanceWorkspace {
  const clean = validateDebtInput(input)
  const at = nowIso()
  const debt: FinanceDebt = { ...clean, id: uid('debt'), created_at: at, updated_at: at }
  return commit(workspace, { debts: [...workspace.debts, debt] }, audit('create', 'debt', debt.id, `Menambah hutang ${debt.borrower} kepada ${debt.lender}`))
}

export function updateDebt(workspace: FinanceWorkspace, id: string, input: DebtInput): FinanceWorkspace {
  const current = workspace.debts.find((debt) => debt.id === id)
  if (!current) throw new FinanceValidationError('Hutang tidak ditemukan.')
  const next = { ...current, ...validateDebtInput(input), updated_at: nowIso() }
  return commit(workspace, { debts: workspace.debts.map((debt) => debt.id === id ? next : debt) }, audit('update', 'debt', id, `Memperbarui hutang ${next.borrower} kepada ${next.lender}`))
}

export function deleteDebt(workspace: FinanceWorkspace, id: string): FinanceWorkspace {
  const debt = workspace.debts.find((item) => item.id === id)
  if (!debt) throw new FinanceValidationError('Hutang tidak ditemukan.')
  return commit(workspace, { debts: workspace.debts.filter((item) => item.id !== id) }, audit('delete', 'debt', id, `Menghapus hutang ${debt.borrower} kepada ${debt.lender}`))
}

function audit(action: FinanceAuditEvent['action'], entity: FinanceAuditEvent['entity'], entity_id: string, summary: string): FinanceAuditEvent {
  return { id: uid('evt'), action, entity, entity_id, at: nowIso(), summary }
}

function commit(workspace: FinanceWorkspace, patch: Partial<Pick<FinanceWorkspace, 'projects' | 'transactions' | 'debts'>>, event: FinanceAuditEvent): FinanceWorkspace {
  const next = { ...workspace, ...patch, updated_at: event.at, audit: [...workspace.audit, event] }
  workspaceTotals(next)
  sumMoney(next.debts.map((debt) => debt.amount), 'hutang')
  sumMoney(next.debts.map((debt) => debt.repaid), 'pembayaran hutang')
  return next
}

export function seedFinanceWorkspace(): FinanceWorkspace {
  return seedDemoFinanceWorkspace()
}

export function resetFinanceWorkspace(workspace: FinanceWorkspace): FinanceWorkspace {
  const seeded = seedFinanceWorkspace()
  const event = audit('reset', 'workspace', 'demo', 'Data demo dikembalikan ke kondisi awal')
  return { ...seeded, audit: [...workspace.audit, event], updated_at: event.at }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

function validIsoDate(value: unknown) {
  return typeof value === 'string' && isRealIsoDate(value)
}

function validTimestamp(value: unknown) {
  return typeof value === 'string' && !Number.isNaN(new Date(value).getTime())
}

function validMoney(value: unknown, allowZero = true) {
  return typeof value === 'number' && Number.isSafeInteger(value) && (allowZero ? value >= 0 : value > 0)
}

export function isFinanceWorkspace(value: unknown): value is FinanceWorkspace {
  if (!isRecord(value) || value.version !== 3 || value.mode !== 'demo' || !Array.isArray(value.projects) || !Array.isArray(value.transactions) || !Array.isArray(value.debts) || !Array.isArray(value.audit) || !validTimestamp(value.updated_at)) return false
  const projectIds = new Set<string>()
  const projectMap = new Map<string, Record<string, unknown>>()
  const projectNames = new Set<string>()
  for (const project of value.projects) {
    if (!isRecord(project) || typeof project.id !== 'string' || projectIds.has(project.id) || typeof project.name !== 'string' || !project.name.trim() || !COMPANIES.includes(project.company as CompanyId) || project.wallet !== COMPANY_WALLET[project.company as CompanyId] || !PROJECT_STATUSES.includes(project.status as ProjectStatus) || !validIsoDate(project.started_on) || !(project.completed_on === null || validIsoDate(project.completed_on)) || typeof project.client !== 'string' || !(project.contract_value === null || validMoney(project.contract_value)) || typeof project.notes !== 'string' || !validTimestamp(project.created_at) || !validTimestamp(project.updated_at)) return false
    const projectNameKey = `${project.company}:${project.name.trim().toLocaleLowerCase('id-ID')}`
    if (projectNames.has(projectNameKey)) return false
    if (project.status === 'completed' && (!validIsoDate(project.completed_on) || String(project.completed_on) < String(project.started_on))) return false
    if (project.status !== 'completed' && project.completed_on !== null) return false
    projectIds.add(project.id)
    projectMap.set(project.id, project)
    projectNames.add(projectNameKey)
  }
  const transactionIds = new Set<string>()
  for (const row of value.transactions) {
    if (!isRecord(row) || typeof row.id !== 'string' || transactionIds.has(row.id) || !validIsoDate(row.date) || !['income', 'expense'].includes(String(row.direction)) || !validMoney(row.amount, false) || !['project', 'office'].includes(String(row.scope)) || !WALLETS.includes(row.wallet as WalletId) || typeof row.notes !== 'string' || !validTimestamp(row.created_at) || !validTimestamp(row.updated_at)) return false
    const linkedProject = typeof row.project_id === 'string' ? projectMap.get(row.project_id) : undefined
    const rowDate = String(row.date)
    if (row.scope === 'project' && (!linkedProject || linkedProject.status === 'planned' || rowDate < String(linkedProject.started_on) || (linkedProject.completed_on !== null && rowDate > String(linkedProject.completed_on)) || row.company !== linkedProject.company || row.wallet !== linkedProject.wallet || row.office_category !== null)) return false
    if (row.scope === 'office' && (row.direction !== 'expense' || row.company !== null || row.project_id !== null || !OFFICE_CATEGORIES.includes(row.office_category as OfficeCategory))) return false
    transactionIds.add(row.id)
  }
  const debtIds = new Set<string>()
  for (const debt of value.debts) {
    if (!isRecord(debt) || typeof debt.id !== 'string' || debtIds.has(debt.id) || !validIsoDate(debt.date) || !WALLETS.includes(debt.borrower as WalletId) || !WALLETS.includes(debt.lender as WalletId) || debt.borrower === debt.lender || !validMoney(debt.amount, false) || !validMoney(debt.repaid) || Number(debt.repaid) > Number(debt.amount) || typeof debt.notes !== 'string' || !validTimestamp(debt.created_at) || !validTimestamp(debt.updated_at)) return false
    debtIds.add(debt.id)
  }
  if (!value.audit.every((event) => isRecord(event) && typeof event.id === 'string' && ['create', 'update', 'delete', 'reset'].includes(String(event.action)) && ['project', 'transaction', 'debt', 'workspace'].includes(String(event.entity)) && typeof event.entity_id === 'string' && validTimestamp(event.at) && typeof event.summary === 'string')) return false
  try {
    workspaceTotals(value as unknown as FinanceWorkspace)
    sumMoney((value.debts as FinanceDebt[]).map((debt) => debt.amount), 'hutang')
    sumMoney((value.debts as FinanceDebt[]).map((debt) => debt.repaid), 'pembayaran hutang')
    return true
  } catch {
    return false
  }
}

export function projectYear(project: FinanceProject) {
  return Number(project.started_on.slice(0, 4))
}

export function projectTotals(project: FinanceProject, transactions: FinanceTransaction[]) {
  const rows = transactions.filter((transaction) => transaction.project_id === project.id)
  const income = sumMoney(rows.filter((row) => row.direction === 'income').map((row) => row.amount), 'pemasukan proyek')
  const expense = sumMoney(rows.filter((row) => row.direction === 'expense').map((row) => row.amount), 'pengeluaran proyek')
  return { income, expense, net: income - expense, transactions: rows.length }
}

export function workspaceTotals(workspace: FinanceWorkspace) {
  const income = sumMoney(workspace.transactions.filter((row) => row.direction === 'income').map((row) => row.amount), 'pemasukan')
  const expense = sumMoney(workspace.transactions.filter((row) => row.direction === 'expense').map((row) => row.amount), 'pengeluaran')
  const office = sumMoney(workspace.transactions.filter((row) => row.scope === 'office').map((row) => row.amount), 'Operasional Kantor')
  return { income, expense, net: income - expense, office }
}
