import { useEffect, useRef, useState } from 'react'
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
import ProjectTransactionsWorkspace from './ProjectTransactionsWorkspace'
import ReportsWorkspace from './ReportsWorkspace'
import type { FinanceDebt, FinanceProject, FinanceTransaction, ProjectInput, TransactionInput, DebtInput } from './financeWorkspace'
import { useFinanceWorkspace } from './useFinanceWorkspace'
import hollawallLogo from './assets/hollawall-logo.png'

type Page = 'overview' | 'cashflow' | 'wallets' | 'projects' | 'office' | 'debts' | 'reports'
type Modal =
  | { kind: 'project'; value?: FinanceProject }
  | { kind: 'transaction'; value?: FinanceTransaction; scope?: 'project' | 'office'; projectId?: string }
  | { kind: 'debt'; value?: FinanceDebt }
  | null
const MOBILE_NAVIGATION_QUERY = '(max-width: 900px)'
const PAGES: Page[] = ['overview', 'cashflow', 'wallets', 'projects', 'office', 'debts', 'reports']

function routeHash(page: Page, projectId?: string) {
  return `#${page}${page === 'projects' && projectId ? `?project=${encodeURIComponent(projectId)}` : ''}`
}

function currentRoute(): { page: Page; projectId?: string } {
  const [rawPage, rawQuery = ''] = window.location.hash.replace(/^#/, '').split('?')
  const params = new URLSearchParams(rawQuery)
  if (rawPage === 'transactions') {
    const projectId = params.get('project') || undefined
    const canonical = routeHash('projects', projectId)
    window.history.replaceState({ page: 'projects', projectId, scrollY: 0 }, '', canonical)
    return { page: 'projects', projectId }
  }
  const page = PAGES.includes(rawPage as Page) ? rawPage as Page : 'overview'
  const projectId = page === 'projects' ? params.get('project') || undefined : undefined
  return { page, projectId }
}

const pageMeta: Record<Page, { eyebrow: string; title: string; copy: string }> = {
  overview: { eyebrow: 'RINGKASAN', title: 'Ringkasan', copy: 'Posisi keuangan dari seluruh data demo.' },
  cashflow: { eyebrow: 'ARUS KAS', title: 'Arus Kas', copy: 'Pemasukan dan pengeluaran per bulan.' },
  wallets: { eyebrow: 'SUMBER DANA', title: 'Dompet', copy: 'Posisi CV HB, TX SBY, dan TX Bali.' },

  projects: { eyebrow: 'PORTOFOLIO', title: 'Proyek', copy: 'Kinerja proyek per tahun, perusahaan, dan status.' },
  office: { eyebrow: 'KEBUTUHAN KANTOR', title: 'Operasional Kantor', copy: 'Biaya kantor yang terpisah dari proyek.' },
  debts: { eyebrow: 'PERGERAKAN INTERNAL', title: 'Hutang Internal', copy: 'Hutang antar-dompet tanpa mengubah kas konsolidasi.' },
  reports: { eyebrow: 'PELAPORAN', title: 'Laporan', copy: 'Filter, pratinjau, dan ekspor PDF.' },
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

function Sidebar({ active, open, mobile, close, navigate }: { active: Page; open: boolean; mobile: boolean; close: () => void; navigate: (page: Page) => void }) {
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (mobile && open) closeButtonRef.current?.focus() }, [mobile, open])
  const items = [
    ['overview', 'Ringkasan', LayoutDashboard], ['cashflow', 'Arus Kas', BarChart3], ['wallets', 'Dompet', WalletCards],
    ['projects', 'Proyek', BriefcaseBusiness], ['office', 'Operasional Kantor', Building2],
    ['debts', 'Hutang Internal', Landmark], ['reports', 'Laporan', FileBarChart],
  ] as const
  const hidden = mobile && !open
  return <>{mobile && open && <button type="button" className="mobile-overlay is-open" onClick={close} aria-label="Tutup navigasi" />}<aside id="app-navigation" className={`sidebar ${open ? 'is-open' : ''}`} aria-hidden={hidden || undefined}><div className="sidebar-head"><img src={hollawallLogo} alt="Hollawall" /><button ref={closeButtonRef} tabIndex={hidden ? -1 : 0} className="icon-button mobile-only" onClick={close} aria-label="Tutup navigasi"><X size={20} /></button></div><div className="workspace-switch"><Building2 size={18} /><span><small>Ruang kerja</small>Hollawall Group</span></div><nav aria-label="Menu utama">{items.map(([key, label, Icon]) => <button type="button" tabIndex={hidden ? -1 : 0} key={key} className={active === key ? 'active' : ''} aria-current={active === key ? 'page' : undefined} onClick={() => { navigate(key); close() }}><Icon size={18} /><span>{label}</span></button>)}</nav><div className="sidebar-bottom"><div className="profile workspace-profile"><span><LockKeyhole size={15} /></span><div><strong>Workspace demo</strong><small>Data lokal · Teraudit</small></div></div></div></aside></>
}

function ThemeToggle({ theme, setTheme }: { theme: string; setTheme: (theme: string) => void }) {
  return <button type="button" className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={`Gunakan tema ${theme === 'dark' ? 'terang' : 'gelap'}`}><Sun size={16} /><span className={theme} /><Moon size={16} /></button>
}

export default function App() {
  const finance = useFinanceWorkspace()
  const initialRoute = useRef(currentRoute()).current
  const [route, setRoute] = useState(initialRoute)
  const { page: active, projectId: projectFilter } = route
  const [menuOpen, setMenuOpen] = useState(false)
  const [modal, setModal] = useState<Modal>(null)
  const [notice, setNotice] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('hollawall-theme') || 'light')
  const mobile = useMobileNavigation()
  const previousMobile = useRef(mobile)
  const pendingScroll = useRef<number | null>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const meta = pageMeta[active]
  const selectedProject = projectFilter ? finance.workspace.projects.find((project) => project.id === projectFilter) : undefined

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
    if (active !== 'projects' || !projectFilter || selectedProject) return
    window.history.replaceState({ page: 'projects', scrollY: 0 }, '', routeHash('projects'))
    setRoute({ page: 'projects' })
    setNotice('Proyek tidak ditemukan.')
  }, [active, projectFilter, selectedProject])

  const pushRoute = (page: Page, projectId?: string) => {
    if (active === page && projectFilter === projectId) return
    window.history.replaceState({ ...window.history.state, page: active, projectId: projectFilter, scrollY: window.scrollY }, '', window.location.href)
    window.history.pushState({ page, projectId, scrollY: 0 }, '', routeHash(page, projectId))
    setRoute({ page, projectId })
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: 'auto' }))
  }
  const navigate = (page: Page) => pushRoute(page)
  const closeMenu = () => { setMenuOpen(false); if (mobile) window.requestAnimationFrame(() => menuButtonRef.current?.focus()) }
  const commit = (action: () => void, success: string) => { action(); setNotice(success) }
  const safe = (action: () => void, success: string) => { try { commit(action, success) } catch (error) { setNotice(error instanceof Error ? error.message : 'Tindakan belum dapat diproses.') } }
  const saveProject = (input: ProjectInput) => modal?.kind === 'project' && modal.value
    ? commit(() => finance.editProject(modal.value!.id, input), 'Proyek diperbarui.')
    : commit(() => finance.addProject(input), 'Proyek ditambahkan.')
  const saveTransaction = (input: TransactionInput) => modal?.kind === 'transaction' && modal.value
    ? commit(() => finance.editTransaction(modal.value!.id, input), 'Transaksi diperbarui.')
    : commit(() => finance.addTransaction(input), 'Transaksi ditambahkan.')
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
  const addAction = active === 'projects'
    ? selectedProject
      ? { label: 'Tambah transaksi', run: () => setModal({ kind: 'transaction', projectId: selectedProject.id } as Modal) }
      : { label: 'Tambah proyek', run: () => setModal({ kind: 'project' } as Modal) }
    : active === 'office'
      ? { label: 'Biaya kantor', run: () => setModal({ kind: 'transaction', scope: 'office' } as Modal) }
      : active === 'debts'
        ? { label: 'Tambah hutang', run: () => setModal({ kind: 'debt' } as Modal) }
        : { label: 'Tambah transaksi', run: () => setModal({ kind: 'transaction' } as Modal) }

  const content = active === 'overview'
    ? <OverviewWorkspace workspace={finance.workspace} onAddTransaction={() => setModal({ kind: 'transaction' })} onAddProject={() => setModal({ kind: 'project' })} onAddOffice={() => setModal({ kind: 'transaction', scope: 'office' })} />
    : active === 'cashflow' ? <CashflowWorkspacePage workspace={finance.workspace} onOpenProject={openProjectByName} />
      : active === 'wallets' ? <WalletWorkspacePage workspace={finance.workspace} onOpenProject={openProjectByName} />
        : active === 'projects' && selectedProject ? <ProjectTransactionsWorkspace workspace={finance.workspace} project={selectedProject} onBack={() => pushRoute('projects')} onAdd={(project) => setModal({ kind: 'transaction', projectId: project.id })} onEdit={(value) => setModal({ kind: 'transaction', value, projectId: selectedProject.id })} onDelete={(value) => confirmDelete('transaksi', () => finance.removeTransaction(value.id))} />
          : active === 'projects' ? <ProjectCommandCenter workspace={finance.workspace} onAdd={() => setModal({ kind: 'project' })} onEdit={(value) => setModal({ kind: 'project', value })} onDelete={(value) => confirmDelete(`proyek ${value.name}`, () => finance.removeProject(value.id))} onOpen={openProject} />
            : active === 'office' ? <OfficeWorkspace workspace={finance.workspace} onAdd={() => setModal({ kind: 'transaction', scope: 'office' })} onEdit={(value) => setModal({ kind: 'transaction', value })} onDelete={(value) => confirmDelete('biaya kantor', () => finance.removeTransaction(value.id))} />
              : active === 'debts' ? <DebtWorkspace workspace={finance.workspace} onAdd={() => setModal({ kind: 'debt' })} onEdit={(value) => setModal({ kind: 'debt', value })} onDelete={(value) => confirmDelete('hutang internal', () => finance.removeDebt(value.id))} />
                : <ReportsWorkspace workspace={finance.workspace} />

  return (
    <div className="app-shell finance-workspace-shell">
      <Sidebar active={active} open={menuOpen} mobile={mobile} close={closeMenu} navigate={navigate} />
      <main ref={mainRef} className="main-canvas" aria-hidden={mobile && menuOpen ? true : undefined}>
        <header className="topbar">
          <button ref={menuButtonRef} className="icon-button mobile-only" onClick={() => setMenuOpen(true)} aria-label="Buka navigasi" aria-controls="app-navigation" aria-expanded={mobile ? menuOpen : undefined}><Menu size={21} /></button>
          <img className="mobile-header-logo" src={hollawallLogo} alt="Hollawall" />
          <div className="breadcrumbs"><span>Hollawall Group</span><b>/</b><strong>{selectedProject?.name ?? meta.title}</strong></div>
          <div className="topbar-actions">
            {active === 'projects' && <ExportButton workspace={finance.workspace} />}
            {active !== 'reports' && <button className="topbar-add" onClick={addAction.run}><Plus size={16} /><span>{addAction.label}</span></button>}
            <ThemeToggle theme={theme} setTheme={setTheme} />
          </div>
        </header>
        <div className="content">
          <DemoBanner updatedAt={finance.workspace.updated_at} onReset={reset} />
          {!['overview', 'projects', 'reports'].includes(active) && <header className="page-heading"><div><p className="eyebrow">{meta.eyebrow}</p><h1>{meta.title}</h1><p>{meta.copy}</p></div><span className="demo-badge">DATA DEMO</span></header>}
          {content}
        </div>
      </main>
      {notice && <div className="finance-toast" role="status">{notice}</div>}
      {modal?.kind === 'project' && <ProjectForm project={modal.value} onSave={saveProject} onClose={() => setModal(null)} />}
      {modal?.kind === 'transaction' && <TransactionForm projects={finance.workspace.projects} transaction={modal.value} initialScope={modal.scope} lockedProjectId={modal.projectId} onSave={saveTransaction} onClose={() => setModal(null)} />}
      {modal?.kind === 'debt' && <DebtForm debt={modal.value} onSave={saveDebt} onClose={() => setModal(null)} />}
    </div>
  )
}
