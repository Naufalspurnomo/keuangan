import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import App from './App'

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.stubGlobal('confirm', vi.fn(() => true))
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.unstubAllGlobals()
})

const renderApp = () => render(<App />)
const nav = (name: string) => fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${name}`) }))

describe('Hollawall demo finance workspace', () => {
  it('renders one reconciled demo workspace with eight navigation views', () => {
    renderApp()
    expect(screen.getByRole('heading', { name: 'Posisi keuangan Hollawall' })).toBeTruthy()
    expect(screen.getByText(/Tidak terhubung ke ledger production/)).toBeTruthy()
    const menu = screen.getByRole('navigation', { name: 'Menu utama' })
    for (const label of ['Ringkasan', 'Arus Kas', 'Dompet', 'Transaksi', 'Proyek', 'Operasional Kantor', 'Hutang Internal', 'Laporan']) {
      expect(within(menu).getByRole('button', { name: new RegExp(`^${label}`) })).toBeTruthy()
    }
  })

  it('shows exact wallet-to-company mapping and keeps office costs separate', () => {
    renderApp()
    nav('Dompet')
    expect(screen.getByText('Holla · Hojja')).toBeTruthy()
    expect(screen.getByText('Texturin Surabaya')).toBeTruthy()
    expect(screen.getByText('Texturin Bali')).toBeTruthy()

    nav('Operasional Kantor')
    expect(screen.getByRole('heading', { name: 'Kebutuhan kantor' })).toBeTruthy()
    expect(screen.getByText(/Biaya kantor terpisah dari proyek/)).toBeTruthy()
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
    expect(screen.getByRole('button', { name: '2026, 7 selesai dari 28 proyek' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Tahun sebelumnya' }))
    expect(screen.getByText((_, element) => element?.tagName === 'SPAN' && element.textContent === '40/74 selesai')).toBeTruthy()
    expect(screen.getByLabelText('Status proyek tahun 2025')).toBeTruthy()
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

  it('filters report preview using the same seven visible scope labels', () => {
    renderApp()
    nav('Laporan')
    expect(screen.getByRole('heading', { name: 'Preview dan ekspor PDF' })).toBeTruthy()
    const preview = screen.getByRole('region', { name: 'Preview laporan' })
    expect(within(preview).getByLabelText('Filter aktif').children).toHaveLength(7)
    fireEvent.change(screen.getByLabelText('Aktivitas'), { target: { value: 'office' } })
    expect(within(preview).getAllByText('Operasional Kantor').length).toBeGreaterThan(0)
    expect(within(preview).getByText('3', { selector: '.preview-metrics strong' })).toBeTruthy()
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
