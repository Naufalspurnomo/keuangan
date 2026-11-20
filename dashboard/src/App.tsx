import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChart3,
  BriefcaseBusiness,
  Building2,

  FileBarChart,

  Landmark,
  LayoutDashboard,
  LockKeyhole,
  Menu,
  Moon,
  Plus,
  RefreshCw,
  Sun,
  WalletCards,
  X,
} from 'lucide-react'

import { DebtForm, ProjectForm, TransactionForm } from './FinanceForms'
import CanonicalTransactionMutationDialog, { type TransactionMutationDraft } from './CanonicalTransactionMutationDialog'
import { CanonicalDebtCreateForm, CanonicalDebtRepaymentForm, type CanonicalDebtCreateInput } from './CanonicalDebtForms'
import { actionProps, type ActionId } from './actionRegistry'
import {
  CashflowWorkspacePage,
  DebtWorkspace,
  DemoBanner,

  OfficeWorkspace,
  OverviewWorkspace,
  TransactionRows,

  WalletWorkspacePage,
} from './FinancePages'
import ProjectCommandCenter from './ProjectCommandCenter'
import ProjectCompleteDialog from './ProjectCompleteDialog'
import { ProjectAuditPanel, ProjectDebtPanel, ProjectOverviewPanel } from './ProjectContextPanels'
import ProjectDetailWorkspace from './ProjectDetailWorkspace'
import ProjectDocumentsWorkspace from './ProjectDocumentsWorkspace'
import ProjectPresensiPanel from './ProjectPresensiPanel'
import ProjectProfitabilityWorkspace from './ProjectProfitabilityWorkspace'
import ProjectRecordForm from './ProjectRecordForm'
import ProjectTransactionsWorkspace from './ProjectTransactionsWorkspace'

import ReportsWorkspace from './ReportsWorkspace'
import InboxReviewWorkspace from './InboxReviewWorkspace'
import type { CompanyId, FinanceDebt, FinanceProject, FinanceTransaction, FinanceWorkspace, ProjectInput, TransactionInput, TransactionFormInput, DebtInput, WalletId } from './financeWorkspace'
import { snapshotFinanceWorkspace } from './snapshot'
import { useLiveSnapshot } from './liveSnapshotView'
import { createCanonicalTransactionMutation, createTransactionWriteAttempt, jakartaToday, loadTransactionWriteSession, sameTransactionPayload, type RecordedTransaction, type TransactionWriteAttempt, type TransactionWritePayload, type TransactionWriteSession } from './transactionApi'
import { useFinanceWorkspace } from './useFinanceWorkspace'
import hollawallLogo from './assets/hollawall-logo.png'
import { createProjectDocumentApi, type ProjectDocumentApi, type ProjectDocumentCommand, type ProjectDocumentSession } from './projectDocumentApi'
import { createInboxReviewApi, type InboxReviewApi } from './inboxReviewApi'
import { canonicalDebtIdentity } from './debtRegistry'
import { normalizeCanonicalPair } from './transactionMappings'
import { createDebtAttempt, createDebtCorrectionAttempt, createDebtRepaymentAttempt, createDebtReversalAttempt } from './debtApi'
import {
  NO_PROJECT_DOCUMENT_WRITES,
  projectDocumentRoute,
  readProjectDocumentRoute,
  type ProjectDetailTab,
  type ProjectDocumentCapabilities,
  type ProjectDocumentRoute,
  type ProjectDraft,
  type ProjectRecord,
  type ProductionProjectStatus,
} from './projectDocuments'

type Page = 'overview' | 'cashflow' | 'wallets' | 'projects' | 'office' | 'debts' | 'reports' | 'inbox-reviews'
type Modal =
  | { kind: 'project'; value?: FinanceProject }
  | { kind: 'complete-project'; value: FinanceProject }
  | { kind: 'transaction'; value?: FinanceTransaction; scope?: 'project' | 'office'; projectId?: string }
  | { kind: 'debt'; value?: FinanceDebt; projectId?: string; borrower?: string }
  | null
const MOBILE_NAVIGATION_QUERY = '(max-width: 900px)'
const PAGES: Page[] = ['overview', 'cashflow', 'wallets', 'projects', 'office', 'debts', 'reports', 'inbox-reviews']

function routeHash(page: Page, projectId?: string, detail?: Partial<ProjectDocumentRoute>) {
  if (page === 'projects' && projectId) return projectDocumentRoute({ projectId, tab: detail?.tab ?? 'transactions', document: detail?.document, type: detail?.type })
  return `#${page}`
}

interface AppRoute {
  page: Page
  projectId?: string
  tab?: ProjectDetailTab
  document?: string
  type?: ProjectDocumentRoute['type']
}

function currentRoute(): AppRoute {
  const [rawPage, rawQuery = ''] = window.location.hash.replace(/^#/, '').split('?')
  const params = new URLSearchParams(rawQuery)
  if (rawPage === 'transactions') {
    const projectId = params.get('project') || undefined
    const canonical = projectId ? `#projects?project=${encodeURIComponent(projectId)}` : '#projects'
    window.history.replaceState({ page: 'projects', projectId, scrollY: 0 }, '', canonical)
    return { page: 'projects', projectId, tab: 'transactions' }
  }
  const page = PAGES.includes(rawPage as Page) ? rawPage as Page : 'overview'
  if (page === 'projects') {
    const detail = readProjectDocumentRoute(window.location.hash)
    return { page, projectId: detail.projectId, tab: detail.tab, document: detail.document, type: detail.type }
  }
  return { page }
}

const pageMeta: Record<Page, { eyebrow: string; title: string; copy: string }> = {
  overview: { eyebrow: 'DASHBOARD', title: 'Dashboard', copy: 'Posisi keuangan dari seluruh sumber data.' },
  cashflow: { eyebrow: 'KEUANGAN', title: 'Arus Kas', copy: 'Pemasukan dan pengeluaran per periode.' },
  wallets: { eyebrow: 'SUMBER DANA', title: 'Dompet', copy: 'Posisi CV HB, TX SBY, dan TX Bali.' },

  projects: { eyebrow: 'PROJECT', title: 'Project', copy: 'Kinerja Project per tahun, perusahaan, dan status.' },
  office: { eyebrow: 'KEBUTUHAN KANTOR', title: 'Operasional Kantor', copy: 'Biaya kantor yang terpisah dari Project.' },
  debts: { eyebrow: 'PERGERAKAN INTERNAL', title: 'Hutang', copy: 'Hutang antar-dompet tanpa mengubah kas konsolidasi.' },
  reports: { eyebrow: 'PELAPORAN', title: 'Laporan', copy: 'Filter, pratinjau, dan ekspor PDF.' },
  'inbox-reviews': { eyebrow: 'KOTAK MASUK', title: 'Perlu Ditinjau', copy: 'Pesan tahan gagal yang memerlukan keputusan owner.' },
}

function useMobileNavigation() {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_NAVIGATION_QUERY).matches)
  useEffect(() => {
    const query = window.matchMedia(MOBILE_NAVIGATION_QUERY)
    const update = () => setMobile(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return mobile
}

function Sidebar({ active, open, mobile, live, close, navigate }: { active: Page; open: boolean; mobile: boolean; live: boolean; close: () => void; navigate: (page: Page) => void }) {
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (mobile && open) closeButtonRef.current?.focus() }, [mobile, open])
  const items: ReadonlyArray<readonly [Page, string, typeof LayoutDashboard]> = [
    ['overview', 'Dashboard', LayoutDashboard], ['cashflow', 'Arus Kas', BarChart3], ['wallets', 'Dompet', WalletCards],
    ['projects', 'Project', BriefcaseBusiness], ['office', 'Operasional Kantor', Building2],
    ['debts', 'Hutang', Landmark], ['reports', 'Laporan', FileBarChart],
  ]
  const navAction: Record<Exclude<Page, 'inbox-reviews'>, ActionId> = {
    overview: 'nav.dashboard', cashflow: 'nav.cashflow', wallets: 'nav.wallets', projects: 'nav.projects',
    office: 'nav.office', debts: 'nav.debts', reports: 'nav.reports',
  }
  const hidden = mobile && !open
  return <>{mobile && open && <button type="button" className="mobile-overlay is-open" onClick={close} aria-label="Tutup navigasi" {...actionProps('shell.navigation-close')} />}<aside id="app-navigation" className={`sidebar ${open ? 'is-open' : ''}`} aria-hidden={hidden || undefined}><div className="sidebar-head"><img src={hollawallLogo} alt="Hollawall" /><button ref={closeButtonRef} tabIndex={hidden ? -1 : 0} className="icon-button mobile-only" onClick={close} aria-label="Tutup navigasi" {...actionProps('shell.navigation-close')}><X size={20} /></button></div><div className="workspace-switch"><Building2 size={18} /><span><small>Ruang kerja</small>Hollawall Group</span></div><nav aria-label="Menu utama">{items.map(([key, label, Icon]) => <button type="button" tabIndex={hidden ? -1 : 0} key={key} className={active === key ? 'active' : ''} aria-current={active === key ? 'page' : undefined} onClick={() => { navigate(key); close() }} {...actionProps(navAction[key as Exclude<Page, 'inbox-reviews'>])}><Icon size={18} /><span>{label}</span></button>)}</nav><div className="sidebar-bottom"><div className="profile workspace-profile"><span><LockKeyhole size={15} /></span><div><strong>{live ? 'Keuangan Hollawall' : 'Workspace demo'}</strong><small>{live ? 'Dashboard dan laporan' : 'Data lokal · Teraudit'}</small></div></div></div></aside></>
}

function ThemeToggle({ theme, setTheme }: { theme: string; setTheme: (theme: string) => void }) {
  const dark = theme === 'dark'
  return <button type="button" className="theme-toggle" onClick={() => setTheme(dark ? 'light' : 'dark')} aria-label={`Gunakan tema ${dark ? 'terang' : 'gelap'}`} aria-pressed={dark} title={`Tema ${dark ? 'gelap' : 'terang'}`} {...actionProps('shell.theme-toggle')}><Sun size={16} aria-hidden="true" /><span className={theme} aria-hidden="true" /><Moon size={16} aria-hidden="true" /></button>
}

function projectStatusInput(project: FinanceProject, status: 'active' | 'completed', completedOn: string | null): ProjectInput {
  return { name: project.name, company: project.company, status, started_on: project.started_on, completed_on: completedOn, client: project.client, contract_value: project.contract_value, notes: project.notes }
}

function localIsoDate() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function productionFinanceProject(project: ProjectRecord): FinanceProject {
  const wallet: WalletId = project.wallet === 'TX SBY(216)' ? 'TX SBY' : project.wallet === 'TX BALI(087)' ? 'TX Bali' : 'CV HB'
  const company: CompanyId = project.company === 'HOJJA'
    ? 'Hojja'
    : ['TEXTURIN-Surabaya', 'TX SBY'].includes(project.company)
      ? 'Texturin Surabaya'
      : ['TEXTURIN-Bali', 'TX BALI'].includes(project.company)
        ? 'Texturin Bali'
        : 'Holla'
  return {
    id: project.id,
    name: project.name,
    company,
    wallet,
    status: project.status,
    started_on: project.started_on,
    completed_on: project.completed_on,
    client: project.client_company || project.client_name,
    contract_value: null,
    notes: project.contract_notes,
    created_at: project.created_at,
    updated_at: project.updated_at,
    presensi_project_id: project.id,
    write_mapping: { wallet: project.wallet, company: project.company, project: project.id },
  }
}

function canonicalProjectWallet(project: ProjectRecord) {
  return normalizeCanonicalPair(project.wallet, project.company)?.wallet ?? null
}

export function DemoApp({ suppliedWorkspace, liveSnapshotError, liveWriteSession, liveWriteStatus, onCreateLiveTransaction, onMutateLiveTransaction, onCreateLiveDebt, onRepayLiveDebt, onMutateLiveDebt, projectApi, inboxReviewApi }: { suppliedWorkspace?: Readonly<FinanceWorkspace>; liveSnapshotError?: Error | null; liveWriteSession?: TransactionWriteSession; liveWriteStatus?: string; onCreateLiveTransaction?: (input: TransactionFormInput) => Promise<RecordedTransaction>; onMutateLiveTransaction?: (row: FinanceTransaction, action: 'correction' | 'reversal', draft: TransactionMutationDraft) => Promise<{ readbackFailed: boolean }>; onCreateLiveDebt?: (input: CanonicalDebtCreateInput) => Promise<void>; onRepayLiveDebt?: (debt: FinanceDebt, amount: number, occurredOn: string, description: string) => Promise<void>; onMutateLiveDebt?: (debt: FinanceDebt, action: 'correction' | 'reversal') => Promise<void>; projectApi?: ProjectDocumentApi; inboxReviewApi?: InboxReviewApi } = {}) {
  const finance = useFinanceWorkspace(suppliedWorkspace)
  const readOnly = finance.readOnly
  const canCreateTransactions = readOnly && liveWriteSession?.canonicalWritesEnabled === true && Boolean(onCreateLiveTransaction)
  const initialRoute = useRef(currentRoute()).current
  const [route, setRoute] = useState<AppRoute>(initialRoute)
  const { page: active, projectId: projectFilter } = route
  const [menuOpen, setMenuOpen] = useState(false)
  const [modal, setModal] = useState<Modal>(null)
  const [projectModal, setProjectModal] = useState<ProjectRecord | 'create' | null>(null)
  const [productionProjects, setProductionProjects] = useState<ProjectRecord[]>([])
  const [projectCapabilities, setProjectCapabilities] = useState<ProjectDocumentCapabilities>(NO_PROJECT_DOCUMENT_WRITES)
  const canMutateTransactions = readOnly
    && liveWriteSession?.canonicalWritesEnabled === true
    && projectCapabilities.transactionCorrections
    && projectCapabilities.transactionReversals
    && Boolean(onMutateLiveTransaction)
  const [projectDataLoading, setProjectDataLoading] = useState(Boolean(readOnly && projectApi))
  const [projectApiAvailable, setProjectApiAvailable] = useState(false)
  const [projectApiError, setProjectApiError] = useState('')
  const [projectBusy, setProjectBusy] = useState(false)
  const [transactionLifecycleBusyId, setTransactionLifecycleBusyId] = useState<string | null>(null)
  const [transactionMutationTarget, setTransactionMutationTarget] = useState<{ row: FinanceTransaction; action: 'correction' | 'reversal' } | null>(null)
  const [debtBusy, setDebtBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
  const mobile = useMobileNavigation()
  const previousMobile = useRef(mobile)
  const pendingScroll = useRef<number | null>(null)
  const activeProjectLoad = useRef<Promise<void> | null>(null)
  const pendingProjectSave = useRef<{ signature: string; command: ProjectDocumentCommand<ProjectRecord>; creating: boolean; savedId?: string } | null>(null)
  const projectLoadSequence = useRef(0)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const meta = pageMeta[active]
  const selectedProject = projectFilter ? finance.workspace.projects.find((project) => project.id === projectFilter) : undefined
  const productionProject = projectFilter ? productionProjects.find((project) => project.id === projectFilter) : undefined
  const projectSession: ProjectDocumentSession = { csrfToken: liveWriteSession?.csrfToken ?? '', capabilities: projectCapabilities }
  const transactionProjects = useMemo(() => {
    const merged = new Map(finance.workspace.projects.map((project) => [project.id, project]))
    productionProjects.forEach((project) => merged.set(project.id, productionFinanceProject(project)))
    return [...merged.values()]
  }, [finance.workspace.projects, productionProjects])

  const loadProductionProjects = useCallback((force = false) => {
    if (!readOnly || !projectApi) return Promise.resolve()
    if (activeProjectLoad.current && !force) return activeProjectLoad.current
    if (force) {
      projectLoadSequence.current += 1
      activeProjectLoad.current = null
    }
    const sequence = ++projectLoadSequence.current
    setProjectDataLoading(true)
    setProjectApiError('')
    const request = projectApi.listProjects()
      .then((result) => {
        if (sequence !== projectLoadSequence.current) return
        const projects = result.projects.filter((project) => !project.archived_at)
        setProductionProjects(projects)
        const pending = pendingProjectSave.current
        if (pending?.savedId && projects.some((project) => project.id === pending.savedId)) {
          pendingProjectSave.current = null
          setProjectModal(null)
          setNotice(pending.creating ? 'Project tersimpan dan berhasil dipulihkan.' : 'Perubahan Project tersimpan dan berhasil dipulihkan.')
        }
        setProjectCapabilities(result.capabilities)
        setProjectApiAvailable(true)
      })
      .catch((error: unknown) => {
        if (sequence !== projectLoadSequence.current) return
        setProjectCapabilities(NO_PROJECT_DOCUMENT_WRITES)
        setProjectApiError(error instanceof Error ? error.message : 'Data Project belum tersedia.')
      })
      .finally(() => {
        if (sequence === projectLoadSequence.current) setProjectDataLoading(false)
        if (activeProjectLoad.current === request) activeProjectLoad.current = null
      })
    activeProjectLoad.current = request
    return request
  }, [projectApi, readOnly])

  useEffect(() => {
    void loadProductionProjects()
    return () => {
      projectLoadSequence.current += 1
      activeProjectLoad.current = null
    }
  }, [loadProductionProjects])
  useEffect(() => {
    if (!readOnly || !projectApi) return
    const refresh = () => { if (document.visibilityState === 'visible') void loadProductionProjects() }
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [loadProductionProjects, projectApi, readOnly])
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('hollawall-theme', theme) }, [theme])
  useEffect(() => { document.title = `${meta.title} — Hollawall` }, [meta.title])
  useEffect(() => {
    const scrollRestoration = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    if (!window.location.hash) window.history.replaceState({ page: initialRoute.page, projectId: initialRoute.projectId, scrollY: 0 }, '', routeHash(initialRoute.page, initialRoute.projectId))
    else if (!window.history.state?.page) window.history.replaceState({ ...window.history.state, page: initialRoute.page, projectId: initialRoute.projectId, scrollY: window.scrollY }, '', window.location.href)
    const restore = (event: PopStateEvent) => {
      const route = currentRoute()
      pendingScroll.current = Number(event.state?.scrollY ?? 0)
      setRoute(route)
      setMenuOpen(false)
    }
    window.addEventListener('popstate', restore)
    return () => {
      window.history.scrollRestoration = scrollRestoration
      window.removeEventListener('popstate', restore)
    }
  }, [])
  useEffect(() => {
    if (pendingScroll.current == null) return
    const top = pendingScroll.current
    let restoreFrame = 0
    const layoutFrame = window.requestAnimationFrame(() => {
      restoreFrame = window.requestAnimationFrame(() => {
        pendingScroll.current = null
        window.scrollTo({ top, behavior: 'auto' })
      })
    })
    return () => {
      window.cancelAnimationFrame(layoutFrame)
      if (restoreFrame) window.cancelAnimationFrame(restoreFrame)
    }
  }, [route])
  useEffect(() => { if (!notice) return; const timeout = window.setTimeout(() => setNotice(''), 3500); return () => window.clearTimeout(timeout) }, [notice])
  useEffect(() => {
    if (!mobile || !menuOpen) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') closeMenu() }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [mobile, menuOpen])
  useEffect(() => {
    if (previousMobile.current === mobile) return
    const focused = document.activeElement as HTMLElement | null
    const focusWasInNavigation = Boolean(focused?.closest('#app-navigation'))
    const focusWasMobileControl = Boolean(focused?.classList.contains('mobile-only') || focused?.classList.contains('mobile-overlay'))
    setMenuOpen(false)
    window.requestAnimationFrame(() => {
      if (mobile && focusWasInNavigation) menuButtonRef.current?.focus()
      if (!mobile && focusWasMobileControl) document.querySelector<HTMLElement>('#app-navigation nav [aria-current="page"]')?.focus()
    })
    previousMobile.current = mobile
  }, [mobile])
  useEffect(() => {
    const main = mainRef.current
    if (!main) return
    if (mobile && menuOpen) main.setAttribute('inert', '')
    else main.removeAttribute('inert')
  }, [mobile, menuOpen])
  useEffect(() => {
    if (active !== 'projects' || !projectFilter || projectDataLoading || selectedProject || productionProject) return
    window.history.replaceState({ page: 'projects', scrollY: 0 }, '', routeHash('projects'))
    setRoute({ page: 'projects' })
    setNotice('Project tidak ditemukan.')
  }, [active, productionProject, projectDataLoading, projectFilter, selectedProject])

  const pushRoute = (page: Page, projectId?: string) => {
    if (active === page && projectFilter === projectId) return
    window.history.replaceState({ ...window.history.state, page: active, projectId: projectFilter, scrollY: window.scrollY }, '', window.location.href)
    window.history.pushState({ page, projectId, scrollY: 0, fromPage: active }, '', routeHash(page, projectId))
    setRoute({ page, projectId })
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: 'auto' }))
  }
  const navigate = (page: Page) => pushRoute(page)
  const openProjectDetail = (projectId: string) => pushRoute('projects', projectId)
  const setProjectDetailRoute = (detail: ProjectDocumentRoute) => {
    const next: AppRoute = { page: 'projects', projectId: detail.projectId, tab: detail.tab, document: detail.document, type: detail.type }
    window.history.replaceState({ ...window.history.state, ...next }, '', routeHash('projects', detail.projectId, detail))
    setRoute(next)
  }
  const backToProjects = () => {
    if (window.history.state?.fromPage === 'projects') {
      window.history.back()
      return
    }
    window.history.replaceState({ page: 'projects', scrollY: 0 }, '', routeHash('projects'))
    setRoute({ page: 'projects' })
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: 'auto' }))
  }
  const closeMenu = () => { setMenuOpen(false); if (mobile) window.requestAnimationFrame(() => menuButtonRef.current?.focus()) }
  const commit = (action: () => void, success: string) => { if (readOnly) throw new Error('Data ini hanya dapat dilihat.'); action(); setNotice(success) }
  const safe = (action: () => void, success: string) => { try { commit(action, success) } catch (error) { setNotice(error instanceof Error ? error.message : 'Tindakan belum dapat diproses.') } }
  const saveProject = (input: ProjectInput) => {
    if (modal?.kind === 'project' && modal.value) return commit(() => finance.editProject(modal.value!.id, input), 'Project diperbarui.')
    if (readOnly) throw new Error('Data ini hanya dapat dilihat.')
    const created = finance.addProject(input)
    setNotice('Project aktif dibuat. Lanjutkan dengan mencatat transaksi Project.')
    pushRoute('projects', created.id)
  }
  const completeProject = (input: ProjectInput) => modal?.kind === 'complete-project'
    && commit(() => finance.editProject(modal.value.id, input), 'Project diselesaikan.')
  const completeProjectNow = (project: FinanceProject) => {
    const latestTransaction = finance.workspace.transactions.filter((row) => row.project_id === project.id).reduce((latest, row) => row.date > latest ? row.date : latest, project.started_on)
    const completedOn = [localIsoDate(), project.started_on, latestTransaction].sort().at(-1)!
    safe(() => finance.editProject(project.id, projectStatusInput(project, 'completed', completedOn)), 'Project diselesaikan.')
  }
  const reactivateProject = (project: FinanceProject) => safe(() => finance.editProject(project.id, projectStatusInput(project, 'active', null)), 'Project diaktifkan kembali.')
  const saveTransaction = (input: TransactionFormInput) => {
    if (readOnly) {
      if (!canCreateTransactions || !onCreateLiveTransaction) throw new Error('Pencatatan transaksi belum tersedia.')
      return onCreateLiveTransaction(input).then((result) => {
        setNotice(result.authority === 'postgresql'
          ? `Transaksi tercatat dengan ID ${result.transactionId}. Data sedang diperbarui.`
          : `Transaksi tercatat di ${result.sheetName}, baris ${result.sheetRow}. Tampilan sedang diperbarui.`)
        if (result.readback) {
          void result.readback.catch(() => setNotice('Transaksi sudah tercatat, tetapi data terbaru belum dapat dimuat. Muat ulang halaman; jangan kirim transaksi yang sama lagi.'))
        }
      })
    }
    const { category: _category, ...demoInput } = input
    return modal?.kind === 'transaction' && modal.value
      ? commit(() => finance.editTransaction(modal.value!.id, demoInput as TransactionInput), 'Transaksi diperbarui.')
      : commit(() => finance.addTransaction(demoInput as TransactionInput), 'Transaksi ditambahkan.')
  }
  const openTransactionMutation = (row: FinanceTransaction, action: 'correction' | 'reversal') => {
    if (!canMutateTransactions || !onMutateLiveTransaction || !row.canonical_transaction_id || !row.transaction_version) return
    if (transactionLifecycleBusyId) return
    setTransactionMutationTarget({ row, action })
  }
  const submitTransactionMutation = async (draft: TransactionMutationDraft) => {
    const target = transactionMutationTarget
    if (!target || !onMutateLiveTransaction) throw new Error('Transaksi yang dipilih sudah tidak tersedia.')
    setTransactionLifecycleBusyId(target.row.id)
    try {
      const result = await onMutateLiveTransaction(target.row, target.action, draft)
      setTransactionMutationTarget(null)
      setNotice(result.readbackFailed
        ? 'Perubahan sudah tersimpan, tetapi pembacaan ulang gagal. Muat ulang data; jangan kirim koreksi atau pembalikan lagi.'
        : target.action === 'correction' ? 'Koreksi tercatat dan data diperbarui.' : 'Pembalikan tercatat dan data diperbarui.')
    } finally {
      setTransactionLifecycleBusyId(null)
    }
  }
  const saveDebt = (input: DebtInput) => modal?.kind === 'debt' && modal.value
    ? commit(() => finance.editDebt(modal.value!.id, input), 'Hutang diperbarui.')
    : commit(() => finance.addDebt(input), 'Hutang ditambahkan.')
  const saveLiveDebt = async (input: CanonicalDebtCreateInput) => {
    if (!onCreateLiveDebt) throw new Error('Pencatatan hutang belum tersedia.')
    setDebtBusy(true)
    try { await onCreateLiveDebt(input); setModal(null); setNotice('Hutang tersimpan dan data sudah diperbarui.') }
    finally { setDebtBusy(false) }
  }
  const repayLiveDebt = async (debt: FinanceDebt, amount: number, occurredOn: string, description: string) => {
    if (!onRepayLiveDebt) throw new Error('Pembayaran hutang belum tersedia.')
    setDebtBusy(true)
    try { await onRepayLiveDebt(debt, amount, occurredOn, description); setModal(null); setNotice('Pembayaran hutang tersimpan dan data sudah diperbarui.') }
    finally { setDebtBusy(false) }
  }
  const confirmDelete = (label: string, action: () => void) => { if (window.confirm(`Hapus ${label} dari data demo?`)) safe(action, `${label} dihapus.`) }
  const reset = () => { if (window.confirm('Reset seluruh perubahan dan kembali ke data demo awal?')) { finance.reset(); setNotice('Data demo direset.') } }
  const openProject = (project: FinanceProject) => pushRoute('projects', project.id)
  const openProjectByName = (name: string) => {
    const project = finance.workspace.projects.find((item) => item.name === name)
    if (project) openProject(project)
  }
  const saveProductionProject = async (draft: ProjectDraft) => {
    if (!projectApi) return
    setProjectBusy(true)
    try {
      const creating = projectModal === 'create'
      const signature = JSON.stringify({ creating, projectId: creating ? null : projectModal!.id, version: creating ? null : projectModal!.lock_version, draft })
      if (pendingProjectSave.current && pendingProjectSave.current.signature !== signature) {
        throw new Error('Hasil penyimpanan sebelumnya belum pasti. Ulangi data yang sama atau muat ulang Project sebelum mengubah isian.')
      }
      const command = pendingProjectSave.current?.command ?? (creating
        ? projectApi.createProject(draft)
        : projectApi.updateProject(projectModal!.id, draft, projectModal!.lock_version))
      pendingProjectSave.current ??= { signature, command, creating }
      if (!pendingProjectSave.current.savedId) {
        const saved = await command.submit(projectSession)
        pendingProjectSave.current.savedId = saved.id
      }
      const current = await projectApi.getProject(pendingProjectSave.current.savedId)
      pendingProjectSave.current = null
      projectLoadSequence.current += 1
      activeProjectLoad.current = null
      setProjectDataLoading(false)
      setProductionProjects((projects) => projects.some((project) => project.id === current.id)
        ? projects.map((project) => project.id === current.id ? current : project)
        : [current, ...projects])
      setProjectModal(null)
      if (creating) openProjectDetail(current.id)
      setNotice(creating ? 'Project aktif dibuat. Lanjutkan dengan mencatat transaksi Project.' : 'Project diperbarui.')
    } catch (error) {
      if (!pendingProjectSave.current?.savedId && !(error instanceof Error && 'uncertain' in error && error.uncertain)) pendingProjectSave.current = null
      throw error instanceof Error ? error : new Error('Project belum dapat disimpan.')
    } finally { setProjectBusy(false) }
  }
  const changeProductionProjectStatusById = async (projectId: string, status: ProductionProjectStatus) => {
    if (!projectApi || projectBusy) return
    const project = productionProjects.find((item) => item.id === projectId)
    if (!project) return
    setProjectBusy(true)
    try {
      const saved = await projectApi.setProjectStatus(project.id, status, project.lock_version).submit(projectSession)
      const current = await projectApi.getProject(saved.id)
      projectLoadSequence.current += 1
      activeProjectLoad.current = null
      setProjectDataLoading(false)
      setProductionProjects((projects) => projects.map((item) => item.id === current.id ? current : item))
      setNotice('Status Project diperbarui.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Status Project belum dapat diperbarui.')
    } finally { setProjectBusy(false) }
  }
  const changeProductionProjectStatus = async (status: ProductionProjectStatus) => {
    if (productionProject) await changeProductionProjectStatusById(productionProject.id, status)
  }
  const deleteProductionProjectById = async (projectId: string) => {
    if (!projectApi || !projectCapabilities.hardDelete) return
    const project = productionProjects.find((item) => item.id === projectId)
    if (!project) return
    const confirmed = window.confirm(
      `Hapus Project ${project.name} secara permanen? Semua transaksi, dokumen, bukti, quotation, dan audit Project ini ikut dihapus. Tindakan ini tidak dapat dibatalkan dari dashboard.`,
    )
    if (!confirmed) return
    const typedName = window.prompt(`Ketik nama Project persis untuk konfirmasi:\n${project.name}`, '')
    if (typedName !== project.name) {
      setNotice('Penghapusan dibatalkan karena nama Project tidak cocok.')
      return
    }
    setProjectBusy(true)
    try {
      await projectApi.deleteProject(project.id, project.lock_version, typedName).submit(projectSession)
      setProductionProjects((projects) => projects.filter((item) => item.id !== project.id))
      await loadProductionProjects(true)
      pushRoute('projects')
      setNotice('Project dan seluruh data turunannya dihapus permanen.')
    } catch (error) {
      try {
        const reconciled = await projectApi.listProjects()
        const targetStillExists = reconciled.projects.some((item) => item.id === project.id)
        const projects = reconciled.projects.filter((item) => !item.archived_at)
        setProductionProjects(projects)
        setProjectCapabilities(reconciled.capabilities)
        if (!targetStillExists) {
          pushRoute('projects')
          setNotice('Project dan seluruh data turunannya dihapus permanen.')
          return
        }
      } catch {
        // Preserve the original command error when authoritative reconciliation is unavailable.
      }
      setNotice(error instanceof Error ? error.message : 'Project belum dapat dihapus.')
    } finally { setProjectBusy(false) }
  }
  const deleteProductionProject = async () => {
    if (productionProject) await deleteProductionProjectById(productionProject.id)
  }
  const addAction = active === 'projects'
    ? { label: 'Tambah Project', run: () => readOnly ? setProjectModal('create') : setModal({ kind: 'project' } as Modal) }
    : active === 'office'
      ? { label: 'Biaya kantor', run: () => setModal({ kind: 'transaction', scope: 'office' } as Modal) }
      : active === 'debts'
        ? { label: 'Tambah hutang', run: () => setModal({ kind: 'debt' } as Modal) }
        : null
  const inProjectDetail = active === 'projects' && Boolean(selectedProject || productionProject)
  const showTopbarAdd = Boolean(addAction) && !inProjectDetail
    && ((!readOnly && ['projects', 'office', 'debts'].includes(active))
      || (canCreateTransactions && active === 'office'))

  const productionFinance = productionProject ? productionFinanceProject(productionProject) : null
  const productionRows = productionProject
    ? finance.workspace.transactions.filter((row) => row.project_id === productionProject.id)
    : []
  const productionTransactions = productionFinance
    ? <section className="recent-command"><header><div><p className="eyebrow">TRANSAKSI Project</p><h2>Aktivitas tercatat</h2></div></header><TransactionRows
        rows={productionRows}
        projects={transactionProjects}
        onCorrect={canMutateTransactions ? (row) => openTransactionMutation(row, 'correction') : undefined}
        onReverse={canMutateTransactions ? (row) => openTransactionMutation(row, 'reversal') : undefined}
        lifecycleBusyId={transactionLifecycleBusyId}
      /></section>
    : null
  const productionProfitability = productionFinance && projectApi
    ? <ProjectProfitabilityWorkspace
        project={productionFinance}
        rows={productionRows}
        api={projectApi}
        session={projectSession}
      />
    : null
  const content = active === 'projects' && projectDataLoading && !projectApiAvailable
    ? <section className="application-state" role="status"><span className="application-state-mark" aria-hidden="true" /><div><p className="eyebrow">DATA Project</p><h2>Memuat data Project</h2><p>Mengambil registry Project terbaru dari server.</p></div></section>
    : active === 'overview'
    ? <OverviewWorkspace workspace={finance.workspace} readOnly={readOnly} onOpenProjects={() => navigate('projects')} onAddProject={!readOnly ? () => setModal({ kind: 'project' }) : projectCapabilities.projectWrites ? () => setProjectModal('create') : undefined} onOpenOffice={() => navigate('office')} onOpenReviews={inboxReviewApi ? () => navigate('inbox-reviews') : undefined} />
    : active === 'cashflow' ? <CashflowWorkspacePage workspace={finance.workspace} onOpenProject={openProjectByName} />
      : active === 'wallets' ? <WalletWorkspacePage workspace={finance.workspace} onOpenProject={openProjectByName} />
        : active === 'projects' && productionProject && projectApi ? <ProjectDetailWorkspace
            project={productionProject}
            tab={route.tab ?? 'transactions'}
            onRouteChange={({ tab }) => setProjectDetailRoute({ projectId: productionProject.id, tab })}
            onBack={backToProjects}
            transactions={productionTransactions}
            overview={productionFinance ? <ProjectOverviewPanel project={productionFinance} workspace={finance.workspace} /> : null}
            debts={productionFinance ? <ProjectDebtPanel project={productionFinance} workspace={finance.workspace} /> : null}
            profitability={productionProfitability}
            presensi={<ProjectPresensiPanel project={productionProject} />}
            documents={<ProjectDocumentsWorkspace project={productionProject} api={projectApi} session={projectSession} route={{ projectId: productionProject.id, tab: route.tab ?? 'documents', document: route.document, type: route.type }} onRouteChange={setProjectDetailRoute} onNotice={setNotice} />}
            audit={productionFinance ? <ProjectAuditPanel project={productionFinance} workspace={finance.workspace} /> : null}
            capabilities={projectCapabilities}
            onEdit={setProjectModal}
            onAddTransaction={productionProject.status === 'active' && canCreateTransactions ? (project) => setModal({ kind: 'transaction', projectId: project.id }) : undefined}
            onOpenDebt={(project) => {
              const borrower = canonicalProjectWallet(project)
              if (!borrower) { setNotice('Dompet Project belum memiliki pemetaan kanonis. Perbarui Project sebelum mencatat hutang.'); return }
              navigate('debts')
              setModal({ kind: 'debt', projectId: project.id, borrower })
            }}
            onStatusChange={changeProductionProjectStatus}
            onDelete={deleteProductionProject}
            busy={projectBusy}
          />
          : active === 'projects' && projectApiAvailable ? <ProjectCommandCenter
              workspace={{ ...finance.workspace, projects: productionProjects.map(productionFinanceProject) }}
              onAdd={() => setProjectModal('create')}
              onEdit={(project) => {
                const record = productionProjects.find((item) => item.id === project.id)
                if (record) setProjectModal(record)
              }}
              onComplete={(project) => void changeProductionProjectStatusById(project.id, 'completed')}
              onQuickComplete={(project) => void changeProductionProjectStatusById(project.id, 'completed')}
              onDelete={(project) => void deleteProductionProjectById(project.id)}
              onOpen={(project) => openProjectDetail(project.id)}
              readOnly={!projectCapabilities.hardDelete}
              canAdd={projectCapabilities.projectWrites}
              destructiveActionLabel="Hapus permanen"
              busy={projectBusy}
              headerAction={readOnly ? <div className="project-registry-refresh"><button type="button" className="secondary-button" onClick={() => void loadProductionProjects()} disabled={projectDataLoading} aria-label="Muat ulang Project"><RefreshCw size={16} /> {projectDataLoading ? 'Memuat Project…' : 'Muat ulang Project'}</button>{projectApiError && projectApiAvailable && <span role="alert">Pembaruan Project gagal: {projectApiError}. Registry terakhir tetap ditampilkan sebagai data lama, bukan sumber terbaru yang otoritatif.</span>}</div> : undefined}
            />
            : active === 'projects' && readOnly ? <section className="application-state application-state-error" role="alert"><div><p className="eyebrow">DATA Project</p><h2>Data Project belum tersedia</h2><p>{projectApiError || 'Layanan Project belum siap. Data snapshot tidak dipakai sebagai pengganti.'}</p><button className="primary-button" onClick={() => void loadProductionProjects()}>Coba lagi</button></div></section>
              : active === 'projects' && selectedProject ? <ProjectTransactionsWorkspace workspace={finance.workspace} project={selectedProject} onBack={backToProjects} onAdd={(project) => setModal({ kind: 'transaction', projectId: project.id })} onEdit={(value) => setModal({ kind: 'transaction', value, projectId: selectedProject.id })} onDelete={(value) => confirmDelete('transaksi', () => finance.removeTransaction(value.id))} onComplete={completeProjectNow} onReactivate={reactivateProject} readOnly={false} canCreateTransactions />
                : active === 'projects' ? <ProjectCommandCenter workspace={finance.workspace} onAdd={() => setModal({ kind: 'project' })} onEdit={(value) => setModal({ kind: 'project', value })} onComplete={(value) => setModal({ kind: 'complete-project', value })} onQuickComplete={completeProjectNow} onDelete={(value) => confirmDelete(`Project ${value.name}`, () => finance.removeProject(value.id))} onOpen={openProject} readOnly={false} />
            : active === 'office' ? <OfficeWorkspace workspace={finance.workspace} onAdd={() => setModal({ kind: 'transaction', scope: 'office' })} onEdit={(value) => setModal({ kind: 'transaction', value })} onDelete={(value) => confirmDelete('biaya kantor', () => finance.removeTransaction(value.id))} onCorrect={canMutateTransactions ? (row) => openTransactionMutation(row, 'correction') : undefined} onReverse={canMutateTransactions ? (row) => openTransactionMutation(row, 'reversal') : undefined} lifecycleBusyId={transactionLifecycleBusyId} readOnly={readOnly} canCreateTransactions={canCreateTransactions} />
              : active === 'debts' ? <DebtWorkspace workspace={finance.workspace} onAdd={() => setModal({ kind: 'debt' })} onEdit={readOnly ? undefined : (value) => setModal({ kind: 'debt', value })} onDelete={readOnly ? undefined : (value) => confirmDelete('hutang internal', () => finance.removeDebt(value.id))} onRepay={readOnly && liveWriteSession?.debtWritesEnabled && onRepayLiveDebt ? (value) => setModal({ kind: 'debt', value }) : undefined} onCorrect={readOnly && liveWriteSession?.debtWritesEnabled && onMutateLiveDebt ? (value) => void onMutateLiveDebt(value, 'correction').then(() => setNotice('Koreksi hutang tersimpan.')).catch((error: unknown) => setNotice(error instanceof Error ? error.message : 'Koreksi hutang gagal.')) : undefined} onReverse={readOnly && liveWriteSession?.debtWritesEnabled && onMutateLiveDebt ? (value) => void onMutateLiveDebt(value, 'reversal').then(() => setNotice('Reversal hutang tersimpan.')).catch((error: unknown) => setNotice(error instanceof Error ? error.message : 'Reversal hutang gagal.')) : undefined} canCreate={!readOnly || Boolean(liveWriteSession?.debtWritesEnabled && onCreateLiveDebt)} />
                : active === 'inbox-reviews' && inboxReviewApi ? <InboxReviewWorkspace api={inboxReviewApi} csrfToken={liveWriteSession?.csrfToken ?? ''} />
                  : <ReportsWorkspace workspace={finance.workspace} />

  return (
    <div className={`app-shell finance-workspace-shell${readOnly ? ' is-readonly' : ''}`}>
      <Sidebar active={active} open={menuOpen} mobile={mobile} live={readOnly} close={closeMenu} navigate={navigate} />
      <main id="main-content" ref={mainRef} className="main-canvas" aria-hidden={mobile && menuOpen ? true : undefined} tabIndex={-1}>
        <header className="topbar">
          <button ref={menuButtonRef} className="icon-button mobile-only" onClick={() => setMenuOpen(true)} aria-label="Buka navigasi" aria-controls="app-navigation" aria-expanded={mobile ? menuOpen : undefined} {...actionProps('shell.navigation-open')}><Menu size={21} /></button>
          <img className="mobile-header-logo" src={hollawallLogo} alt="Hollawall" />
          <div className="breadcrumbs"><span>Hollawall Group</span><b>/</b><strong>{productionProject?.name ?? selectedProject?.name ?? meta.title}</strong></div>
          <div className="topbar-actions">

            {showTopbarAdd && addAction && <button className="topbar-add" onClick={addAction.run}><Plus size={16} /><span>{addAction.label}</span></button>}
            <ThemeToggle theme={theme} setTheme={setTheme} />
          </div>
        </header>
        <div className="content">
          {readOnly && liveSnapshotError && <section className="document-state-alert live-data-warning" role="alert"><strong>Data keuangan tidak terverifikasi.</strong> Pembaruan gagal: {liveSnapshotError.message}. Angka yang tampil adalah pembacaan terakhir, bukan data terbaru.</section>}
          {!readOnly && <p className="demo-mode-label">Mode demo · data browser</p>}
          {readOnly && !canCreateTransactions && active !== 'inbox-reviews' && <p className="form-error">{liveWriteStatus ?? 'Pencatatan transaksi belum tersedia.'}</p>}
          {!readOnly && <DemoBanner updatedAt={finance.workspace.updated_at} onReset={reset} />}
          {!['overview', 'projects', 'reports', 'inbox-reviews'].includes(active) && <header className="page-heading"><div><h1>{meta.title}</h1><p>{meta.copy}</p></div>{!readOnly && <span className="demo-badge">DATA DEMO</span>}</header>}
          {content}
        </div>
      </main>
      {notice && <div className="finance-toast" role="status" aria-live="polite" aria-atomic="true">{notice}</div>}
      {!readOnly && modal?.kind === 'project' && <ProjectForm project={modal.value} onSave={saveProject} onClose={() => setModal(null)} />}
      {!readOnly && modal?.kind === 'complete-project' && <ProjectCompleteDialog project={modal.value} onSave={completeProject} onClose={() => setModal(null)} />}
      {(!readOnly || canCreateTransactions) && modal?.kind === 'transaction' && <TransactionForm projects={transactionProjects} transaction={modal.value} initialScope={modal.scope} lockedProjectId={modal.projectId} onSave={saveTransaction} onClose={() => setModal(null)} liveWrite={readOnly} currentDate={readOnly ? jakartaToday() : undefined} />}
      {!readOnly && modal?.kind === 'debt' && <DebtForm debt={modal.value} onSave={saveDebt} onClose={() => setModal(null)} />}
      {readOnly && modal?.kind === 'debt' && !modal.value && <CanonicalDebtCreateForm projects={transactionProjects} initialProjectId={modal.projectId} initialBorrower={modal.borrower} saving={debtBusy} onSave={saveLiveDebt} onClose={() => setModal(null)} />}
      {readOnly && modal?.kind === 'debt' && modal.value && <CanonicalDebtRepaymentForm debt={modal.value} saving={debtBusy} onSave={(amount, occurredOn, description) => repayLiveDebt(modal.value!, amount, occurredOn, description)} onClose={() => setModal(null)} />}
      {readOnly && transactionMutationTarget && <CanonicalTransactionMutationDialog row={transactionMutationTarget.row} action={transactionMutationTarget.action} saving={transactionLifecycleBusyId === transactionMutationTarget.row.id} onSubmit={submitTransactionMutation} onClose={() => { if (!transactionLifecycleBusyId) setTransactionMutationTarget(null) }} />}
      {projectModal && <ProjectRecordForm project={projectModal === 'create' ? undefined : projectModal} clients={productionProjects} saving={projectBusy} onSave={saveProductionProject} onClose={() => setProjectModal(null)} />}
    </div>
  )
}

export default function App() {
  return <LiveDashboardApp />
}

function LiveDashboardApp() {
  const state = useLiveSnapshot({ endpoint: '/admin/api/snapshot.php' })
  const projectApi = useMemo(() => createProjectDocumentApi(), [])
  const inboxReviewApi = useMemo(() => createInboxReviewApi(), [])
  const [writeSession, setWriteSession] = useState<TransactionWriteSession>()
  const [writeStatus, setWriteStatus] = useState('Memeriksa kemampuan pencatatan transaksi…')
  const pendingAttempt = useRef<TransactionWriteAttempt | null>(null)
  const pendingMutation = useRef<{ signature: string; command: ReturnType<typeof createCanonicalTransactionMutation> } | null>(null)
  const workspace = useMemo(() => state.status === 'ready' ? snapshotFinanceWorkspace(state.data) : null, [state])

  useEffect(() => {
    const controller = new AbortController()
    loadTransactionWriteSession().then((session) => {
      if (controller.signal.aborted) return
      setWriteSession(session)
      setWriteStatus(session.canonicalWritesEnabled
        ? ''
        : 'Pencatatan transaksi belum tersedia sampai konfigurasi produksi diaktifkan.')
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      setWriteSession(undefined)
      setWriteStatus(error instanceof Error ? error.message : 'Pencatatan transaksi belum tersedia.')
    })
    return () => controller.abort()
  }, [])

  const createLiveTransaction = async (input: TransactionFormInput) => {
    if (!writeSession?.canonicalWritesEnabled) throw new Error(writeStatus || 'Pencatatan transaksi belum tersedia.')
    if (!Number.isSafeInteger(input.amount) || input.amount <= 0) throw new Error('Jumlah harus berupa rupiah bulat lebih dari nol.')
    if (!input.wallet || !input.company || !input.category) throw new Error('Pilihan transaksi belum lengkap.')
    const description = input.notes
    if (!description || description !== description.trim() || description !== description.split(/\s+/).join(' ')) {
      throw new Error('Keterangan wajib diisi tanpa spasi berlebih di awal, akhir, atau tengah.')
    }
    if (/^[=+\-@]/.test(description)) throw new Error('Keterangan tidak boleh diawali =, +, -, atau @.')
    const projectId = input.scope === 'project' ? input.project_id?.trim() : null
    if (input.scope === 'project' && !projectId) throw new Error('Project ini belum tersedia untuk pencatatan.')
    const payload: TransactionWritePayload = {
      date: input.date,
      scope: input.scope,
      direction: input.direction === 'income' ? 'Pemasukan' : 'Pengeluaran',
      amount: input.amount,
      description,
      wallet: input.wallet,
      company: input.company,
      category: input.category,
      ...(input.scope === 'project' ? { project: projectId! } : {}),
    }
    if (pendingAttempt.current && !sameTransactionPayload(pendingAttempt.current.payload, payload)) {
      throw new Error('Ada transaksi sebelumnya dengan status belum pasti. Muat ulang data atau coba lagi transaksi yang sama; transaksi berbeda belum dikirim.')
    }
    if (!pendingAttempt.current) {
      pendingAttempt.current = createTransactionWriteAttempt(payload)
    }
    try {
      const result = await pendingAttempt.current.submit(writeSession)
      pendingAttempt.current = null
      return { ...result, readback: state.reload({ afterActive: true }).then(() => undefined) }
    } catch (error) {
      if (!(error && typeof error === 'object' && 'uncertain' in error && error.uncertain)) {
        pendingAttempt.current = null
      }
      throw error
    }
  }

  const mutateLiveTransaction = async (row: FinanceTransaction, action: 'correction' | 'reversal', draft: TransactionMutationDraft) => {
    if (!writeSession?.canonicalWritesEnabled || !row.canonical_transaction_id || !row.transaction_version) {
      throw new Error('Lifecycle transaksi belum tersedia.')
    }
    const input = {
      action,
      transactionId: row.canonical_transaction_id,
      expectedVersion: row.transaction_version,
      ...draft,
    }
    const signature = JSON.stringify(input)
    if (pendingMutation.current && pendingMutation.current.signature !== signature) {
      throw new Error('Perubahan sebelumnya belum dapat dipastikan. Coba lagi dengan isian yang sama atau muat ulang data sebelum membuat perubahan lain.')
    }
    if (!pendingMutation.current) {
      pendingMutation.current = { signature, command: createCanonicalTransactionMutation(input) }
    }
    try {
      await pendingMutation.current.command.submit(writeSession)
      pendingMutation.current = null
      try {
        await state.reload()
        return { readbackFailed: false }
      } catch {
        return { readbackFailed: true }
      }
    } catch (error) {
      if (!(error && typeof error === 'object' && 'uncertain' in error && error.uncertain)) {
        pendingMutation.current = null
      }
      throw error
    }
  }

  const createLiveDebt = async (input: CanonicalDebtCreateInput) => {
    if (!writeSession?.debtWritesEnabled) throw new Error('Pencatatan hutang belum tersedia.')
    const lender = canonicalDebtIdentity(input.lender)
    const borrower = canonicalDebtIdentity(input.borrower)
    const attempt = createDebtAttempt({
      lenderWalletId: lender.walletId,
      borrowerWalletId: borrower.walletId,
      lenderBusinessUnitId: lender.businessUnitId,
      borrowerBusinessUnitId: borrower.businessUnitId,
      projectId: input.projectId,
      principal: input.principal,
      occurredAt: `${input.occurredOn}T12:00:00+07:00`,
      dueAt: input.dueOn ? `${input.dueOn}T12:00:00+07:00` : null,
      description: input.description,
    })
    await attempt.submit(writeSession)
    await state.reload()
  }

  const repayLiveDebt = async (debt: FinanceDebt, amount: number, occurredOn: string, description: string) => {
    if (!writeSession?.debtWritesEnabled || !debt.version) throw new Error('Pembayaran hutang belum tersedia.')
    const attempt = createDebtRepaymentAttempt({
      debtId: debt.id,
      expectedVersion: debt.version,
      amount,
      occurredAt: `${occurredOn}T12:00:00+07:00`,
      description,
    })
    await attempt.submit(writeSession)
    await state.reload()
  }

  const mutateLiveDebt = async (debt: FinanceDebt, action: 'correction' | 'reversal') => {
    if (!writeSession?.debtWritesEnabled || !debt.version) throw new Error('Lifecycle hutang belum tersedia.')
    const events = debt.events ?? []
    const claimed = new Set(events.flatMap((event) => [event.corrects_event_id, event.reverses_event_id].filter(Boolean)))
    const target = [...events].reverse().find((event) => event.event_type !== 'reversal' && !claimed.has(event.id))
    if (!target) throw new Error('Kejadian hutang yang dapat diubah tidak ditemukan.')
    const reason = window.prompt(action === 'correction' ? 'Alasan koreksi hutang:' : 'Alasan reversal hutang:')?.trim()
    if (!reason) return
    const occurredAt = `${jakartaToday()}T12:00:00+07:00`
    const input = { debtId: debt.id, eventId: target.id, expectedVersion: debt.version, occurredAt, reason }
    const attempt = action === 'correction'
      ? createDebtCorrectionAttempt({ ...input, amount: Number(window.prompt('Nominal pengganti:', String(target.amount))) })
      : createDebtReversalAttempt(input)
    await attempt.submit(writeSession)
    await state.reload()
  }

  if (state.status === 'loading') return <main className="application-state" role="status"><span className="application-state-mark" aria-hidden="true" /><div><p className="eyebrow">RUANG FINANSIAL</p><h1>Memuat data keuangan</h1><p>Menyiapkan posisi kas, Project, dan laporan terbaru.</p></div></main>
  if (state.status === 'error') return <main className="application-state application-state-error" role="alert"><div><p className="eyebrow">DATA PRODUKSI</p><h1>Data belum tersedia</h1><p>Data demo tidak ditampilkan sebagai pengganti. Periksa koneksi, lalu coba lagi.</p><button className="primary-button" onClick={() => void state.reload()}>Coba lagi</button></div></main>
  return workspace ? <DemoApp suppliedWorkspace={workspace} liveSnapshotError={state.error} liveWriteSession={writeSession} liveWriteStatus={writeStatus} onCreateLiveTransaction={createLiveTransaction} onMutateLiveTransaction={mutateLiveTransaction} onCreateLiveDebt={createLiveDebt} onRepayLiveDebt={repayLiveDebt} onMutateLiveDebt={mutateLiveDebt} projectApi={projectApi} inboxReviewApi={inboxReviewApi} /> : null
}
