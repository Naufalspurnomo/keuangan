import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import App from './App'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState(null, '', '/')
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

const renderApp = () => render(<App />)
const nav = (name: string) => fireEvent.click(within(screen.getByRole('navigation', { name: 'Menu utama' })).getByRole('button', { name: new RegExp(`^${name}`) }))

describe('Hollawall demo finance workspace', () => {
  it('renders one reconciled demo workspace with seven navigation views', () => {
    renderApp()
    expect(screen.getByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })).toBeTruthy()
    expect(screen.getByText(/Tidak terhubung ke buku besar produksi/)).toBeTruthy()
    const menu = screen.getByRole('navigation', { name: 'Menu utama' })
    for (const label of ['Ringkasan', 'Arus Kas', 'Dompet', 'Proyek', 'Operasional Kantor', 'Hutang Internal', 'Laporan']) {
      expect(within(menu).getByRole('button', { name: new RegExp(`^${label}`) })).toBeTruthy()
    }
    expect(within(menu).queryByRole('button', { name: /^Transaksi/ })).toBeNull()
  })

  it('keeps the overview showcase dense, transparent, and additive', () => {
    renderApp()
    expect(screen.getByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Arus kas per unit' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Tren kas 12 bulan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Sebaran saldo dompet' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Kontribusi proyek terbesar' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Omzet dan rentang proyek' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Audit data demo' })).toBeTruthy()
    expect(document.querySelectorAll('.showcase-chart')).toHaveLength(3)
  })

  it('keeps cashflow as a full analytical workspace instead of one chart', () => {
    renderApp()
    nav('Arus Kas')
    expect(screen.getByRole('heading', { name: 'Aliran kas, bukan sekadar saldo' })).toBeTruthy()
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
    expect(screen.getByRole('button', { name: 'Kembali ke Proyek' })).toBeTruthy()
    expect(screen.queryByLabelText('Filter proyek')).toBeNull()
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
    expect(screen.getByText(/Biaya kantor terpisah dari proyek/)).toBeTruthy()
  })

  it('connects the restored project timeline to the writable demo workspace', () => {
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: 'Tambah proyek Hollawall' }))
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(within(screen.getByRole('dialog')).getByRole('heading', { name: 'Tambah proyek' })).toBeTruthy()
  })

  it('creates a project, persists it, and records an audit event', async () => {
    const first = renderApp()
    nav('Proyek')
    fireEvent.click(screen.getAllByRole('button', { name: 'Tambah proyek' })[0])
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Nama proyek *'), { target: { value: 'Proyek Integrasi' } })
    fireEvent.change(within(dialog).getByLabelText('Klien'), { target: { value: 'Klien Integrasi' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Tambah proyek' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getAllByText('Proyek Integrasi').length).toBeGreaterThan(0)

    first.unmount()
    renderApp()
    nav('Proyek')
    expect(screen.getAllByText('Proyek Integrasi').length).toBeGreaterThan(0)
    nav('Ringkasan')
    expect(screen.getByText('Menambah proyek Proyek Integrasi')).toBeTruthy()
  })

  it('keeps invalid project submission open without mutating storage', () => {
    renderApp()
    nav('Proyek')
    fireEvent.click(screen.getAllByRole('button', { name: 'Tambah proyek' })[0])
    const before = localStorage.getItem('hollawall-finance-demo-v2')
    const dialog = screen.getByRole('dialog')
    fireEvent.submit(within(dialog).getByRole('button', { name: 'Tambah proyek' }).closest('form')!)
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(localStorage.getItem('hollawall-finance-demo-v2')).toBe(before)
  })

  it('navigates annual project data and exposes explicit completion ratios', () => {
    renderApp()
    nav('Proyek')
    expect(screen.getByRole('button', { name: '2024, 120 selesai dari 120 proyek' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '2025, 40 selesai dari 74 proyek' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '2026, 7 selesai dari 52 proyek' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Tahun sebelumnya' }))
    expect(screen.getByText((_, element) => element?.tagName === 'SPAN' && element.textContent === '40/74 selesai')).toBeTruthy()
    expect(screen.getByLabelText('Status proyek tahun 2025')).toBeTruthy()
  })

  it('keeps annual summaries aligned with company filters and exposes transaction ranges', () => {
    renderApp()
    nav('Proyek')
    fireEvent.change(screen.getByLabelText('Perusahaan'), { target: { value: 'Holla' } })
    const summary = screen.getByLabelText('Status proyek tahun 2026')
    expect(within(summary).getByText(/Hasil filter · \d+\/13/)).toBeTruthy()
    expect(document.querySelectorAll('.project-market-canvas')).toHaveLength(4)
    expect(screen.getByText('41 / 52 aktif')).toBeTruthy()
    expect(screen.getByText('Garis putih = rentang transaksi')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /transaksi pertama .* transaksi terakhir/ }).length).toBeGreaterThan(0)
  })

  it('opens project detail under Projects and returns with the explicit back action', async () => {
    renderApp()
    nav('Proyek')
    fireEvent.click(document.querySelector('button[data-project-candle]')!)
    expect(window.location.hash).toMatch(/^#projects\?project=/)
    fireEvent.click(screen.getByRole('button', { name: 'Kembali ke Proyek' }))
    await waitFor(() => expect(window.location.hash).toBe('#projects'))
    expect(screen.getByRole('heading', { name: 'Umur dan status proyek' })).toBeTruthy()
  })

  it('returns from a project drilldown to the Projects page with its view state', async () => {
    renderApp()
    nav('Proyek')
    expect(window.location.hash).toBe('#projects')
    fireEvent.click(screen.getByRole('button', { name: 'Tahun sebelumnya' }))
    fireEvent.change(screen.getByLabelText('Perusahaan'), { target: { value: 'Holla' } })
    fireEvent.click(document.querySelector('button[data-project-candle]')!)
    expect(window.location.hash).toMatch(/^#projects\?project=/)
    expect(screen.getByRole('button', { name: 'Kembali ke Proyek' })).toBeTruthy()

    act(() => window.history.back())
    await waitFor(() => expect(window.location.hash).toBe('#projects'))
    expect(screen.getByRole('heading', { name: 'Umur dan status proyek' })).toBeTruthy()
    expect((screen.getByLabelText('Perusahaan') as HTMLSelectElement).value).toBe('Holla')
    expect(screen.getByRole('button', { name: '2025, 40 selesai dari 74 proyek' }).getAttribute('aria-current')).toBe('page')
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
    expect(screen.getByRole('heading', { name: 'Pratinjau dan ekspor PDF' })).toBeTruthy()
    const preview = screen.getByRole('region', { name: 'Pratinjau laporan' })
    expect(within(preview).getByLabelText('Filter aktif').children).toHaveLength(7)
    expect(within(preview).getAllByRole('row')).toHaveLength(420)
    expect(within(preview).queryByText(/Pratinjau menampilkan 50/)).toBeNull()
    fireEvent.change(screen.getByLabelText('Aktivitas'), { target: { value: 'office' } })
    expect(within(preview).getAllByText('Operasional Kantor').length).toBeGreaterThan(0)
    expect(within(preview).getByText('3', { selector: '.preview-metrics strong' })).toBeTruthy()
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
    const activeNavigation = within(document.querySelector('aside.sidebar') as HTMLElement).getByRole('button', { name: 'Ringkasan' })
    activeNavigation.focus()
    mobile = true
    act(() => navigationListener?.())
    await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toBe('Buka navigasi'))
    fireEvent.click(screen.getByRole('button', { name: 'Buka navigasi' }))
    await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toBe('Tutup navigasi'))
    mobile = false
    act(() => navigationListener?.())
    await waitFor(() => expect(document.activeElement?.textContent).toContain('Ringkasan'))
    expect(document.querySelector('aside.sidebar')?.classList.contains('is-open')).toBe(false)
  })

  it('persists theme choice and exposes contextual add actions', async () => {
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: 'Gunakan tema gelap' }))
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
    expect(localStorage.getItem('hollawall-theme')).toBe('dark')
    nav('Hutang Internal')
    expect(screen.getAllByRole('button', { name: 'Tambah hutang' }).length).toBeGreaterThan(0)
    nav('Laporan')
    expect(screen.queryByRole('button', { name: /Tambah transaksi/ })).toBeNull()
  })
})
