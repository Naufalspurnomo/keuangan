import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChart3,
  BriefcaseBusiness,
  Building2,

  FileBarChart,
  Inbox,
  Landmark,
  LayoutDashboard,
  LockKeyhole,
  Menu,
  Moon,
  Plus,
  Sun,
  WalletCards,
  X,
} from 'lucide-react'

import { DebtForm, ProjectForm, TransactionForm } from './FinanceForms'
import {
  CashflowWorkspacePage,
  DebtWorkspace,
  DemoBanner,
  ExportButton,
  OfficeWorkspace,
  OverviewWorkspace,

  WalletWorkspacePage,
} from './FinancePages'
import ProjectCommandCenter from './ProjectCommandCenter'
import ProjectCompleteDialog from './ProjectCompleteDialog'
import ProjectDetailWorkspace from './ProjectDetailWorkspace'
import ProjectDocumentsWorkspace from './ProjectDocumentsWorkspace'
import ProjectPresensiPanel from './ProjectPresensiPanel'
import ProjectProfitabilityWorkspace from './ProjectProfitabilityWorkspace'
import ProjectRecordForm from './ProjectRecordForm'
import ProjectTransactionsWorkspace from './ProjectTransactionsWorkspace'
import ProductionProjectsWorkspace from './ProductionProjectsWorkspace'
import ReportsWorkspace from './ReportsWorkspace'
import InboxReviewWorkspace from './InboxReviewWorkspace'
import type { CompanyId, FinanceDebt, FinanceProject, FinanceTransaction, FinanceWorkspace, ProjectInput, TransactionInput, TransactionFormInput, DebtInput, WalletId } from './financeWorkspace'
import { snapshotFinanceWorkspace } from './snapshot'
import { useLiveSnapshot } from './liveSnapshotView'
import { createTransactionWriteAttempt, jakartaToday, loadTransactionWriteSession, type RecordedTransaction, type TransactionWriteAttempt, type TransactionWriteSession } from './transactionApi'
import { useFinanceWorkspace } from './useFinanceWorkspace'
import hollawallLogo from './assets/hollawall-logo.png'
import { createProjectDocumentApi, type ProjectDocumentApi, type ProjectDocumentSession } from './projectDocumentApi'
import { createInboxReviewApi, type InboxReviewApi } from './inboxReviewApi'
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
  | { kind: 'debt'; value?: FinanceDebt }
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
  overview: { eyebrow: 'RINGKASAN', title: 'Ringkasan', copy: 'Posisi keuangan dari seluruh sumber data.' },
  cashflow: { eyebrow: 'ARUS KAS', title: 'Arus Kas', copy: 'Pemasukan dan pengeluaran per bulan.' },
  wallets: { eyebrow: 'SUMBER DANA', title: 'Dompet', copy: 'Posisi CV HB, TX SBY, dan TX Bali.' },

  projects: { eyebrow: 'PORTOFOLIO', title: 'Proyek', copy: 'Kinerja proyek per tahun, perusahaan, dan status.' },
  office: { eyebrow: 'KEBUTUHAN KANTOR', title: 'Operasional Kantor', copy: 'Biaya kantor yang terpisah dari proyek.' },
  debts: { eyebrow: 'PERGERAKAN INTERNAL', title: 'Hutang Internal', copy: 'Hutang antar-dompet tanpa mengubah kas konsolidasi.' },
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
    ['overview', 'Ringkasan', LayoutDashboard], ['cashflow', 'Arus Kas', BarChart3], ['wallets', 'Dompet', WalletCards],
    ['projects', 'Proyek', BriefcaseBusiness], ['office', 'Operasional Kantor', Building2],
    ['debts', 'Hutang Internal', Landmark], ['reports', 'Laporan', FileBarChart],
    ...(live ? [['inbox-reviews', 'Perlu Ditinjau', Inbox] as const] : []),
  ]
  const hidden = mobile && !open
  return <>{mobile && open && <button type="button" className="mobile-overlay is-open" onClick={close} aria-label="Tutup navigasi" />}<aside id="app-navigation" className={`sidebar ${open ? 'is-open' : ''}`} aria-hidden={hidden || undefined}><div className="sidebar-head"><img src={hollawallLogo} alt="Hollawall" /><button ref={closeButtonRef} tabIndex={hidden ? -1 : 0} className="icon-button mobile-only" onClick={close} aria-label="Tutup navigasi"><X size={20} /></button></div><div className="workspace-switch"><Building2 size={18} /><span><small>Ruang kerja</small>Hollawall Group</span></div><nav aria-label="Menu utama">{items.map(([key, label, Icon]) => <button type="button" tabIndex={hidden ? -1 : 0} key={key} className={active === key ? 'active' : ''} aria-current={active === key ? 'page' : undefined} onClick={() => { navigate(key); close() }}><Icon size={18} /><span>{label}</span></button>)}</nav><div className="sidebar-bottom"><div className="profile workspace-profile"><span><LockKeyhole size={15} /></span><div><strong>{live ? 'Keuangan Hollawall' : 'Workspace demo'}</strong><small>{live ? 'Ringkasan dan laporan' : 'Data lokal · Teraudit'}</small></div></div></div></aside></>
}

function ThemeToggle({ theme, setTheme }: { theme: string; setTheme: (theme: string) => void }) {
  const dark = theme === 'dark'
  return <button type="button" className="theme-toggle" onClick={() => setTheme(dark ? 'light' : 'dark')} aria-label={`Gunakan tema ${dark ? 'terang' : 'gelap'}`} aria-pressed={dark} title={`Tema ${dark ? 'gelap' : 'terang'}`}><Sun size={16} aria-hidden="true" /><span className={theme} aria-hidden="true" /><Moon size={16} aria-hidden="true" /></button>
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
    status: project.status === 'cancelled' ? 'completed' : project.status,
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

export function DemoApp({ suppliedWorkspace, liveWriteSession, liveWriteStatus, onCreateLiveTransaction, projectApi, inboxReviewApi }: { suppliedWorkspace?: Readonly<FinanceWorkspace>; liveWriteSession?: TransactionWriteSession; liveWriteStatus?: string; onCreateLiveTransaction?: (input: TransactionFormInput) => Promise<RecordedTransaction>; projectApi?: ProjectDocumentApi; inboxReviewApi?: InboxReviewApi } = {}) {
  const finance = useFinanceWorkspace(suppliedWorkspace)
  const readOnly = finance.readOnly
  const canCreateTransactions = readOnly && liveWriteSession?.writesEnabled === true && Boolean(onCreateLiveTransaction)
  const initialRoute = useRef(currentRoute()).current
  const [route, setRoute] = useState<AppRoute>(initialRoute)
  const { page: active, projectId: projectFilter } = route
  const [menuOpen, setMenuOpen] = useState(false)
  const [modal, setModal] = useState<Modal>(null)
  const [projectModal, setProjectModal] = useState<ProjectRecord | 'create' | null>(null)
  const [productionProjects, setProductionProjects] = useState<ProjectRecord[]>([])
  const [projectCapabilities, setProjectCapabilities] = useState<ProjectDocumentCapabilities>(NO_PROJECT_DOCUMENT_WRITES)
  const [projectDataLoading, setProjectDataLoading] = useState(Boolean(readOnly && projectApi))
  const [projectApiAvailable, setProjectApiAvailable] = useState(false)
  const [projectBusy, setProjectBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
  const mobile = useMobileNavigation()
  const previousMobile = useRef(mobile)
  const pendingScroll = useRef<number | null>(null)
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

  const loadProductionProjects = async () => {
    if (!readOnly || !projectApi) return
    setProjectDataLoading(true)
    try {
      const result = await projectApi.listProjects()
      const projects = result.projects.filter((project) => !project.archived_at)
      setProductionProjects(projects)
      setProjectCapabilities(result.capabilities)
      setProjectApiAvailable(projects.length > 0 || result.capabilities.projectWrites)
    } catch {
      setProductionProjects([])
      setProjectCapabilities(NO_PROJECT_DOCUMENT_WRITES)
      setProjectApiAvailable(false)
    } finally { setProjectDataLoading(false) }
  }

  useEffect(() => { void loadProductionProjects() }, [projectApi, readOnly])
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
    setNotice('Proyek tidak ditemukan.')
  }, [active, productionProject, projectDataLoading, projectFilter, selectedProject])

  const pushRoute = (page: Page, projectId?: string) => {
    if (active === page && projectFilter === projectId) return
    window.history.replaceState({ ...window.history.state, page: active, projectId: projectFilter, scrollY: window.scrollY }, '', window.location.href)
    window.history.pushState({ page, projectId, scrollY: 0, fromPage: active }, '', routeHash(page, projectId))
    setRoute({ page, projectId })
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: 'auto' }))
  }
  const navigate = (page: Page) => pushRoute(page)
  const setProjectDetailRoute = (detail: ProjectDocumentRoute) => {
    const next: AppRoute = { page: 'projects', projectId: detail.projectId, tab: detail.tab, document: detail.document, type: detail.type }
    window.history.pushState({ ...next, scrollY: 0 }, '', routeHash('projects', detail.projectId, detail))
    setRoute(next)
  }
  const backToProjects = () => window.history.state?.fromPage === 'projects' ? window.history.back() : pushRoute('projects')
  const closeMenu = () => { setMenuOpen(false); if (mobile) window.requestAnimationFrame(() => menuButtonRef.current?.focus()) }
  const commit = (action: () => void, success: string) => { if (readOnly) throw new Error('Data ini hanya dapat dilihat.'); action(); setNotice(success) }
  const safe = (action: () => void, success: string) => { try { commit(action, success) } catch (error) { setNotice(error instanceof Error ? error.message : 'Tindakan belum dapat diproses.') } }
  const saveProject = (input: ProjectInput) => modal?.kind === 'project' && modal.value
    ? commit(() => finance.editProject(modal.value!.id, input), 'Proyek diperbarui.')
    : commit(() => finance.addProject(input), 'Proyek ditambahkan.')
  const completeProject = (input: ProjectInput) => modal?.kind === 'complete-project'
    && commit(() => finance.editProject(modal.value.id, input), 'Proyek diselesaikan.')
  const completeProjectNow = (project: FinanceProject) => {
    const latestTransaction = finance.workspace.transactions.filter((row) => row.project_id === project.id).reduce((latest, row) => row.date > latest ? row.date : latest, project.started_on)
    const completedOn = [localIsoDate(), project.started_on, latestTransaction].sort().at(-1)!
    safe(() => finance.editProject(project.id, projectStatusInput(project, 'completed', completedOn)), 'Proyek diselesaikan.')
  }
  const reactivateProject = (project: FinanceProject) => safe(() => finance.editProject(project.id, projectStatusInput(project, 'active', null)), 'Proyek diaktifkan kembali.')
  const saveTransaction = (input: TransactionFormInput) => {
    if (readOnly) {
      if (!canCreateTransactions || !onCreateLiveTransaction) throw new Error('Pencatatan transaksi belum tersedia.')
      return onCreateLiveTransaction(input).then((result) => {
        setNotice(`Transaksi tercatat di ${result.sheetName}, baris ${result.sheetRow}. Tampilan sedang diperbarui.`)
      })
    }
    const { category: _category, ...demoInput } = input
    return modal?.kind === 'transaction' && modal.value
      ? commit(() => finance.editTransaction(modal.value!.id, demoInput as TransactionInput), 'Transaksi diperbarui.')
      : commit(() => finance.addTransaction(demoInput as TransactionInput), 'Transaksi ditambahkan.')
  }
  const saveDebt = (input: DebtInput) => modal?.kind === 'debt' && modal.value
    ? commit(() => finance.editDebt(modal.value!.id, input), 'Hutang diperbarui.')
    : commit(() => finance.addDebt(input), 'Hutang ditambahkan.')
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
      const command = projectModal === 'create'
        ? projectApi.createProject(draft)
        : projectApi.updateProject(projectModal!.id, draft, projectModal!.lock_version)
      const saved = await command.submit(projectSession)
      const current = await projectApi.getProject(saved.id)
      setProductionProjects((projects) => projects.some((project) => project.id === current.id)
        ? projects.map((project) => project.id === current.id ? current : project)
        : [current, ...projects])
      setProjectModal(null)
      setNotice('Proyek disimpan dan ditampilkan kembali.')
    } finally { setProjectBusy(false) }
  }
  const changeProductionProjectStatus = async (status: ProductionProjectStatus) => {
    if (!projectApi || !productionProject) return
    setProjectBusy(true)
    try {
      const saved = await projectApi.setProjectStatus(productionProject.id, status, productionProject.lock_version).submit(projectSession)
      const current = await projectApi.getProject(saved.id)
      setProductionProjects((projects) => projects.map((project) => project.id === current.id ? current : project))
      setNotice('Status proyek diperbarui.')
    } finally { setProjectBusy(false) }
  }
  const archiveProductionProject = async () => {
    if (!projectApi || !productionProject || !window.confirm(`Arsipkan proyek ${productionProject.name}?`)) return
    setProjectBusy(true)
    try {
      await projectApi.archiveProject(productionProject.id, productionProject.lock_version).submit(projectSession)
      await loadProductionProjects()
      pushRoute('projects')
      setNotice('Proyek diarsipkan.')
    } finally { setProjectBusy(false) }
  }
  const addAction = active === 'projects'
    ? selectedProject
      ? { label: 'Tambah transaksi', run: () => setModal({ kind: 'transaction', projectId: selectedProject.id } as Modal) }
      : { label: 'Tambah proyek', run: () => setModal({ kind: 'project' } as Modal) }
    : active === 'office'
      ? { label: 'Biaya kantor', run: () => setModal({ kind: 'transaction', scope: 'office' } as Modal) }
      : active === 'debts'
        ? { label: 'Tambah hutang', run: () => setModal({ kind: 'debt' } as Modal) }
        : { label: 'Tambah transaksi', run: () => setModal({ kind: 'transaction' } as Modal) }

  const productionTransactions = productionProject && projectApi
    ? <ProjectProfitabilityWorkspace
        project={productionFinanceProject(productionProject)}
        rows={finance.workspace.transactions.filter((row) => row.project_id === productionProject.id)}
        projects={transactionProjects}
        api={projectApi}
        session={projectSession}
      />
    : null
  const content = active === 'overview'
    ? <OverviewWorkspace workspace={finance.workspace} readOnly={readOnly} canCreateTransactions={canCreateTransactions} onAddTransaction={() => setModal({ kind: 'transaction' })} onAddProject={() => setModal({ kind: 'project' })} onAddOffice={() => setModal({ kind: 'transaction', scope: 'office' })} />
    : active === 'cashflow' ? <CashflowWorkspacePage workspace={finance.workspace} onOpenProject={openProjectByName} />
      : active === 'wallets' ? <WalletWorkspacePage workspace={finance.workspace} onOpenProject={openProjectByName} />
        : active === 'projects' && productionProject && projectApi ? <ProjectDetailWorkspace
            project={productionProject}
            tab={route.tab ?? 'transactions'}
            onRouteChange={({ tab }) => setProjectDetailRoute({ projectId: productionProject.id, tab })}
            onBack={backToProjects}
            transactions={productionTransactions}
            presensi={<ProjectPresensiPanel project={productionProject} />}
            documents={<ProjectDocumentsWorkspace project={productionProject} api={projectApi} session={projectSession} route={{ projectId: productionProject.id, tab: route.tab ?? 'documents', document: route.document, type: route.type }} onRouteChange={setProjectDetailRoute} />}
            capabilities={projectCapabilities}
            onEdit={setProjectModal}
            onStatusChange={changeProductionProjectStatus}
            onArchive={archiveProductionProject}
          />
          : active === 'projects' && projectApiAvailable ? <ProductionProjectsWorkspace projects={productionProjects} capabilities={projectCapabilities} loading={projectDataLoading} onAdd={() => setProjectModal('create')} onEdit={setProjectModal} onOpen={(project) => setProjectDetailRoute({ projectId: project.id, tab: 'transactions' })} />
            : active === 'projects' && selectedProject ? <ProjectTransactionsWorkspace workspace={finance.workspace} project={selectedProject} onBack={backToProjects} onAdd={(project) => setModal({ kind: 'transaction', projectId: project.id })} onEdit={readOnly ? () => undefined : (value) => setModal({ kind: 'transaction', value, projectId: selectedProject.id })} onDelete={readOnly ? () => undefined : (value) => confirmDelete('transaksi', () => finance.removeTransaction(value.id))} onComplete={readOnly ? () => undefined : completeProjectNow} onReactivate={readOnly ? () => undefined : reactivateProject} readOnly={readOnly} canCreateTransactions={canCreateTransactions} />
              : active === 'projects' ? <ProjectCommandCenter workspace={finance.workspace} onAdd={() => setModal({ kind: 'project' })} onEdit={(value) => setModal({ kind: 'project', value })} onComplete={(value) => setModal({ kind: 'complete-project', value })} onQuickComplete={completeProjectNow} onDelete={(value) => confirmDelete(`proyek ${value.name}`, () => finance.removeProject(value.id))} onOpen={openProject} readOnly={readOnly} />
            : active === 'office' ? <OfficeWorkspace workspace={finance.workspace} onAdd={() => setModal({ kind: 'transaction', scope: 'office' })} onEdit={(value) => setModal({ kind: 'transaction', value })} onDelete={(value) => confirmDelete('biaya kantor', () => finance.removeTransaction(value.id))} readOnly={readOnly} canCreateTransactions={canCreateTransactions} />
              : active === 'debts' ? <DebtWorkspace workspace={finance.workspace} onAdd={() => setModal({ kind: 'debt' })} onEdit={(value) => setModal({ kind: 'debt', value })} onDelete={(value) => confirmDelete('hutang internal', () => finance.removeDebt(value.id))} />
                : active === 'inbox-reviews' && inboxReviewApi ? <InboxReviewWorkspace api={inboxReviewApi} csrfToken={liveWriteSession?.csrfToken ?? ''} />
                  : <ReportsWorkspace workspace={finance.workspace} />

  return (
    <div className={`app-shell finance-workspace-shell${readOnly ? ' is-readonly' : ''}`}>
      <Sidebar active={active} open={menuOpen} mobile={mobile} live={readOnly} close={closeMenu} navigate={navigate} />
      <main id="main-content" ref={mainRef} className="main-canvas" aria-hidden={mobile && menuOpen ? true : undefined} tabIndex={-1}>
        <header className="topbar">
          <button ref={menuButtonRef} className="icon-button mobile-only" onClick={() => setMenuOpen(true)} aria-label="Buka navigasi" aria-controls="app-navigation" aria-expanded={mobile ? menuOpen : undefined}><Menu size={21} /></button>
          <img className="mobile-header-logo" src={hollawallLogo} alt="Hollawall" />
          <div className="breadcrumbs"><span>Hollawall Group</span><b>/</b><strong>{mobile ? meta.title : productionProject?.name ?? selectedProject?.name ?? meta.title}</strong></div>
          <div className="topbar-actions">
            {active === 'projects' && <ExportButton workspace={finance.workspace} />}
            {((!readOnly && active !== 'reports' && active !== 'inbox-reviews') || (canCreateTransactions && active !== 'reports' && active !== 'debts' && active !== 'inbox-reviews' && !(active === 'projects' && !selectedProject))) && <button className="topbar-add" onClick={addAction.run}><Plus size={16} /><span>{addAction.label}</span></button>}
            <ThemeToggle theme={theme} setTheme={setTheme} />
          </div>
        </header>
        <div className="content">
          {!readOnly && <p className="demo-mode-label">Mode demo · data browser</p>}
          {readOnly && !canCreateTransactions && active !== 'inbox-reviews' && <p className="form-error">{liveWriteStatus ?? 'Pencatatan transaksi belum tersedia.'}</p>}
          {!readOnly && <DemoBanner updatedAt={finance.workspace.updated_at} onReset={reset} />}
          {!['overview', 'projects', 'reports', 'inbox-reviews'].includes(active) && <header className="page-heading"><div><p className="eyebrow">{meta.eyebrow}</p><h1>{meta.title}</h1><p>{meta.copy}</p></div>{!readOnly && <span className="demo-badge">DATA DEMO</span>}</header>}
          {content}
        </div>
      </main>
      {notice && <div className="finance-toast" role="status">{notice}</div>}
      {!readOnly && modal?.kind === 'project' && <ProjectForm project={modal.value} onSave={saveProject} onClose={() => setModal(null)} />}
      {!readOnly && modal?.kind === 'complete-project' && <ProjectCompleteDialog project={modal.value} onSave={completeProject} onClose={() => setModal(null)} />}
      {(!readOnly || canCreateTransactions) && modal?.kind === 'transaction' && <TransactionForm projects={transactionProjects} transaction={modal.value} initialScope={modal.scope} lockedProjectId={modal.projectId} onSave={saveTransaction} onClose={() => setModal(null)} liveWrite={readOnly} currentDate={readOnly ? jakartaToday() : undefined} />}
      {!readOnly && modal?.kind === 'debt' && <DebtForm debt={modal.value} onSave={saveDebt} onClose={() => setModal(null)} />}
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
  const workspace = useMemo(() => state.status === 'ready' ? snapshotFinanceWorkspace(state.data) : null, [state])

  useEffect(() => {
    const controller = new AbortController()
    loadTransactionWriteSession().then((session) => {
      if (controller.signal.aborted) return
      setWriteSession(session)
      setWriteStatus(session.writesEnabled
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
    if (!writeSession?.writesEnabled) throw new Error(writeStatus || 'Pencatatan transaksi belum tersedia.')
    if (!Number.isSafeInteger(input.amount) || input.amount <= 0) throw new Error('Jumlah harus berupa rupiah bulat lebih dari nol.')
    if (input.date !== jakartaToday()) throw new Error('Tanggal transaksi harus tanggal Jakarta hari ini.')
    if (!input.wallet || !input.company || !input.category) throw new Error('Pilihan transaksi belum lengkap.')
    const description = input.notes
    if (!description || description !== description.trim() || description !== description.split(/\s+/).join(' ')) {
      throw new Error('Keterangan wajib diisi tanpa spasi berlebih di awal, akhir, atau tengah.')
    }
    if (/^[=+\-@]/.test(description)) throw new Error('Keterangan tidak boleh diawali =, +, -, atau @.')
    const projectId = input.scope === 'project' ? input.project_id?.trim() : null
    if (input.scope === 'project' && !projectId) throw new Error('Proyek ini belum tersedia untuk pencatatan.')
    if (!pendingAttempt.current) {
      pendingAttempt.current = createTransactionWriteAttempt({
        date: input.date,
        scope: input.scope,
        direction: input.direction === 'income' ? 'Pemasukan' : 'Pengeluaran',
        amount: input.amount,
        description,
        wallet: input.wallet,
        company: input.company,
        category: input.category,
        ...(input.scope === 'project' ? { project: projectId! } : {}),
      })
    }
    try {
      const result = await pendingAttempt.current.submit(writeSession)
      pendingAttempt.current = null
      state.reload()
      return result
    } catch (error) {
      if (!(error && typeof error === 'object' && 'uncertain' in error && error.uncertain)) {
        pendingAttempt.current = null
      }
      throw error
    }
  }

  if (state.status === 'loading') return <main className="application-state" role="status"><span className="application-state-mark" aria-hidden="true" /><div><p className="eyebrow">RUANG FINANSIAL</p><h1>Memuat data keuangan</h1><p>Menyiapkan posisi kas, proyek, dan laporan terbaru.</p></div></main>
  if (state.status === 'error') return <main className="application-state application-state-error" role="alert"><div><p className="eyebrow">DATA PRODUKSI</p><h1>Data belum tersedia</h1><p>Data demo tidak ditampilkan sebagai pengganti. Periksa koneksi, lalu coba lagi.</p><button className="primary-button" onClick={() => void state.reload()}>Coba lagi</button></div></main>
  return workspace ? <DemoApp suppliedWorkspace={workspace} liveWriteSession={writeSession} liveWriteStatus={writeStatus} onCreateLiveTransaction={createLiveTransaction} projectApi={projectApi} inboxReviewApi={inboxReviewApi} /> : null
}
