import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ProjectTransactionsWorkspace from './ProjectTransactionsWorkspace'
import { seedFinanceWorkspace } from './financeWorkspace'

const records = [
  {
    id: 'prs-1', employee_id: 'pegawai-1', employee_name: 'Pegawai 1', project_id: 'p26-griya', project_name: 'Griya Wellness Center',
    check_in: { id: 'evt-in', occurred_at: '2026-10-31T01:00:00Z', distance_m: 18, accuracy_m: 12, radius_m: 150, photo_url: '/admin/api/presensi-photo.php?id=evt-in' },
    check_out: { id: 'evt-out', occurred_at: '2026-10-31T09:15:00Z', distance_m: 21, accuracy_m: 9, radius_m: 150, photo_url: '/admin/api/presensi-photo.php?id=evt-out' },
    status: 'completed', duration_minutes: 495,
  },
  {
    id: 'prs-2', employee_id: 'pegawai-2', employee_name: 'Pegawai 2', project_id: 'p26-griya', project_name: 'Griya Wellness Center',
    check_in: { id: 'evt-in-2', occurred_at: '2026-10-31T02:00:00Z', distance_m: 12, accuracy_m: 8, radius_m: 150, photo_url: '/admin/api/presensi-photo.php?id=evt-in-2' },
    check_out: null, status: 'active', duration_minutes: null,
  },
]

describe('project presensi detail', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ version: 'presensi.admin.v1', records }) }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  function renderWorkspace() {
    const workspace = seedFinanceWorkspace()
    const project = workspace.projects.find((item) => item.id === 'p26-griya')!
    render(<ProjectTransactionsWorkspace workspace={workspace} project={project} onBack={vi.fn()} onAdd={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />)
  }

  it('defaults to Transaksi and switches to project-scoped Presensi', async () => {
    renderWorkspace()
    expect(screen.getByRole('tab', { name: 'Transaksi', selected: true })).toBeTruthy()
    expect(screen.queryByText('Pegawai 1')).toBeNull()

    const transactionTab = screen.getByRole('tab', { name: 'Transaksi' })
    transactionTab.focus()
    fireEvent.keyDown(transactionTab, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Presensi', selected: true })).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Presensi' }))
    await waitFor(() => expect(screen.getByText('Pegawai 1')).toBeTruthy())
    expect(screen.getByText('Pegawai 2')).toBeTruthy()
    expect(screen.getAllByText('Selesai').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Sedang bekerja').length).toBeGreaterThan(0)
    expect(screen.getByText('8 jam 15 menit')).toBeTruthy()
    expect(fetch).toHaveBeenCalledWith('/admin/api/presensi.php?project_id=p26-griya', expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }))
  })

  it('shows paired selfie, location evidence, filters, and safe failure state', async () => {
    renderWorkspace()
    fireEvent.click(screen.getByRole('tab', { name: 'Presensi' }))
    await waitFor(() => expect(screen.getByRole('img', { name: 'Selfie check-in Pegawai 1' })).toBeTruthy())
    expect(screen.getByRole('img', { name: 'Selfie check-out Pegawai 1' })).toBeTruthy()
    expect(screen.getByText('18 m dari titik proyek')).toBeTruthy()
    expect(screen.getByText('Akurasi 12 m')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Cari presensi'), { target: { value: 'Pegawai 2' } })
    expect(screen.queryByText('Pegawai 1')).toBeNull()
    expect(screen.getByText('Pegawai 2')).toBeTruthy()
  })

  it('does not leak stale data when the admin endpoint fails', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 503 } as Response)
    renderWorkspace()
    fireEvent.click(screen.getByRole('tab', { name: 'Presensi' }))
    await waitFor(() => expect(screen.getByText('Data presensi belum dapat dimuat.')).toBeTruthy())
    expect(screen.queryByText('Pegawai 1')).toBeNull()
  })
})
