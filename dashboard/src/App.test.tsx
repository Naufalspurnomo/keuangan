import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { DemoApp } from './App'
import { seedFinanceWorkspace } from './financeWorkspace'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState(null, '', '/?source=demo')
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState(null, '', '/')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const renderApp = () => render(<DemoApp />)
const nav = (name: string) => fireEvent.click(within(screen.getByRole('navigation', { name: 'Menu utama' })).getByRole('button', { name: new RegExp(`^${name}`) }))

describe('Hollawall demo finance workspace', () => {
  it('renders the canonical shell with exactly seven owned navigation views', () => {
    renderApp()
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeTruthy()
    expect(screen.getByText(/Data keuangan demo tersimpan di browser ini dan tidak terhubung ke buku besar produksi\. Data Presensi privat dibaca dari server\./)).toBeTruthy()
    const menu = screen.getByRole('navigation', { name: 'Menu utama' })
    expect(within(menu).getAllByRole('button')).toHaveLength(7)
    for (const [label, id] of [
      ['Dashboard', 'nav.dashboard'], ['Arus Kas', 'nav.cashflow'], ['Dompet', 'nav.wallets'],
      ['Project', 'nav.projects'], ['Operasional Kantor', 'nav.office'], ['Hutang', 'nav.debts'], ['Laporan', 'nav.reports'],
    ] as const) {
      const item = within(menu).getByRole('button', { name: new RegExp(`^${label}`) })
      expect(item.getAttribute('data-action-id')).toBe(id)
    }
    expect(within(menu).queryByRole('button', { name: /Perlu Ditinjau/ })).toBeNull()
  })

  it('keeps exports in Reports and preserves project context in the mobile breadcrumb', () => {
    renderApp()
    nav('Project')
    const candle = document.querySelector('button[data-project-candle]')!
    fireEvent.click(candle)
    fireEvent.click(candle)
    const projectName = document.querySelector('.project-detail-identity h1')?.textContent
    expect(projectName).toBeTruthy()
    expect(document.querySelector('.breadcrumbs strong')?.textContent).toBe(projectName)
    expect(screen.queryByRole('button', { name: 'Ekspor CSV' })).toBeNull()
    nav('Laporan')
    expect(screen.getByRole('button', { name: 'Ekspor CSV' }).getAttribute('data-action-id')).toBe('reports.export-csv')
    expect(screen.getByRole('button', { name: 'Ekspor PDF' }).getAttribute('data-action-id')).toBe('reports.export-pdf')
  })

  it('registers visible action controls with a stable id and one owner route', () => {
    renderApp()
    for (const label of ['Dashboard', 'Arus Kas', 'Dompet', 'Project', 'Operasional Kantor', 'Hutang', 'Laporan']) nav(label)
    const registered = [...document.querySelectorAll<HTMLElement>('[data-action-id]')]
    expect(registered.length).toBeGreaterThan(7)
    expect(registered.every((control) => Boolean(control.dataset.ownerRoute))).toBe(true)
  })

  it('keeps the overview showcase dense, transparent, and additive', () => {
    renderApp()
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Arus kas per unit' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Tren kas 12 bulan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Sebaran saldo dompet' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Kontribusi Project terbesar' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Saldo per dompet' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Audit data demo' })).toBeTruthy()
    expect(document.querySelectorAll('.showcase-chart')).toHaveLength(3)
  })

  it('keeps cashflow as a full analytical workspace instead of one chart', () => {
    renderApp()
    nav('Arus Kas')
    expect(screen.getByRole('heading', { name: 'Arus Kas' })).toBeTruthy()
    expect(screen.getByText('Kas masuk eksternal')).toBeTruthy()
    expect(screen.getByText('Kas keluar eksternal')).toBeTruthy()
    expect(screen.getByText('Arus bersih eksternal')).toBeTruthy()
    expect(screen.getByText('Transfer internal terbuka')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Masuk vs keluar bulanan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Tren arus kas tercatat' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Kontribusi bersih per perusahaan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Ledger transaksi' })).toBeTruthy()
    expect(screen.getByLabelText('Tahun arus kas')).toBeTruthy()
    expect(document.querySelectorAll('.cashflow-workspace .showcase-chart')).toHaveLength(2)
  })

  it('drills from cashflow project rows into project-owned transaction detail', () => {
    renderApp()
    nav('Arus Kas')
    const project = document.querySelector<HTMLButtonElement>('.ops-ledger article > button')
    expect(project).toBeTruthy()
    fireEvent.click(project!)
    expect(window.location.hash).toMatch(/^#projects\?project=/)
    expect(screen.getByRole('button', { name: 'Kembali ke Project' })).toBeTruthy()
    expect(screen.queryByLabelText('Filter Project')).toBeNull()
  })

  it('keeps wallet analysis traceable from distribution to mutation ledger', () => {
    renderApp()
    nav('Dompet')
    expect(screen.getByRole('heading', { name: 'Posisi kas per sumber' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Sebaran saldo semua dompet' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Arus bulanan dompet terpilih' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Jejak sumber' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Mutasi dompet' })).toBeTruthy()
    expect(screen.getByText('Masuk · seluruh data eksternal')).toBeTruthy()
    expect(screen.getByText('Keluar · seluruh data eksternal')).toBeTruthy()
    expect(screen.getByText('Arus bersih · seluruh data eksternal')).toBeTruthy()
    expect(screen.getByRole('navigation', { name: 'Pilih dompet' })).toBeTruthy()
    expect(screen.getAllByText('Holla · Hojja').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Texturin Surabaya').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Texturin Bali').length).toBeGreaterThanOrEqual(1)
    expect(document.querySelectorAll('.wallet-workspace .showcase-chart')).toHaveLength(2)
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Filter mutasi' })).getByRole('button', { name: 'Internal' }))
    expect(screen.getByText(/Source demo-debt-1:lender/)).toBeTruthy()

    nav('Operasional Kantor')
    expect(screen.getByRole('heading', { name: 'Kebutuhan kantor' })).toBeTruthy()
    expect(screen.getByText(/Biaya kantor terpisah dari Project/)).toBeTruthy()
  })

  it('opens Project creation from the dashboard into the writable demo workspace', () => {
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: 'Tambah Project' }))
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(within(screen.getByRole('dialog')).getByRole('heading', { name: 'Tambah Project' })).toBeTruthy()
  })

  it('creates a project, persists it, and records an audit event', async () => {
    const first = renderApp()
    nav('Project')
    fireEvent.click(screen.getByRole('button', { name: 'Buat Project' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Nama Project *'), { target: { value: 'Integrasi Baru' } })
    fireEvent.change(within(dialog).getByLabelText('Klien'), { target: { value: 'Klien Integrasi' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Tambah Project' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getAllByText('Integrasi Baru').length).toBeGreaterThan(0)
    expect(window.location.hash).toMatch(/^#projects\?project=prj-/)
    expect(screen.getAllByRole('button', { name: 'Tambah transaksi' })).toHaveLength(1)
    expect(JSON.parse(localStorage.getItem('hollawall-finance-demo-v3')!).projects.at(-1).status).toBe('active')

    first.unmount()
    renderApp()
    nav('Project')
    expect(screen.getAllByText('Integrasi Baru').length).toBeGreaterThan(0)
    nav('Dashboard')
    expect(screen.getByText('Menambah Project Integrasi Baru')).toBeTruthy()
  })

  it('keeps invalid project submission open without mutating storage', () => {
    renderApp()
    nav('Project')
    fireEvent.click(screen.getByRole('button', { name: 'Buat Project' }))
    const before = localStorage.getItem('hollawall-finance-demo-v3')
    const dialog = screen.getByRole('dialog')
    fireEvent.submit(within(dialog).getByRole('button', { name: 'Tambah Project' }).closest('form')!)
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(localStorage.getItem('hollawall-finance-demo-v3')).toBe(before)
  })

  it('completes an active project and updates its status, candle marker, and audit trail', async () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'active' && item.started_on.startsWith('2026'))!
    workspace.projects = [project]
    workspace.transactions = workspace.transactions.filter((row) => row.project_id === project.id)
    localStorage.setItem('hollawall-finance-demo-v3', JSON.stringify(workspace))
    renderApp()
    nav('Project')

    fireEvent.click(screen.getByRole('button', { name: `Selesaikan ${project.name}` }))
    const dialog = screen.getByRole('dialog')
    const latestTransactionDate = workspace.transactions.reduce((latest, row) => row.date > latest ? row.date : latest, project.started_on)
    fireEvent.change(within(dialog).getByLabelText('Tanggal selesai *'), { target: { value: latestTransactionDate } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Selesaikan Project' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByRole('status').textContent).toBe('Project diselesaikan.')
    expect(document.querySelector('.status-chip.completed')?.textContent).toBe('Selesai')
    expect(document.querySelector('.project-market-completed')?.textContent).toContain('Selesai')
    expect(screen.queryByRole('button', { name: `Selesaikan ${project.name}` })).toBeNull()
    nav('Dashboard')
    expect(screen.getByText(`Memperbarui Project ${project.name}`)).toBeTruthy()
  }, 30_000)

  it('quick-completes an active project from the candle context menu without opening a dialog', async () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'active' && item.started_on.startsWith('2026'))!
    workspace.projects = [project]
    workspace.transactions = workspace.transactions.filter((row) => row.project_id === project.id)
    localStorage.setItem('hollawall-finance-demo-v3', JSON.stringify(workspace))
    renderApp()
    nav('Project')

    fireEvent.contextMenu(document.querySelector(`[data-project-id="${project.id}"]`)!)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Selesaikan Project' }))

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Project diselesaikan.'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.querySelector(`[data-project-id="${project.id}"]`)?.classList.contains('is-completed')).toBe(true)
    expect(JSON.parse(localStorage.getItem('hollawall-finance-demo-v3')!).projects[0].status).toBe('completed')
  }, 30_000)

  it('reactivates an accidentally completed project from project detail', async () => {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.status === 'completed' && item.started_on.startsWith('2026'))!
    workspace.projects = [project]
    workspace.transactions = workspace.transactions.filter((row) => row.project_id === project.id)
    localStorage.setItem('hollawall-finance-demo-v3', JSON.stringify(workspace))
    renderApp()
    nav('Project')
    const candle = document.querySelector(`[data-project-id="${project.id}"]`)!
    fireEvent.click(candle)
    fireEvent.click(candle)

    fireEvent.click(screen.getByRole('button', { name: 'Aktifkan kembali' }))

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Project diaktifkan kembali.'))
    expect(screen.getByRole('region', { name: 'Status Project' }).textContent).toContain('Aktif')
    const stored = JSON.parse(localStorage.getItem('hollawall-finance-demo-v3')!).projects[0]
    expect(stored.status).toBe('active')
    expect(stored.completed_on).toBeNull()
  })

  it('navigates annual project data and exposes explicit completion ratios', () => {
    renderApp()
    nav('Project')
    const year = screen.getByRole('combobox', { name: 'Project per tahun' })
    for (const value of ['2024', '2025', '2026']) expect(within(year).getByRole('option', { name: value })).toBeTruthy()
    fireEvent.change(year, { target: { value: '2025' } })
    expect(screen.getByText('Hasil filter · 12/15')).toBeTruthy()
    expect(screen.getByLabelText('Status Project tahun 2025')).toBeTruthy()
  })

  it('keeps annual summaries aligned with company filters and exposes transaction ranges', () => {
    renderApp()
    nav('Project')
    fireEvent.change(screen.getByLabelText('Perusahaan'), { target: { value: 'Holla' } })
    const summary = screen.getByLabelText('Status Project tahun 2026')
    expect(within(summary).getByText(/Hasil filter · \d+\/5/)).toBeTruthy()
    expect(document.querySelectorAll('.project-market-canvas')).toHaveLength(4)
    expect(screen.getByText('10 / 18 aktif')).toBeTruthy()
    expect(screen.getByText('Garis putih = rentang transaksi')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /transaksi pertama .* transaksi terakhir/ }).length).toBeGreaterThan(0)
  })

  it('opens project detail under Projects and restores view state with the explicit back action', async () => {
    vi.spyOn(window, 'scrollY', 'get').mockReturnValue(640)
    renderApp()
    nav('Project')
    fireEvent.change(screen.getByRole('combobox', { name: 'Project per tahun' }), { target: { value: '2025' } })
    fireEvent.change(screen.getByLabelText('Perusahaan'), { target: { value: 'Holla' } })
    const candle = document.querySelector('button[data-project-candle]')!
    fireEvent.click(candle)
    fireEvent.click(candle)
    expect(window.location.hash).toMatch(/^#projects\?project=/)
    fireEvent.click(screen.getByRole('button', { name: 'Kembali ke Project' }))
    await waitFor(() => expect(window.location.hash).toBe('#projects'))
    expect(screen.getByRole('heading', { name: 'Umur dan status Project' })).toBeTruthy()
    expect((screen.getByLabelText('Perusahaan') as HTMLSelectElement).value).toBe('Holla')
    expect(screen.getByRole('combobox', { name: 'Project per tahun' })).toHaveValue('2025')
    await waitFor(() => expect(window.scrollTo).toHaveBeenCalledWith({ top: 640, behavior: 'auto' }))
  })

  it('returns from a project drilldown to the Projects page with its view state', async () => {
    renderApp()
    nav('Project')
    expect(window.location.hash).toBe('#projects')
    fireEvent.change(screen.getByRole('combobox', { name: 'Project per tahun' }), { target: { value: '2025' } })
    fireEvent.change(screen.getByLabelText('Perusahaan'), { target: { value: 'Holla' } })
    const candle = document.querySelector('button[data-project-candle]')!
    fireEvent.click(candle)
    fireEvent.click(candle)
    expect(window.location.hash).toMatch(/^#projects\?project=/)
    expect(screen.getByRole('button', { name: 'Kembali ke Project' })).toBeTruthy()

    act(() => window.history.back())
    await waitFor(() => expect(window.location.hash).toBe('#projects'))
    expect(screen.getByRole('heading', { name: 'Umur dan status Project' })).toBeTruthy()
    expect((screen.getByLabelText('Perusahaan') as HTMLSelectElement).value).toBe('Holla')
    expect(screen.getByRole('combobox', { name: 'Project per tahun' })).toHaveValue('2025')
  })

  it('creates an office expense from an explicitly selected wallet', async () => {
    renderApp()
    nav('Operasional Kantor')
    fireEvent.click(screen.getAllByRole('button', { name: /Biaya kantor|Catat biaya/ })[0])
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Dompet *'), { target: { value: 'TX Bali' } })
    fireEvent.change(within(dialog).getByLabelText('Jumlah *'), { target: { value: '500000' } })
    fireEvent.change(within(dialog).getByLabelText('Keterangan *'), { target: { value: 'Listrik kantor QA' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan transaksi' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByText('Listrik kantor QA')).toBeTruthy()
    expect(screen.getAllByText('TX Bali').length).toBeGreaterThan(0)
  })

  it('filters report preview using the same seven visible scope labels and complete row set', () => {
    renderApp()
    nav('Laporan')
    expect(screen.getByRole('heading', { name: 'Laporan' })).toBeTruthy()
    const preview = screen.getByRole('region', { name: 'Pratinjau laporan' })
    expect(within(preview).getByLabelText('Filter aktif').children).toHaveLength(7)
    expect(within(preview).getAllByRole('row')).toHaveLength(95)
    expect(within(preview).queryByText(/Pratinjau menampilkan 50/)).toBeNull()
    fireEvent.change(screen.getByLabelText('Lingkup'), { target: { value: 'office' } })
    expect(within(preview).getAllByText('Operasional Kantor').length).toBeGreaterThan(0)
    expect(within(preview).getByText('4', { selector: '.preview-metrics strong' })).toBeTruthy()
  })

  it('keeps the mobile navigation state aligned with the 900px CSS breakpoint', async () => {
    const matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })
    vi.stubGlobal('matchMedia', matchMedia)
    renderApp()
    expect(matchMedia).toHaveBeenCalledWith('(max-width: 900px)')
    const aside = document.querySelector('aside.sidebar')!
    expect(aside.getAttribute('aria-hidden')).toBe('true')
    const hiddenButtons = within(aside as HTMLElement).getAllByRole('button', { hidden: true })
    expect(hiddenButtons.every((button) => button.tabIndex === -1)).toBe(true)
    const open = screen.getByRole('button', { name: 'Buka navigasi' })
    expect(open.getAttribute('aria-controls')).toBe('app-navigation')
    expect(open.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(open)
    expect(open.getAttribute('aria-expanded')).toBe('true')
    expect(document.querySelector('main')?.hasAttribute('inert')).toBe(true)
    await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toBe('Tutup navigasi'))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(open.getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('main')?.hasAttribute('inert')).toBe(false)
    await waitFor(() => expect(document.activeElement).toBe(open))
  })

  it('reconciles navigation focus and open state across breakpoint changes', async () => {
    let mobile = false
    let navigationListener: (() => void) | undefined
    const matchMedia = vi.fn((query: string) => ({
      get matches() { return query === '(max-width: 900px)' ? mobile : false },
      addEventListener: (_type: string, listener: () => void) => { if (query === '(max-width: 900px)') navigationListener = listener },
      removeEventListener: vi.fn(),
    }))
    vi.stubGlobal('matchMedia', matchMedia)
    renderApp()
    const activeNavigation = within(document.querySelector('aside.sidebar') as HTMLElement).getByRole('button', { name: 'Dashboard' })
    activeNavigation.focus()
    mobile = true
    act(() => navigationListener?.())
    await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toBe('Buka navigasi'))
    fireEvent.click(screen.getByRole('button', { name: 'Buka navigasi' }))
    await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toBe('Tutup navigasi'))
    mobile = false
    act(() => navigationListener?.())
    await waitFor(() => expect(document.activeElement?.textContent).toContain('Dashboard'))
    expect(document.querySelector('aside.sidebar')?.classList.contains('is-open')).toBe(false)
  })

  it('persists theme choice and exposes contextual add actions', async () => {
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: 'Gunakan tema gelap' }))
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
    expect(localStorage.getItem('hollawall-theme')).toBe('dark')
    nav('Hutang')
    expect(screen.getAllByRole('button', { name: 'Tambah hutang' }).length).toBeGreaterThan(0)
    nav('Laporan')
    expect(screen.queryByRole('button', { name: /Tambah transaksi/ })).toBeNull()
  })
})
